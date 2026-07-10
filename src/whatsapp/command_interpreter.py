"""Command Parsing for Agent WhatsApp Messages.

Uses Gemini Flash-Lite to parse free-text commands from agents into structured
AgentCommand objects. Extracts verb, target_phone/lead_id, and duration params.

Verbs supported:
- CALL_LEAD: Initiate outbound call to customer
- FOLLOW_UP: Send follow-up message to customer
- PAUSE_OUTBOUND: Temporarily disable outbound campaigns
- RESUME_OUTBOUND: Re-enable outbound campaigns
- UPLOAD_PROPERTY: Start property upload flow
- LIST_LEADS: Get list of assigned leads
- HELP: Show command help
- UNKNOWN: Could not parse command
"""

import os
import json
import logging
import re
from typing import Dict, Optional

from livekit.plugins import google

from whatsapp.models import AgentCommand

logger = logging.getLogger(__name__)


# ============================================================================
# LLM INITIALIZATION
# ============================================================================

def _get_gemini_llm():
    """Initialize Gemini Flash-Lite for command parsing."""
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY environment variable not set")
    
    return google.LLM(
        api_key=api_key,
        model="gemini-2.0-flash-lite",
        temperature=0.1,  # Low temperature for deterministic parsing
    )


# ============================================================================
# COMMAND INTERPRETER
# ============================================================================

class CommandInterpreter:
    """Parse agent commands from free-text WhatsApp messages."""
    
    def __init__(self):
        """Initialize interpreter with Gemini Flash-Lite."""
        self.llm = _get_gemini_llm()
        self.valid_verbs = {
            "CALL_LEAD",
            "FOLLOW_UP",
            "PAUSE_OUTBOUND",
            "RESUME_OUTBOUND",
            "UPLOAD_PROPERTY",
            "LIST_LEADS",
            "HELP",
            "UNKNOWN",
        }
    
    async def parse(self, text: str, agent_id: Optional[str] = None) -> Dict[str, any]:
        """
        Parse free-text command into structured AgentCommand.
        
        Args:
            text (str): Agent's message (e.g., "Call +919876543210")
            agent_id (str): UUID of agent (for context)
        
        Returns:
            {
                "verb": "CALL_LEAD"|"UNKNOWN"|...,
                "target_phone": "+919876543210" or None,
                "target_lead_id": "uuid" or None,
                "duration_minutes": 60 or None,
                "confidence": 0.0-1.0,
                "raw_text": original text,
            }
        """
        try:
            # Build prompt
            prompt = self._build_prompt(text)
            
            # Call LLM
            response_text = await self._call_llm(prompt)
            
            # Parse response
            result = self._parse_response(response_text, text)
            
            logger.info(
                f"✓ Parsed agent command: '{text[:50]}...' → "
                f"{result['verb']} ({result['confidence']:.2f})"
            )
            
            return result
            
        except Exception as e:
            logger.error(f"❌ Command parsing error: {e}")
            return {
                "verb": "UNKNOWN",
                "target_phone": None,
                "target_lead_id": None,
                "duration_minutes": None,
                "confidence": 0.0,
                "raw_text": text,
            }
    
    def _build_prompt(self, text: str) -> str:
        """Build LLM prompt for command parsing."""
        return f"""You are a command parser for a real estate agent WhatsApp interface.

Your job: Parse the agent's message into a structured command.

VALID VERBS:
1. CALL_LEAD - Call a customer (extract phone number)
2. FOLLOW_UP - Send follow-up to customer (extract phone)
3. PAUSE_OUTBOUND - Pause outbound campaigns (extract duration in minutes if mentioned)
4. RESUME_OUTBOUND - Resume outbound campaigns
5. UPLOAD_PROPERTY - Start property upload flow
6. LIST_LEADS - Get list of assigned leads
7. HELP - Show help
8. UNKNOWN - Command not recognized

AGENT MESSAGE:
"{text}"

Extract:
- verb: Which command is this?
- target_phone: If verb is CALL_LEAD/FOLLOW_UP, extract phone number (keep + sign, e.g., +919876543210)
- duration_minutes: If PAUSE_OUTBOUND, extract duration (default 120)
- confidence: How confident are you? (0.0-1.0)

If you can't determine the verb, use UNKNOWN.
If the phone number is incomplete (missing digits), still extract it and mark lower confidence.

Respond ONLY with valid JSON (no markdown):
{{
  "verb": "CALL_LEAD",
  "target_phone": "+919876543210",
  "target_lead_id": null,
  "duration_minutes": null,
  "confidence": 0.92
}}
"""
    
    async def _call_llm(self, prompt: str) -> str:
        """Call Gemini Flash-Lite."""
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
    
    def _parse_response(self, response: str, original_text: str) -> Dict:
        """Parse LLM JSON response."""
        try:
            # Extract JSON
            response = response.strip()
            if response.startswith("```"):
                response = response.split("```")[1]
                if response.startswith("json"):
                    response = response[4:]
            
            result = json.loads(response)
            
            verb = result.get("verb", "UNKNOWN").upper()
            target_phone = result.get("target_phone")
            target_lead_id = result.get("target_lead_id")
            duration_minutes = result.get("duration_minutes")
            confidence = float(result.get("confidence", 0.0))
            
            # Validate verb
            if verb not in self.valid_verbs:
                verb = "UNKNOWN"
                confidence = 0.0
            
            # Normalize phone number
            if target_phone and not target_phone.startswith("+"):
                target_phone = "+" + target_phone.lstrip("0")
            
            # Clamp confidence
            confidence = max(0.0, min(1.0, confidence))
            
            return {
                "verb": verb,
                "target_phone": target_phone,
                "target_lead_id": target_lead_id,
                "duration_minutes": duration_minutes,
                "confidence": confidence,
                "raw_text": original_text,
            }
            
        except json.JSONDecodeError:
            logger.warning(f"Failed to parse command JSON: {response[:100]}")
            return {
                "verb": "UNKNOWN",
                "target_phone": None,
                "target_lead_id": None,
                "duration_minutes": None,
                "confidence": 0.0,
                "raw_text": original_text,
            }
        except Exception as e:
            logger.error(f"Parse error: {e}")
            return {
                "verb": "UNKNOWN",
                "target_phone": None,
                "target_lead_id": None,
                "duration_minutes": None,
                "confidence": 0.0,
                "raw_text": original_text,
            }


# ============================================================================
# FACTORY FUNCTION
# ============================================================================

async def parse_command(
    text: str,
    agent_id: Optional[str] = None,
) -> Dict[str, any]:
    """
    Parse an agent command from free text.
    
    Convenience function that creates interpreter and parses in one call.
    
    Args:
        text (str): Agent's message
        agent_id (str): UUID of agent
    
    Returns:
        Parsed command (see CommandInterpreter.parse)
    """
    interpreter = CommandInterpreter()
    return await interpreter.parse(text, agent_id)
