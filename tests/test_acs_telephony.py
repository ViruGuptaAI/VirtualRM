import base64
import json
import sys
import unittest
from pathlib import Path

import jwt

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))

from acs_telephony import (
    CallStateStore,
    _bearer_token,
    _caller_phone,
    _media_call_connection_matches,
    _resolve_customer_id,
)
from app import _route_confirmation_is_valid, build_session_config
from crm_tools import normalize_phone_number
from voice_transports import AcsMediaTransport, parse_acs_media_message


class FakeWebSocket:
    def __init__(self):
        self.messages: list[str] = []

    async def send(self, message: str) -> None:
        self.messages.append(message)


class AcsMediaTransportTests(unittest.IsolatedAsyncioTestCase):
    async def test_serializes_audio_for_acs(self):
        websocket = FakeWebSocket()
        transport = AcsMediaTransport(websocket)

        await transport.send(b"\x01\x02")

        payload = json.loads(websocket.messages[0])
        self.assertEqual(payload["Kind"], "AudioData")
        self.assertEqual(
            base64.b64decode(payload["AudioData"]["Data"]),
            b"\x01\x02",
        )

    async def test_maps_stop_audio_and_ignores_transcripts(self):
        websocket = FakeWebSocket()
        transport = AcsMediaTransport(websocket)

        await transport.send(json.dumps({"Kind": "StopAudio"}))
        await transport.send(json.dumps({"Kind": "AgentTranscription"}))

        self.assertEqual(len(websocket.messages), 1)
        self.assertEqual(json.loads(websocket.messages[0])["StopAudio"], {})

    def test_parses_audio_metadata_and_audio(self):
        kind, metadata = parse_acs_media_message(json.dumps({
            "kind": "AudioMetadata",
            "audioMetadata": {"sampleRate": 24000, "channels": 1},
        }))
        self.assertEqual((kind, metadata["sampleRate"]), ("AudioMetadata", 24000))

        kind, audio = parse_acs_media_message(json.dumps({
            "kind": "AudioData",
            "audioData": {"data": base64.b64encode(b"pcm").decode("ascii")},
        }))
        self.assertEqual((kind, audio), ("AudioData", b"pcm"))

class CallStateTests(unittest.IsolatedAsyncioTestCase):
    async def test_memory_store_create_is_idempotent(self):
        store = CallStateStore("", "", None)

        self.assertTrue(await store.create("events", "event-1", {"value": 1}))
        self.assertFalse(await store.create("events", "event-1", {"value": 2}))
        self.assertEqual((await store.get("events", "event-1"))["value"], 1)


class SecurityAndIdentityTests(unittest.TestCase):
    def test_route_requires_confirmation_on_a_later_turn(self):
        pending = {
            "intent": "loan",
            "sub_intent": "new_inquiry",
            "summary": "Customer wants a home loan.",
            "proposed_at_turn": 1,
        }

        self.assertFalse(
            _route_confirmation_is_valid(
                pending, "loan", "new_inquiry", "Yes", "Yes", 1
            )
        )
        self.assertFalse(
            _route_confirmation_is_valid(
                pending, "credit_card", "limit_increase", "Yes", "Yes", 2
            )
        )
        self.assertTrue(
            _route_confirmation_is_valid(
                pending, "loan", "new_inquiry", "Haan, sahi hai", "Haan, sahi hai", 2
            )
        )

    def test_unknown_caller_uses_explicit_demo_customer(self):
        data = {"from": {"phoneNumber": {"value": "+1-555-0100"}}}

        self.assertEqual(_resolve_customer_id(data, "viru"), "viru")

    def test_voice_live_config_uses_supported_model_arguments(self):
        session = build_session_config("triage")["session"]

        self.assertNotIn("reasoning_effort", session)

    def test_callbacks_require_bearer_authentication(self):
        with self.assertRaises(jwt.InvalidTokenError):
            _bearer_token({})
        self.assertEqual(_bearer_token({"Authorization": "Bearer token"}), "token")

    def test_media_uses_call_state_without_bearer_authentication(self):
        state = {"callConnectionId": "call-1"}

        self.assertTrue(_media_call_connection_matches({}, state))
        self.assertTrue(_media_call_connection_matches(
            {"x-ms-call-connection-id": "call-1"},
            state,
        ))
        self.assertFalse(_media_call_connection_matches(
            {"x-ms-call-connection-id": "other-call"},
            state,
        ))

    def test_normalizes_customer_phone_and_acs_raw_id(self):
        phone = _caller_phone({"from": {"rawId": "4:+919820715902"}})
        self.assertEqual(phone, "+919820715902")
        self.assertEqual(normalize_phone_number("+91 9820715902"), phone)


if __name__ == "__main__":
    unittest.main()