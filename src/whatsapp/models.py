"""Data models for WhatsApp Conversational Channel.

Dataclasses for all key entities:
- InboundMessage: Canonical, provider-agnostic representation of inbound messages
- Session: Multi-turn conversation state (customer or agent channel)
- AgentCommand: Parsed agent command (CALL_LEAD, PAUSE_OUTBOUND, etc.)
- PropertyDraft: In-progress property record awaiting agent confirmation
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List, Dict
from enum import Enum


@dataclass
class InboundMessage:
    """Canonical representation of an inbound WhatsApp message (provider-agnostic).
    
    The provider-specific handler converts provider payloads into this form.
    All identity and contact info is normalized to E.164 format.
    """
    
    provider: str
    """Provider name: 'gupshup' | 'twilio'"""
    
    provider_message_id: str
    """Unique message ID from provider (used for idempotency)"""
    
    from_phone: str
    """Sender phone (E.164 format, normalized)"""
    
    to_phone: str
    """Recipient phone (business number, E.164)"""
    
    timestamp: datetime
    """When the message was sent (provider timestamp, converted to UTC)"""
    
    type: str
    """Message type: 'text' | 'image' | 'document' | 'audio' | 'interactive'"""
    
    text: Optional[str] = None
    """Message body text (for text messages)"""
    
    media_ids: List[str] = field(default_factory=list)
    """Provider media IDs (used to fetch media binaries via provider API)"""
    
    raw: Dict = field(default_factory=dict)
    """Original provider payload (retained for audit and debugging)"""


@dataclass
class Session:
    """Multi-turn conversation state for a (phone, channel) pair.
    
    Stored in wa_conversations table; provides context for subsequent messages.
    History is bounded to the last N turns (default 12) for efficiency.
    """
    
    phone: str
    """E.164 phone number (+91XXXXXXXXXX)"""
    
    channel: str
    """'customer' | 'agent' (determines permissions and flow)"""
    
    customer_id: Optional[str] = None
    """UUID of resolved customer (null until identified)"""
    
    agent_id: Optional[str] = None
    """UUID of resolved agent (null for customer channel)"""
    
    property_id: Optional[str] = None
    """UUID of active property being discussed"""
    
    draft_property_id: Optional[str] = None
    """UUID of in-progress property upload"""
    
    state: str = "idle"
    """Conversation state: 'idle' | 'collecting_media' | 'awaiting_confirmation'"""
    
    history: List[Dict] = field(default_factory=list)
    """Bounded array of recent message turns: [{role, text, ts, type}, ...]
    
    Each turn contains:
      - role: 'customer' | 'agent'
      - text: message text
      - ts: ISO timestamp
      - type: 'text' | 'image' | 'interactive' | etc.
    
    Array is auto-truncated to last 12 turns by database trigger.
    """
    
    service_window_expires_at: Optional[datetime] = None
    """Last inbound customer message + 24h (for window gate).
    
    Used to enforce WhatsApp Business 24-hour service window:
    - If now() <= this timestamp: free-form messages allowed
    - If now() > this timestamp: template (HSM) messages required
    """
    
    opted_in: bool = False
    """Customer consent for business-initiated (template) messages.
    
    False by default; customer must explicitly opt-in.
    Required for any template message send.
    """
    
    created_at: Optional[datetime] = None
    """When session was first created"""
    
    updated_at: Optional[datetime] = None
    """When session was last updated"""


@dataclass
class AgentCommand:
    """Parsed agent command extracted from free-text WhatsApp message.
    
    The CommandInterpreter uses Gemini Flash-Lite to extract intent and parameters.
    Confidence < 0.6 triggers a clarifying question instead of execution.
    """
    
    verb: str
    """Command verb: 'CALL_LEAD' | 'FOLLOW_UP' | 'PAUSE_OUTBOUND' |
    'RESUME_OUTBOUND' | 'UPLOAD_PROPERTY' | 'LIST_LEADS' | 'HELP' | 'UNKNOWN'"""
    
    target_phone: Optional[str] = None
    """Phone of target customer (for CALL_LEAD, FOLLOW_UP)"""
    
    target_lead_id: Optional[str] = None
    """UUID of target lead (alternative to target_phone)"""
    
    duration_minutes: Optional[int] = None
    """Duration in minutes (for PAUSE_OUTBOUND)"""
    
    confidence: float = 0.0
    """LLM confidence score (0.0-1.0). If < 0.6, send clarifying question."""
    
    raw_text: str = ""
    """Original free-text command from agent"""


@dataclass
class PropertyDraft:
    """In-progress property record extracted from agent's caption + photos.
    
    Created during property upload flow. Fields with confidence < 0.7 are marked
    in low_confidence and returned as None (never fabricated).
    """
    
    type: Optional[str] = None
    """Property type: '2bhk' | 'studio' | '3bhk' | etc.
    
    Extracted from caption text via LLM.
    """
    
    price_rupees: Optional[int] = None
    """Asking price in rupees. Must be positive if set."""
    
    sqft: Optional[int] = None
    """Built-up area in square feet. Must be positive if set."""
    
    area_name: Optional[str] = None
    """Locality/area name: 'Bandra' | 'Andheri' | etc."""
    
    location: Optional[str] = None
    """Geographic location context (if provided)"""
    
    amenities: Optional[List[str]] = None
    """List of amenities: ['parking', 'gym', 'pool'] | etc."""
    
    low_confidence: List[str] = field(default_factory=list)
    """Fields where LLM confidence < 0.7 (flagged for agent review).
    
    These fields are returned as None in the corresponding property field.
    Examples: ['price_rupees', 'sqft'] → agent needs to confirm these.
    """
    
    raw_text: str = ""
    """Original caption text from agent (for audit)"""
    
    timestamp: Optional[datetime] = None
    """When this draft was created"""
