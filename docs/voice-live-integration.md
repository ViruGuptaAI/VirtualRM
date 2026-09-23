# Azure Voice Live Integration

## Overview

VirtualRM uses **Azure Voice Live API** — a unified real-time voice AI service that combines STT (Speech-to-Text), LLM inference, and TTS (Text-to-Speech) in a single WebSocket connection. The server acts as a relay between the browser and Voice Live.

**API Version:** `2026-01-01-preview`

---

## Connection Setup

### WebSocket URL

```
wss://<endpoint>/voice-live/realtime?api-version=2026-01-01-preview&model=<model>
```

Built by `build_wss_url()` in `app.py`:

```python
base = VOICE_LIVE_ENDPOINT.replace("https://", "wss://")
url = f"{base}/voice-live/realtime?api-version=2026-01-01-preview&model={VOICE_LIVE_MODEL}"
```

Optional BYOM (Bring Your Own Model) parameters:
- `profile=byom-azure-openai-chat-completion` — routes to external Azure OpenAI
- `foundry-resource-override=<resource-name>` — specifies the LLM's Foundry resource name (e.g., `my-llm-resource`)

> **BYOM RBAC requirement:** The Voice Live resource's **system-assigned managed identity** must have the **`Foundry User`** role on the BYOM target resource. Without this, you'll get `byom_authentication_error`.

### Authentication

Two modes:

**API Key:**
```
api-key: <key>
```

**Azure CLI / Managed Identity:**
```
Authorization: Bearer <token>
```

Token is obtained from `azure.identity.aio.DefaultAzureCredential` with scope `https://cognitiveservices.azure.com/.default`. The token is cached with a 5-minute buffer before expiry to avoid refreshing mid-session.

---

## Session Configuration

The `session.update` payload configures all aspects of the Voice Live session:

### System Prompt Assembly

```python
{
    "type": "session.update",
    "session": {
        "instructions": "<assembled prompt>",
        "turn_detection": { ... },
        "input_audio_transcription": { ... },
        "input_audio_noise_reduction": { ... },
        "input_audio_echo_cancellation": { ... },
        "output_audio": { ... },
        "tools": [ ... ],
        "tool_choice": "auto",
        "temperature": 0.1,
        "max_response_output_tokens": 1000,
    }
}
```

The system prompt is assembled from:
1. **Context header** — customer name, triage summary, specialist identity
2. **Base prompt** — agent personality and rules (from `agents/<agent>.py`)
3. **SOP workflow** — step-by-step procedure (from `sops/<domain>_sops.py`)

For specialist handoffs, the prompt includes:
```
CONTEXT: Customer {name} was speaking with our Virtual RM. Here's what happened: {summary}
CRITICAL: You ARE the specialist. Do NOT say 'let me connect you'. You are already connected.
```

### Voice Activity Detection (VAD)

```python
"turn_detection": {
    "type": "azure_semantic_vad",
    "threshold": 0.5,
    "speech_duration_ms": 200,
    "prefix_padding_ms": 400,
    "silence_duration_ms": 400,
    "remove_filler_words": True,
    "languages": ["en", "hi"],
    "create_response": True,
    "interrupt_response": True,
    "auto_truncate": True,
    "appended_text_after_truncation": " [The user interrupted me.]",
}
```

| Parameter | Value | Purpose |
|---|---|---|
| `type` | `azure_semantic_vad` | Azure's semantic-aware VAD (better than simple energy-based) |
| `threshold` | 0.5 | Speech detection sensitivity |
| `speech_duration_ms` | 200 | Min speech to trigger detection |
| `prefix_padding_ms` | 400 | Audio captured before speech start |
| `silence_duration_ms` | 400 | Silence before end-of-turn |
| `remove_filler_words` | true | Removes "um", "uh", etc. |
| `languages` | `["en", "hi"]` | Hindi + English detection |
| `create_response` | true | Auto-create response when turn ends |
| `interrupt_response` | true | Allow user to interrupt agent mid-speech |
| `auto_truncate` | true | Truncate agent's response on interrupt |
| `appended_text_after_truncation` | `"[The user interrupted me.]"` | Context for the model |

### Input Audio Transcription

```python
"input_audio_transcription": {
    "model": "azure-speech",
    "language": "hi-IN,en-IN",
    "phrase_list": [
        "Contoso Bank", "credit card", "EMI", "CIBIL", "KYC",
        "Anika", "Meera", "Priya", "Kavya", "Riya",
        "अनिका", "मीरा", "प्रिया", "काव्या", "रिया",
        ...
    ],
}
```

The `phrase_list` biases STT towards banking terminology and agent names (including Hindi).

### Noise & Echo Handling

```python
"input_audio_noise_reduction": {
    "type": "azure_deep_noise_suppression",
},
"input_audio_echo_cancellation": {
    "type": "server_echo_cancellation",
},
```

### TTS Configuration

```python
"output_audio": {
    "voice": "en-IN-Diya:DragonHDLatestNeural",
    "audio_format": "pcm16",
    "speed": 1.05,
    "temperature": 0.5,
}
```

All agents use `en-IN-Diya:DragonHDLatestNeural` — an Azure Dragon HD Neural voice optimized for Indian English with natural prosody.

### Model Configuration

```python
"temperature": 0.1,
"max_response_output_tokens": 1000,
```

Low temperature (0.1) for consistent, predictable responses. Max 1000 tokens per response.

---

## Event Protocol

### Events from Voice Live (Server receives)

| Event | Purpose |
|---|---|
| `session.created` | WebSocket connected, session ID assigned |
| `session.updated` | Session config applied successfully |
| `input_audio_buffer.cleared` | Audio buffer cleared |
| `input_audio_buffer.speech_started` | User started speaking (VAD trigger) |
| `input_audio_buffer.speech_stopped` | User stopped speaking (end of turn) |
| `conversation.item.input_audio_transcription.completed` | STT result with transcript + language |
| `conversation.item.input_audio_transcription.failed` | STT failure |
| `response.created` | Model started generating a response |
| `response.output_item.added` | New output item (audio/function call) |
| `response.audio.delta` | TTS audio chunk (base64 PCM16) |
| `response.audio_transcript.delta` | Incremental text of audio response |
| `response.audio_transcript.done` | Complete text of audio response |
| `response.function_call_arguments.done` | Function call with name + arguments |
| `conversation.item.truncated` | Agent response truncated by interruption |
| `response.done` | Response complete (status: completed/cancelled/failed) |
| `error` | Error event |

### Events to Voice Live (Server sends)

| Event | Purpose |
|---|---|
| `session.update` | Configure/reconfigure session |
| `input_audio_buffer.append` | Send audio chunk (base64 PCM16) |
| `conversation.item.create` | Add function call output to conversation |
| `response.create` | Trigger a new model response |

---

## Audio Format

All audio is **PCM16 at 24kHz** (24,000 samples/sec, 16-bit signed integers, mono):

- **Browser → Server:** Raw PCM16 bytes over WebSocket binary frames
- **Server → Voice Live:** Base64-encoded PCM16 in `input_audio_buffer.append`
- **Voice Live → Server:** Base64-encoded PCM16 in `response.audio.delta`
- **Server → Browser:** Raw PCM16 bytes over WebSocket binary frames

---

## Deferred Response Pattern

When a function call happens mid-response, Voice Live may still be generating audio. The server uses `_safe_response_create()` to avoid collisions:

```
If _response_active:
    Set _pending_response_create = True  (defer)
Else:
    Send response.create immediately
```

On `response.done`:
```
_response_active = False
If _pending_hold_music → play music → inject message → safe response.create
Elif _pending_response_create → send response.create
```

This prevents the `conversation_already_has_active_response` error.

---

## Response Watchdog

Voice Live's VAD occasionally fails to auto-create a response after rapid interruption patterns. The watchdog catches this:

1. `speech_stopped` → start 5-second timer
2. If `response.created` arrives → cancel timer (normal path)
3. If 5 seconds pass without response AND transcription was non-empty → force `response.create`
4. If transcription was empty (noise/breathing) → skip (don't force response for noise)

---

## Connection Heartbeat

A background task checks every 10 seconds if Voice Live has sent any event. If 30 seconds pass with no events, the connection is considered dead and the browser is notified to refresh.

---

## Known Limitations

1. **VAD race condition:** After 3+ rapid interruptions, Voice Live may fail to auto-create the next response. The watchdog mitigates this.

2. **TTS failures:** Occasional `speech_synthesis_error: Internal server error` — transient Azure-side issue. The model typically retries on the next turn.

3. **60-minute session limit:** Voice Live sessions have a maximum duration. Not currently handled with reconnection.

4. **NCPM quota:** Default 30 new connections per minute. For load testing, request increase via [aka.ms/foundry-tools-quota-increase](https://aka.ms/foundry-tools-quota-increase).
