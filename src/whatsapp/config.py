"""Configuration and enums for WhatsApp Conversational Channel.

Centralizes all configuration constants, enums, and HSM templates.
"""

from enum import Enum


class Channel(Enum):
    """Conversation channel type."""
    CUSTOMER = "customer"
    """Customer-facing Priya AI channel for Q&A and follow-ups"""
    
    AGENT = "agent"
    """Agent/broker command channel for operational commands"""


class Provider(Enum):
    """WhatsApp Business Service Provider."""
    GUPSHUP = "gupshup"
    """Gupshup (primary provider)"""
    
    TWILIO = "twilio"
    """Twilio (alternative/fallback provider)"""


class Intent(Enum):
    """Customer message intent (classified by LLM)."""
    PROPERTY_QUESTION = "property_question"
    """Customer asking about a specific property"""
    
    REQUEST_DETAILS = "request_details"
    """Customer requesting more details (photos, amenities, price breakdown)"""
    
    SCHEDULE_VISIT = "schedule_visit"
    """Customer wants to schedule a property visit"""
    
    QUALIFY_LEAD = "qualify_lead"
    """Qualifying conversation (budget, preferences, timeline)"""
    
    SMALLTALK = "smalltalk"
    """Non-business conversation (greetings, off-topic)"""
    
    OPTOUT = "optout"
    """Customer opting out (STOP, unsubscribe, etc.)"""
    
    HANDOFF_HUMAN = "handoff_human"
    """Escalation to human agent"""
    
    UNKNOWN = "unknown"
    """Intent could not be determined"""


# ============================================================================
# HSM Templates (WhatsApp Business pre-approved templates)
# ============================================================================

HSM_TEMPLATES = {
    "property_followup_v1": {
        "name": "property_followup_v1",
        "params": ["property_name", "time"],
        "lang": "en",
        "body": "Hi! Thought you might be interested in {property_name}. "
                "Available for viewing on {time}. Reply to learn more!",
        "approved": True,
    },
    "visit_confirmation_v1": {
        "name": "visit_confirmation_v1",
        "params": ["visit_date", "property_name"],
        "lang": "en",
        "body": "Visit confirmation for {property_name} on {visit_date}. "
                "See you then! Reply with any questions.",
        "approved": True,
    },
    "quote_followup_v1": {
        "name": "quote_followup_v1",
        "params": ["price", "area"],
        "lang": "en",
        "body": "Offering {price} for {area}. Interested? Reply YES to proceed.",
        "approved": True,
    },
    "appointment_reminder_v1": {
        "name": "appointment_reminder_v1",
        "params": ["time", "property"],
        "lang": "en",
        "body": "Reminder: Your appointment for {property} is at {time}. "
                "Reply CONFIRM to confirm.",
        "approved": True,
    },
}


# ============================================================================
# Service Window & Compliance Settings
# ============================================================================

SERVICE_WINDOW_HOURS = 24
"""Duration of WhatsApp Business customer-service window (hours).

Per WhatsApp Business API: after last inbound customer message,
free-form messages are allowed for 24 hours. After that, template-only.
"""

MAX_HISTORY_TURNS = 12
"""Maximum number of conversation turns to retain in session history.

Older turns are automatically truncated to keep context manageable for LLM.
"""

DPDP_RETENTION_DAYS = 90
"""Data retention guideline per DPDP for audit purposes.

Messages are retained indefinitely; this is a suggested minimum per policy.
"""

DEFAULT_CONFIDENCE_THRESHOLD = 0.6
"""Minimum LLM confidence for command execution.

Below this threshold, send clarifying question instead of executing.
Applies to: intent classification, command parsing, field extraction.
"""

# ============================================================================
# Provider-Specific Configuration
# ============================================================================

PROVIDER_CONFIG = {
    "gupshup": {
        "base_url": "https://api.gupshup.io/sm/api/v1",
        "media_ttl_seconds": 604800,  # 7 days
        "rate_limit_rps": 80,
        "supported_media_types": [
            "image/jpeg",
            "image/png",
            "application/pdf",
            "audio/ogg",
            "audio/mpeg",
        ],
    },
    "twilio": {
        "base_url": "https://api.twilio.com",
        "media_ttl_seconds": 259200,  # 3 days
        "rate_limit_rps": 100,
        "supported_media_types": [
            "image/jpeg",
            "image/png",
            "application/pdf",
            "audio/ogg",
        ],
    },
}

# ============================================================================
# Validation Rules
# ============================================================================

ALLOWED_IMAGE_MIME_TYPES = {
    "image/jpeg",
    "image/png",
    "image/webp",
}

ALLOWED_DOCUMENT_MIME_TYPES = {
    "application/pdf",
}

ALLOWED_AUDIO_MIME_TYPES = {
    "audio/ogg",
    "audio/mpeg",
    "audio/wav",
}

ALLOWED_VIDEO_MIME_TYPES = {
    "video/mp4",
    "video/quicktime",  # .mov files
    "video/mpeg",
    "video/webm",
}

MAX_MEDIA_FILE_SIZE_MB = 100
"""Maximum file size for uploaded media (MB).

Updated from 5MB to 100MB to support high-quality photos from modern phones
and video uploads for property walkthroughs.

Breakdown by type:
- High-quality photos (4K from modern phones): 15-30 MB typical
- Video clips (property walkthrough, 30-60 sec): 50-100 MB typical
- Documents (floor plans, PDFs): 5-20 MB typical
"""

MAX_PROPERTY_PHOTOS = 30
"""Maximum media items (photos + videos) per property upload.

Increased from 10 to 30 to support comprehensive property documentation:
- Multiple angles (exterior, interior rooms, amenities)
- Video walkthrough(s) for key selling points
"""

# ============================================================================
# Command Verb Registry
# ============================================================================

AGENT_COMMAND_VERBS = {
    "CALL_LEAD",
    "FOLLOW_UP",
    "PAUSE_OUTBOUND",
    "RESUME_OUTBOUND",
    "UPLOAD_PROPERTY",
    "LIST_LEADS",
    "HELP",
    "UNKNOWN",
}

PAUSE_OUTBOUND_MAX_MINUTES = 480
"""Maximum pause duration for PAUSE_OUTBOUND command (8 hours)"""

# ============================================================================
# Message Type Registry
# ============================================================================

MESSAGE_TYPES = {
    "text",
    "image",
    "document",
    "audio",
    "interactive",
    "sticker",
}

# ============================================================================
# Conversation States
# ============================================================================

CONVERSATION_STATES = {
    "idle",
    "collecting_media",
    "awaiting_confirmation",
}

# ============================================================================
# Message Status Registry
# ============================================================================

MESSAGE_STATUS = {
    "received",     # Inbound: received from provider
    "sent",         # Outbound: delivered to provider
    "delivered",    # Outbound: delivered to recipient
    "read",         # Outbound: read by recipient
    "failed",       # Inbound or Outbound: processing failed
}

MESSAGE_DIRECTION = {
    "inbound",      # Customer or agent → system
    "outbound",     # System → customer or agent
}
