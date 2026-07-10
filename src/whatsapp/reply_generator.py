"""Reply Generation for WhatsApp Customer Messages.

Uses Google Gemini Flash-Lite + Priya persona to generate contextual replies.
Supports Hinglish, Hindi, and English based on customer language preference.
Returns reply text with confidence score and optional media URLs.
"""

import os
import json
import logging
from typing import Dict, List, Optional

from livekit.plugins import google

from whatsapp.config import Intent
from whatsapp.models import Session
from prompts import _PERSONA, _extract_property_context

logger = logging.getLogger(__name__)


# ============================================================================
# LLM INITIALIZATION
# ============================================================================

def _get_gemini_llm():
    """Initialize Gemini Flash-Lite for reply generation."""
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY environment variable not set")
    
    return google.LLM(
        api_key=api_key,
        model="gemini-2.0-flash-lite",
        temperature=0.7,  # Slightly higher for natural conversation
    )


# ============================================================================
# REPLY GENERATOR
# ============================================================================

class ReplyGenerator:
    """Generate contextual WhatsApp replies using Priya persona."""
    
    def __init__(self):
        """Initialize generator with Gemini Flash-Lite LLM."""
        self.llm = _get_gemini_llm()
    
    async def generate(
        self,
        intent: str,
        session: Optional[Session] = None,
        customer_message: str = "",
        property_facts: Optional[Dict] = None,
    ) -> Dict[str, any]:
        """
        Generate a reply to customer message.
        
        Args:
            intent (str): Classified intent (e.g., "property_question")
            session (Session): Conversation session for context
            customer_message (str): The customer's message being replied to
            property_facts (dict): Property context {title, price, location, amenities, ...}
        
        Returns:
            {
                "text": "Reply text (TTS-friendly, no symbols)",
                "confidence": 0.0-1.0,
                "media_urls": ["url1", "url2"],
                "language": "en"|"hi"|"hinglish",
            }
        """
        try:
            # Build context
            history_context = self._build_history_context(session)
            property_context = self._build_property_context(property_facts)
            intent_guidance = self._build_intent_guidance(intent)
            
            # Build prompt
            prompt = self._build_prompt(
                customer_message,
                intent,
                history_context,
                property_context,
                intent_guidance,
            )
            
            # Call LLM
            response_text = await self._call_llm(prompt)
            
            # Parse response
            result = self._parse_response(response_text, intent)
            
            logger.info(
                f"✓ Generated reply for intent {intent}: "
                f"'{result['text'][:60]}...' ({result['confidence']:.2f})"
            )
            
            return result
            
        except Exception as e:
            logger.error(f"❌ Reply generation error: {e}")
            return {
                "text": "Maaf kijiye, kuch technical issue aya. Ek dum check karke contact deti hoon.",
                "confidence": 0.0,
                "media_urls": [],
                "language": "hinglish",
            }
    
    def _build_history_context(self, session: Optional[Session]) -> str:
        """Build conversation history for context."""
        if not session or not session.history:
            return "First message in conversation."
        
        # Last 3 turns
        recent = session.history[-3:]
        lines = []
        for turn in recent:
            role = turn.get("role", "unknown")
            text = turn.get("text", "")[:100]
            lines.append(f"{role}: {text}")
        
        return "\n".join(lines)
    
    def _build_property_context(self, facts: Optional[Dict]) -> str:
        """Build property context for reply."""
        if not facts:
            return "No property context available."
        
        # Use existing helper from prompts
        try:
            return _extract_property_context(facts)
        except:
            return "Property context: " + ", ".join(
                [f"{k}: {v}" for k, v in list(facts.items())[:5]]
            )
    
    def _build_intent_guidance(self, intent: str) -> str:
        """Build intent-specific guidance."""
        guidance = {
            "property_question": (
                "Customer asked about a property. Give specific facts if available. "
                "If not available, offer to fetch details or schedule visit."
            ),
            "request_details": (
                "Customer wants more info (photos, amenities, etc.). "
                "Promise to send via WhatsApp. Don't list everything now."
            ),
            "schedule_visit": (
                "Customer wants to visit. Offer 2-3 time slots. "
                "Ask for preferred timing. Be warm and encouraging."
            ),
            "qualify_lead": (
                "Customer sharing budget/preferences. Listen actively. "
                "Confirm what they said. Suggest next step."
            ),
            "smalltalk": (
                "Light conversation. Respond warmly. Then gently guide to property interest."
            ),
            "optout": (
                "Customer opting out. Acknowledge politely. Don't be pushy. "
                "Say 'Contact when interested'. Respect choice."
            ),
            "handoff_human": (
                "Escalate to human agent. Apologize for inconvenience. "
                "Say 'Our team will help shortly'. Set expectations."
            ),
            "unknown": (
                "Unclear intent. Politely ask clarifying question. "
                "Keep it simple. Ask one thing at a time."
            ),
        }
        return guidance.get(intent, "Respond helpfully and naturally.")
    
    def _build_prompt(
        self,
        message: str,
        intent: str,
        history: str,
        property_facts: str,
        intent_guidance: str,
    ) -> str:
        """Build LLM prompt for reply generation."""
        return f"""You are Priya, a real estate consultant on WhatsApp for Jain Estates.

{_PERSONA}

CONVERSATION HISTORY:
{history}

CURRENT CUSTOMER MESSAGE:
"{message}"

CLASSIFIED INTENT:
{intent}

GUIDANCE FOR THIS INTENT:
{intent_guidance}

PROPERTY CONTEXT (if relevant):
{property_facts}

Your task:
1. Generate a natural, warm reply as Priya
2. Keep it short (1-2 sentences max)
3. No symbols (₹, Cr, L, sqft) — spell out numbers naturally
4. Match customer's language (English, Hindi, or Hinglish)
5. Be helpful but conversational — not a robot
6. Don't mention system/technical terms

Respond ONLY with valid JSON (no markdown):
{{
  "text": "Your reply here",
  "confidence": 0.85,
  "language": "en",
  "media_urls": []
}}

confidence = your confidence in this reply (0.0-1.0)
language = "en" (English), "hi" (Hindi), or "hinglish" (mixed)
media_urls = list of image/document URLs to send (usually empty)
"""
    
    async def _call_llm(self, prompt: str) -> str:
        """Call Gemini Flash-Lite and get response."""
        try:
            chat_ctx = google.llm.ChatContext()
            chat_ctx.add_message(role="user", content=prompt)
            
            stream = self.llm.chat(chat_ctx=chat_ctx)
            
            response_text = ""
            async for chunk in stream:
                if chunk.choices:
                    delta = chunk.choices[0].delta
                    if delta.content:
                        response_text += delta.content
            
            await stream.aclose()
            return response_text
            
        except Exception as e:
            logger.error(f"LLM call failed: {e}")
            raise
    
    def _parse_response(self, response: str, intent: str) -> Dict:
        """Parse LLM JSON response."""
        try:
            # Extract JSON
            response = response.strip()
            if response.startswith("```"):
                response = response.split("```")[1]
                if response.startswith("json"):
                    response = response[4:]
            
            result = json.loads(response)
            
            text = result.get("text", "").strip()
            confidence = float(result.get("confidence", 0.5))
            language = result.get("language", "hinglish")
            media_urls = result.get("media_urls", [])
            
            # Validate
            if not text:
                text = self._fallback_reply(intent)
                confidence = 0.3
            
            confidence = max(0.0, min(1.0, confidence))
            
            return {
                "text": text,
                "confidence": confidence,
                "language": language,
                "media_urls": media_urls or [],
            }
            
        except json.JSONDecodeError:
            logger.warning(f"Failed to parse reply JSON: {response[:100]}")
            return {
                "text": self._fallback_reply(intent),
                "confidence": 0.0,
                "language": "hinglish",
                "media_urls": [],
            }
        except Exception as e:
            logger.error(f"Parse error: {e}")
            return {
                "text": self._fallback_reply(intent),
                "confidence": 0.0,
                "language": "hinglish",
                "media_urls": [],
            }
    
    def _fallback_reply(self, intent: str) -> str:
        """Fallback reply when LLM fails."""
        fallbacks = {
            "property_question": "Kya specific property ke baare mein pooch rhe ho? Batao!",
            "request_details": "Bilkul, main aapko details WhatsApp pe bhej deti hoon.",
            "schedule_visit": "Dekhiye na, kal aur parson ke liye slots available hain.",
            "qualify_lead": "Achha, aapka budget aur preference samajh jaun?",
            "smalltalk": "Acha bilkul!",
            "optout": "Koi baat nahi, contact kar dijiyega when interested.",
            "handoff_human": "Maaf kijiye. Hamara team aapko contact karega.",
            "unknown": "Bilkul, batao na kya chahiye?",
        }
        return fallbacks.get(intent, "Boliye na, kaise help kar sakti hoon?")


# ============================================================================
# FACTORY FUNCTION
# ============================================================================

async def generate_reply(
    intent: str,
    session: Optional[Session] = None,
    customer_message: str = "",
    property_facts: Optional[Dict] = None,
) -> Dict[str, any]:
    """
    Generate a reply to customer message.
    
    Convenience function that creates generator and generates reply in one call.
    
    Args:
        intent (str): Classified intent
        session (Session): Conversation session
        customer_message (str): Customer message being replied to
        property_facts (dict): Property context
    
    Returns:
        Reply result (see ReplyGenerator.generate)
    """
    generator = ReplyGenerator()
    return await generator.generate(intent, session, customer_message, property_facts)
