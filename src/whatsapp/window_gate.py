"""WhatsApp Business Window Gate and Template Routing.

Enforces WhatsApp Business 24-hour service window:
- If within service window: FREEFORM messages allowed
- If outside window: Only HSM (template) messages allowed (requires opted_in)
- If outside window and opted_out: Message BLOCKED

Returns SendDecision to determine message type (freeform, template, blocked).
"""

import logging
from datetime import datetime
from typing import Dict, Optional

from .config import HSM_TEMPLATES, SERVICE_WINDOW_HOURS
from .models import Session

logger = logging.getLogger(__name__)


class SendDecision:
    """Describes whether and how a message should be sent."""
    
    FREEFORM = "freeform"
    TEMPLATE = "template"
    BLOCKED = "blocked"


class WindowTemplateGate:
    """Enforce WhatsApp Business service window compliance."""
    
    @staticmethod
    async def decide(
        session: Session,
        reply_text: str,
        now: Optional[datetime] = None,
    ) -> Dict[str, any]:
        """
        Decide whether message can be sent and which format to use.
        
        Args:
            session (Session): Current conversation session
            reply_text (str): Proposed reply text (for informational purposes)
            now (datetime): Current time (default: now)
        
        Returns:
            {
                "decision": "freeform"|"template"|"blocked",
                "template_name": null or "template_name_v1",
                "reason": "Within service window" | "Opted in" | "Message blocked",
                "service_window_expires_at": ISO timestamp,
                "opted_in": bool,
            }
        """
        if not now:
            now = datetime.utcnow()
        
        # Check service window
        window_expires = session.service_window_expires_at
        
        if window_expires and now <= window_expires:
            # Within service window: freeform allowed
            logger.debug(
                f"✓ Message allowed (within service window for {session.phone})"
            )
            return {
                "decision": SendDecision.FREEFORM,
                "template_name": None,
                "reason": "Within WhatsApp Business 24-hour service window",
                "service_window_expires_at": window_expires.isoformat(),
                "opted_in": session.opted_in,
            }
        
        # Outside service window: check opt-in
        if session.opted_in:
            # Customer opted in: can use template
            # Select a template based on context (or use default)
            template_name = "property_followup_v1"  # Default template
            
            if template_name not in HSM_TEMPLATES:
                logger.warning(f"Template not found: {template_name}")
                return {
                    "decision": SendDecision.BLOCKED,
                    "template_name": None,
                    "reason": "Template not available",
                    "service_window_expires_at": window_expires.isoformat() if window_expires else None,
                    "opted_in": session.opted_in,
                }
            
            logger.info(
                f"✓ Message allowed (template {template_name} for {session.phone})"
            )
            return {
                "decision": SendDecision.TEMPLATE,
                "template_name": template_name,
                "reason": "Outside service window, using HSM template",
                "service_window_expires_at": window_expires.isoformat() if window_expires else None,
                "opted_in": session.opted_in,
            }
        
        # Outside service window and not opted in: blocked
        logger.warning(
            f"⚠️ Message blocked (outside service window, not opted in) for {session.phone}"
        )
        return {
            "decision": SendDecision.BLOCKED,
            "template_name": None,
            "reason": "Outside service window and customer not opted in",
            "service_window_expires_at": window_expires.isoformat() if window_expires else None,
            "opted_in": session.opted_in,
        }


# ============================================================================
# FACTORY FUNCTION
# ============================================================================

async def check_send_compliance(
    session: Session,
    reply_text: str = "",
    now: Optional[datetime] = None,
) -> Dict[str, any]:
    """
    Check if a message can be sent and determine its format.
    
    Convenience function.
    
    Args:
        session (Session): Current session
        reply_text (str): Proposed reply (for context)
        now (datetime): Current time
    
    Returns:
        SendDecision (see WindowTemplateGate.decide)
    """
    gate = WindowTemplateGate()
    return await gate.decide(session, reply_text, now)
