from __future__ import annotations

import base64
import json
from typing import Any, Protocol


class VoiceOutputTransport(Protocol):
    async def send(self, data: str | bytes) -> None: ...


class BrowserTransport:
    def __init__(self, browser_ws: Any):
        self._browser_ws = browser_ws

    async def send(self, data: str | bytes) -> None:
        await self._browser_ws.send(data)


class AcsMediaTransport:
    def __init__(self, media_ws: Any):
        self._media_ws = media_ws

    async def send(self, data: str | bytes) -> None:
        if isinstance(data, bytes):
            envelope = {
                "Kind": "AudioData",
                "AudioData": {"Data": base64.b64encode(data).decode("ascii")},
                "StopAudio": None,
            }
            await self._media_ws.send(json.dumps(envelope))
            return

        message = json.loads(data)
        if message.get("Kind") == "StopAudio":
            await self._media_ws.send(json.dumps({
                "Kind": "StopAudio",
                "AudioData": None,
                "StopAudio": {},
            }))


def parse_acs_media_message(message: str) -> tuple[str, Any]:
    payload = json.loads(message)
    kind = payload.get("kind") or payload.get("Kind")
    if kind == "AudioData":
        audio = payload.get("audioData") or payload.get("AudioData") or {}
        return kind, base64.b64decode(audio["data"] if "data" in audio else audio["Data"])
    if kind == "DtmfData":
        dtmf = payload.get("dtmfData") or payload.get("DtmfData") or {}
        return kind, dtmf.get("data") or dtmf.get("Data")
    if kind == "AudioMetadata":
        return kind, payload.get("audioMetadata") or payload.get("AudioMetadata") or {}
    return str(kind or "Unknown"), payload