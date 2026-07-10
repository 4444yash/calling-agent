"""WhatsApp Conversational Channel

A two-channel conversational layer over WhatsApp Business API:
- Customer channel: Priya AI agent handles Q&A, follow-ups, media sharing
- Agent channel: Registered brokers issue commands (CALL_LEAD, UPLOAD_PROPERTY, etc.)

This module provides the core data models and configuration for the feature.
"""

from .models import InboundMessage, Session, AgentCommand, PropertyDraft
from .config import Channel, Provider, Intent
from .errors import WhatsAppError

__all__ = [
    "InboundMessage",
    "Session",
    "AgentCommand",
    "PropertyDraft",
    "Channel",
    "Provider",
    "Intent",
    "WhatsAppError",
]
