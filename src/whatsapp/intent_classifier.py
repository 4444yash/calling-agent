"""Intent Classification for WhatsApp Customer Messages.

Uses Google Gemini Flash-Lite to classify customer messages into intents:
- PROPERTY_QUESTION: Asking about a specific property
- REQUEST_DETAILS: Requesting more information (photos, amenities, pricing)
- SCHEDULE_VISIT: Wants to visit/schedule viewing
- QUALIFY_LEAD: Budget/preferences/timeline conversation
- SMALLTALK: Greetings, off-topic, non-business
- OPTOUT: Customer opting out (STOP, unsubscribe, etc.)
- HANDOFF_HUMAN: Escalation to human agent needed
- UNKNOWN: Intent unclear

Confidence scores reflect LLM certainty (0.0-1.0).
Below 0.6 confidence, result marked as uncertain for n8n to handle.
"""

import os
import json
import logging
from typing import Dict, List, Optional, Tuple
from enum import Enum

from livekit.plugins import google

from whatsapp.config import Intent
from whatsapp.models import Session

logger = logging.getLogger(__name__)


# ============================================================================
# LLM INITIALIZATION
# ============================================================================

def _get_gemini_llm():
    """Initialize Gemini Flash-Lite for intent classification."""
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY environment variable not set")
    
    return google.LLM(
        api_key=api_key,
        model="gemini-2.0-flash-lite",
        temperature=0.1,  # Low temperature for deterministic classification
    )


# ============================================================================
# INTENT CLASSIFIER
# ============================================================================

class IntentClassifier:
    """Classify customer WhatsApp messages into business intents."""
    
    def __init__(self):
        """Initialize classifier with Gemini Flash-Lite LLM."""
        self.llm = _get_gemini_llm()
        self.intent_names = [intent.value for intent in Intent]
    
    async def classify(
        self, 
        text: str, 
        session_history: Optional[List[Dict]] = None
    ) -> Dict[str, any]:
        """
        Classify customer message into an intent.
        
        Args:
            text (str): Customer message text (Hinglish, Hindi, English)
            session_history (list): Prior conversation turns for context
                Format: [{role: 'customer'|'agent', text: str, ts: str}, ...]
        
        Returns:
            {
                "intent": "PROPERTY_QUESTION"|"UNKNOWN"|...,
                "confidence": 0.0-1.0,
                "reasoning": "Why this intent...",
                "uncertain": bool (True if confidence < 0.6)
            }
        """
        try:
            # Build context from history
            context = self._build_context(session_history)
            
            # Build classification prompt
            prompt = self._build_prompt(text, context)
            
            # Call Gemini
            response_text = await self._call_llm(prompt)
            
            # Parse response
            result = self._parse_response(response_text, text)
            
            logger.info(
                f"✓ Classified: '{text[:50]}...' → "
                f"{result['intent']} ({result['confidence']:.2f})"
            )
            
            return result
            
        except Exception as e:
            logger.error(f"❌ Classification error: {e}")
            return {
                "intent": Intent.UNKNOWN.value,
                "confidence": 0.0,
                "reasoning": f"Classification failed: {str(e)}",
                "uncertain": True,
            }
    
    def _build_context(self, history: Optional[List[Dict]]) -> str:
        """Build conversation context from history."""
        if not history:
            return "First message in conversation."
        
        # Limit to last 5 turns for brevity
        recent = history[-5:]
        context_lines = []
        
        for turn in recent:
            role = turn.get("role", "unknown")
            msg_text = turn.get("text", "")
            context_lines.append(f"{role}: {msg_text[:100]}")
        
        return "\n".join(context_lines)
    
    def _build_prompt(self, text: str, context: str) -> str:
        """Build LLM prompt for classification."""
        return f"""You are a WhatsApp message classifier for a real estate business.

Your job: Classify the customer's message into ONE of these intents:
1. PROPERTY_QUESTION - Customer asking about a specific property (price, location, size, etc.)
2. REQUEST_DETAILS - Customer requesting more information (photos, amenities, breakdown)
3. SCHEDULE_VISIT - Customer wants to schedule a property visit/viewing
4. QUALIFY_LEAD - Customer sharing budget, preferences, or timeline
5. SMALLTALK - Greetings, off-topic, non-business conversation
6. OPTOUT - Customer opting out (STOP, unsubscribe, "not interested")
7. HANDOFF_HUMAN - Escalation needed (customer angry, technical issue, etc.)
8. UNKNOWN - Intent is unclear or cannot be determined

CONVERSATION CONTEXT:
{context}

CURRENT MESSAGE:
"{text}"

Respond ONLY with valid JSON (no markdown, no extra text):
{{
  "intent": "PROPERTY_QUESTION",
  "confidence": 0.85,
  "reasoning": "Customer is asking about property features"
}}

confidence must be a number from 0.0 to 1.0.
intent must be one of the 8 values listed above (use UPPERCASE with underscores).
"""
    
    async def _call_llm(self, prompt: str) -> str:
        """Call Gemini Flash-Lite and get response."""
        try:
            # Use chat API
            chat_ctx = google.llm.ChatContext()
            chat_ctx.add_message(role="user", content=prompt)
            
            # Stream response
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
    
    def _parse_response(self, response: str, original_text: str) -> Dict:
        """Parse LLM JSON response."""
        try:
            # Extract JSON from response (may have markdown)
            response = response.strip()
            if response.startswith("```"):
                response = response.split("```")[1]
                if response.startswith("json"):
                    response = response[4:]
            
            result = json.loads(response)
            
            # Validate fields
            intent = result.get("intent", Intent.UNKNOWN.value).upper()
            confidence = float(result.get("confidence", 0.0))
            reasoning = result.get("reasoning", "")
            
            # Ensure valid intent
            valid_intents = [i.value.upper() for i in Intent]
            if intent not in valid_intents:
                intent = Intent.UNKNOWN.value
                confidence = 0.0
            
            # Clamp confidence
            confidence = max(0.0, min(1.0, confidence))
            
            return {
                "intent": intent.lower(),
                "confidence": confidence,
                "reasoning": reasoning,
                "uncertain": confidence < 0.6,
            }
            
        except json.JSONDecodeError:
            logger.warning(f"Failed to parse LLM JSON: {response[:100]}")
            return {
                "intent": Intent.UNKNOWN.value,
                "confidence": 0.0,
                "reasoning": "Could not parse classification response",
                "uncertain": True,
            }
        except Exception as e:
            logger.error(f"Parse error: {e}")
            return {
                "intent": Intent.UNKNOWN.value,
                "confidence": 0.0,
                "reasoning": str(e),
                "uncertain": True,
            }


# ============================================================================
# FACTORY FUNCTION
# ============================================================================

async def classify_intent(
    text: str, 
    session_history: Optional[List[Dict]] = None
) -> Dict[str, any]:
    """
    Classify a customer message into an intent.
    
    Convenience function that creates classifier and classifies in one call.
    
    Args:
        text (str): Customer message
        session_history (list): Conversation history
    
    Returns:
        Intent classification result (see IntentClassifier.classify)
    """
    classifier = IntentClassifier()
    return await classifier.classify(text, session_history)
