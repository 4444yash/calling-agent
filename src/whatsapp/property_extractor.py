"""Property Information Extraction from Caption Text.

Uses Gemini Flash-Lite to parse Hinglish/Hindi/English free-text property
captions and extract structured fields.

Extracted fields:
- type: 2bhk, 3bhk, studio, 1rk, etc.
- price_rupees: Asking price (numeric)
- sqft: Built-up area in square feet (numeric)
- area_name: Locality name (e.g., Bandra, Andheri)
- amenities: List of amenities (parking, gym, pool, etc.)

Low-confidence fields (< 0.7) are marked in low_confidence array and returned
as None (never fabricated).
"""

import os
import json
import logging
from typing import Dict, Optional, List

from livekit.plugins import google

from .models import PropertyDraft
from .config import DEFAULT_CONFIDENCE_THRESHOLD

logger = logging.getLogger(__name__)


# ============================================================================
# LLM INITIALIZATION
# ============================================================================

def _get_gemini_llm():
    """Initialize Gemini Flash-Lite for property extraction."""
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY environment variable not set")
    
    return google.LLM(
        api_key=api_key,
        model="gemini-2.0-flash-lite",
        temperature=0.1,  # Low temperature for deterministic extraction
    )


# ============================================================================
# PROPERTY EXTRACTOR
# ============================================================================

class PropertyExtractor:
    """Extract property information from free-text captions."""
    
    def __init__(self):
        """Initialize extractor with Gemini Flash-Lite."""
        self.llm = _get_gemini_llm()
        self.low_confidence_threshold = 0.7
    
    async def extract(self, caption_text: str) -> Dict[str, any]:
        """
        Extract property information from caption text.
        
        Args:
            caption_text (str): Agent's caption (Hinglish/Hindi/English)
                Example: "3BHK flat in Bandra, 1200 sqft, 2.5 cr"
        
        Returns:
            {
                "type": "3bhk" or None,
                "price_rupees": 2500000 or None,
                "sqft": 1200 or None,
                "area_name": "Bandra" or None,
                "amenities": ["parking", "gym"] or None,
                "low_confidence": ["price_rupees", ...],  # Fields below threshold
                "confidence_breakdown": {
                    "type": 0.95,
                    "price_rupees": 0.65,  # Below threshold
                    ...
                }
            }
        """
        try:
            # Build extraction prompt
            prompt = self._build_prompt(caption_text)
            
            # Call LLM
            response_text = await self._call_llm(prompt)
            
            # Parse response
            result = self._parse_response(response_text, caption_text)
            
            logger.info(
                f"✓ Extracted property: {result.get('type')} at "
                f"{result.get('area_name', 'unknown area')} "
                f"({', '.join(result.get('low_confidence', []))} uncertain)"
            )
            
            return result
            
        except Exception as e:
            logger.error(f"❌ Extraction error: {e}")
            return {
                "type": None,
                "price_rupees": None,
                "sqft": None,
                "area_name": None,
                "amenities": None,
                "low_confidence": ["type", "price_rupees", "sqft", "area_name", "amenities"],
                "error": str(e),
            }
    
    def _build_prompt(self, caption: str) -> str:
        """Build extraction prompt."""
        return f"""You are a real estate data extractor. Your job: Parse a property caption
and extract structured fields.

PROPERTY CAPTION:
"{caption}"

Extract the following fields (return null if not found):
- type: Property type (2bhk, 3bhk, studio, 1rk, villa, office, shop, etc.)
  Normalize to lowercase with no spaces (e.g., "2 BHK" → "2bhk")
- price_rupees: Asking price as integer (e.g., "25 lac" → 2500000)
  Handle abbreviations: "cr" = crore (×10M), "lac/lakh" (×100K)
  Extract numeric part only, return as integer
- sqft: Built-up area in square feet as integer (e.g., "1200 sq ft" → 1200)
- area_name: Locality name (e.g., "Bandra", "Andheri", "Thane")
- amenities: List of amenities (parking, gym, pool, security, ac, furnished, etc.)

For each field, also provide a confidence score (0.0-1.0):
- 1.0 = Explicitly stated, no ambiguity
- 0.7-0.9 = Clear but requires slight interpretation
- 0.5-0.7 = Inferred from context, some uncertainty
- <0.5 = Guessed or uncertain (return null for these)

Respond ONLY with valid JSON (no markdown):
{{
  "type": "3bhk",
  "type_confidence": 0.95,
  "price_rupees": 2500000,
  "price_confidence": 0.85,
  "sqft": 1200,
  "sqft_confidence": 0.80,
  "area_name": "Bandra",
  "area_name_confidence": 0.90,
  "amenities": ["parking", "gym", "pool"],
  "amenities_confidence": 0.70
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
        """Parse extraction JSON response."""
        try:
            # Extract JSON
            response = response.strip()
            if response.startswith("```"):
                response = response.split("```")[1]
                if response.startswith("json"):
                    response = response[4:]
            
            result = json.loads(response)
            
            # Extract fields with confidence checks
            extracted = {
                "type": None,
                "price_rupees": None,
                "sqft": None,
                "area_name": None,
                "amenities": None,
                "low_confidence": [],
                "confidence_breakdown": {},
            }
            
            # Process type
            ptype = result.get("type")
            ptype_conf = float(result.get("type_confidence", 0.0))
            if ptype_conf >= self.low_confidence_threshold:
                extracted["type"] = ptype.lower() if ptype else None
            else:
                extracted["low_confidence"].append("type")
            extracted["confidence_breakdown"]["type"] = ptype_conf
            
            # Process price
            price = result.get("price_rupees")
            price_conf = float(result.get("price_confidence", 0.0))
            if price and price_conf >= self.low_confidence_threshold:
                try:
                    extracted["price_rupees"] = int(price)
                except (ValueError, TypeError):
                    extracted["low_confidence"].append("price_rupees")
            elif price:
                extracted["low_confidence"].append("price_rupees")
            extracted["confidence_breakdown"]["price_rupees"] = price_conf
            
            # Process sqft
            sqft = result.get("sqft")
            sqft_conf = float(result.get("sqft_confidence", 0.0))
            if sqft and sqft_conf >= self.low_confidence_threshold:
                try:
                    extracted["sqft"] = int(sqft)
                except (ValueError, TypeError):
                    extracted["low_confidence"].append("sqft")
            elif sqft:
                extracted["low_confidence"].append("sqft")
            extracted["confidence_breakdown"]["sqft"] = sqft_conf
            
            # Process area_name
            area = result.get("area_name")
            area_conf = float(result.get("area_name_confidence", 0.0))
            if area and area_conf >= self.low_confidence_threshold:
                extracted["area_name"] = area
            elif area:
                extracted["low_confidence"].append("area_name")
            extracted["confidence_breakdown"]["area_name"] = area_conf
            
            # Process amenities
            amenities = result.get("amenities", [])
            amenities_conf = float(result.get("amenities_confidence", 0.0))
            if amenities and amenities_conf >= self.low_confidence_threshold:
                extracted["amenities"] = [a.lower() for a in amenities]
            elif amenities:
                extracted["low_confidence"].append("amenities")
            extracted["confidence_breakdown"]["amenities"] = amenities_conf
            
            return extracted
            
        except json.JSONDecodeError:
            logger.warning(f"Failed to parse extraction JSON: {response[:100]}")
            return {
                "type": None,
                "price_rupees": None,
                "sqft": None,
                "area_name": None,
                "amenities": None,
                "low_confidence": ["type", "price_rupees", "sqft", "area_name", "amenities"],
                "error": "JSON parse failed",
            }
        except Exception as e:
            logger.error(f"Parse error: {e}")
            return {
                "type": None,
                "price_rupees": None,
                "sqft": None,
                "area_name": None,
                "amenities": None,
                "low_confidence": ["type", "price_rupees", "sqft", "area_name", "amenities"],
                "error": str(e),
            }


# ============================================================================
# FACTORY FUNCTION
# ============================================================================

async def extract_property(caption_text: str) -> Dict[str, any]:
    """
    Extract property information from caption.
    
    Convenience function that creates extractor and extracts in one call.
    
    Args:
        caption_text (str): Agent's caption text
    
    Returns:
        Extraction result (see PropertyExtractor.extract)
    """
    extractor = PropertyExtractor()
    return await extractor.extract(caption_text)
