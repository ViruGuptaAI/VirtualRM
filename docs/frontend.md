# Frontend

## Overview

The frontend is a set of static HTML/JS/CSS files served by Quart. No build step, no frameworks — vanilla HTML5 with Web Audio API.

### Pages

| Page | File | Purpose |
|---|---|---|
| Login | `server/static/login.html` | User authentication (demo) |
| Dashboard | `server/static/home.html` | Banking dashboard with accounts, transactions, quick actions |
| Chat | `server/static/index.html` | Voice conversation UI with agent pipeline |

---

## Login Page (`login.html`)

Self-contained page with inline styles and JS.

**Auth flow:**
1. User enters ID + password
2. Client-side validation against hardcoded `VALID_USERS` object
3. All 5 users (`rajesh`, `priya`, `amit`, `sneha`, `vikram`) use password `contoso123`
4. On success: stores user ID in `sessionStorage` → redirects to `/home`

**Note:** This is demo-only authentication. Passwords are validated client-side.

**Visual:** Animated gradient background with floating blurred orbs. Split layout: brand panel (left) + login form (right).

---

## Dashboard (`home.html`)

Self-contained banking dashboard with inline styles and JS.

**Features:**
- Time-based greeting ("Good Morning/Afternoon/Evening")
- Account cards grid (4 per user) showing balances
- Quick actions: Talk to RM, Send Money, Statements, Card Controls, Loan EMI, Investments
- Recent transactions table (5 per user) with icons and debit/credit coloring
- Floating chat button (FAB) with breathing animation

**Data:** Complete `USERS` object hardcoded with all 5 users' accounts and transactions — matches the SQLite seed data.

**Auth guard:** Reads `sessionStorage.getItem('contosoUser')`. Redirects to `/login` if not set.

**Entry to chat:** "Talk to RM" button or chat FAB → navigates to `/chat`.

---

## Chat UI (`index.html` + `app.js` + `styles.css`)

The main voice conversation interface.

### Layout

```
┌─────────────────────────────────────────────────────┐
│  Header: Logo │ Speaking Indicator │ Agent Badge │   │
├──────────┬──────────────────────────────────────────┤
│          │                                          │
│ Sidebar  │              Chat Area                   │
│          │                                          │
│ ┌──────┐ │  ┌─────────────────────────────────┐     │
│ │Agent │ │  │  Agent/User messages             │     │
│ │Pipe- │ │  │  Handoff banners                 │     │
│ │line  │ │  │  System messages                 │     │
│ │      │ │  │                                  │     │
│ │Anika │ │  │                                  │     │
│ │  │   │ │  │                                  │     │
│ │Meera │ │  └─────────────────────────────────┘     │
│ │  │   │ │                                          │
│ │Priya │ │  ┌─────────────────────────────────┐     │
│ │  │   │ │  │  Start / Stop Controls           │     │
│ │Kavya │ │  └─────────────────────────────────┘     │
│ │  │   │ │                                          │
│ │Riya  │ │                                          │
│ └──────┘ │                                          │
│          │                                          │
│ Routing  │                                          │
│ History  │                                          │
│          │                                          │
│ Session  │                                          │
│ Info     │                                          │
├──────────┴──────────────────────────────────────────┤
│  Footer: Technology credits                          │
└─────────────────────────────────────────────────────┘
```

### Sidebar Components

**Agent Pipeline:** 5 agent cards with:
- Colored status dot (grey = inactive, green pulse = active, green check = visited)
- Pipeline connectors (vertical lines that animate green with arrow when handoff happens)

**Routing History:** Timeline of agent transitions with timestamps.

**Session Info:** Status, current agent, call duration timer, handoff count.

---

## Audio Pipeline (`app.js`)

### Microphone Capture

```
Microphone → MediaStream → AudioContext (24kHz)
    → ScriptProcessor (bufferSize: 4096)
    → Float32 → PCM16 conversion
    → WebSocket binary frame
```

The `ScriptProcessor` captures audio in 4096-sample chunks, converts Float32 [-1, 1] to Int16 [-32768, 32767], and sends raw PCM16 bytes over the WebSocket.

### TTS Playback

```
WebSocket binary frame (PCM16)
    → AudioWorklet (RingBufferProcessor)
    → AudioContext destination (speakers)
```

Uses an `AudioWorklet` with a ring buffer for low-latency playback. The ring buffer enables instant barge-in: when the user starts speaking, the buffer is cleared (zero samples remain), immediately silencing the agent.

### AudioWorklet Ring Buffer (`audio-processor.js`)

28-line processor that implements:
- **`postMessage({pcm: Float32Array})`** — append audio samples to ring buffer
- **`postMessage({clear: true})`** — flush buffer instantly (barge-in)
- **`process()`** — copy samples from buffer to output; fill with silence if empty

---

## WebSocket Protocol

### Connection

```javascript
ws = new WebSocket("ws://localhost:8000/web/ws");
```

### First Message (Browser → Server)

```json
{"customerId": "rajesh"}
```

Customer ID from `sessionStorage`.

### Audio (Browser → Server)

Raw PCM16 bytes as `ArrayBuffer` — no JSON wrapping.

### Audio (Server → Browser)

Raw PCM16 bytes as binary WebSocket frame — forwarded directly from Voice Live's `audio.delta`.

### Control Messages (Server → Browser)

All JSON with a `Kind` field:

| Kind | Payload | Purpose |
|---|---|---|
| `StopAudio` | — | Barge-in: clear AudioWorklet buffer |
| `AgentTranscription` | `Text`, `Agent` | Agent's spoken text (for chat display) |
| `UserTranscription` | `Text`, `Language` | User's transcribed speech |
| `AgentSwitch` | `Agent`, `AgentKey` | Agent handoff notification |
| `PlayHoldMusic` | `Duration` | Trigger hold music synthesis |

---

## Hold Music Synthesis

`playHoldMusic(duration)` in `app.js` generates a synthesized melody:

**Notes:** C4 → E4 → G4 → C5 → G4 → E4 (arpeggio pattern)

**Synthesis:**
- Separate `AudioContext` at native sample rate
- `OscillatorNode` (sine wave) for each note
- Envelope shaping: 80ms attack, 150ms release
- Gain: 0.7
- Notes repeat to fill the requested duration

---

## Handoff Chime

`playHandoffChime()` generates a two-note ascending tone:
- G4 (0.4s) → silence → C5 (0.6s)
- Played when agent switches via `AgentSwitch` message

---

## UI Theme (`styles.css`)

840 lines of CSS using custom properties for theming.

**Design patterns:**
- **Glassmorphism:** `backdrop-filter: blur(16px)` on panels with semi-transparent backgrounds
- **Animated background:** Radial gradients with `hue-rotate` animation, floating orbs
- **Agent cards:** Scale(1.03) + glow on active, green checkmark border on visited
- **Pipeline connectors:** 2px lines that animate to green with gradient + arrow
- **Chat messages:** User = right-aligned primary gradient, Agent = left-aligned
- **Handoff banners:** Centered with gold gradient, shine animation, pill-shaped labels
- **Speaking indicator:** 4 bouncing bars at staggered delays

**Responsive:** At ≤768px, sidebar hides and layout becomes single-column.

---

## State Variables

Key state in `app.js`:

| Variable | Type | Purpose |
|---|---|---|
| `ws` | WebSocket | Connection to server |
| `audioContext` | AudioContext | 24kHz context for playback |
| `mediaStream` | MediaStream | Microphone access |
| `scriptProcessor` | ScriptProcessorNode | Mic audio capture |
| `isPlaying` | boolean | TTS audio currently playing |
| `audioQueue` | Array | Buffered audio chunks |
| `callTimer` | interval | Call duration counter |
| `callStart` | Date | Call start timestamp |
| `handoffCount` | number | Number of agent switches |
| `previousAgentKey` | string | For pipeline path animation |
| `handoffHistory` | Array | Timeline of all handoffs |

---

## Agent Metadata

```javascript
const AGENT_META = {
    triage:          { label: "Anika",  desc: "Virtual RM",  color: "#667eea", icon: "🏦" },
    credit_card:     { label: "Meera",  desc: "Cards",       color: "#f093fb", icon: "💳" },
    loan:            { label: "Priya",  desc: "Loans",       color: "#4facfe", icon: "🏠" },
    savings_account: { label: "Kavya",  desc: "Savings",     color: "#43e97b", icon: "💰" },
    general_banking: { label: "Riya",   desc: "General",     color: "#fa709a", icon: "🏦" },
};
```

Used for sidebar display, message colors, and handoff banners.
