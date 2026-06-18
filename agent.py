import os
import sys
import asyncio
import logging
from dotenv import load_dotenv
from loguru import logger

# Force UTF-8 encoding for Windows terminals to support emojis
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')

# Correct v1.6.1 framework topology structure
from livekit.agents import JobContext, JobRequest, WorkerOptions, cli, AgentSession, Agent, llm
from livekit.plugins import google, sarvam
import livekit.agents.inference as inference

load_dotenv()

# --- 🧼 SILENT LOGGING CONFIGURATION ---
logger.remove()
logger.add(
    sys.stdout, 
    format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{message}</cyan>",
    level="INFO"
)

# 1. Silencing Loguru's internal loggers
for noisy_library in ["livekit", "asyncio", "aiohttp", "google", "tenacity"]:
    logger.disable(noisy_library)

# 2. Silencing standard Python logging library (which is what LiveKit uses under the hood)
logging.getLogger().setLevel(logging.WARNING)
for noisy_logger in ["livekit", "livekit.plugins", "livekit.agents", "asyncio", "aiohttp", "google", "tenacity", "webrtc"]:
    logging.getLogger(noisy_logger).setLevel(logging.WARNING)
# ----------------------------------------

PRIYA_PROMPT = (
    "You are Priya, a friendly, local Mumbai real estate broker helping a client find a property. "
    "Your objective is to discover 5 details in a natural, conversational way: "
    "1. Property type (1/2/3 BHK, flat, shop), 2. Location in Mumbai (e.g., Andheri, Thane, Bandra), "
    "3. Budget (e.g., in Lakhs/Crores or monthly rent), 4. Buy or Rent, 5. Timeline (possession date). "
    "SPEECH STYLE RULES:\n"
    "- Speak in natural, colloquial Mumbai Hinglish (mix of simple Hindi & English) just like a real broker would talk over the phone.\n"
    "- Keep responses short and conversational (strictly under 8-12 words per turn).\n"
    "- Use natural fillers at the start of your turns (e.g., 'Acha', 'Theek hai', 'Haan', 'Ok', 'Achha, toh...') to sound human.\n"
    "- Do not repeat back details the user already gave. Instead, acknowledge and move to the next question naturally (e.g., 'Acha, Andheri. Toh budget range kya hoga?').\n"
    "- If they ask off-topic questions, answer briefly in 3-4 words and pivot back immediately: 'Pata nahi sir. Acha flat buying ka kya socha hai?'\n"
    "Example turns:\n"
    "- User: 'Hi' -> Priya: 'Hello! Priya baat kar rahi hoon. Mumbai mein flat search kar rahe ho?'\n"
    "- User: 'Andheri mein chahiye flat' -> Priya: 'Ok, Andheri East ya West? Aur rent pe chahiye ya buy karna hai?'\n"
    "- User: 'Rent pe budget 40k tak' -> Priya: 'Theek hai, 40k. 1 BHK ya 2 BHK dekh rahe ho?'"
)

async def entrypoint(ctx: JobContext):
    logger.info(f"🚀 INBOUND CALL PATCHED IN | Connected to Room: {ctx.room.name}")
    await ctx.connect()

    # 1. Native Low-Latency STT (saaras:v3)
    stt_engine = sarvam.STT(
        api_key=os.getenv("SARVAM_API_KEY"),
        model="saaras:v3",
        language="hi-IN"
    )

    # 2. Ultra-Fast LLM Execution (gemini-3.1-flash-lite)
    llm_engine = google.LLM(
        api_key=os.getenv("GEMINI_API_KEY"),
        model="gemini-3.1-flash-lite",
        temperature=0.3
    )

    # 3. Clean Streaming TTS Instance
    tts_engine = sarvam.TTS(
        api_key=os.getenv("SARVAM_API_KEY"),
        model="bulbul:v3",
        speaker="shruti",
        speech_sample_rate=8000,   # Forces 8kHz narrow-band phone profile natively
        pace=1.10,                 # Speeds up synthesis delivery output natively
        min_buffer_size=30         # Reduces character buffering delay before TTS to minimum allowed (30)
    )

    # 4. Native Hardware VAD (Silero)
    # The pre-warmed system VAD is loaded via inference.VAD
    vad_engine = inference.VAD(model="silero")

    # 5. Construct Stream Session Wrapper with Latency and Interruption tuning
    session = AgentSession(
        stt=stt_engine,
        llm=llm_engine,
        tts=tts_engine,
        vad=vad_engine,
        turn_handling={
            "endpointing": {
                "mode": "fixed",
                "min_delay": 0.25, # Sub-800ms response goal: start thinking after 250ms silence
                "max_delay": 0.6,
            },
            "interruption": {
                "enabled": True,
                "mode": "vad", # Instant interruption when user speaks
                "min_duration": 0.2, # Interrupt after 200ms of user speech
            },
            "preemptive_generation": {
                "enabled": True,
                "preemptive_tts": True, # Start TTS synthesis/playback before user turn is finalized
            }
        }
    )

    # 6. Clean Transcript Event Hooks (mapped to correct LiveKit 1.6.1 events)
    @session.on("user_input_transcribed")
    def on_user_transcript(event):
         if event.is_final and event.transcript.strip():
             logger.info(f"🗣️ Customer: {event.transcript}")

    @session.on("conversation_item_added")
    def on_conversation_item_added(event):
         item = event.item
         if isinstance(item, llm.ChatMessage) and item.role == "assistant" and item.text_content.strip():
             logger.info(f"🤖 Priya: {item.text_content}")

    # Initialize the chat context and set system prompt
    chat_context = llm.ChatContext()
    chat_context.add_message(role="system", content=PRIYA_PROMPT)

    # 7. Initialize and start the pipeline loop
    await session.start(
        room=ctx.room,
        agent=Agent(
            instructions=PRIYA_PROMPT,
            chat_ctx=chat_context
        )
    )
    
    # 8. Deliver introductory greeting instantly down the open audio channel
    await session.say("Namaste, main Priya hoon. Aap Mumbai mein property dhoond rahe hain?")

async def request_fnc(req: JobRequest):
    await req.accept()

if __name__ == "__main__":
    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,
            request_fnc=request_fnc,
        )
    )