from __future__ import annotations

import asyncio
import json
import logging
import os
import secrets
import time
from typing import Any, Callable

import jwt
from azure.communication.callautomation import (
    AudioFormat,
    MediaStreamingAudioChannelType,
    MediaStreamingContentType,
    MediaStreamingOptions,
    StreamingTransportType,
)
from azure.communication.callautomation.aio import CallAutomationClient
from azure.core.exceptions import HttpResponseError, ResourceExistsError, ResourceNotFoundError
from azure.data.tables import UpdateMode
from azure.data.tables.aio import TableClient
from azure.identity.aio import AzureCliCredential, ManagedIdentityCredential
from quart import Blueprint, abort, request, websocket

from crm_tools import find_customer_id_by_phone
from voice_transports import AcsMediaTransport, parse_acs_media_message

logger = logging.getLogger("virtual_rm.acs")

ACS_ISSUER = "https://acscallautomation.communication.azure.com"
ACS_JWKS_URL = f"{ACS_ISSUER}/calling/keys"
CALL_STATE_PARTITION = "calls"
EVENT_PARTITION = "events"


class CallStateStore:
    def __init__(self, endpoint: str, table_name: str, credential: Any):
        self._table = (
            TableClient(endpoint, table_name, credential=credential)
            if endpoint and table_name
            else None
        )
        self._memory: dict[tuple[str, str], dict[str, Any]] = {}

    async def initialize(self) -> None:
        return None

    async def create(self, partition: str, key: str, values: dict[str, Any]) -> bool:
        entity = {"PartitionKey": partition, "RowKey": key, **values}
        if not self._table:
            identity = (partition, key)
            if identity in self._memory:
                return False
            self._memory[identity] = entity
            return True
        try:
            await self._table.create_entity(entity)
            return True
        except ResourceExistsError:
            return False

    async def merge(self, partition: str, key: str, values: dict[str, Any]) -> None:
        entity = {"PartitionKey": partition, "RowKey": key, **values}
        if not self._table:
            self._memory.setdefault((partition, key), {}).update(entity)
            return
        await self._table.update_entity(entity, mode=UpdateMode.MERGE)

    async def get(self, partition: str, key: str) -> dict[str, Any] | None:
        if not self._table:
            return self._memory.get((partition, key))
        try:
            return dict(await self._table.get_entity(partition, key))
        except ResourceNotFoundError:
            return None

    async def delete(self, partition: str, key: str) -> None:
        if not self._table:
            self._memory.pop((partition, key), None)
            return
        try:
            await self._table.delete_entity(partition, key)
        except ResourceNotFoundError:
            pass

    async def close(self) -> None:
        if self._table:
            await self._table.close()


def _bearer_token(headers: Any) -> str:
    value = headers.get("Authorization", "")
    if not value.startswith("Bearer "):
        raise jwt.InvalidTokenError("Missing bearer token")
    return value.removeprefix("Bearer ").strip()


async def _validate_acs_jwt(headers: Any, audience: str) -> None:
    token = _bearer_token(headers)
    jwks = jwt.PyJWKClient(ACS_JWKS_URL)

    def decode() -> None:
        signing_key = jwks.get_signing_key_from_jwt(token)
        jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            issuer=ACS_ISSUER,
            audience=audience,
        )

    await asyncio.to_thread(decode)


def _media_call_connection_matches(headers: Any, state: dict[str, Any]) -> bool:
    expected_id = state.get("callConnectionId")
    received_id = headers.get("x-ms-call-connection-id")
    return not expected_id or not received_id or expected_id == received_id


def _event_list(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [event for event in payload if isinstance(event, dict)]
    return [payload] if isinstance(payload, dict) else []


def _caller_phone(data: dict[str, Any]) -> str:
    caller = data.get("from", {})
    phone = caller.get("phoneNumber", {}).get("value")
    if phone:
        return str(phone)
    raw_id = str(caller.get("rawId", ""))
    return raw_id.removeprefix("4:") if raw_id.startswith("4:+") else ""


def _resolve_customer_id(data: dict[str, Any], fallback_customer_id: str) -> str:
    return find_customer_id_by_phone(_caller_phone(data)) or fallback_customer_id or "unknown"


def register_acs_routes(app: Any, session_factory: Callable[..., Any]) -> None:
    enabled = os.getenv("ACS_TELEPHONY_ENABLED", "false").lower() == "true"
    endpoint = os.getenv("ACS_ENDPOINT", "")
    resource_id = os.getenv("ACS_RESOURCE_ID", "")
    callback_audience = os.getenv("ACS_CALLBACK_AUDIENCE", "")
    callback_base = os.getenv("ACS_CALLBACK_BASE_URL", "").rstrip("/")
    table_endpoint = os.getenv("ACS_CALL_STATE_TABLE_ENDPOINT", "")
    table_name = os.getenv("ACS_CALL_STATE_TABLE_NAME", "acscallstate")
    fallback_customer_id = os.getenv("ACS_DEMO_CUSTOMER_ID", "").strip()
    client_id = os.getenv("AZURE_USER_ASSIGNED_IDENTITY_CLIENT_ID", "")

    credential = (
        ManagedIdentityCredential(client_id=client_id)
        if client_id
        else AzureCliCredential()
    )
    store = CallStateStore(table_endpoint, table_name, credential)
    acs_client = CallAutomationClient(endpoint, credential) if endpoint else None
    active_sessions: dict[str, Any] = {}
    blueprint = Blueprint("acs_telephony", __name__)

    def require_enabled() -> None:
        if (
            not enabled
            or not acs_client
            or not resource_id
            or not callback_audience
            or not callback_base
        ):
            abort(503)

    @blueprint.post("/api/acs/incoming-call")
    async def incoming_call():
        require_enabled()
        assert acs_client is not None
        events = _event_list(await request.get_json())
        responses = []
        for event in events:
            event_type = event.get("eventType") or event.get("type")
            data = event.get("data", {})
            if event_type == "Microsoft.EventGrid.SubscriptionValidationEvent":
                responses.append({"validationResponse": data.get("validationCode")})
                continue
            if event_type != "Microsoft.Communication.IncomingCall":
                continue
            if str(event.get("topic") or event.get("source", "")).lower() != resource_id.lower():
                abort(403)

            event_id = str(event.get("id", ""))
            if not event_id or not await store.create(
                EVENT_PARTITION,
                event_id,
                {"expiresAt": int(time.time()) + 86400},
            ):
                continue

            token = secrets.token_urlsafe(32)
            customer_id = _resolve_customer_id(data, fallback_customer_id)
            await store.create(CALL_STATE_PARTITION, token, {
                "customerId": customer_id,
                "expiresAt": int(time.time()) + 86400,
                "eventId": event_id,
            })
            callback_url = f"{callback_base}/api/acs/callbacks/{token}"
            media_url = callback_base.replace("https://", "wss://") + f"/api/acs/media/{token}"
            options = MediaStreamingOptions(
                transport_url=media_url,
                transport_type=StreamingTransportType.WEBSOCKET,
                content_type=MediaStreamingContentType.AUDIO,
                audio_channel_type=MediaStreamingAudioChannelType.MIXED,
                start_media_streaming=True,
                enable_bidirectional=True,
                enable_dtmf_tones=False,
                audio_format=AudioFormat.PCM24_K_MONO,
            )
            try:
                result = await acs_client.answer_call(
                    incoming_call_context=data["incomingCallContext"],
                    callback_url=callback_url,
                    media_streaming=options,
                    operation_context=token,
                )
                await store.merge(CALL_STATE_PARTITION, token, {
                    "callConnectionId": result.call_connection_id,
                    "correlationId": result.correlation_id or "",
                })
                logger.info(
                    "Accepted incoming ACS call (event=%s, customer_recognized=%s)",
                    event_id,
                    customer_id != "unknown",
                )
            except (KeyError, HttpResponseError):
                await store.delete(CALL_STATE_PARTITION, token)
                logger.exception("Failed to answer incoming ACS call (event=%s)", event_id)
                raise
        return (responses[0] if len(responses) == 1 else responses), 200

    @blueprint.post("/api/acs/callbacks/<token>")
    async def callbacks(token: str):
        require_enabled()
        try:
            await _validate_acs_jwt(request.headers, callback_audience)
        except jwt.InvalidTokenError:
            abort(401)
        state = await store.get(CALL_STATE_PARTITION, token)
        if not state or int(state.get("expiresAt", 0)) < time.time():
            abort(404)
        for event in _event_list(await request.get_json()):
            event_type = str(event.get("type") or event.get("eventType", ""))
            event_data = event.get("data", {})
            received_id = event_data.get("callConnectionId")
            expected_id = state.get("callConnectionId")
            if expected_id and received_id and received_id != expected_id:
                abort(403)
            if event_type.endswith(("CallDisconnected", "AnswerFailed", "MediaStreamingFailed")):
                session = active_sessions.pop(token, None)
                if session:
                    await session.close()
                await store.delete(CALL_STATE_PARTITION, token)
                logger.info("ACS call ended (event_type=%s)", event_type.rsplit(".", 1)[-1])
        return "", 200

    @blueprint.websocket("/api/acs/media/<token>")
    async def media(token: str):
        require_enabled()
        state = await store.get(CALL_STATE_PARTITION, token)
        if not state or int(state.get("expiresAt", 0)) < time.time():
            await websocket.close(1008)
            return
        if not _media_call_connection_matches(websocket.headers, state):
            await websocket.close(1008)
            return

        customer_id = str(state.get("customerId", "unknown"))
        session = session_factory(
            AcsMediaTransport(websocket),
            customer_id=customer_id,
            customer_verified=True,
        )
        active_sessions[token] = session
        await session.start()
        try:
            while True:
                message = await websocket.receive()
                if not isinstance(message, str):
                    continue
                kind, value = parse_acs_media_message(message)
                if kind == "AudioData":
                    await session.handle_browser_audio(value)
                elif kind == "AudioMetadata":
                    if value.get("sampleRate") != 24000 or value.get("channels") != 1:
                        await websocket.close(1003)
                        break
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("ACS media WebSocket failed")
        finally:
            active_sessions.pop(token, None)
            await session.close()

    @app.before_serving
    async def initialize_acs() -> None:
        if enabled:
            await store.initialize()

    @app.after_serving
    async def close_acs() -> None:
        await store.close()
        if acs_client:
            await acs_client.close()
        await credential.close()

    app.register_blueprint(blueprint)