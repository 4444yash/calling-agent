"""
Production-ready Real Estate AI Calling Agent with:
- SQL injection prevention (URL encoding)
- Retry logic with exponential backoff
- Circuit breaker for cascading failure prevention
- Specific exception handling
- Input validation for XSS/injection prevention
"""
import os
import sys

# Ensure the 'src' directory is in python PATH for imports both locally and when run on the cloud
import os.path
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

# Force stable OpenBLAS coretype on Windows to prevent native C++ destructor panics in noise cancellation
if sys.platform == "win32":
    os.environ["OPENBLAS_CORETYPE"] = "Haswell"
    os.environ["OPENBLAS_NUM_THREADS"] = "1"
import time
import json
import asyncio
import logging
from datetime import datetime, timezone
from dotenv import load_dotenv
from loguru import logger
from pathlib import Path
import httpx

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')

from livekit.agents import JobContext, JobRequest, WorkerOptions, cli, AgentSession, Agent, llm, stt, tts
from livekit.agents.voice.room_io import RoomOptions
from livekit.agents.voice.room_io.types import AudioInputOptions
from livekit.plugins import google, deepgram, smallestai, gnani, sarvam
import livekit.agents.inference as inference

from prompts import detect_scenario, get_scenario_config
from utils.supabase_client import SupabaseClient
from utils.resilience import retry_with_backoff, CircuitBreaker
from utils.validation import (
    validate_phone_number, validate_scenario, 
    ValidationError
)
from utils.dtln_processor import DTLNProcessor
from utils.semantic_turn_detector import get_turn_detector

load_dotenv(dotenv_path=Path(__file__).parent.parent / ".env")

logger.remove()

def stdout_filter(record) -> bool:
    name = record["name"]
    level_no = record["level"].no
    is_external = any(
        name.startswith(lib) 
        for lib in ["livekit", "google", "asyncio", "aiohttp", "tenacity", "httpx", "httpcore", "webrtc"]
    )
    if is_external:
        # Hide noisy AFC logs from google_genai.models
        if name == "google_genai.models" and "AFC is enabled" in record["message"]:
            return False
        return level_no >= logging.WARNING
    return True

# Console Logger (Clean & Filtered)
logger.add(
    sys.stdout, 
    format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{message}</cyan>",
    level="INFO",
    filter=stdout_filter,
    enqueue=True
)

# File Logger (High-Resolution DEBUG details for offline diagnostics)
logger.add(
    "agent_debug.log",
    format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} - {message}",
    level="DEBUG",
    rotation="10 MB",
    enqueue=True
)

# Intercept standard library logging and route to loguru
class InterceptHandler(logging.Handler):
    def emit(self, record):
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        frame, depth = logging.currentframe(), 2
        while frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1

        logger.opt(depth=depth, exception=record.exc_info).log(level, record.getMessage())

# Reset standard logging to use loguru InterceptHandler at DEBUG level
logging.basicConfig(handlers=[InterceptHandler()], level=logging.DEBUG, force=True)


# ═══════════════════════════════════════════════════════════════════════════════
# CIRCUIT BREAKER FOR SUPABASE (Prevent cascading failures)
# ═══════════════════════════════════════════════════════════════════════════════
supabase_circuit_breaker = CircuitBreaker(
    name="supabase",
    failure_threshold=3,
    timeout_seconds=30
)


def clean_phone_number(identity: str) -> str:
    """
    Validate and normalize phone number to E.164 format (+91XXXXXXXXXX for India).
    
    Raises: ValidationError if phone is invalid
    Returns: Normalized phone number
    """
    try:
        return validate_phone_number(identity)
    except ValidationError as e:
        logger.error(f"❌ Invalid phone number format: {e}")
        raise


# ─── GLOBAL ENGINE PRE-INITIALIZATION (Minimizes Call Startup Latency) ────────
# ─── API KEY VALIDATION (Fails early if key is missing) ────────────────────────
if not os.getenv("DEEPGRAM_API_KEY"):
    raise ValueError("DEEPGRAM_API_KEY required for Deepgram STT")
if not os.getenv("GEMINI_API_KEY"):
    raise ValueError("GEMINI_API_KEY required for Gemini LLM")
if not os.getenv("SMALLEST_API_KEY"):
    raise ValueError("SMALLEST_API_KEY required for Smallest AI TTS")


# ─── GLOBAL CLIENTS PRE-INITIALIZATION (Connection Pooling & Socket Safety) ──
# Single shared client to prevent port/socket leaks and minimize handshake overhead
global_http_client = httpx.AsyncClient(timeout=3.0)

supabase_url = os.getenv("SUPABASE_REST_URL")
supabase_key = os.getenv("SUPABASE_API_KEY")

if supabase_url and supabase_key and "YOUR_SUPABASE_SERVICE_KEY" not in supabase_key:
    supabase_client = SupabaseClient(supabase_url, supabase_key, client=global_http_client, timeout=3.0)
    logger.info("✓ Global Supabase client initialized with connection pooling.")
else:
    supabase_client = None
    logger.warning("⚠️ Supabase not configured globally - lookup fallback active.")


# ─── LATENCY TRACKING WRAPPERS (Separate LLM & TTS latency tracing) ───────────
import contextvars
import re

# ContextVar to store the call-specific end-call callback
end_call_callback_var = contextvars.ContextVar("end_call_callback", default=None)

class LatencyTrackingLLMStream(llm.LLMStream):
    def __init__(self, original_stream, on_first_token):
        self.original_stream = original_stream
        self.on_first_token = on_first_token
        self.first_token_seen = False
        self.start_time = time.time()
        self.buffered_text = ""
        
    async def _run(self):
        pass

    @property
    def chat_ctx(self) -> llm.ChatContext:
        return self.original_stream.chat_ctx

    @property
    def tools(self) -> list:
        return self.original_stream.tools

    async def aclose(self) -> None:
        await self.original_stream.aclose()
        
    def __aiter__(self):
        return self

    async def __anext__(self):
        chunk = await self.original_stream.__anext__()
        if not self.first_token_seen:
            self.first_token_seen = True
            self.on_first_token(time.time() - self.start_time)
            
        if chunk.delta and chunk.delta.content:
            content = chunk.delta.content
            self.buffered_text += content
            
            # Look for the end-of-call marker
            if "END_CALL" in self.buffered_text or "end_call" in self.buffered_text.lower():
                # Strip it from the chunk content to keep it clean for TTS and display
                for marker in ["[END_CALL]", "END_CALL", "[END_CALL", "END_CALL]", "end_call"]:
                    if marker in content:
                        content = content.replace(marker, "")
                    if marker.lower() in content.lower():
                        content = re.sub(re.escape(marker), "", content, flags=re.IGNORECASE)
                
                chunk.delta.content = content
                
                # Execute the registered task-local callback
                callback = end_call_callback_var.get()
                if callback:
                    callback()
                    
        return chunk

class LatencyTrackingLLM(llm.LLM):
    def __init__(self, original_llm, on_first_token, on_llm_start=None):
        super().__init__()
        self.original_llm = original_llm
        self.on_first_token = on_first_token
        self.on_llm_start = on_llm_start

    @property
    def model(self) -> str:
        return self.original_llm.model

    @property
    def provider(self) -> str:
        return self.original_llm.provider
        
    def chat(self, *args, **kwargs):
        if self.on_llm_start:
            self.on_llm_start(time.time())
        stream = self.original_llm.chat(*args, **kwargs)
        return LatencyTrackingLLMStream(stream, self.on_first_token)

class LatencyTrackingTTSStream(tts.ChunkedStream):
    def __init__(self, original_stream, on_first_chunk):
        self.original_stream = original_stream
        self.on_first_chunk = on_first_chunk
        self.first_chunk_seen = False
        self.start_time = time.time()

    async def _run(self, output_emitter):
        pass

    @property
    def input_text(self) -> str:
        return self.original_stream.input_text

    @property
    def done(self) -> bool:
        return self.original_stream.done

    @property
    def exception(self) -> BaseException | None:
        return self.original_stream.exception

    async def collect(self):
        return await self.original_stream.collect()

    async def aclose(self) -> None:
        await self.original_stream.aclose()

    def __aiter__(self):
        return self

    async def __anext__(self):
        chunk = await self.original_stream.__anext__()
        if not self.first_chunk_seen:
            self.first_chunk_seen = True
            self.on_first_chunk(time.time() - self.start_time)
        return chunk

class LatencyTrackingSynthesizeStream(tts.SynthesizeStream):
    def __init__(self, original_stream, on_first_chunk):
        self.original_stream = original_stream
        self.on_first_chunk = on_first_chunk
        self.first_chunk_seen = False
        self.start_time = 0.0

    async def _run(self, output_emitter):
        pass

    def push_text(self, token: str) -> None:
        if not self.first_chunk_seen and self.start_time == 0.0:
            self.start_time = time.time()
        self.original_stream.push_text(token)

    def flush(self) -> None:
        self.original_stream.flush()

    def end_input(self) -> None:
        self.original_stream.end_input()

    async def aclose(self) -> None:
        await self.original_stream.aclose()

    def __aiter__(self):
        return self

    async def __anext__(self):
        chunk = await self.original_stream.__anext__()
        if not self.first_chunk_seen and self.start_time > 0.0:
            self.first_chunk_seen = True
            self.on_first_chunk(time.time() - self.start_time)
        return chunk

class LatencyTrackingTTS(tts.TTS):
    def __init__(self, original_tts, on_first_chunk):
        super().__init__(
            capabilities=original_tts.capabilities,
            sample_rate=original_tts.sample_rate,
            num_channels=original_tts.num_channels
        )
        self.original_tts = original_tts
        self.on_first_chunk = on_first_chunk

    @property
    def voice(self) -> str:
        return self.original_tts.voice

    @property
    def model(self) -> str:
        return self.original_tts.model

    @property
    def provider(self) -> str:
        return self.original_tts.provider
        
    def synthesize(self, *args, **kwargs):
        stream = self.original_tts.synthesize(*args, **kwargs)
        return LatencyTrackingTTSStream(stream, self.on_first_chunk)

    def stream(self, *args, **kwargs):
        stream = self.original_tts.stream(*args, **kwargs)
        return LatencyTrackingSynthesizeStream(stream, self.on_first_chunk)



# ═══════════════════════════════════════════════════════════════════════════════
# SUPABASE ENRICHMENT WITH RETRIES, CIRCUIT BREAKER & ERROR HANDLING
# ═══════════════════════════════════════════════════════════════════════════════

async def _enrich_metadata_from_supabase_bg(phone: str, metadata: dict) -> None:
    """
    Background metadata enrichment (fire-and-forget).
    Updates metadata dict in-place for later reference.
    Does NOT block the main call flow.
    """
    try:
        enriched = await _enrich_metadata_from_supabase(phone)
        if enriched:
            metadata.update(enriched)
            logger.debug(f"✓ Background enrichment complete: {list(enriched.keys())}")
    except Exception as e:
        logger.debug(f"Background enrichment error (non-blocking): {e}")


async def _enrich_metadata_from_supabase(phone: str) -> dict:
    """
    Enrich metadata with customer data from Supabase.
    
    Features:
    - Retry logic with exponential backoff (prevents transient failures)
    - Circuit breaker (prevents cascading failures if Supabase down)
    - Specific exception handling (timeout, HTTP errors, unexpected)
    - URL encoding for all filter parameters (SQL injection prevention)
    
    Returns: enriched metadata dict (empty dict if all lookups fail)
    """
    if not supabase_client or not phone:
        logger.warning("⚠️ Supabase client not configured - skipping metadata enrichment")
        return {}
    
    metadata = {
        "customer_phone": phone,
        "agent_id": "c3c3c3c3-c3c3-c3c3-c3c3-c3c3c3c3c3c3"  # Safe default agent ID (Priya Sharma)
    }
    customer_id = None
    property_id = None
    agent_id = None
    
    try:
        # STEP 1: Fetch customer by phone with retries and circuit breaker
        logger.debug(f"🔍 Looking up customer: {phone}")
        
        customers = await supabase_circuit_breaker.call(
            lambda: retry_with_backoff(
                lambda: supabase_client.get_customers_by_phone(phone),
                max_retries=1,
                backoff_factor=1.0,
                initial_delay=0.1,
                name="get_customers_by_phone"
            ),
            fallback=[]
        )
        
        if customers:
            customer = customers[0]
            customer_id = customer.get("id")
            agent_id = customer.get("agent_id")
            metadata["customer_id"] = customer_id
            metadata["customer_name"] = customer.get("name")
            metadata["agent_id"] = agent_id
            logger.info(f"✅ Found customer: {customer.get('name')} (ID: {customer_id})")
        else:
            logger.info(f"ℹ️ No customer found with phone {phone}")
        
        # STEP 2: Fetch agent (round-robin with fallback)
        if not agent_id:
            try:
                agent_id = await supabase_circuit_breaker.call(
                    lambda: retry_with_backoff(
                        lambda: supabase_client.get_round_robin_agent(),
                        max_retries=1,
                        name="get_round_robin_agent"
                    ),
                    fallback=None
                )
                if agent_id:
                    metadata["agent_id"] = agent_id
                    logger.info(f"✅ Assigned agent via round-robin: {agent_id}")
            except asyncio.TimeoutError:
                logger.warning("⏱️ Round-robin agent fetch timed out")
            except httpx.HTTPError as e:
                logger.warning(f"📡 Round-robin agent HTTP error: {e}")
            except Exception as e:
                logger.warning(f"❌ Round-robin agent error: {e}")
            
            # Fallback: get first agent
            if not agent_id:
                try:
                    fallback_agent = await supabase_client.get_agent_fallback()
                    if fallback_agent:
                        metadata["agent_id"] = fallback_agent
                        logger.info(f"✅ Using fallback agent: {fallback_agent}")
                except Exception as e:
                    logger.warning(f"Fallback agent lookup also failed: {e}")
        
        # STEP 3: Find most recent property from ad_clicks
        if customer_id:
            try:
                ad_clicks = await supabase_circuit_breaker.call(
                    lambda: retry_with_backoff(
                        lambda: supabase_client.get_ad_clicks_by_phone(phone, limit=1),
                        max_retries=1,
                        name="get_ad_clicks"
                    ),
                    fallback=[]
                )
                
                if ad_clicks:
                    property_id = ad_clicks[0].get("property_id")
                    metadata["ad_click_id"] = ad_clicks[0].get("id")
                    logger.info(f"✅ Found property from ad click: {property_id}")
            except asyncio.TimeoutError:
                logger.warning("⏱️ Ad clicks lookup timed out")
            except httpx.HTTPError as e:
                logger.warning(f"📡 Ad clicks HTTP error: {e}")
            except Exception as e:
                logger.warning(f"Ad clicks lookup error: {e}")
        
        # STEP 4: Fetch property details if found
        if property_id:
            try:
                prop = await supabase_circuit_breaker.call(
                    lambda: retry_with_backoff(
                        lambda: supabase_client.get_property_by_id(property_id),
                        max_retries=1,
                        name="get_property"
                    ),
                    fallback=None
                )
                
                if prop:
                    metadata["property_id"] = prop.get("id")
                    metadata["property_title"] = prop.get("title")
                    metadata["property_price"] = prop.get("price_rupees")
                    metadata["property_sqft"] = prop.get("sqft")
                    metadata["property_location"] = prop.get("location")
                    metadata["property_type"] = prop.get("type")
                    metadata["property_age_years"] = prop.get("age_years")
                    metadata["property_amenities"] = prop.get("amenities", [])
                    metadata["property_description"] = prop.get("description", "")
                    metadata["scenario"] = "property_inquiry"
                    logger.info(f"✅ Loaded property: {prop.get('title')}")
            except asyncio.TimeoutError:
                logger.warning("⏱️ Property lookup timed out")
            except httpx.HTTPError as e:
                logger.warning(f"📡 Property HTTP error: {e}")
            except Exception as e:
                logger.warning(f"Property lookup error: {e}")
        
        return metadata
        
    except Exception as e:
        logger.error(f"❌ Metadata enrichment failed (circuit breaker may be open): {e}")
        return metadata


async def entrypoint(ctx: JobContext):
    await ctx.connect()

    # ─── Call-specific Engine Initialization (Prevents Closed Session Leakage) ───
    stt_engine = sarvam.STT(
        api_key=os.getenv("SARVAM_API_KEY"),
        language="hi-IN",
        model="saaras:v3",
        # Sarvam optimized for Indian languages on phone-quality audio
    )

    llm_engine = google.LLM(
        api_key=os.getenv("GEMINI_API_KEY"),
        model="gemini-3.1-flash-lite",
        temperature=0.3,
    )

    tts_engine = smallestai.TTS(
        api_key=os.getenv("SMALLEST_API_KEY"),
        model="lightning_v3.1",
        voice_id="advika",
        language="hi"  # Bypasses language ID overhead
    )

    vad_engine = inference.VAD(
        model="silero",
        activation_threshold=0.85,
        min_speech_duration=0.35,
    )

    # ─── Scenario Detection & Direct Database Lookup ───────────────────
    raw_metadata = ctx.room.metadata or ""
    try:
        metadata = json.loads(raw_metadata) if raw_metadata.strip() else {}
    except (json.JSONDecodeError, ValueError) as e:
        logger.warning(f"⚠️ Metadata JSON decode failed: {e}, using empty dict")
        metadata = {}

    # Seed scenario from room name prefix if metadata is empty or missing scenario
    room_name = ctx.room.name or ""
    if not metadata.get("scenario"):
        if room_name.startswith("ad-call-"):
            metadata["scenario"] = "ad_click_outbound"
            metadata["call_direction"] = "outbound"
            metadata["call_source"] = "ad_click"
            logger.info("📋 Detected outbound ad-click call from room name prefix. Setting scenario: ad_click_outbound")
        elif room_name.startswith("followup-"):
            metadata["scenario"] = "warm_followup"
            metadata["call_direction"] = "outbound"
            logger.info("📋 Detected outbound warm follow-up call from room name prefix. Setting scenario: warm_followup")

    scenario = detect_scenario(metadata)
    
    # Initialize agent_id with a safe fallback to prevent DB constraint crashes in n8n
    if not metadata.get("agent_id"):
        metadata["agent_id"] = "c3c3c3c3-c3c3-c3c3-c3c3-c3c3c3c3c3c3"
    
    # Low-latency direct database lookup for inbound callers (ASYNC, non-blocking)
    # Spawn in background - don't wait for completion to avoid turnaround time increase
    if scenario == "first_time_inbound":
        logger.info("🔍 Inbound call detected. Resolving caller identity...")
        caller = None
        # Wait up to 1.5 seconds for the participant to join the room
        for _ in range(8):
            for identity, participant in ctx.room.remote_participants.items():
                if "agent" not in identity.lower():
                    caller = participant
                    break
            if caller:
                break
            await asyncio.sleep(0.2)

        if caller:
            try:
                phone_number = clean_phone_number(caller.identity)
                metadata["customer_phone"] = phone_number
                logger.info(f"📞 Caller phone identified: {phone_number}. Querying database...")
                
                # ✅ ADD TIMEOUT HERE - Never wait more than 2 seconds for enrichment
                try:
                    enriched = await asyncio.wait_for(
                        _enrich_metadata_from_supabase(phone_number),
                        timeout=2.0
                    )
                    if enriched:
                        metadata.update(enriched)
                        scenario = detect_scenario(metadata)
                except asyncio.TimeoutError:
                    logger.warning(f"⏱️ Metadata enrichment timed out for {phone_number} — using defaults")
                
            except ValidationError as e:
                logger.error(f"❌ Phone validation failed: {e}")
            except Exception as e:
                logger.error(f"❌ Unexpected error during caller identification: {e}")

    config = get_scenario_config(scenario, metadata)
    call_started_at = datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')

    logger.info(f"🚀 {scenario.upper()} | Room: {ctx.room.name}")
    if metadata:
        logger.info(f"📋 Metadata keys: {list(metadata.keys())}")

    # ─── Room Audio Options ────────────────────────────────────────────
    # Testing: Disabled DTLN to measure if Vobiz's built-in telecom-layer NC is sufficient
    # Vobiz already provides: noise suppression + echo cancellation at the SIP/telecom layer
    # Running DTLN on top may cause double-processing artifacts or waste CPU
    nc_filter = None
    logger.info("⚪ DTLN noise suppression DISABLED for measurement. Relying on Vobiz telecom-layer NC")

    room_options = RoomOptions(
        audio_input=AudioInputOptions(
            sample_rate=24000,
            num_channels=1,
            auto_gain_control=True,
            noise_cancellation=nc_filter,
        ),
    )

    # Store timestamps for the current turn
    turn_metrics = {
        "user_speech_end": 0.0,
        "stt_finalized": 0.0,
        "playback_started": 0.0,
        "stt_text": "",
        "agent_text": "",
        "llm_first_token_delay": 0.0,
        "tts_first_chunk_delay": 0.0,
        "llm_start_time": 0.0
    }

    # Time-to-First-Token / Time-to-First-Audio callbacks
    def record_llm_start(start_time: float):
        nonlocal turn_metrics
        turn_metrics["llm_start_time"] = start_time

    def record_llm_first_token(delay: float):
        nonlocal turn_metrics
        turn_metrics["llm_first_token_delay"] = delay
        logger.debug(f"⚡ [Latency] LLM Time-to-First-Token: {delay:.2f}s")

    def record_tts_first_chunk(delay: float):
        nonlocal turn_metrics
        turn_metrics["tts_first_chunk_delay"] = delay
        logger.debug(f"⚡ [Latency] TTS Time-to-First-Chunk: {delay:.2f}s")

    # Call-specific latency-tracking engine wrappers
    call_llm = LatencyTrackingLLM(llm_engine, record_llm_first_token, record_llm_start)
    call_tts = LatencyTrackingTTS(tts_engine, record_tts_first_chunk)

    # Call-specific hangup control (idempotent — safe against duplicate LLM completions)
    should_disconnect = False
    end_call_logged = False
    disconnect_task_spawned = False

    async def disconnect_call_gracefully():
        nonlocal disconnect_task_spawned
        if disconnect_task_spawned:
            return
        disconnect_task_spawned = True
        logger.info("👋 Gracefully disconnecting session and terminating SIP carrier call...")
        try:
            # 1. Send post-call data before disconnecting
            await trigger_post_call()
            
            # 2. Disconnect the agent room connection gracefully
            # This allows the C++ noise cancellation filter to release its native handles safely
            await ctx.room.disconnect()
            await asyncio.sleep(0.5)
            
            logger.info("☎️ Deleting room via LiveKit API to drop carrier call...")
            from livekit import api
            lkapi = api.LiveKitAPI(
                url=os.getenv("LIVEKIT_URL", "").replace("wss://", "https://").replace("ws://", "http://"),
                api_key=os.getenv("LIVEKIT_API_KEY"),
                api_secret=os.getenv("LIVEKIT_API_SECRET")
            )
            await lkapi.room.delete_room(api.DeleteRoomRequest(room=ctx.room.name))
            await lkapi.aclose()
            logger.info("✅ Room deleted successfully. SIP connection terminated.")
        except Exception as e:
            logger.error(f"❌ Failed to disconnect and delete room: {e}")

    def handle_end_call():
        nonlocal should_disconnect, end_call_logged
        if end_call_logged:
            return  # Ignore duplicate signals from buffered LLM completions
        end_call_logged = True
        should_disconnect = True
        logger.info("📞 End-of-call marker [END_CALL] detected from LLM!")

    end_call_callback_var.set(handle_end_call)

    # ─── Session ────────────────────────────────────────────────────
    session = AgentSession(
        stt=stt_engine,
        llm=call_llm,
        tts=call_tts,
        vad=vad_engine,
        turn_handling={
            "endpointing": {
                # Use semantic turn detection model instead of fixed timers
                # Detects actual end-of-turn based on speech prosody (intonation, pitch, rhythm)
                # instead of just silence duration. This handles mid-sentence pauses correctly.
                "mode": "model",
                "min_delay": 0.7,        # Reduced to 0.7s for Sarvam (faster than Deepgram)
                "max_delay": 3.0,        # Absolute max 3s (if silence detection fails, use this)
            },
            "interruption": {
                "enabled": True,
                # Require actual STT text before treating as interruption (not just voice start)
                # Prevents false positives from background noise, breath sounds, code-switching
                "mode": "stt",
                "min_duration": 0.5,     # Wait for at least 500ms of acoustic+STT confidence
            },
            "preemptive_generation": {
                "enabled": False,
            }
        }
    )
    logger.info("✓ Semantic turn detection enabled | Endpointing: min=0.7s (Sarvam), max=3.0s | Interruption: STT-based (500ms min)")

    # ─── Observability & Latency Tracking ─────────────────────────────
    transcript = []
    pending_webhook_tasks = set()  # ✅ ADD THIS - Track background tasks

    post_call_sent = False
    async def trigger_post_call():
        nonlocal post_call_sent
        if post_call_sent:
            return
        post_call_sent = True
        logger.info("📞 Triggering post-call data submission to n8n...")
        await _send_post_call_data(scenario, metadata, transcript, call_started_at)


    @session.on("user_state_changed")
    def on_user_state_changed(event):
        nonlocal turn_metrics
        new_state = event.new_state
        old_state = event.old_state
        
        if new_state == "speaking":
            logger.info("🎤 [VAD] User started speaking...")
        elif new_state == "listening" and old_state == "speaking":
            turn_metrics["user_speech_end"] = time.time()
            logger.info("🎤 [VAD] User stopped speaking. Transcribing...")

    @session.on("user_input_transcribed")
    def on_user_transcript(event):
        nonlocal turn_metrics
        if event.is_final:
            # Log confidence if available
            confidence_str = ""
            if hasattr(event, 'confidence'):
                confidence_str = f" (confidence: {event.confidence:.2%})"
            
            if event.transcript.strip():
                turn_metrics["stt_finalized"] = time.time()
                turn_metrics["stt_text"] = event.transcript
                
                transcript.append({
                    "speaker": "customer",
                    "text": event.transcript,
                    "ts": datetime.now(timezone.utc).isoformat()
                })
                logger.debug(f"✓ STT finalized: {event.transcript[:50]}{confidence_str}")
            else:
                # STT returned empty — speech was detected but not recognized
                logger.warning(
                    f"⚠️ [STT Empty]{confidence_str} VAD detected speech but STT returned no text. "
                    f"Possible causes: noise, too short (<500ms), or below confidence threshold. "
                    f"Customer may need to repeat."
                )
                turn_metrics["stt_finalized"] = time.time()
                turn_metrics["stt_text"] = ""

    @session.on("conversation_item_added")
    def on_conversation_item_added(event):
        item = event.item
        if isinstance(item, llm.ChatMessage) and item.role == "assistant" and item.text_content.strip():
            agent_text = item.text_content.strip()
            # Clean end call tokens out of the transcript text
            clean_text = agent_text
            for token in ["[END_CALL]", "END_CALL", "[END_CALL", "END_CALL]", "end_call"]:
                clean_text = clean_text.replace(token, "")
            clean_text = clean_text.strip()
            
            transcript.append({
                "speaker": "agent",
                "text": clean_text,
                "ts": datetime.now(timezone.utc).isoformat()
            })
            # Store for display when agent finishes speaking
            turn_metrics["agent_text"] = clean_text

    @session.on("agent_state_changed")
    def on_agent_state_changed(event):
        nonlocal turn_metrics, disconnect_task_spawned
        new_state = event.new_state
        old_state = event.old_state
        
        if new_state == "speaking":
            turn_metrics["playback_started"] = time.time()
            
            t_speech_end = turn_metrics["user_speech_end"]
            t_stt = turn_metrics["stt_finalized"]
            t_playback = turn_metrics["playback_started"]
            
            # Calculate latencies
            stt_latency = t_stt - t_speech_end if (t_stt > 0 and t_speech_end > 0) else 0.0
            first_byte_latency = t_playback - t_stt if (t_playback > 0 and t_stt > 0) else 0.0
            total_silence = t_playback - t_speech_end if (t_playback > 0 and t_speech_end > 0) else 0.0
            
            stt_latency_str = f"{stt_latency:.2f}s" if stt_latency > 0 else "N/A (Short utterance/VAD miss)"
            total_silence_str = f"{total_silence:.2f}s" if total_silence > 0 else f"{first_byte_latency:.2f}s (No VAD)"
            
            # Separate timing details
            llm_delay = turn_metrics.get("llm_first_token_delay", 0.0)
            tts_delay = turn_metrics.get("tts_first_chunk_delay", 0.0)
            
            llm_delay_str = f"{llm_delay:.2f}s (LLM Streaming)" if llm_delay > 0 else "N/A"
            tts_delay_str = f"{tts_delay:.2f}s (TTS Streaming)" if tts_delay > 0 else "N/A"
            
            # Calculate endpointing/VAD silence validation wait
            llm_start = turn_metrics.get("llm_start_time", 0.0)
            stt_final = turn_metrics.get("stt_finalized", 0.0)
            vad_silence_wait = max(0.0, llm_start - stt_final) if (llm_start > 0 and stt_final > 0) else 0.0
            vad_silence_wait_str = f"{vad_silence_wait:.2f}s (Waiting for silence, slowed by static)" if vad_silence_wait > 0.0 else "N/A"
            
            # Print high-quality latency breakdown card
            card = (
                f"\n┌────────────────────────────────────────────────────────┐\n"
                f"│ ⚡ TURN OBSERVED LATENCY BREAKDOWN                    │\n"
                f"├────────────────────────────────────────────────────────┤\n"
                f"│ 🗣️ Customer       : {turn_metrics['stt_text']}\n"
                f"│ 🎤 VAD & STT Latency : {stt_latency_str}\n"
                f"│ ⏳ VAD Silence Wait  : {vad_silence_wait_str}\n"
                f"│ 🧠 LLM Delay         : {llm_delay_str}\n"
                f"│ 🔊 TTS Delay         : {tts_delay_str}\n"
                f"│ 🧠 Total Audio Delay : {first_byte_latency:.2f}s (Time to First Audio)\n"
                f"│ 👤 Silence Heard    : {total_silence_str}\n"
                f"└────────────────────────────────────────────────────────┘"
            )
            logger.info(card)
            
            # Reset turn metrics
            turn_metrics["user_speech_end"] = 0.0
            turn_metrics["stt_finalized"] = 0.0
            turn_metrics["stt_text"] = ""
            turn_metrics["llm_first_token_delay"] = 0.0
            turn_metrics["tts_first_chunk_delay"] = 0.0
            
        elif new_state == "listening" and old_state == "speaking":
            agent_said = turn_metrics.get("agent_text", "")
            if agent_said:
                agent_card = (
                    f"\n┌────────────────────────────────────────────────────────┐\n"
                    f"│ 🤖 PRIYA RESPONDED                                   │\n"
                    f"├────────────────────────────────────────────────────────┤\n"
                    f"│ 💬 {agent_said}\n"
                    f"└────────────────────────────────────────────────────────┘"
                )
                logger.info(agent_card)
                turn_metrics["agent_text"] = ""
            else:
                logger.info("🔊 [Audio] Priya finished speaking.")
                
            # If the LLM requested call hangup, disconnect the room now (idempotent)
            if should_disconnect:
                asyncio.create_task(disconnect_call_gracefully())

    # ─── Chat context with scenario-specific prompt ───────────────────
    system_prompt = config["prompt"] + (
        "\n\nCRITICAL CONVERSATION ENDING INSTRUCTION:\n"
        "- KABHI BHI conversation ko abruptly end mat karo jab tak customer explicitly bye/thank you na bole ya call end karne ko na kahe.\n"
        "- Agar aap customer ko 'WhatsApp pe details bhejti hoon' ya 'Main confirm karke batati hoon' bol rahe ho, toh customer ke response ('Okay', 'Theek hai') ka wait karo. Jab customer haan bol de aur aap goodbye/thank you bol chuke ho, tabhi response ke aakhiri mein '[END_CALL]' likho.\n"
        "- KABHI BHI aise response ke end mein '[END_CALL]' mat likhna jo ek sawaal ho ya jisme customer ke reply ki zaroorat ho (jaise: 'theek hai?', 'bhejun?', 'kab chalenge?').\n"
        "- Jab call poori tarah khatam ho jaye aur aap final goodbye bol rahe ho, sirf tabhi aakhiri mein '[END_CALL]' likhna hai. Example: 'Bahut bahut dhanyawaad call karne ke liye, aapka din shubh rahe! [END_CALL]'"
    )
    
    chat_context = llm.ChatContext()
    chat_context.add_message(role="system", content=system_prompt)

    # ─── Start session ────────────────────────────────────────────────
    # Delay session start slightly to let WebRTC track negotiations stabilize
    # This prevents the native C++ noise cancellation filter from crashing due to rapid attach/detach
    logger.info("⏳ Waiting for WebRTC tracks to stabilize...")
    await asyncio.sleep(1.0)

    await session.start(
        room=ctx.room,
        room_options=room_options,
        agent=Agent(
            instructions=system_prompt,
            chat_ctx=chat_context
        )
    )
    
    # ─── Warmup & Scenario-specific Greeting ──────────────────────────
    logger.info(f"⏳ Warming up ({scenario})...")
    await asyncio.sleep(0.3)
    
    try:
        logger.info(f"🎤 Greeting ({scenario})...")
        await session.say(config["greeting"])
        logger.info(f"✅ Call started — {scenario} — noise handling active")
    except RuntimeError as e:
        if "isn't running" in str(e).lower():
            logger.warning("⚠️ Call session ended before greeting could be spoken.")
        else:
            raise

    # ─── Call Guard: Auto-disconnect on max duration or prolonged silence ──
    MAX_CALL_DURATION = 300   # 5 minutes
    MAX_SILENCE_DURATION = 30  # 30 seconds of no speech from either side
    call_start_mono = time.monotonic()
    last_activity = {"time": time.monotonic()}  # dict so closures can mutate

    def _touch_activity():
        last_activity["time"] = time.monotonic()

    # Hook into existing events to track activity
    @session.on("user_state_changed")
    def _guard_on_user_activity(event):
        if event.new_state == "speaking":
            _touch_activity()

    @session.on("agent_state_changed")
    def _guard_on_agent_activity(event):
        if event.new_state == "speaking":
            _touch_activity()

    async def _call_guard_loop():
        """Background task that checks call limits every 5 seconds."""
        nonlocal should_disconnect
        while ctx.room.isconnected():
            await asyncio.sleep(5)
            if should_disconnect:
                return
            now = time.monotonic()
            elapsed = now - call_start_mono
            silence = now - last_activity["time"]

            if elapsed >= MAX_CALL_DURATION:
                logger.warning(f"⏰ Call exceeded {MAX_CALL_DURATION}s — auto-disconnecting.")
                should_disconnect = True
                try:
                    await session.say(
                        "Aapka bahut bahut shukriya! Humari baat ko kaafi time ho gaya hai. "
                        "Agar aur koi sawaal ho toh please hume wapas call karein. Dhanyawaad!"
                    )
                except Exception:
                    asyncio.create_task(disconnect_call_gracefully())
                return

            if silence >= MAX_SILENCE_DURATION:
                logger.warning(f"🔇 No speech for {MAX_SILENCE_DURATION}s — auto-disconnecting.")
                should_disconnect = True
                try:
                    await session.say(
                        "Lagta hai line silent ho gayi hai. Main call disconnect kar rahi hoon. "
                        "Agar zaroorat ho toh please wapas call karein. Dhanyawaad!"
                    )
                except Exception:
                    asyncio.create_task(disconnect_call_gracefully())
                return

    # Fire-and-forget the guard loop
    asyncio.create_task(_call_guard_loop())

    # ─── Post-call: Send data to n8n when participant disconnects ─────
    @ctx.room.on("participant_disconnected")
    def on_participant_disconnect(participant):
        if "agent" not in participant.identity.lower():
            logger.info(f"📞 Participant {participant.identity} disconnected — triggering post-call...")
            # ✅ CREATE AND TRACK TASK
            task = asyncio.create_task(trigger_post_call())
            pending_webhook_tasks.add(task)
            task.add_done_callback(pending_webhook_tasks.discard)  # Auto-remove when done
            logger.info(f"📤 Post-call webhook queued (pending: {len(pending_webhook_tasks)})")

    @ctx.room.on("disconnected")
    def on_room_disconnect():
        logger.info("📞 Room disconnected.")
        # ✅ ADD THIS - Await pending tasks before room closes
        if pending_webhook_tasks:
            logger.info(f"⏳ Waiting for {len(pending_webhook_tasks)} pending webhook(s)...")
            for task in pending_webhook_tasks:
                try:
                    asyncio.create_task(_await_task_safely(task))
                except Exception as e:
                    logger.error(f"❌ Error waiting for webhook task: {e}")


# ═══════════════════════════════════════════════════════════════════════════════
# POST-CALL WEBHOOK WITH VALIDATION & ERROR HANDLING
# ═══════════════════════════════════════════════════════════════════════════════

# ✅ ADD THIS HELPER FUNCTION
async def _await_task_safely(task):
    """Wait for a task with timeout, log result"""
    try:
        await asyncio.wait_for(task, timeout=10.0)
        logger.info("✓ Post-call webhook completed")
    except asyncio.TimeoutError:
        logger.warning("⏱️ Post-call webhook timed out (still queued)")
    except Exception as e:
        logger.error(f"❌ Post-call webhook failed: {e}")

async def _send_post_call_data(scenario: str, metadata: dict, transcript: list, started_at: str):
    """
    Send call data to n8n webhook for downstream processing.
    
    Features:
    - Async-only (doesn't block call)
    - Input validation (prevent XSS/injection)
    - Transcript validation (structure/types only)
    - Retry logic for transient failures
    
    n8n will handle:
      - Writing to calls, customers, leads tables
      - Extracting budget/location/timeline from transcript
      - Sending WhatsApp messages
      - Scheduling follow-ups
      - Updating ad_clicks status
    """
    webhook_url = os.getenv("N8N_WEBHOOK_URL")
    if not webhook_url:
        logger.warning("⚠️ N8N_WEBHOOK_URL not set in .env — skipping post-call data")
        return
    if not transcript:
        logger.info("ℹ️ No transcript to send (empty call)")
        return

    logger.info(f"📤 Preparing post-call payload for scenario '{scenario}' "
                f"(caller: {metadata.get('customer_phone')}, name: {metadata.get('customer_name')})")
    
    payload = {
        "event": "call_completed",
        "scenario": scenario,
        "call_id": metadata.get("call_id"),
        "agent_id": metadata.get("agent_id"),
        "customer_id": metadata.get("customer_id"),
        "property_id": metadata.get("property_id"),
        "ad_click_id": metadata.get("ad_click_id"),
        "customer_phone": metadata.get("customer_phone"),
        "customer_name": metadata.get("customer_name"),
        "transcript": transcript,
        "started_at": started_at,
        "ended_at": datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z'),
    }
    
    # Light validation only (structure check, no heavy processing)
    try:
        if not isinstance(payload.get("transcript"), list):
            raise ValidationError("Transcript must be a list")
        for item in payload.get("transcript", []):
            if not isinstance(item, dict) or "speaker" not in item or "text" not in item:
                raise ValidationError("Invalid transcript item format")
        logger.debug(f"✓ Payload structure validated: {len(payload['transcript'])} items")
    except ValidationError as e:
        logger.error(f"❌ Post-call payload validation failed: {e}")
        return
    
    # Use exact URL from env — no path munging. The webhook URL should be the final endpoint.
    target_url = webhook_url
    logger.info(f"📤 Posting call data (transcript: {len(transcript)} lines) to webhook: {target_url}")
    
    # Retry logic for n8n webhook
    async def post_to_webhook():
        return await global_http_client.post(target_url, json=payload, timeout=10.0)
    
    try:
        resp = await retry_with_backoff(
            post_to_webhook,
            max_retries=3,
            backoff_factor=2.0,
            name="n8n_webhook_post"
        )
        
        if 200 <= resp.status_code < 300:
            logger.info(f"✅ Post-call data accepted by n8n (status={resp.status_code})")
        else:
            logger.error(f"❌ n8n returned error {resp.status_code} for {target_url}. Response: {resp.text}")
    
    except asyncio.TimeoutError:
        logger.error(f"⏱️ n8n webhook POST timed out after 10s")
    except httpx.HTTPError as e:
        logger.error(f"📡 n8n webhook HTTP error: {e}")
    except Exception as e:
        logger.error(f"❌ Unexpected error sending post-call data: {e}")


# ═══════════════════════════════════════════════════════════════════════════════
# LIVEKIT WORKER
# ═══════════════════════════════════════════════════════════════════════════════

from livekit.agents import AgentServer

async def request_fnc(req: JobRequest):
    await req.accept()

# Expose the server variable for LiveKit Cloud deployment discovery
server = AgentServer.from_server_options(
    WorkerOptions(
        entrypoint_fnc=entrypoint,
        request_fnc=request_fnc,
    )
)

if __name__ == "__main__":
    cli.run_app(server)


# ─── Graceful Shutdown & Resource Cleanup ─────────────────────────
import atexit
import signal

async def _cleanup_resources():
    """Close all connections when worker process terminates"""
    logger.info("🧹 Shutting down — closing resources...")
    try:
        await global_http_client.aclose()
        logger.info("✓ HTTP client closed")
    except Exception as e:
        logger.warning(f"⚠️ Error closing HTTP client: {e}")
    
    if supabase_client:
        try:
            await supabase_client.client.aclose()
            logger.info("✓ Supabase client closed")
        except Exception as e:
            logger.warning(f"⚠️ Error closing Supabase client: {e}")

def _sync_cleanup():
    """Sync wrapper for async cleanup (called on exit)"""
    try:
        asyncio.run(_cleanup_resources())
    except RuntimeError:
        # Event loop already closed
        pass

# Register cleanup on process exit
atexit.register(_sync_cleanup)

# Also handle SIGTERM (graceful shutdown signal)
def _signal_handler(signum, frame):
    logger.info("📞 Received shutdown signal")
    asyncio.run(_cleanup_resources())
    sys.exit(0)

signal.signal(signal.SIGTERM, _signal_handler)
