from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import socket
import sys
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import quote

from azure.identity.aio import AzureCliCredential, ManagedIdentityCredential
from dotenv import load_dotenv
from quart import Quart, websocket, redirect
from websockets.asyncio.client import connect as ws_connect

# Ensure the server directory is on sys.path for agent imports
_server_dir = str(Path(__file__).resolve().parent)
if _server_dir not in sys.path:
    sys.path.insert(0, _server_dir)

from agents import AGENT_REGISTRY  # noqa: E402
from crm_tools import TOOL_FUNCTIONS  # noqa: E402
from sops import get_sop  # noqa: E402
from voice_transports import BrowserTransport, VoiceOutputTransport  # noqa: E402

load_dotenv()

# ──────────────────────────────────────────────────────────────────────────────
# Configuration
# ──────────────────────────────────────────────────────────────────────────────
VOICE_LIVE_ENDPOINT = os.getenv("AZURE_VOICE_LIVE_ENDPOINT", "")
VOICE_LIVE_API_KEY = os.getenv("AZURE_VOICE_LIVE_API_KEY", "")
VOICE_LIVE_MODEL = os.getenv("VOICE_LIVE_MODEL", "gpt-4.1-mini")
MANAGED_IDENTITY_CLIENT_ID = os.getenv(
    "AZURE_USER_ASSIGNED_IDENTITY_CLIENT_ID", ""
)

# ── BYO LLM ─────────────────────────────────────────────────────────────────
BYOM_PROFILE = os.getenv("BYOM_PROFILE", "")
FOUNDRY_RESOURCE_OVERRIDE = os.getenv("FOUNDRY_RESOURCE_OVERRIDE", "")

# ── Conversation summarization (token optimization for long calls) ───────────
SUMMARY_EVERY_N_TURNS = int(os.getenv("SUMMARY_EVERY_N_TURNS", "18"))
SUMMARY_KEEP_RECENT = int(os.getenv("SUMMARY_KEEP_RECENT", "6"))

# ──────────────────────────────────────────────────────────────────────────────
# Logging
# ──────────────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=getattr(logging, os.getenv("LOG_LEVEL", "INFO")),
    format="%(asctime)s %(name)s %(levelname)s: %(message)s",
)
logger = logging.getLogger("virtual_rm")
logging.getLogger("websockets").setLevel(logging.WARNING)
logging.getLogger("azure").setLevel(logging.WARNING)

# ── Tool name redaction (safety net for agent transcripts) ───────────────────
import re as _re
_TOOL_NAMES_FOR_REDACTION = [
    "get_customer_profile", "get_customer_summary", "get_eligibility_assessment",
    "get_credit_card_details", "get_credit_card_transactions", "get_reward_points",
    "get_card_spending_analysis", "check_card_upgrade_eligibility",
    "get_active_loans", "get_loan_product_details", "get_preapproved_offers",
    "get_negotiation_terms", "calculate_emi", "get_competitor_rates",
    "check_cibil_score", "check_rbi_repo_rate", "assess_collateral",
    "get_account_details", "get_fixed_deposits", "get_recurring_deposits",
    "get_savings_transactions", "get_fd_rate_card", "get_debit_card_details",
    "get_investments", "get_all_transactions", "route_to_agent", "play_hold_music",
]
_TOOL_NAME_PATTERN = _re.compile(
    r"\b(?:" + "|".join(_re.escape(n) for n in _TOOL_NAMES_FOR_REDACTION) + r")\b",
    _re.IGNORECASE,
)


def _redact_tool_names(text: str) -> str:
    """Replace any leaked tool names in agent speech with 'our system'."""
    return _TOOL_NAME_PATTERN.sub("our system", text)


def _route_confirmation_is_valid(
    pending_route: dict[str, Any] | None,
    intent: str,
    sub_intent: str,
    confirmation_evidence: str,
    latest_transcript: str,
    user_turn_count: int,
) -> bool:
    if not pending_route or not confirmation_evidence.strip():
        return False
    return (
        pending_route["intent"] == intent
        and pending_route["sub_intent"] == sub_intent
        and user_turn_count > pending_route["proposed_at_turn"]
        and confirmation_evidence.strip().casefold()
        == latest_transcript.strip().casefold()
    )


# ── Friendly labels for tool calls (shown in browser UI) ─────────────────────
TOOL_DISPLAY_LABELS = {
    "get_customer_profile": "Looking up your profile",
    "get_customer_summary": "Pulling your account summary",
    "get_eligibility_assessment": "Running eligibility check",
    "get_credit_card_details": "Fetching credit card details",
    "get_credit_card_transactions": "Loading recent transactions",
    "get_reward_points": "Checking reward points balance",
    "get_card_spending_analysis": "Analyzing spending patterns",
    "check_card_upgrade_eligibility": "Checking upgrade eligibility",
    "get_active_loans": "Fetching active loans",
    "get_loan_product_details": "Looking up loan products",
    "get_preapproved_offers": "Checking pre-approved offers",
    "get_negotiation_terms": "Invoking risk model",
    "calculate_emi": "Calculating EMI",
    "get_competitor_rates": "Fetching market rates",
    "check_cibil_score": "Pulling CIBIL score",
    "check_rbi_repo_rate": "Checking RBI repo rate",
    "get_account_details": "Fetching account details",
    "get_fixed_deposits": "Loading fixed deposits",
    "get_recurring_deposits": "Loading recurring deposits",
    "get_savings_transactions": "Loading recent transactions",
    "get_fd_rate_card": "Fetching FD rate card",
    "get_debit_card_details": "Fetching debit card info",
    "get_investments": "Loading investment portfolio",
    "get_all_transactions": "Pulling transaction history",
    "route_to_agent": "Connecting you to a specialist",
    "play_hold_music": "Checking with supervisor",
    "assess_collateral": "Assessing property collateral",
}

# ── Cached credential (avoids spawning az.cmd on every connection) ────────────
_cached_credential = None
_cached_token = None
_token_expiry = 0  # epoch seconds


# ──────────────────────────────────────────────────────────────────────────────
# Voice Live session configuration builder
# ──────────────────────────────────────────────────────────────────────────────
def build_session_config(
    agent_key: str,
    context_summary: str = "",
    customer_name: str = "",
    sub_intent: str = "",
    verification_required: bool = False,
) -> dict:
    """
    Build the session.update payload for a given agent.
    Assembles: context header + lean base prompt + SOP workflow.
    """
    agent = AGENT_REGISTRY[agent_key]
    base_prompt = agent["prompt"]

    # Look up the right SOP + its required tool names
    sop_text, sop_tool_names = get_sop(agent_key, sub_intent)

    # Assemble instructions: base prompt + SOP
    instructions = base_prompt
    if sop_text:
        instructions += "\n" + sop_text

    # Universal guardrail — appended to every agent's instructions
    instructions += (
        "\n\n# CRITICAL: NEVER EXPOSE TOOL OR FUNCTION NAMES\n"
        "- NEVER say tool names, function names, or API names to the customer. "
        "Examples of what you must NEVER say: 'get_loan_product_details', 'assess_collateral', 'calculate_emi', 'check_cibil_score', etc.\n"
        "- Instead of 'Let me call get_loan_product_details', say 'Let me look up the details for you.'\n"
        "- Instead of 'Running assess_collateral', say 'Let me assess the property details.'\n"
        "- A real bank RM would NEVER say function names. Speak naturally.\n"
    )

    # Inject customer name as context (greeting is handled by response.create)
    if customer_name:
        instructions = (
            f"CUSTOMER NAME: {customer_name}\n"
            f"Address the customer as {customer_name.split()[0]}. Do NOT repeat the greeting — it has already been delivered.\n\n"
            + instructions
        )

    if context_summary:
        first_name = customer_name.split()[0] if customer_name else "there"
        instructions = (
            f"CONTEXT FROM TRIAGE: The customer ({customer_name or 'unknown'}) was transferred to you. "
            f"Their query: {context_summary}\n\n"
            f"CRITICAL: You ARE the specialist. Do NOT say 'let me connect you' or 'let me transfer you'. "
            f"You are already connected.\n"
            f"Start with a brief personal introduction: 'Hello {first_name}, I'm [your name] from the [department]. "
            f"Let me look into that for you.' Then immediately call the relevant tools to fetch their data.\n"
            f"Do NOT repeat the triage agent's routing language.\n\n"
            + instructions
        )

    if verification_required:
        instructions = (
            "TELEPHONE VERIFICATION REQUIRED: Caller ID is not authentication. "
            "Before discussing any customer-specific information, ask the caller "
            "to enter their four-digit telephone PIN using the phone keypad. "
            "Do not ask them to speak the PIN and do not invoke CRM data tools "
            "until the system confirms verification.\n\n"
            + instructions
        )

    config = {
        "type": "session.update",
        "session": {
            "instructions": instructions,
            # ── Turn detection (VAD) ─────────────────────────────────────
            "turn_detection": {
                "type": "azure_semantic_vad",
                "threshold": 0.5,
                "speech_duration_ms": 200,
                "prefix_padding_ms": 700,
                "silence_duration_ms": 400,
                "remove_filler_words": True,
                "languages": ["en", "hi"],
                "create_response": True,
                "interrupt_response": True,
                "auto_truncate": True,
                "appended_text_after_truncation": " [The user interrupted me.]",
            },
            # ── Input audio transcription ────────────────────────────────
            "input_audio_transcription": {
                "model": "azure-speech",
                "language": "en-IN,hi-IN",
                "phrase_list": [
                    "Contoso Bank", "credit card", "debit card",
                    "savings account", "fixed deposit", "recurring deposit",
                    "home loan", "personal loan", "car loan", "education loan",
                    "EMI", "CIBIL", "KYC", "UPI", "NEFT", "RTGS", "IMPS",
                    "net banking", "mobile banking", "cheque book",
                    "reward points", "cashback", "annual fee",
                    "interest rate", "loan balance", "foreclose",
                    "Anika", "Meera", "Priya", "Kavya", "Riya",
                    "अनिका", "मीरा", "प्रिया", "काव्या", "रिया",
                ],
            },
            # ── Noise / echo handling ────────────────────────────────────
            "input_audio_noise_reduction": {
                "type": "azure_deep_noise_suppression",
            },
            "input_audio_echo_cancellation": {
                "type": "server_echo_cancellation",
            },
            # ── TTS voice ────────────────────────────────────────────────
            "voice": {
                "name": agent["voice"],
                "type": "azure-standard",
                "temperature": 0.5,
                "rate": "1.05",
            },
            # ── Model behaviour ──────────────────────────────────────────
            # "temperature": 0.1,
            "max_response_output_tokens": "1000",
        },
    }

    # Add tools — filter to only what the SOP needs
    if agent["tools"]:
        if sop_tool_names is not None:
            # SOP specifies exact tools needed — filter
            tools = [t for t in agent["tools"] if t["name"] in sop_tool_names]
        else:
            # Default/fallback — send all agent tools
            tools = agent["tools"]
        if tools:
            config["session"]["tools"] = tools
            config["session"]["tool_choice"] = "auto"

    return config


# ──────────────────────────────────────────────────────────────────────────────
# Authentication helper
# ──────────────────────────────────────────────────────────────────────────────
async def get_auth_headers() -> dict:
    """Build authentication headers for Voice Live WebSocket.
    Caches the credential and token to avoid spawning az.cmd on every call.
    """
    global _cached_credential, _cached_token, _token_expiry
    headers = {"x-ms-client-request-id": str(uuid.uuid4())}

    if VOICE_LIVE_API_KEY:
        headers["api-key"] = VOICE_LIVE_API_KEY
        logger.info("Auth: using API key")
        return headers

    scope = "https://cognitiveservices.azure.com/.default"
    now = time.time()

    # Reuse cached token if still valid (with 5-min buffer)
    if _cached_token and _token_expiry > now + 300:
        headers["Authorization"] = f"Bearer {_cached_token}"
        logger.info("Auth: using cached token (expires in %ds)", int(_token_expiry - now))
        return headers

    # Create credential if not cached
    if _cached_credential is None:
        if MANAGED_IDENTITY_CLIENT_ID:
            _cached_credential = ManagedIdentityCredential(
                client_id=MANAGED_IDENTITY_CLIENT_ID
            )
            logger.info("Auth: created Managed Identity credential")
        else:
            _cached_credential = AzureCliCredential()
            logger.info("Auth: created Azure CLI credential")

    t0 = time.time()
    token = await _cached_credential.get_token(scope)
    elapsed = time.time() - t0
    _cached_token = token.token
    _token_expiry = token.expires_on
    headers["Authorization"] = f"Bearer {_cached_token}"
    logger.info("Auth: fetched token in %.1fs (expires in %ds)",
                elapsed, int(_token_expiry - now))
    return headers


def build_wss_url() -> str:
    """Build the Voice Live WebSocket URL."""
    endpoint = VOICE_LIVE_ENDPOINT.rstrip("/")
    model = VOICE_LIVE_MODEL.strip()
    # Only convert the base endpoint to wss://, not query-parameter URLs
    wss_endpoint = endpoint.replace("https://", "wss://")
    url = (
        f"{wss_endpoint}/voice-live/realtime"
        f"?api-version=2026-01-01-preview&model={model}&debug=on"
    )
    if BYOM_PROFILE:
        url += f"&profile={BYOM_PROFILE}"
        if FOUNDRY_RESOURCE_OVERRIDE:
            url += f"&foundry-resource-override={FOUNDRY_RESOURCE_OVERRIDE}&debug=on"
    return url


# ──────────────────────────────────────────────────────────────────────────────
# Voice Live Session — manages a single call lifecycle
# ──────────────────────────────────────────────────────────────────────────────
class VoiceLiveSession:
    """
    Manages a single Voice Live session with agent handoff support.

    Flow:
      1. Browser connects via /web/ws (raw PCM16 audio)
      2. Server opens WebSocket to Voice Live API
      3. Triage agent greets the customer and identifies intent
      4. Triage agent calls route_to_agent(intent, summary)
      5. Session reconfigures with specialist agent's prompt (session.update)
      6. Specialist agent continues the conversation seamlessly
    """

    def __init__(
        self,
        output_transport: VoiceOutputTransport,
        customer_id: str = "rajesh",
        customer_verified: bool = True,
    ):
        self.output_transport = output_transport
        self.vl_ws: Any = None
        self._send_queue: asyncio.Queue = asyncio.Queue()
        self._user_speech_end_ts = None
        self._first_audio_latency_logged = False
        self._current_agent = "triage"
        self._call_id = str(uuid.uuid4())[:8]
        self._customer_id = customer_id
        self._customer_verified = customer_verified
        self._response_agent = "triage"  # agent that started the current response
        self._response_active = False  # True while a response is being generated
        self._pending_response_create = False  # deferred response.create after handoff
        self._pending_hold_music: int | None = None  # deferred hold music duration
        self._last_vl_event_ts: float = time.monotonic()  # heartbeat tracking
        self._response_watchdog: asyncio.Task | None = None  # safety net for dead sessions
        self._last_transcription_empty: bool = True  # track if last speech had real content
        self._tool_call_counts: dict[str, int] = {}  # loop guard: per-tool call count within a response cycle
        self._conversation_item_ids: list[str] = []  # ordered list of conversation item IDs
        self._retrieved_items: dict[str, dict] = {}  # item_id → item data (populated at close)
        self._retrieve_pending = 0  # counter for in-flight retrieval requests
        self._transcript_log: list[tuple[str, str]] = []  # local (role, text) pairs for compaction
        self._pending_route: dict[str, Any] | None = None
        # ── Summarization state ──────────────────────────────────────────────
        self._user_turn_count = 0
        self._last_summarized_at_turn = 0
        self._compaction_running = False
        # ── Barge-in transcript truncation ────────────────────────────────────
        self._last_agent_transcript: tuple[str, str] | None = None  # (text, agent_name)
        self._response_audio_bytes: int = 0  # audio bytes sent in current response
        self._response_truncated: bool = False  # set when truncated fires before transcript.done
        self._truncation_audio_end_ms: int = 0  # audio_end_ms from the truncation event

    # ── 1. Connect to Voice Live ─────────────────────────────────────────

    async def start(self, auth_task=None):
        """Open WebSocket to Voice Live, send triage config, spawn loops."""
        url = build_wss_url()
        # Use pre-started auth task if available, otherwise fetch fresh
        if auth_task:
            headers = await auth_task
        else:
            headers = await get_auth_headers()

        logger.info("[%s] Connecting to Voice Live: %s", self._call_id, url)
        try:
            # Run WebSocket connect and CRM lookup in parallel
            from crm_tools import get_customer_profile

            async def _connect_ws():
                return await ws_connect(
                    url, additional_headers=headers, family=socket.AF_INET,
                    max_size=16 * 1024 * 1024,  # 16MB — retrieved items include audio
                )

            async def _lookup_customer():
                # SQLite is sync but fast — wrap for gather()
                return get_customer_profile(self._customer_id)

            ws_result, profile = await asyncio.gather(
                _connect_ws(), _lookup_customer()
            )
            self.vl_ws = ws_result
            self._customer_name = (
                profile.get("name", "")
                if self._customer_verified and isinstance(profile, dict)
                else ""
            )
        except Exception as exc:
            logger.error(
                "[%s] Voice Live connection failed: %s", self._call_id, exc
            )
            await self._send_to_browser(
                json.dumps({"Kind": "AgentTranscription",
                 "Text": f"Connection failed: {exc}",
                 "Agent": "System"})
            )
            return
        logger.info(
            "[%s] Voice Live connected — starting with TRIAGE agent",
            self._call_id,
        )

        # Send triage agent config
        await self._send_json(build_session_config(
            "triage",
            customer_name=self._customer_name,
            verification_required=not self._customer_verified,
        ))

        # Trigger the opening greeting with explicit text to skip model inference.
        # The model only needs to synthesize speech, not figure out what to say.
        first_name = self._customer_name.split()[0] if self._customer_name else "there"
        await self._send_json({
            "type": "response.create",
            "response": {
                "modalities": ["audio", "text"],
                "instructions": (
                    f"Say exactly: 'Hello {first_name}! Welcome to Contoso Bank. "
                    f"I'm Anika, your Virtual RM. How can I help you today?'"
                ),
            },
        })

        # Notify browser of current agent
        await self._send_agent_info("triage")

        # Start bidirectional relay loops
        asyncio.create_task(self._receiver_loop())
        asyncio.create_task(self._sender_loop())
        asyncio.create_task(self._heartbeat_loop())

    async def complete_phone_verification(self) -> None:
        from crm_tools import get_customer_profile

        profile = get_customer_profile(self._customer_id)
        self._customer_verified = True
        self._customer_name = profile.get("name", "") if isinstance(profile, dict) else ""
        await self._send_json(build_session_config(
            self._current_agent,
            customer_name=self._customer_name,
        ))
        await self._send_json({
            "type": "response.create",
            "response": {
                "modalities": ["audio", "text"],
                "instructions": "Confirm verification succeeded, then ask how you can help.",
            },
        })

    async def reject_phone_verification(self) -> None:
        await self._send_json({
            "type": "response.create",
            "response": {
                "modalities": ["audio", "text"],
                "instructions": (
                    "Say the PIN was not accepted. Ask the caller to try again "
                    "using the phone keypad, without saying the digits aloud."
                ),
            },
        })

    # ── 2. Agent Handoff ─────────────────────────────────────────────────

    async def _handle_agent_handoff(
        self, intent: str, summary: str, sub_intent: str = ""
    ):
        """
        Switch from triage to a specialist agent mid-conversation.
        Sends session.update with: lean base prompt + SOP for sub_intent + context.
        """
        if intent not in AGENT_REGISTRY:
            logger.warning(
                "[%s] Unknown intent '%s', defaulting to general_banking",
                self._call_id,
                intent,
            )
            intent = "general_banking"

        agent_info = AGENT_REGISTRY[intent]
        logger.info(
            "[%s] ✦ HANDOFF: %s → %s [sop=%s] (summary: %s)",
            self._call_id,
            AGENT_REGISTRY[self._current_agent]["name"],
            agent_info["name"],
            sub_intent or "default",
            summary,
        )

        self._current_agent = intent

        # Reconfigure the session with the specialist agent + SOP
        new_config = build_session_config(
            intent,
            context_summary=summary,
            customer_name=self._customer_name,
            sub_intent=sub_intent,
        )
        await self._send_json(new_config)

        # Trigger the specialist's opening response
        await self._safe_response_create()

        # Notify browser
        await self._send_agent_info(intent)

    # ── 3. Browser → Voice Live (sender) ─────────────────────────────────

    async def handle_browser_audio(self, raw_pcm: bytes):
        """Queue raw PCM16 audio from the browser for Voice Live."""
        audio_b64 = base64.b64encode(raw_pcm).decode("ascii")
        await self._send_queue.put(
            json.dumps({
                "type": "input_audio_buffer.append",
                "audio": audio_b64,
            })
        )

    async def _sender_loop(self):
        """Drain queue and forward to Voice Live WebSocket."""
        try:
            while True:
                msg = await self._send_queue.get()
                if self.vl_ws:
                    try:
                        await self.vl_ws.send(msg)
                    except Exception:
                        logger.warning("[%s] Voice Live connection lost", self._call_id)
                        break
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("[%s] Sender loop error", self._call_id)

    # ── 4. Voice Live → Browser (receiver) ───────────────────────────────

    async def _receiver_loop(self):
        """Handle all Voice Live events, including function calls for routing."""
        try:
            async for message in self.vl_ws:
                self._last_vl_event_ts = time.monotonic()  # heartbeat
                event = json.loads(message)
                event_type = event.get("type")

                match event_type:
                    # ── Lifecycle ─────────────────────────────────────────
                    case "session.created":
                        vl_session_id = event.get("session", {}).get("id", "unknown")
                        logger.info(
                            "[%s] Session created (vl_session_id=%s)",
                            self._call_id,
                            vl_session_id,
                        )

                    case "conversation.item.created":
                        item = event.get("item", {})
                        item_id = item.get("id", "")
                        # Skip interim response items — they're ephemeral and get removed
                        # once the real response arrives
                        if item_id and not item_id.startswith("interim_"):
                            self._conversation_item_ids.append(item_id)

                    case "conversation.item.retrieved":
                        item = event.get("item", {})
                        item_id = item.get("id", "")
                        if item_id:
                            self._retrieved_items[item_id] = item
                        self._retrieve_pending -= 1

                    case "session.updated":
                        logger.info(
                            "[%s] Session updated (agent: %s)",
                            self._call_id,
                            AGENT_REGISTRY[self._current_agent]["name"],
                        )

                    case "input_audio_buffer.cleared":
                        pass

                    # ── User speech events ────────────────────────────────
                    case "input_audio_buffer.speech_started":
                        await self._send_to_browser(
                            json.dumps({"Kind": "StopAudio"})
                        )

                    case "input_audio_buffer.speech_stopped":
                        self._user_speech_end_ts = time.monotonic()
                        self._first_audio_latency_logged = False
                        self._last_transcription_empty = True  # assume empty until transcription proves otherwise
                        # Start watchdog: if no response starts within 5s, force one
                        if self._response_watchdog and not self._response_watchdog.done():
                            self._response_watchdog.cancel()
                        self._response_watchdog = asyncio.create_task(
                            self._response_watchdog_timer()
                        )

                    # ── User transcription ────────────────────────────────
                    case "conversation.item.input_audio_transcription.completed":
                        self._tool_call_counts.clear()  # reset loop guard on new user input
                        transcript = event.get("transcript", "")
                        stt_lang = event.get("language", "")
                        # Track whether this was real speech or just noise
                        if transcript.strip():
                            self._last_transcription_empty = False
                            self._user_turn_count += 1
                            self._transcript_log.append(("user", transcript.strip()))
                        logger.info(
                            "[%s] USER [lang=%s]: %s",
                            self._call_id,
                            stt_lang,
                            transcript,
                        )
                        await self._send_to_browser(
                            json.dumps({
                                "Kind": "UserTranscription",
                                "Text": transcript,
                                "Language": stt_lang,
                            })
                        )

                    case "conversation.item.input_audio_transcription.failed":
                        logger.error(
                            "[%s] Transcription failed: %s",
                            self._call_id,
                            event.get("error"),
                        )

                    # ── Function call (agent routing) ─────────────────────
                    case "response.function_call_arguments.done":
                        await self._handle_function_call(event)

                    # ── Agent response audio ─────────────────────────────
                    case "response.audio.delta":
                        if (
                            self._user_speech_end_ts
                            and not self._first_audio_latency_logged
                        ):
                            latency_ms = int(
                                (time.monotonic() - self._user_speech_end_ts)
                                * 1000
                            )
                            logger.info(
                                "[%s] Time to first audio byte: [latency=%dms]",
                                self._call_id,
                                latency_ms,
                            )
                            self._first_audio_latency_logged = True

                        delta = event.get("delta", "")
                        audio_bytes = base64.b64decode(delta)
                        self._response_audio_bytes += len(audio_bytes)
                        await self._send_to_browser(audio_bytes)

                    # ── Agent transcript ──────────────────────────────────
                    case "response.audio_transcript.done":
                        transcript = event.get("transcript", "").strip()
                        if not transcript:
                            break
                        agent_name = AGENT_REGISTRY[self._response_agent]["name"]
                        transcript = _redact_tool_names(transcript)
                        logger.info(
                            "[%s] AGENT (%s): %s",
                            self._call_id,
                            agent_name,
                            transcript,
                        )
                        self._transcript_log.append(("agent", transcript))

                        # Case B: truncation already fired before transcript arrived
                        if self._response_truncated:
                            transcript = self._truncate_text(
                                transcript, self._truncation_audio_end_ms
                            )
                            self._response_truncated = False

                        self._last_agent_transcript = (transcript, agent_name)
                        await self._send_to_browser(
                            json.dumps({
                                "Kind": "AgentTranscription",
                                "Text": transcript,
                                "Agent": agent_name,
                            })
                        )

                    # ── Truncation (interruption) ────────────────────────
                    case "conversation.item.truncated":
                        audio_end_ms = event.get("audio_end_ms", 0)
                        logger.info(
                            "[%s] Response truncated (user interrupted). item_id=%s audio_end_ms=%d",
                            self._call_id,
                            event.get("item_id"),
                            audio_end_ms,
                        )
                        if self._last_agent_transcript:
                            # Case A: transcript already sent — replace it on the UI
                            text, agent_name = self._last_agent_transcript
                            text = self._truncate_text(text, audio_end_ms)
                            await self._send_to_browser(
                                json.dumps({
                                    "Kind": "ReplaceLastAgent",
                                    "Text": text,
                                    "Agent": agent_name,
                                })
                            )
                            self._last_agent_transcript = None
                        else:
                            # Case B: transcript hasn't arrived yet — set flag for when it does
                            self._response_truncated = True
                            self._truncation_audio_end_ms = audio_end_ms

                    # ── Intermediate events (ignored) ────────────────────
                    case (
                        "response.created"
                        | "response.output_item.added"
                        | "response.audio_transcript.delta"
                        | "response.function_call_arguments.delta"
                    ):
                        if event_type == "response.created":
                            self._response_agent = self._current_agent
                            self._response_active = True
                            self._response_audio_bytes = 0
                            self._response_truncated = False
                            self._truncation_audio_end_ms = 0
                            # Cancel watchdog — response started normally
                            if self._response_watchdog and not self._response_watchdog.done():
                                self._response_watchdog.cancel()
                                self._response_watchdog = None

                    # ── Response complete ─────────────────────────────────
                    case "response.done":
                        self._response_active = False
                        resp = event.get("response", {})
                        status = resp.get("status")
                        if status == "cancelled":
                            details = resp.get("status_details", {})
                            logger.info(
                                "[%s] Response cancelled (reason=%s)",
                                self._call_id,
                                details.get("reason", "unknown"),
                            )
                            # Clear deferred state so hold music doesn't play
                            # when the agent never got to say "please hold".
                            if self._pending_hold_music is not None:
                                logger.info("[%s] Clearing pending hold music (response was cancelled)", self._call_id)
                                self._pending_hold_music = None
                            self._pending_response_create = False
                        elif status != "completed":
                            logger.error(
                                "[%s] Response error: %s",
                                self._call_id,
                                json.dumps(resp.get("status_details", {})),
                            )

                        # Play deferred hold music AFTER agent finishes speaking
                        if self._pending_hold_music is not None:
                            duration = self._pending_hold_music
                            self._pending_hold_music = None
                            logger.info("[%s] 🎵 Playing hold music (%ds)", self._call_id, duration)
                            await self._send_to_browser(
                                json.dumps({"Kind": "PlayHoldMusic", "Duration": duration})
                            )
                            await asyncio.sleep(duration)
                            logger.info("[%s] 🎵 Hold music finished, injecting thank-for-waiting instruction", self._call_id)
                            # Inject a system hint so the model thanks the customer for waiting
                            await self._send_json({
                                "type": "conversation.item.create",
                                "item": {
                                    "type": "message",
                                    "role": "user",
                                    "content": [{
                                        "type": "input_text",
                                        "text": "[System: Hold music has ended. Start your response by thanking the customer for waiting before delivering your answer.]",
                                    }],
                                },
                            })
                            # Use safe create — VAD may have already started a response
                            await self._safe_response_create()
                        # Fire deferred response.create (from handoff or tool calls)
                        elif self._pending_response_create:
                            self._pending_response_create = False
                            logger.info("[%s] Firing deferred response.create", self._call_id)
                            await self._send_json({"type": "response.create"})

                        # ── Trigger background summarization (non-blocking) ──
                        if (
                            status == "completed"
                            and SUMMARY_EVERY_N_TURNS > 0
                            and not self._compaction_running
                            and (self._user_turn_count - self._last_summarized_at_turn) >= SUMMARY_EVERY_N_TURNS
                        ):
                            asyncio.create_task(self._compact_conversation())

                    # ── Errors ────────────────────────────────────────────
                    case "error":
                        err = event.get("error", {})
                        code = err.get("code", "")
                        if code == "item_retrieve_invalid_item_id":
                            # Item was removed due to barge-in truncation or cancelled response
                            # Must decrement pending counter to avoid hanging on retrieval
                            self._retrieve_pending -= 1
                            logger.debug(
                                "[%s] Item retrieve failed (invalid item_id) — likely truncated",
                                self._call_id,
                            )
                        else:
                            logger.error(
                                "[%s] Voice Live error: %s",
                                self._call_id,
                                json.dumps(event),
                            )

                    case _:
                        logger.debug(
                            "[%s] Unhandled event: %s",
                            self._call_id,
                            event_type,
                        )

        except Exception:
            logger.exception("[%s] Receiver loop error", self._call_id)

    # ── Function call handler ────────────────────────────────────────────

    async def _handle_function_call(self, event: dict):
        """
        Process function calls from the LLM.
        Currently handles 'route_to_agent' for triage → specialist handoff.
        """
        call_id = event.get("call_id", "")
        fn_name = event.get("name", "")
        args_str = event.get("arguments", "{}")

        # ── Loop guard: cap repeated calls to the same tool ──────────
        MAX_TOOL_CALLS_PER_CYCLE = 3
        self._tool_call_counts[fn_name] = self._tool_call_counts.get(fn_name, 0) + 1
        if self._tool_call_counts[fn_name] > MAX_TOOL_CALLS_PER_CYCLE:
            blocked_count = self._tool_call_counts[fn_name] - MAX_TOOL_CALLS_PER_CYCLE
            logger.warning(
                "[%s] Tool loop detected: %s called %d times (blocked #%d) — returning error",
                self._call_id, fn_name, self._tool_call_counts[fn_name], blocked_count,
            )
            await self._send_json({
                "type": "conversation.item.create",
                "item": {
                    "type": "function_call_output",
                    "call_id": call_id,
                    "output": json.dumps({
                        "error": f"STOP. Tool '{fn_name}' already called {MAX_TOOL_CALLS_PER_CYCLE} times. "
                                 "Do NOT call this tool again. Respond to the customer using the data you already have.",
                    }),
                },
            })
            if blocked_count <= 1:
                # Give the model ONE more chance (first blocked call).
                await self._safe_response_create()
            else:
                # Force a speech-only response — inject a strong instruction
                # and prevent any further tool calls so the model MUST speak.
                logger.warning(
                    "[%s] Forcing speech-only response to break tool loop for %s",
                    self._call_id, fn_name,
                )
                await self._send_json({
                    "type": "conversation.item.create",
                    "item": {
                        "type": "message",
                        "role": "user",
                        "content": [{
                            "type": "input_text",
                            "text": (
                                "[System: CRITICAL — You are stuck in a tool loop. "
                                "Do NOT call any tool. Respond to the customer RIGHT NOW "
                                "using the information you already have. Summarize what you know "
                                "and ask the customer how to proceed.]"
                            ),
                        }],
                    },
                })
                await self._safe_response_create()
            return

        logger.info(
            "[%s] Function call: %s(%s)",
            self._call_id,
            fn_name,
            args_str,
        )

        # Send workflow step to browser UI
        label = TOOL_DISPLAY_LABELS.get(fn_name)
        if label:
            await self._send_to_browser(
                json.dumps({"Kind": "ToolStatus", "Tool": fn_name, "Label": label})
            )

        if fn_name == "route_to_agent":
            try:
                args = json.loads(args_str)
            except json.JSONDecodeError:
                args = {"intent": "general_banking", "summary": ""}

            action = args.get("action", "request_confirmation")
            intent = args.get("intent", "general_banking")
            sub_intent = args.get("sub_intent", "general")
            summary = args.get("summary", "")
            latest_transcript = next(
                (text for role, text in reversed(self._transcript_log) if role == "user"),
                "",
            )

            if action == "request_confirmation":
                self._pending_route = {
                    "intent": intent,
                    "sub_intent": sub_intent,
                    "summary": summary,
                    "proposed_at_turn": self._user_turn_count,
                }
                await self._send_json({
                    "type": "conversation.item.create",
                    "item": {
                        "type": "function_call_output",
                        "call_id": call_id,
                        "output": json.dumps({
                            "status": "confirmation_required",
                            "message": (
                                "Ask the caller to confirm your understanding before routing. "
                                "Do not announce or perform a transfer yet."
                            ),
                        }),
                    },
                })
                await self._safe_response_create()
                return

            confirmation_evidence = args.get("confirmation_evidence", "")
            if not _route_confirmation_is_valid(
                self._pending_route,
                intent,
                sub_intent,
                confirmation_evidence,
                latest_transcript,
                self._user_turn_count,
            ):
                logger.warning(
                    "[%s] Rejected unconfirmed route (intent=%s, turn=%d)",
                    self._call_id,
                    intent,
                    self._user_turn_count,
                )
                await self._send_json({
                    "type": "conversation.item.create",
                    "item": {
                        "type": "function_call_output",
                        "call_id": call_id,
                        "output": json.dumps({
                            "status": "rejected",
                            "message": (
                                "Routing was not confirmed on a later caller turn. "
                                "Clarify the request and ask for confirmation again."
                            ),
                        }),
                    },
                })
                await self._safe_response_create()
                return

            summary = self._pending_route["summary"]
            self._pending_route = None

            # Send function call output (acknowledge the call)
            await self._send_json({
                "type": "conversation.item.create",
                "item": {
                    "type": "function_call_output",
                    "call_id": call_id,
                    "output": json.dumps({
                        "status": "success",
                        "message": f"Routing to {intent} specialist [sop={sub_intent}]",
                    }),
                },
            })

            # Perform the handoff with sub_intent for SOP activation
            await self._handle_agent_handoff(intent, summary, sub_intent)

        elif fn_name == "play_hold_music":
            # ── Hold music — DEFERRED until current response finishes ────
            # The model says "please hold" as audio in the same response.
            # We defer music playback until response.done so the spoken
            # hold message plays BEFORE the music starts.
            try:
                args = json.loads(args_str) if args_str.strip() else {}
            except json.JSONDecodeError:
                args = {}
            duration = args.get("duration", 5)
            logger.info("[%s] 🎵 Hold music queued (%ds, will play after response finishes)", self._call_id, duration)

            # Store for later — will fire in response.done handler
            self._pending_hold_music = duration

            # Return tool output immediately so the model can finish speaking
            await self._send_json({
                "type": "conversation.item.create",
                "item": {
                    "type": "function_call_output",
                    "call_id": call_id,
                    "output": json.dumps({
                        "status": "hold_music_queued",
                        "message": "Hold music will play after you finish speaking. Finish your hold announcement now. After the music ends, your next response MUST start with thanking the customer for waiting before delivering your answer.",
                    }),
                },
            })
            # Do NOT trigger response.create here — let the model finish
            # its current response (saying "please hold"), then music
            # plays on response.done, then we trigger a new response.

        elif fn_name in TOOL_FUNCTIONS:
            # ── CRM data tool call ───────────────────────────────────────
            try:
                args = json.loads(args_str) if args_str.strip() else {}
            except json.JSONDecodeError:
                args = {}

            if not self._customer_verified:
                await self._send_json({
                    "type": "conversation.item.create",
                    "item": {
                        "type": "function_call_output",
                        "call_id": call_id,
                        "output": json.dumps({
                            "error": "Telephone PIN verification is required before customer data can be accessed."
                        }),
                    },
                })
                await self._safe_response_create()
                return

            tool_fn = TOOL_FUNCTIONS[fn_name]

            # Determine which params the function needs
            import inspect
            sig = inspect.signature(tool_fn)
            call_kwargs = {}
            for param_name in sig.parameters:
                if param_name == "customer_id":
                    call_kwargs["customer_id"] = self._customer_id
                elif param_name in args:
                    call_kwargs[param_name] = args[param_name]

            try:
                result = tool_fn(**call_kwargs)
            except Exception as exc:
                logger.exception("[%s] CRM tool error: %s", self._call_id, fn_name)
                result = {"error": str(exc)}

            logger.info(
                "[%s] Tool %s → %d chars",
                self._call_id, fn_name, len(json.dumps(result)),
            )

            # Return the result to the model
            await self._send_json({
                "type": "conversation.item.create",
                "item": {
                    "type": "function_call_output",
                    "call_id": call_id,
                    "output": json.dumps(result),
                },
            })

            # Trigger the model to continue with the data
            await self._safe_response_create()

        else:
            logger.warning(
                "[%s] Unknown function call: %s",
                self._call_id,
                fn_name,
            )

    # ── Helpers ───────────────────────────────────────────────────────────

    async def _safe_response_create(self):
        """Send response.create, or defer if a response is already active."""
        if self._response_active:
            logger.info("[%s] Deferring response.create (response still active)", self._call_id)
            self._pending_response_create = True
        else:
            await self._send_json({"type": "response.create"})

    async def _response_watchdog_timer(self):
        """Safety net: if no response starts within 5s of speech ending, force one."""
        try:
            await asyncio.sleep(5)
            if not self._response_active:
                # Don't force a response for empty transcriptions (noise/breathing)
                if self._last_transcription_empty:
                    logger.debug(
                        "[%s] Watchdog: skipping — last transcription was empty (noise/breathing)",
                        self._call_id,
                    )
                    return
                logger.warning(
                    "[%s] ⚠️ Watchdog: no response 5s after speech ended — forcing response.create",
                    self._call_id,
                )
                await self._send_json({"type": "response.create"})
        except asyncio.CancelledError:
            pass  # Normal — response started before timeout

    async def _heartbeat_loop(self):
        """Detect dead Voice Live connections and notify the browser."""
        try:
            while self.vl_ws and not self.vl_ws.close_code:
                await asyncio.sleep(10)
                silence = time.monotonic() - self._last_vl_event_ts
                if silence > 30:
                    logger.error(
                        "[%s] 💔 No Voice Live events for %.0fs — connection appears dead",
                        self._call_id, silence,
                    )
                    await self._send_to_browser(
                        json.dumps({
                            "Kind": "AgentTranscription",
                            "Text": "Connection lost. Please refresh the page to reconnect.",
                            "Agent": "System",
                        })
                    )
                    break
        except asyncio.CancelledError:
            pass
        except Exception:
            pass

    async def _send_json(self, obj: dict):
        if self.vl_ws:
            await self.vl_ws.send(json.dumps(obj))

    async def _send_to_browser(self, data):
        try:
            await self.output_transport.send(data)
        except Exception:
            logger.exception("[%s] Failed to send to voice client", self._call_id)

    async def _send_agent_info(self, agent_key: str):
        """Notify browser which agent is currently active."""
        agent = AGENT_REGISTRY[agent_key]
        await self._send_to_browser(
            json.dumps({
                "Kind": "AgentSwitch",
                "Agent": agent["name"],
                "AgentKey": agent_key,
            })
        )

    def _truncate_text(self, text: str, audio_end_ms: int) -> str:
        """Truncate transcript to what the user heard, based on audio timing."""
        sent_s = self._response_audio_bytes / 48000  # PCM16 @ 24kHz
        heard_s = audio_end_ms / 1000
        # Only truncate if we have a reliable audio_end_ms (> 0)
        # API sometimes returns 0 even when user heard audio
        if audio_end_ms > 0 and sent_s > 0 and heard_s < sent_s:
            heard_ratio = heard_s / sent_s
            chars_heard = int(len(text) * heard_ratio)
            if chars_heard < len(text):
                cut = text[:chars_heard].rfind(" ")
                if cut > 0:
                    text = text[:cut]
        return text + " [interrupted]"

    async def _compact_conversation(self):
        """
        Background task: summarize older conversation items and delete them
        to reduce token consumption. Runs only when no response is active and
        user is not speaking, so the user is never interrupted.
        """
        if self._compaction_running:
            return
        self._compaction_running = True
        try:
            # Wait until no response is in-flight (user finished hearing the agent)
            for _ in range(50):  # up to 5s
                if not self._response_active:
                    break
                await asyncio.sleep(0.1)

            total_ids = len(self._conversation_item_ids)
            keep = max(SUMMARY_KEEP_RECENT, 4)
            if total_ids <= keep:
                return

            old_ids = set(self._conversation_item_ids[:-keep])

            # Build summary from local transcript log (no network round-trip)
            lines: list[str] = []
            remaining: list[tuple[str, str]] = []
            # We don't have a 1:1 mapping of transcript entries to item IDs,
            # so summarize the oldest entries proportionally
            entries_to_summarize = max(0, len(self._transcript_log) - keep)
            for i, (role, text) in enumerate(self._transcript_log):
                if i < entries_to_summarize:
                    speaker = "Customer" if role == "user" else "Agent"
                    if len(text) > 200:
                        text = text[:200] + "..."
                    lines.append(f"- {speaker}: {text}")
                else:
                    remaining.append((role, text))

            if not lines:
                return

            summary = "\n".join(lines)

            # Inject summary as a single context item
            await self._send_json({
                "type": "conversation.item.create",
                "item": {
                    "type": "message",
                    "role": "user",
                    "content": [{
                        "type": "input_text",
                        "text": (
                            "[System — Conversation Summary for context. "
                            "Do NOT read this aloud. Use as memory of earlier turns.]\n"
                            f"{summary}"
                        ),
                    }],
                },
            })

            # Delete old items from Voice Live context
            for item_id in self._conversation_item_ids[:-keep]:
                await self._send_json({"type": "conversation.item.delete", "item_id": item_id})

            # Update local tracking
            self._conversation_item_ids = self._conversation_item_ids[-keep:]
            self._transcript_log = remaining
            self._last_summarized_at_turn = self._user_turn_count
            logger.info(
                "[%s] ✂️ Compacted conversation at turn %d (summarized=%d entries, kept=%d)",
                self._call_id, self._user_turn_count, entries_to_summarize, len(remaining),
            )
        except Exception:
            logger.exception("[%s] Conversation compaction failed", self._call_id)
        finally:
            self._compaction_running = False

    async def _dump_conversation_history(self):
        """
        Retrieve all remaining conversation items at session close
        via conversation.item.retrieve and log the full history.
        This is the ONLY time we use retrieval — one-time at close, acceptable cost.
        """
        if not self.vl_ws or not self._conversation_item_ids:
            return

        logger.info(
            "[%s] Retrieving %d conversation items for audit log...",
            self._call_id,
            len(self._conversation_item_ids),
        )
        self._retrieved_items = {}
        self._retrieve_pending = len(self._conversation_item_ids)

        for item_id in self._conversation_item_ids:
            await self._send_json({
                "type": "conversation.item.retrieve",
                "item_id": item_id,
            })

        # Wait for all retrieve responses (up to 5s timeout)
        deadline = time.monotonic() + 5.0
        while self._retrieve_pending > 0 and time.monotonic() < deadline:
            await asyncio.sleep(0.1)

        if self._retrieve_pending > 0:
            logger.warning(
                "[%s] Timed out waiting for %d item retrievals",
                self._call_id,
                self._retrieve_pending,
            )

        logger.info("[%s] " + "=" * 50, self._call_id)
        logger.info("[%s] CONVERSATION HISTORY (as seen by LLM)", self._call_id)
        logger.info("[%s] " + "-" * 50, self._call_id)

        for item_id in self._conversation_item_ids:
            item = self._retrieved_items.get(item_id, {})
            if not item:
                continue
            role = item.get("role", item.get("type", "?"))
            contents = item.get("content", [])
            texts = []
            for part in contents:
                if part.get("text"):
                    texts.append(part["text"])
                elif part.get("transcript"):
                    texts.append(part["transcript"])
                elif part.get("type") == "input_audio":
                    texts.append("[audio]")
            text = " ".join(texts) if texts else "(no text content)"
            if len(text) > 300:
                text = text[:300] + "..."
            logger.info(
                "[%s]   %s: %s",
                self._call_id,
                role.upper(),
                text,
            )
        logger.info("[%s] " + "=" * 50, self._call_id)

    async def close(self):
        # ── Retrieve full conversation history from Voice Live ────
        await self._dump_conversation_history()
        
        if self.vl_ws:
            try:
                await self.vl_ws.close()
            except Exception:
                pass


# ──────────────────────────────────────────────────────────────────────────────
# Quart app
# ──────────────────────────────────────────────────────────────────────────────
app = Quart(__name__, static_folder="static")

from acs_telephony import register_acs_routes  # noqa: E402

register_acs_routes(app, VoiceLiveSession)


@app.route("/")
async def index():
    return redirect("/login")


@app.route("/login")
async def login_page():
    return await app.send_static_file("login.html")


@app.route("/home")
async def home_page():
    return await app.send_static_file("home.html")


@app.route("/chat")
async def chat_page():
    return await app.send_static_file("index.html")


@app.websocket("/web/ws")
async def web_ws():
    """
    Browser WebSocket endpoint.

    Protocol:
        Browser → Server:  raw PCM16 bytes (ArrayBuffer)
        Server → Browser:  raw PCM16 bytes (TTS audio)
                           OR JSON: {"Kind": "StopAudio"}
                           OR JSON: {"Kind": "AgentTranscription", "Text": "...", "Agent": "..."}
                           OR JSON: {"Kind": "UserTranscription", "Text": "...", "Language": "..."}
                           OR JSON: {"Kind": "AgentSwitch", "Agent": "...", "AgentKey": "..."}
    """
    logger.info("Browser connected")

    # Start auth + WSS connection IN PARALLEL with waiting for customer ID
    # This overlaps the ~1.2s WSS connect with the browser→server message latency
    auth_task = asyncio.create_task(get_auth_headers())

    # First text message from browser is the customer ID
    customer_id = "rajesh"  # default fallback
    try:
        first_msg = await websocket.receive()
        if isinstance(first_msg, str):
            data = json.loads(first_msg)
            customer_id = data.get("customerId", "rajesh")
            logger.info("Customer ID: %s", customer_id)
    except Exception:
        pass

    # Pass the pre-started auth task to the session
    session = VoiceLiveSession(
        BrowserTransport(websocket),
        customer_id=customer_id,
    )
    asyncio.create_task(session.start(auth_task=auth_task))

    try:
        while True:
            msg = await websocket.receive()
            if isinstance(msg, bytes):
                await session.handle_browser_audio(msg)
    except asyncio.CancelledError:
        pass
    except Exception:
        logger.exception("Web WebSocket error")
    finally:
        await session.close()


# ──────────────────────────────────────────────────────────────────────────────
# Startup — pre-warm auth token so first connection is fast
# ──────────────────────────────────────────────────────────────────────────────
@app.before_serving
async def _prewarm_auth():
    """Fetch auth token at startup so the first browser connection is instant."""
    if not VOICE_LIVE_API_KEY:
        logger.info("Pre-warming auth token...")
        try:
            await get_auth_headers()
            logger.info("Auth token pre-warmed successfully")
        except Exception as e:
            logger.warning("Auth pre-warm failed (will retry on first connection): %s", e)


# ──────────────────────────────────────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    app.run(
        debug=os.getenv("APP_DEBUG", "false").lower() == "true",
        host=os.getenv("APP_HOST", "0.0.0.0"),
        port=int(os.getenv("APP_PORT", "8000")),
    )
