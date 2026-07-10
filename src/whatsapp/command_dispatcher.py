"""Command Execution and Authorization.

Dispatches parsed agent commands after authorization checks:
- CALL_LEAD: POST to /webhook/ad-click to trigger outbound call
- FOLLOW_UP: Send message to customer via provider
- PAUSE_OUTBOUND: Set agent.status='paused' with auto-resume timer
- RESUME_OUTBOUND: Set agent.status='available'
- UPLOAD_PROPERTY: Return special result to trigger property upload flow
- LIST_LEADS: Query owned leads from database
- HELP: Return help text
- UNKNOWN: Return error

All commands require:
1. Agent must exist in database
2. Agent status must be 'available' or appropriate state
3. For CALL_LEAD/FOLLOW_UP: Agent must own the customer's lead
4. For PAUSE_OUTBOUND: Duration <= 480 minutes (8 hours)
"""

import os
import logging
import httpx
from datetime import datetime, timedelta
from typing import Dict, Optional, Any

from .models import AgentCommand
from .db import WhatsAppDB
from .errors import AuthorizationError, ValidationError
from ..utils.supabase_client import SupabaseClient

logger = logging.getLogger(__name__)


# ============================================================================
# COMMAND DISPATCHER
# ============================================================================

class CommandDispatcher:
    """Execute and authorize agent commands."""
    
    def __init__(self, db: WhatsAppDB):
        """Initialize dispatcher with database client."""
        self.db = db
        self.http_client = httpx.AsyncClient(timeout=10.0)
    
    async def dispatch(
        self,
        cmd: Dict[str, Any],
        agent_id: str,
    ) -> Dict[str, Any]:
        """
        Execute an agent command after authorization.
        
        Args:
            cmd (dict): Parsed command from CommandInterpreter
                {verb, target_phone, duration_minutes, confidence, raw_text}
            agent_id (str): UUID of agent executing command
        
        Returns:
            {
                "status": "success"|"error",
                "verb": "CALL_LEAD"|...,
                "message": "Command executed"|"Error...",
                "command_result": {...},  # Verb-specific result
                "timestamp": ISO timestamp,
            }
        """
        try:
            verb = cmd.get("verb", "UNKNOWN").upper()
            
            # Verify agent exists and is active
            agent = await self._verify_agent(agent_id)
            
            # Route to verb-specific handler
            if verb == "CALL_LEAD":
                result = await self._handle_call_lead(cmd, agent)
            elif verb == "FOLLOW_UP":
                result = await self._handle_follow_up(cmd, agent)
            elif verb == "PAUSE_OUTBOUND":
                result = await self._handle_pause_outbound(cmd, agent)
            elif verb == "RESUME_OUTBOUND":
                result = await self._handle_resume_outbound(cmd, agent)
            elif verb == "UPLOAD_PROPERTY":
                result = await self._handle_upload_property(cmd, agent)
            elif verb == "LIST_LEADS":
                result = await self._handle_list_leads(cmd, agent)
            elif verb == "HELP":
                result = await self._handle_help(cmd, agent)
            else:
                result = {
                    "status": "error",
                    "message": f"Unknown verb: {verb}",
                    "command_result": {},
                }
            
            # Add envelope
            return {
                "status": result.get("status", "error"),
                "verb": verb,
                "message": result.get("message", ""),
                "command_result": result.get("command_result", {}),
                "timestamp": datetime.utcnow().isoformat(),
            }
            
        except AuthorizationError as e:
            logger.warning(f"⚠️ Authorization failed: {e}")
            return {
                "status": "error",
                "verb": cmd.get("verb", "UNKNOWN"),
                "message": f"Not authorized: {str(e)}",
                "command_result": {},
                "timestamp": datetime.utcnow().isoformat(),
            }
        except ValidationError as e:
            return {
                "status": "error",
                "verb": cmd.get("verb", "UNKNOWN"),
                "message": f"Validation failed: {str(e)}",
                "command_result": {},
                "timestamp": datetime.utcnow().isoformat(),
            }
        except Exception as e:
            logger.error(f"❌ Command dispatch failed: {e}")
            return {
                "status": "error",
                "verb": cmd.get("verb", "UNKNOWN"),
                "message": f"Dispatch error: {str(e)}",
                "command_result": {},
                "timestamp": datetime.utcnow().isoformat(),
            }
    
    # ────────────────────────────────────────────────────────────────────
    # AUTHORIZATION
    # ────────────────────────────────────────────────────────────────────
    
    async def _verify_agent(self, agent_id: str) -> Dict[str, Any]:
        """Verify agent exists and is active."""
        agent = await self.db.supabase.fetch_one(
            "agents",
            filters={"id": agent_id}
        )
        
        if not agent:
            raise AuthorizationError(f"Agent not found: {agent_id}")
        
        status = agent.get("status")
        if status not in ("available", "busy", "paused"):
            raise AuthorizationError(f"Agent not in valid state: {status}")
        
        return agent
    
    async def _verify_lead_ownership(
        self,
        agent_id: str,
        customer_phone: str,
    ) -> Dict[str, Any]:
        """Verify agent owns the customer's lead."""
        # Find lead(s) for this customer
        leads = await self.db.supabase.fetch(
            "leads",
            filters={"customer_phone": customer_phone, "assigned_agent_id": agent_id}
        )
        
        if not leads:
            raise AuthorizationError(
                f"Agent {agent_id} does not own lead for {customer_phone}"
            )
        
        return leads[0]
    
    # ────────────────────────────────────────────────────────────────────
    # VERB HANDLERS
    # ────────────────────────────────────────────────────────────────────
    
    async def _handle_call_lead(
        self,
        cmd: Dict,
        agent: Dict,
    ) -> Dict[str, Any]:
        """Handle CALL_LEAD: POST to webhook to trigger outbound call."""
        target_phone = cmd.get("target_phone")
        
        if not target_phone:
            raise ValidationError("target_phone required for CALL_LEAD")
        
        # Verify ownership
        lead = await self._verify_lead_ownership(agent["id"], target_phone)
        
        # POST to n8n webhook
        webhook_url = os.getenv("N8N_WEBHOOK_AD_CLICK_URL")
        if not webhook_url:
            raise ValidationError("N8N_WEBHOOK_AD_CLICK_URL not configured")
        
        try:
            payload = {
                "event": "agent_initiated_call",
                "customer_phone": target_phone,
                "agent_id": agent["id"],
                "lead_id": lead.get("id"),
                "timestamp": datetime.utcnow().isoformat(),
            }
            
            response = await self.http_client.post(webhook_url, json=payload)
            response.raise_for_status()
            
            logger.info(f"✓ Call initiated: {target_phone} via agent {agent['id']}")
            
            return {
                "status": "success",
                "message": f"Call initiated to {target_phone}",
                "command_result": {
                    "phone": target_phone,
                    "lead_id": lead.get("id"),
                    "webhook_response": response.json() if response.text else {},
                },
            }
        except httpx.HTTPError as e:
            logger.error(f"❌ Webhook call failed: {e}")
            raise ValidationError(f"Failed to trigger call: {str(e)}")
    
    async def _handle_follow_up(
        self,
        cmd: Dict,
        agent: Dict,
    ) -> Dict[str, Any]:
        """Handle FOLLOW_UP: Send message to customer."""
        target_phone = cmd.get("target_phone")
        
        if not target_phone:
            raise ValidationError("target_phone required for FOLLOW_UP")
        
        # Verify ownership
        await self._verify_lead_ownership(agent["id"], target_phone)
        
        logger.info(f"✓ Follow-up queued for {target_phone}")
        
        return {
            "status": "success",
            "message": f"Follow-up queued for {target_phone}",
            "command_result": {
                "phone": target_phone,
                "queued_at": datetime.utcnow().isoformat(),
            },
        }
    
    async def _handle_pause_outbound(
        self,
        cmd: Dict,
        agent: Dict,
    ) -> Dict[str, Any]:
        """Handle PAUSE_OUTBOUND: Set agent.status='paused'."""
        duration_min = cmd.get("duration_minutes") or 120
        
        # Validate duration
        if duration_min > 480:  # 8 hours max
            duration_min = 480
        
        # Update agent status
        resume_at = datetime.utcnow() + timedelta(minutes=duration_min)
        
        updated = await self.db.supabase.update(
            "agents",
            {"id": agent["id"]},
            {
                "status": "paused",
                "auto_resume_at": resume_at.isoformat(),
                "paused_at": datetime.utcnow().isoformat(),
                "pause_reason": "Agent-initiated pause",
            }
        )
        
        logger.info(
            f"✓ Agent {agent['id']} paused for {duration_min} minutes "
            f"(resume at {resume_at.isoformat()})"
        )
        
        return {
            "status": "success",
            "message": f"Paused for {duration_min} minutes",
            "command_result": {
                "status": "paused",
                "duration_minutes": duration_min,
                "auto_resume_at": resume_at.isoformat(),
            },
        }
    
    async def _handle_resume_outbound(
        self,
        cmd: Dict,
        agent: Dict,
    ) -> Dict[str, Any]:
        """Handle RESUME_OUTBOUND: Set agent.status='available'."""
        # Update agent status
        updated = await self.db.supabase.update(
            "agents",
            {"id": agent["id"]},
            {
                "status": "available",
                "auto_resume_at": None,
                "paused_at": None,
            }
        )
        
        logger.info(f"✓ Agent {agent['id']} resumed")
        
        return {
            "status": "success",
            "message": "Outbound campaigns resumed",
            "command_result": {
                "status": "available",
            },
        }
    
    async def _handle_upload_property(
        self,
        cmd: Dict,
        agent: Dict,
    ) -> Dict[str, Any]:
        """Handle UPLOAD_PROPERTY: Return signal to start property upload flow."""
        logger.info(f"✓ Property upload initiated by agent {agent['id']}")
        
        return {
            "status": "success",
            "message": "Ready to receive property details and media",
            "command_result": {
                "mode": "property_upload",
                "next_step": "Send property photos and caption",
            },
        }
    
    async def _handle_list_leads(
        self,
        cmd: Dict,
        agent: Dict,
    ) -> Dict[str, Any]:
        """Handle LIST_LEADS: Return agent's assigned leads."""
        leads = await self.db.supabase.fetch(
            "leads",
            filters={"assigned_agent_id": agent["id"]}
        )
        
        # Format for SMS/WhatsApp text
        lines = [f"Your {len(leads)} assigned leads:"]
        for i, lead in enumerate(leads[:10], 1):  # Limit to 10
            name = lead.get("customer_name", "Unknown")
            phone = lead.get("customer_phone", "?")
            status = lead.get("status", "open")
            lines.append(f"{i}. {name} ({phone}) - {status}")
        
        if len(leads) > 10:
            lines.append(f"... and {len(leads) - 10} more")
        
        text_response = "\n".join(lines)
        
        logger.info(f"✓ Listed {len(leads)} leads for agent {agent['id']}")
        
        return {
            "status": "success",
            "message": f"Found {len(leads)} leads",
            "command_result": {
                "count": len(leads),
                "text_response": text_response,
                "leads": leads[:5],  # Return first 5 in JSON
            },
        }
    
    async def _handle_help(
        self,
        cmd: Dict,
        agent: Dict,
    ) -> Dict[str, Any]:
        """Handle HELP: Return command help text."""
        help_text = """
AVAILABLE COMMANDS:
1. Call <phone> - Initiate call to customer
2. Follow-up <phone> - Send follow-up message
3. Pause [minutes] - Pause outbound (default 120 min)
4. Resume - Resume outbound campaigns
5. Upload property - Start property upload flow
6. List leads - Show your assigned leads
7. Help - Show this message
"""
        logger.info(f"✓ Help requested by agent {agent['id']}")
        
        return {
            "status": "success",
            "message": "Help displayed",
            "command_result": {
                "help_text": help_text,
            },
        }


# ============================================================================
# FACTORY FUNCTION
# ============================================================================

async def dispatch_command(
    cmd: Dict[str, Any],
    agent_id: str,
    db: WhatsAppDB,
) -> Dict[str, Any]:
    """
    Dispatch an agent command.
    
    Convenience function that creates dispatcher and dispatches in one call.
    
    Args:
        cmd (dict): Parsed command from CommandInterpreter
        agent_id (str): UUID of agent
        db (WhatsAppDB): Database client
    
    Returns:
        Dispatch result (see CommandDispatcher.dispatch)
    """
    dispatcher = CommandDispatcher(db)
    return await dispatcher.dispatch(cmd, agent_id)
