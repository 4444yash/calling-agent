"""
Input validation and sanitization utilities.
Production-ready safety checks for all external inputs.
"""
import re
import json
from typing import Any, Dict, List
from loguru import logger


class ValidationError(ValueError):
    """Custom exception for validation failures."""
    pass


def validate_phone_number(phone: str) -> str:
    """
    Validate and normalize phone number to E.164 format.
    
    Raises: ValidationError if phone is invalid
    Returns: Normalized phone in +91XXXXXXXXXX format (for India)
    """
    if not phone or not isinstance(phone, str):
        raise ValidationError(f"Invalid phone: must be non-empty string, got {type(phone)}")
    
    # Remove common artifacts
    clean = phone.replace("sip:", "").replace("sip_", "").replace("customer-", "").strip()
    if "@" in clean:
        clean = clean.split("@")[0]
    
    # Extract digits only
    digits = "".join(re.findall(r"\d+", clean))
    
    # Standardize to E.164
    if len(digits) == 10:
        return f"+91{digits}"
    elif len(digits) == 11 and digits.startswith("0"):
        return f"+91{digits[1:]}"
    elif len(digits) == 12 and digits.startswith("91"):
        return f"+{digits}"
    elif len(digits) == 13 and digits.startswith("+91"):
        return f"+{digits}"
    elif len(digits) >= 10:
        # Take last 10 digits (handles international formats)
        return f"+91{digits[-10:]}"
    else:
        raise ValidationError(
            f"Invalid phone number: {phone} "
            f"(cleaned: {clean}, digits: {len(digits)})"
        )


def validate_scenario(scenario: str, valid_scenarios: set) -> str:
    """
    Validate scenario against allowed values.
    
    Raises: ValidationError if scenario invalid
    Returns: Validated scenario string
    """
    if not scenario or not isinstance(scenario, str):
        return "first_time_inbound"  # Safe default
    
    if scenario.lower() not in {s.lower() for s in valid_scenarios}:
        raise ValidationError(
            f"Invalid scenario: {scenario}. "
            f"Must be one of: {', '.join(valid_scenarios)}"
        )
    
    return scenario.lower()


def sanitize_transcript_item(item: Dict[str, Any]) -> Dict[str, Any]:
    """
    Sanitize a single transcript item for safe transmission.
    
    Only validates structure and types, does NOT escape HTML (n8n handles that).
    """
    if not isinstance(item, dict):
        raise ValidationError(f"Transcript item must be dict, got {type(item)}")
    
    speaker = item.get("speaker", "").strip()
    if speaker not in ("customer", "agent"):
        raise ValidationError(f"Invalid speaker: {speaker}")
    
    text = item.get("text", "")
    if not isinstance(text, str):
        raise ValidationError(f"Transcript text must be string, got {type(text)}")
    
    # Validate timestamp
    timestamp = item.get("ts", "")
    if not isinstance(timestamp, str) or not timestamp:
        raise ValidationError("Transcript item missing 'ts' (timestamp)")
    
    # Return WITHOUT HTML escaping — n8n/frontend handles rendering safely
    return {
        "speaker": speaker,
        "text": text.strip(),
        "ts": timestamp
    }


def sanitize_transcript(transcript: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Sanitize entire transcript before sending to n8n.
    
    Ensures all items are valid and safe.
    """
    if not isinstance(transcript, list):
        raise ValidationError(f"Transcript must be list, got {type(transcript)}")
    
    sanitized = []
    for i, item in enumerate(transcript):
        try:
            sanitized_item = sanitize_transcript_item(item)
            sanitized.append(sanitized_item)
        except ValidationError as e:
            logger.error(f"Invalid transcript item at index {i}: {e}")
            raise
    
    return sanitized


def validate_post_call_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Validate post-call webhook payload for n8n.
    
    Ensures all required fields are present and valid.
    Raises: ValidationError if validation fails
    """
    required_fields = [
        "event", "scenario", "customer_phone", "transcript", "started_at", "ended_at"
    ]
    
    for field in required_fields:
        if field not in payload:
            raise ValidationError(f"Missing required field: {field}")
    
    # Validate event type
    if payload.get("event") != "call_completed":
        raise ValidationError(f"Invalid event: {payload.get('event')}")
    
    # Validate scenario
    valid_scenarios = {
        "first_time_inbound", "ad_click_outbound",
        "property_inquiry", "warm_followup"
    }
    validate_scenario(payload.get("scenario"), valid_scenarios)
    
    # Validate phone
    try:
        validate_phone_number(payload.get("customer_phone"))
    except ValidationError as e:
        raise ValidationError(f"Invalid customer_phone: {e}")
    
    # Validate transcript
    try:
        sanitize_transcript(payload.get("transcript", []))
    except ValidationError as e:
        raise ValidationError(f"Invalid transcript: {e}")
    
    # Validate ISO timestamps
    for ts_field in ["started_at", "ended_at"]:
        try:
            # Just try to parse as ISO format
            ts = payload.get(ts_field)
            if not isinstance(ts, str) or not ts.endswith("Z"):
                raise ValueError("Must be ISO format ending with Z")
        except Exception as e:
            raise ValidationError(f"Invalid {ts_field}: {e}")
    
    logger.info(f"✓ Post-call payload validated: {payload.get('event')} "
                f"for scenario {payload.get('scenario')}")
    
    return payload


def validate_metadata(metadata: Dict[str, Any]) -> Dict[str, Any]:
    """
    Validate room metadata from n8n.
    
    Ensures metadata keys and values are sensible (but permissive).
    """
    if not isinstance(metadata, dict):
        logger.warning(f"Invalid metadata type: {type(metadata)}, using empty dict")
        return {}
    
    # Whitelist of allowed metadata keys
    allowed_keys = {
        "scenario", "call_direction", "call_source", "call_id",
        "customer_phone", "customer_id", "customer_name", "agent_id",
        "property_id", "ad_click_id", "property_title", "property_type",
        "property_price", "property_location", "property_amenities",
        "days_since_visit", "previous_objections", "customer_budget_max",
        "trace_id", "additional_context"
    }
    
    validated = {}
    for key, value in metadata.items():
        if key not in allowed_keys:
            logger.debug(f"Ignoring unknown metadata key: {key}")
            continue
        
        # Basic type checks
        if isinstance(value, (str, int, float, bool, type(None))):
            validated[key] = value
        elif isinstance(value, list):
            # Allow lists (for amenities, objections)
            validated[key] = value
        else:
            logger.warning(f"Skipping invalid metadata value for {key}: {type(value)}")
    
    return validated


def is_valid_uuid(value: str) -> bool:
    """Check if value looks like a UUID."""
    uuid_pattern = re.compile(
        r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$',
        re.IGNORECASE
    )
    return bool(uuid_pattern.match(str(value)))
