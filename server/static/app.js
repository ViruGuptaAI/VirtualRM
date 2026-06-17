// ── State ────────────────────────────────────────────────────────
let ws = null;
let audioContext = null;
let mediaStream = null;
let scriptProcessor = null;
let isPlaying = false;
let audioQueue = [];
let callTimer = null;
let callStart = null;
let handoffCount = 0;
let previousAgentKey = 'triage';
let handoffHistory = [];

const SAMPLE_RATE = 24000;
const BUFFER_SIZE = 4096;

const AGENT_META = {
    triage:          { label: 'Anika',  short: 'Virtual RM',       color: '#4299e1', icon: '🎧' },
    credit_card:     { label: 'Meera',  short: 'Credit Cards',     color: '#9f7aea', icon: '💳' },
    loan:            { label: 'Priya',  short: 'Loans',            color: '#ed8936', icon: '🏠' },
    savings_account: { label: 'Kavya',  short: 'Savings',          color: '#38a169', icon: '💰' },
    general_banking: { label: 'Riya',   short: 'General Banking',  color: '#718096', icon: '🏦' },
};

// ── Audio visualizer ─────────────────────────────────────────────
const visualizerEl = document.getElementById('visualizer');
const NUM_BARS = 20;
for (let i = 0; i < NUM_BARS; i++) {
    const bar = document.createElement('div');
    bar.className = 'visualizer-bar';
    bar.style.height = '4px';
    visualizerEl.appendChild(bar);
}

function animateVisualizer(active) {
    const bars = visualizerEl.querySelectorAll('.visualizer-bar');
    if (!active) {
        bars.forEach(b => b.style.height = '4px');
        return;
    }
    bars.forEach(b => {
        b.style.height = `${4 + Math.random() * 30}px`;
    });
}

// ── Start conversation ───────────────────────────────────────────
async function startConversation() {
    document.getElementById('btn-start').disabled = true;
    document.getElementById('btn-stop').disabled = false;

    // Clear messages
    const messagesEl = document.getElementById('messages');
    messagesEl.innerHTML = '';
    addSystemMessage('Connecting to Virtual RM...');

    // Microphone access
    try {
        mediaStream = await navigator.mediaDevices.getUserMedia({
            audio: {
                sampleRate: SAMPLE_RATE,
                channelCount: 1,
                echoCancellation: true,
                noiseSuppression: true,
            }
        });
    } catch (err) {
        addSystemMessage('⚠️ Microphone access denied. Please allow microphone access.');
        document.getElementById('btn-start').disabled = false;
        document.getElementById('btn-stop').disabled = true;
        return;
    }

    // Audio context for recording
    audioContext = new AudioContext({ sampleRate: SAMPLE_RATE });

    // Initialize AudioWorklet for playback (must be done after user gesture)
    await initAudioWorklet();

    const source = audioContext.createMediaStreamSource(mediaStream);
    scriptProcessor = audioContext.createScriptProcessor(BUFFER_SIZE, 1, 1);

    scriptProcessor.onaudioprocess = (e) => {
        if (ws && ws.readyState === WebSocket.OPEN) {
            const float32 = e.inputBuffer.getChannelData(0);
            const pcm16 = new Int16Array(float32.length);
            for (let i = 0; i < float32.length; i++) {
                const s = Math.max(-1, Math.min(1, float32[i]));
                pcm16[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
            }
            ws.send(pcm16.buffer);
        }
    };

    source.connect(scriptProcessor);
    scriptProcessor.connect(audioContext.destination);

    // WebSocket connection
    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
    ws = new WebSocket(`${protocol}//${location.host}/web/ws`);
    ws.binaryType = 'arraybuffer';

    ws.onopen = () => {
        // Send customer ID as the first message
        const userId = sessionStorage.getItem('contosoUser') || 'rajesh';
        ws.send(JSON.stringify({ customerId: userId }));

        updateStatus('connected');
        addSystemMessage('✅ Connected — listening...');
        callStart = Date.now();
        callTimer = setInterval(updateDuration, 1000);
    };

    ws.onmessage = (event) => {
        if (event.data instanceof ArrayBuffer) {
            // Raw PCM16 audio from agent — play through worklet
            stopHoldMusic(); // Kill hold music if playing
            playAudio(event.data);
            animateVisualizer(true);
            showSpeakingIndicator(true);
            clearTimeout(window._speakTimeout);
            window._speakTimeout = setTimeout(() => {
                animateVisualizer(false);
                showSpeakingIndicator(false);
            }, 300);
        } else {
            // JSON control message
            try {
                const msg = JSON.parse(event.data);
                handleControlMessage(msg);
            } catch (e) {
                console.warn('Non-JSON text message:', event.data);
            }
        }
    };

    ws.onclose = () => {
        updateStatus('disconnected');
        addSystemMessage('Call ended.');
        cleanup();
    };

    ws.onerror = () => {
        addSystemMessage('⚠️ Connection error.');
        cleanup();
    };
}

// ── Handle control messages ──────────────────────────────────────
function handleControlMessage(msg) {
    switch (msg.Kind) {
        case 'StopAudio':
            stopPlayback();
            break;

        case 'AgentTranscription':
            clearToolStatus();
            addAgentMessage(msg.Text, msg.Agent);
            break;

        case 'ReplaceLastAgent':
            replaceLastAgentMessage(msg.Text, msg.Agent);
            break;

        case 'UserTranscription':
            clearToolStatus();
            addUserMessage(msg.Text);
            break;

        case 'AgentSwitch':
            handleAgentSwitch(msg.AgentKey, msg.Agent);
            break;

        case 'PlayHoldMusic':
            playHoldMusic(msg.Duration || 5);
            break;

        case 'ToolStatus':
            addToolStatus(msg.Label);
            break;

        // Legacy compat
        case 'Transcription':
            addAgentMessage(msg.Text, '');
            break;
    }
}

// ── Agent switch UI ──────────────────────────────────────────────
function handleAgentSwitch(agentKey, agentName) {
    const fromKey = previousAgentKey;
    const fromMeta = AGENT_META[fromKey] || AGENT_META.triage;
    const toMeta = AGENT_META[agentKey] || AGENT_META.general_banking;

    // Mark previous agent as visited
    const prevCard = document.getElementById(`agent-${fromKey}`);
    if (prevCard) prevCard.classList.add('visited');

    // Update active state in sidebar
    document.querySelectorAll('.agent-card').forEach(el => el.classList.remove('active'));
    const card = document.getElementById(`agent-${agentKey}`);
    if (card) card.classList.add('active');

    // Animate the pipeline connector between the two agents
    activatePipelinePath(fromKey, agentKey);

    // Update header badge
    const badge = document.getElementById('agent-badge');
    badge.textContent = `${toMeta.icon} ${toMeta.label} — ${toMeta.short}`;
    badge.style.background = toMeta.color;
    badge.style.boxShadow = `0 2px 10px ${toMeta.color}44`;

    // Update status panel
    document.getElementById('current-agent-label').textContent =
        `${toMeta.label} (${toMeta.short})`;

    // If it's a handoff (not the initial triage assignment)
    if (agentKey !== 'triage' && fromKey !== agentKey) {
        handoffCount++;
        document.getElementById('handoff-count').textContent = handoffCount;

        // Play a short handoff chime
        playHandoffChime();

        // Rich handoff banner in chat
        addRichHandoffMessage(fromKey, agentKey);

        // Add to routing history timeline
        addHandoffTimelineEntry(fromKey, agentKey);
    }

    previousAgentKey = agentKey;
}

function activatePipelinePath(fromKey, toKey) {
    // Light up all connectors between agent positions
    const order = ['triage', 'credit_card', 'loan', 'savings_account', 'general_banking'];
    const connectors = document.querySelectorAll('.pipeline-connector');
    // Reset all
    connectors.forEach(c => c.classList.remove('active'));

    const fromIdx = order.indexOf(fromKey);
    const toIdx = order.indexOf(toKey);
    if (fromIdx < 0 || toIdx < 0) return;

    const lo = Math.min(fromIdx, toIdx);
    const hi = Math.max(fromIdx, toIdx);
    for (let i = lo; i < hi; i++) {
        const connId = `conn-${order[i]}-${order[i+1]}`;
        const conn = document.getElementById(connId);
        if (conn) conn.classList.add('active');
    }
}

function addRichHandoffMessage(fromKey, toKey) {
    const from = AGENT_META[fromKey] || AGENT_META.triage;
    const to = AGENT_META[toKey] || AGENT_META.general_banking;

    const el = document.createElement('div');
    el.className = 'message handoff';
    el.innerHTML = `
        <div class="handoff-banner-header">Agent Handoff</div>
        <div class="handoff-banner-body">
            <span class="handoff-agent-pill" style="background:${from.color}">
                <span class="pill-dot"></span>
                ${from.icon} ${from.label}
            </span>
            <span class="handoff-arrow-icon">→</span>
            <span class="handoff-agent-pill" style="background:${to.color}">
                <span class="pill-dot"></span>
                ${to.icon} ${to.label}
            </span>
        </div>
    `;
    appendMessage(el);
}

function addHandoffTimelineEntry(fromKey, toKey) {
    const from = AGENT_META[fromKey] || AGENT_META.triage;
    const to = AGENT_META[toKey] || AGENT_META.general_banking;
    const elapsed = callStart ? Math.floor((Date.now() - callStart) / 1000) : 0;
    const m = Math.floor(elapsed / 60);
    const s = elapsed % 60;
    const timestamp = `${m}:${s.toString().padStart(2, '0')}`;

    // Remove "no handoffs yet" placeholder
    const empty = document.getElementById('handoff-empty');
    if (empty) empty.remove();

    const timeline = document.getElementById('handoff-timeline');
    const entry = document.createElement('div');
    entry.className = 'handoff-entry';
    entry.innerHTML = `
        <div class="handoff-entry-dot-col">
            <div class="handoff-entry-dot" style="border-color:${to.color};background:${to.color}"></div>
            <div class="handoff-entry-line"></div>
        </div>
        <div class="handoff-entry-content">
            <div class="handoff-entry-agents">
                <span>${from.icon} ${from.label}</span>
                <span class="handoff-entry-arrow">→</span>
                <span style="color:${to.color}">${to.icon} ${to.label}</span>
            </div>
            <div class="handoff-entry-time">at ${timestamp} into call</div>
        </div>
    `;
    timeline.appendChild(entry);
}

function getAgentColor(key) {
    return (AGENT_META[key] || AGENT_META.general_banking).color;
}

function showSpeakingIndicator(active) {
    const el = document.getElementById('speaking-indicator');
    const label = document.getElementById('speaking-label');
    if (active) {
        el.classList.add('active');
        const meta = AGENT_META[previousAgentKey] || AGENT_META.triage;
        label.textContent = `${meta.label} Speaking`;
    } else {
        el.classList.remove('active');
    }
}

// ── Audio playback (AudioWorklet ring buffer — instant barge-in) ─────
let workletNode = null;

async function initAudioWorklet() {
    if (!audioContext || workletNode) return;
    await audioContext.audioWorklet.addModule('/static/audio-processor.js');
    workletNode = new AudioWorkletNode(audioContext, 'audio-processor');
    workletNode.connect(audioContext.destination);
}

function playAudio(pcm16Buffer) {
    if (!audioContext || !workletNode) return;
    const int16 = new Int16Array(pcm16Buffer);
    const float32 = new Float32Array(int16.length);
    for (let i = 0; i < int16.length; i++) {
        float32[i] = int16[i] / 0x8000;
    }
    workletNode.port.postMessage({ pcm: float32 });
}

function stopPlayback() {
    // Instantly clear the ring buffer — zero latency barge-in
    if (workletNode) {
        workletNode.port.postMessage({ clear: true });
    }
    showSpeakingIndicator(false);
    animateVisualizer(false);
}

// ── Hold music (uses separate AudioContext at native sample rate) ─
let holdMusicCtx = null;
let holdMusicSource = null;

function playHoldMusic(duration = 5) {
    stopHoldMusic();
    try {
        // Use a separate AudioContext at native sample rate (not 24kHz)
        holdMusicCtx = new AudioContext();
        const sr = holdMusicCtx.sampleRate;
        const len = Math.floor(sr * duration);
        const buf = holdMusicCtx.createBuffer(1, len, sr);
        const data = buf.getChannelData(0);
        // Pleasant hold melody: C4-E4-G4-C5-G4-E4 arpeggio
        const notes = [
            { freq: 261.63, start: 0, end: 1.2 },
            { freq: 329.63, start: 0.8, end: 2.0 },
            { freq: 392.00, start: 1.6, end: 2.8 },
            { freq: 523.25, start: 2.4, end: 3.6 },
            { freq: 392.00, start: 3.2, end: 4.4 },
            { freq: 329.63, start: 4.0, end: 5.0 },
        ];
        for (let i = 0; i < len; i++) {
            const t = i / sr;
            let sample = 0;
            for (const n of notes) {
                if (t >= n.start && t <= n.end) {
                    const noteT = t - n.start;
                    const noteDur = n.end - n.start;
                    const env = Math.min(1, noteT / 0.08) * Math.min(1, (noteDur - noteT) / 0.15);
                    sample += Math.sin(2 * Math.PI * n.freq * t) * 0.35 * env;
                }
            }
            data[i] = sample;
        }
        holdMusicSource = holdMusicCtx.createBufferSource();
        holdMusicSource.buffer = buf;
        const gain = holdMusicCtx.createGain();
        gain.gain.value = 0.7;
        holdMusicSource.connect(gain);
        gain.connect(holdMusicCtx.destination);
        holdMusicSource.start();
        console.log('[HoldMusic] Playing for', duration, 'seconds at', sr, 'Hz');
        addSystemMessage('🎵 Please hold...');
    } catch (e) {
        console.error('[HoldMusic] Failed:', e);
    }
}

function stopHoldMusic() {
    if (holdMusicSource) {
        try { holdMusicSource.stop(); } catch (_) {}
        holdMusicSource = null;
    }
    if (holdMusicCtx) {
        try { holdMusicCtx.close(); } catch (_) {}
        holdMusicCtx = null;
    }
}

// ── Handoff chime (short ascending two-note tone) ────────────────
function playHandoffChime() {
    if (!audioContext) return;
    const sr = audioContext.sampleRate;
    const duration = 1.2;
    const buf = audioContext.createBuffer(1, sr * duration, sr);
    const data = buf.getChannelData(0);
    // Note 1: G4 (392 Hz) for 0.4s, Note 2: C5 (523 Hz) for 0.6s
    for (let i = 0; i < sr * duration; i++) {
        const t = i / sr;
        let freq, amp;
        if (t < 0.4) {
            freq = 392.00; // G4
            amp = 0.1 * Math.min(1, t / 0.05) * Math.min(1, (0.4 - t) / 0.1);
        } else if (t < 0.5) {
            freq = 0; amp = 0; // brief silence
        } else {
            freq = 523.25; // C5
            amp = 0.12 * Math.min(1, (t - 0.5) / 0.05) * Math.min(1, (duration - t) / 0.3);
        }
        data[i] = amp * Math.sin(2 * Math.PI * freq * t);
    }
    const src = audioContext.createBufferSource();
    src.buffer = buf;
    src.connect(audioContext.destination);
    src.start();
}

// ── Message helpers ──────────────────────────────────────────────
function addSystemMessage(text) {
    const el = document.createElement('div');
    el.className = 'message system';
    el.textContent = text;
    appendMessage(el);
}

function addAgentMessage(text, agent) {
    const el = document.createElement('div');
    el.className = 'message agent';
    if (agent) {
        const label = document.createElement('div');
        label.className = 'agent-label';
        label.textContent = agent;
        el.appendChild(label);
    }
    const content = document.createElement('div');
    content.className = 'agent-content';
    content.textContent = text;
    el.appendChild(content);
    appendMessage(el);
}

function replaceLastAgentMessage(text, agent) {
    const container = document.getElementById('messages');
    const agents = container.querySelectorAll('.message.agent');
    if (agents.length === 0) return;
    const last = agents[agents.length - 1];
    const content = last.querySelector('.agent-content');
    if (content) {
        content.textContent = text;
    }
}

function addUserMessage(text) {
    const el = document.createElement('div');
    el.className = 'message user';
    el.textContent = text;
    appendMessage(el);
}

// ── Tool status (ChatGPT-style workflow steps) ───────────────────
function addToolStatus(label) {
    const container = document.getElementById('messages');
    let group = container.querySelector('.tool-status-group:last-child');

    // If the last element isn't a tool-status-group, or an agent message came in between, create new
    if (!group || group.nextElementSibling) {
        group = document.createElement('div');
        group.className = 'tool-status-group';
        container.appendChild(group);
    }

    const step = document.createElement('div');
    step.className = 'tool-step';
    step.innerHTML = `<span class="tool-step-spinner"></span><span class="tool-step-label">${label}</span>`;
    group.appendChild(step);

    // Animate in
    requestAnimationFrame(() => step.classList.add('visible'));

    container.scrollTop = container.scrollHeight;
}

function clearToolStatus() {
    const container = document.getElementById('messages');
    container.querySelectorAll('.tool-status-group').forEach(group => {
        group.querySelectorAll('.tool-step').forEach(step => {
            step.classList.add('done');
            step.querySelector('.tool-step-spinner')?.classList.add('done');
        });
        // Fade out after a short delay
        setTimeout(() => {
            group.classList.add('fade-out');
            setTimeout(() => group.remove(), 400);
        }, 600);
    });
}

function addHandoffMessage(text) {
    // Legacy fallback — rich version is used via addRichHandoffMessage
    const el = document.createElement('div');
    el.className = 'message handoff';
    el.innerHTML = `<div class="handoff-banner-header">Agent Handoff</div><div class="handoff-banner-body">${text}</div>`;
    appendMessage(el);
}

function appendMessage(el) {
    const container = document.getElementById('messages');
    container.appendChild(el);
    container.scrollTop = container.scrollHeight;
}

// ── Status helpers ───────────────────────────────────────────────
function updateStatus(state) {
    const el = document.getElementById('conn-status');
    if (state === 'connected') {
        el.textContent = 'Connected';
        el.className = 'status-value connected';
    } else {
        el.textContent = 'Disconnected';
        el.className = 'status-value disconnected';
    }
}

function updateDuration() {
    if (!callStart) return;
    const elapsed = Math.floor((Date.now() - callStart) / 1000);
    const m = Math.floor(elapsed / 60);
    const s = elapsed % 60;
    document.getElementById('call-duration').textContent =
        `${m}:${s.toString().padStart(2, '0')}`;
}

// ── Stop / cleanup ───────────────────────────────────────────────
function stopConversation() {
    if (ws) ws.close();
    cleanup();
    addSystemMessage('Call ended by user.');
}

function cleanup() {
    document.getElementById('btn-start').disabled = false;
    document.getElementById('btn-stop').disabled = true;
    updateStatus('disconnected');

    if (callTimer) { clearInterval(callTimer); callTimer = null; }
    if (scriptProcessor) { scriptProcessor.disconnect(); scriptProcessor = null; }
    if (mediaStream) {
        mediaStream.getTracks().forEach(t => t.stop());
        mediaStream = null;
    }
    if (audioContext) { audioContext.close(); audioContext = null; }
    ws = null;
    workletNode = null;
}
