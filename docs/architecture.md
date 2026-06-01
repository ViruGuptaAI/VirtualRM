# Architecture

## System Overview

VirtualRM is a real-time voice banking agent built on three layers:

1. **Browser Client** — captures microphone audio, plays TTS audio, renders chat UI
2. **Python Server** — bridges browser and Azure, orchestrates agents, executes CRM tools
3. **Azure Voice Live API** — handles STT, LLM inference, and TTS in a single WebSocket

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              BROWSER CLIENT                                 │
│                                                                             │
│  ┌─────────────┐  PCM16 bytes   ┌──────────────┐  JSON control  ┌────────┐│
│  │ Microphone  │ ────────────►  │  WebSocket   │ ◄────────────► │  Chat  ││
│  │ (24kHz)     │                │  /web/ws     │                │   UI   ││
│  └─────────────┘                └──────┬───────┘                └────────┘│
│  ┌─────────────┐  PCM16 bytes          │                                   │
│  │  Speaker    │ ◄────────────  (binary frames)                            │
│  │ (AudioWork) │                       │                                   │
│  └─────────────┘                       │                                   │
└────────────────────────────────────────┼───────────────────────────────────┘
                                         │
                                         ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                           PYTHON SERVER (Quart)                             │
│                                                                             │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │                    VoiceLiveSession                                   │   │
│  │                                                                      │   │
│  │  handle_browser_audio()  ──►  _send_queue  ──►  _sender_loop()       │   │
│  │                                                      │               │   │
│  │                                                      ▼               │   │
│  │                                              Voice Live WSS          │   │
│  │                                                      │               │   │
│  │  _receiver_loop()  ◄──────────────────────────────────┘               │   │
│  │       │                                                              │   │
│  │       ├── speech_started → StopAudio to browser                      │   │
│  │       ├── speech_stopped → start watchdog timer                      │   │
│  │       ├── transcription → log + send to browser                      │   │
│  │       ├── audio.delta → forward PCM16 to browser                     │   │
│  │       ├── function_call → _handle_function_call()                    │   │
│  │       │      ├── route_to_agent → _handle_agent_handoff()            │   │
│  │       │      ├── play_hold_music → queue deferred playback           │   │
│  │       │      └── CRM tools → TOOL_FUNCTIONS dispatch                 │   │
│  │       ├── response.done → fire deferred actions                      │   │
│  │       └── error → log                                                │   │
│  │                                                                      │   │
│  │  _heartbeat_loop() — detects dead connections (30s timeout)          │   │
│  │  _response_watchdog_timer() — forces response after 5s silence       │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│  ┌───────────────┐  ┌───────────────┐  ┌───────────────┐                   │
│  │ Agent Registry │  │ SOP Registry  │  │  CRM Tools    │                   │
│  │ (5 agents)     │  │ (27 SOPs)     │  │ (22 functions)│                   │
│  └───────────────┘  └───────────────┘  └───────┬───────┘                   │
│                                                 │                           │
│                                          ┌──────▼──────┐                    │
│                                          │  SQLite DB  │                    │
│                                          │  (crm.db)   │                    │
│                                          └─────────────┘                    │
└─────────────────────────────────────────────────────────────────────────────┘
                                         │
                                         ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                        AZURE VOICE LIVE API                                 │
│                                                                             │
│  ┌──────────┐    ┌───────────────┐    ┌──────────┐                         │
│  │  Azure   │    │  GPT-4.1-mini │    │  Azure   │                         │
│  │  Speech  │───►│  (non-realtime│───►│  Dragon  │                         │
│  │  STT     │    │   model)      │    │  HD TTS  │                         │
│  └──────────┘    └───────────────┘    └──────────┘                         │
│                                                                             │
│  Semantic VAD │ Turn Detection │ Auto-truncate │ Echo Cancellation          │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Data Flow

### 1. Session Initialization

```
Browser                    Server                      Voice Live
   │                          │                            │
   │  WS connect /web/ws      │                            │
   │ ─────────────────────►   │                            │
   │                          │  WSS connect               │
   │  {"customerId":"rajesh"} │ ─────────────────────────► │
   │ ─────────────────────►   │                            │
   │                          │  session.update (triage)   │
   │                          │ ─────────────────────────► │
   │                          │                            │
   │                          │  response.create (greeting)│
   │                          │ ─────────────────────────► │
   │                          │                            │
   │  PCM16 (TTS greeting)    │  audio.delta               │
   │ ◄─────────────────────   │ ◄───────────────────────── │
   │                          │                            │
```

### 2. Normal Conversation Turn

```
Browser                    Server                      Voice Live
   │                          │                            │
   │  PCM16 (user speech)     │  input_audio_buffer.append │
   │ ─────────────────────►   │ ─────────────────────────► │
   │                          │                            │
   │  {"Kind":"StopAudio"}    │  speech_started            │
   │ ◄─────────────────────   │ ◄───────────────────────── │
   │                          │                            │
   │                          │  speech_stopped            │
   │                          │ ◄───────────────────────── │
   │                          │  (start 5s watchdog)       │
   │                          │                            │
   │                          │  transcription.completed   │
   │  {"Kind":"UserTranscr"}  │ ◄───────────────────────── │
   │ ◄─────────────────────   │                            │
   │                          │                            │
   │                          │  response.created          │
   │                          │ ◄───────────────────────── │
   │                          │  (cancel watchdog)         │
   │                          │                            │
   │  PCM16 (TTS response)    │  audio.delta (multiple)    │
   │ ◄─────────────────────   │ ◄───────────────────────── │
   │                          │                            │
   │  {"Kind":"AgentTranscr"} │  audio_transcript.done     │
   │ ◄─────────────────────   │ ◄───────────────────────── │
   │                          │                            │
   │                          │  response.done             │
   │                          │ ◄───────────────────────── │
```

### 3. Agent Handoff

```
Browser                    Server                      Voice Live
   │                          │                            │
   │                          │  function_call:            │
   │                          │  route_to_agent(           │
   │                          │    intent="loan",          │
   │                          │    sub_intent="rate_red",  │
   │                          │    summary="..."           │
   │                          │  )                         │
   │                          │ ◄───────────────────────── │
   │                          │                            │
   │                          │  conversation.item.create  │
   │                          │  (function_call_output)    │
   │                          │ ─────────────────────────► │
   │                          │                            │
   │                          │  session.update            │
   │                          │  (new agent prompt + SOP   │
   │                          │   + filtered tools)        │
   │                          │ ─────────────────────────► │
   │                          │                            │
   │  {"Kind":"AgentSwitch"}  │  response.create           │
   │ ◄─────────────────────   │ ─────────────────────────► │
   │  (update sidebar)        │                            │
   │                          │                            │
   │  PCM16 (specialist       │  audio.delta               │
   │   greeting)              │ ◄───────────────────────── │
   │ ◄─────────────────────   │                            │
```

### 4. CRM Tool Call

```
Voice Live                  Server                      
   │                          │                          
   │  function_call:          │                          
   │  get_active_loans({})    │                          
   │ ─────────────────────►   │                          
   │                          │  SQLite query             
   │                          │  ──► crm.db              
   │                          │  ◄── results             
   │                          │                          
   │  conversation.item.create│                          
   │  (function_call_output   │                          
   │   with JSON results)     │                          
   │ ◄─────────────────────   │                          
   │                          │                          
   │  response.create         │                          
   │ ◄─────────────────────   │  (or deferred if active) 
```

### 5. Hold Music Flow

```
Voice Live                  Server                    Browser
   │                          │                          │
   │  function_call:          │                          │
   │  play_hold_music(5)      │                          │
   │ ─────────────────────►   │                          │
   │                          │  Queue: _pending=5       │
   │  function_call_output    │  (don't play yet)        │
   │  "hold_music_queued"     │                          │
   │ ◄─────────────────────   │                          │
   │                          │                          │
   │  audio.delta (agent says │                          │
   │  "please hold...")       │  forward PCM16           │
   │ ─────────────────────►   │ ─────────────────────►   │
   │                          │                          │
   │  response.done           │                          │
   │ ─────────────────────►   │                          │
   │                          │  PlayHoldMusic(5)        │
   │                          │ ─────────────────────►   │
   │                          │                          │  ♪ Arpeggio
   │                          │  asyncio.sleep(5)        │  ♪ melody
   │                          │                          │
   │                          │  inject: "hold ended"    │
   │  conversation.item       │                          │
   │ ◄─────────────────────   │                          │
   │                          │                          │
   │  response.create         │                          │
   │ ◄─────────────────────   │                          │
   │                          │                          │
   │  audio.delta ("Thank     │  forward PCM16           │
   │  you for holding...")    │ ─────────────────────►   │
   │ ─────────────────────►   │                          │
```

---

## Session State Machine

```
                    ┌──────────┐
           start()  │  INIT    │
          ─────────►│          │
                    └────┬─────┘
                         │ WSS connected + session.update
                         ▼
                    ┌──────────┐
                    │  TRIAGE  │◄──────────────────┐
                    │ (Anika)  │                    │
                    └────┬─────┘                    │
                         │ route_to_agent()         │ (not implemented yet)
                         ▼                          │
                    ┌──────────┐                    │
                    │SPECIALIST│  session.update     │
                    │ (Meera/  │  with new prompt    │
                    │  Priya/  │  + SOP + tools      │
                    │  Kavya/  │                    │
                    │  Riya)   │────────────────────┘
                    └────┬─────┘     (re-route)
                         │
                         │ WS close / timeout
                         ▼
                    ┌──────────┐
                    │  CLOSED  │
                    └──────────┘
```

---

## Response Lifecycle

Each Voice Live response goes through this lifecycle:

```
response.created
    │  _response_active = True
    │  cancel watchdog
    │
    ├── audio.delta (multiple)     → forward PCM16 to browser
    ├── audio_transcript.done      → send text to browser
    ├── function_call.done         → execute tool, return output
    │
    └── response.done
            │  _response_active = False
            │
            ├── status = "completed"
            │   ├── _pending_hold_music? → play music → inject message → response.create
            │   └── _pending_response_create? → fire deferred response.create
            │
            ├── status = "cancelled" (user interrupted)
            │   └── clear _pending_hold_music + _pending_response_create
            │
            └── status = "failed" (e.g., TTS error)
                └── log error (transient, model will retry)
```

---

## Concurrency Model

The server is fully async (Quart + asyncio). Each `VoiceLiveSession` spawns 3 concurrent tasks:

| Task | Purpose | Lifecycle |
|---|---|---|
| `_receiver_loop` | Process Voice Live events | Lives for entire session |
| `_sender_loop` | Drain audio queue → Voice Live | Lives for entire session |
| `_heartbeat_loop` | Detect dead connections | Lives for entire session |

Additional ephemeral tasks:
- `_response_watchdog_timer` — created per `speech_stopped`, cancelled on `response.created`

All Voice Live sends go through `_send_json()` (direct) or `_send_queue` (audio). The queue ensures audio frames are serialized without blocking the receiver.

---

## Security Considerations

This is a **demo application**. For production use:

- Replace client-side auth (hardcoded passwords in `login.html`) with proper authentication
- Add HTTPS/TLS termination
- Validate WebSocket origins
- Rate-limit API calls
- Encrypt PII in the database
- Use Azure Managed Identity instead of API keys
- Add input sanitization for function call arguments
