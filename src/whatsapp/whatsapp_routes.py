"""HTTP Service Endpoints for WhatsApp integration.

FastAPI routes callable by n8n for all WhatsApp operations:
- Provider initialization and message parsing
- Router classification (agent/customer identification)
- Session management
- Health checks

All endpoints return JSON with {status, data, error} structure.
"""

import os
import json
import logging
from typing import Dict, Any, Optional
from datetime import datetime

from fastapi import FastAPI, APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from whatsapp.provider import WhatsAppProvider
from whatsapp.router import SenderIdentityRouter
from whatsapp.session_store import ConversationSessionStore
from whatsapp.db import WhatsAppDB
from whatsapp.models import Session
from whatsapp.errors import WhatsAppError, ValidationError, SignatureVerificationError
from utils.supabase_client import SupabaseClient

logger = logging.getLogger(__name__)

# ============================================================================
# INITIALIZATION
# ============================================================================

router = APIRouter(prefix="/whatsapp", tags=["whatsapp"])

# Global instances (lazy-initialized)
_provider: Optional[WhatsAppProvider] = None
_db: Optional[WhatsAppDB] = None
_session_store: Optional[ConversationSessionStore] = None
_identity_router: Optional[SenderIdentityRouter] = None


def _get_provider() -> WhatsAppProvider:
    """Lazy initialization of WhatsApp provider."""
    global _provider
    if _provider is None:
        provider_name = os.getenv("WA_PROVIDER", "gupshup").lower()
        _provider = WhatsAppProvider.factory(provider_name)
        logger.info(f"✓ WhatsApp provider initialized: {provider_name}")
    return _provider


def _get_db() -> WhatsAppDB:
    """Lazy initialization of database client."""
    global _db
    if _db is None:
        supabase_url = os.getenv("SUPABASE_REST_URL")
        supabase_key = os.getenv("SUPABASE_API_KEY")
        if not supabase_url or not supabase_key:
            raise ValueError("SUPABASE_REST_URL and SUPABASE_API_KEY required")
        supabase = SupabaseClient(supabase_url, supabase_key)
        _db = WhatsAppDB(supabase)
        logger.info("✓ WhatsApp DB client initialized")
    return _db


def _get_session_store() -> ConversationSessionStore:
    """Lazy initialization of session store."""
    global _session_store
    if _session_store is None:
        db = _get_db()
        _session_store = ConversationSessionStore(db)
        logger.info("✓ Session store initialized")
    return _session_store


def _get_identity_router() -> SenderIdentityRouter:
    """Lazy initialization of identity router."""
    global _identity_router
    if _identity_router is None:
        db = _get_db()
        _identity_router = SenderIdentityRouter(db)
        logger.info("✓ Identity router initialized")
    return _identity_router


# ============================================================================
# RESPONSE HELPERS
# ============================================================================

def success_response(data: Any = None, message: str = "OK") -> Dict[str, Any]:
    """Standard success response."""
    return {
        "status": "success",
        "message": message,
        "data": data,
        "error": None,
        "timestamp": datetime.utcnow().isoformat(),
    }


def error_response(error: str, status_code: int = 400, details: Optional[Dict] = None) -> Dict[str, Any]:
    """Standard error response."""
    return {
        "status": "error",
        "message": error,
        "data": None,
        "error": {
            "message": error,
            "details": details or {},
        },
        "timestamp": datetime.utcnow().isoformat(),
    }, status_code


# ============================================================================
# HEALTH CHECK
# ============================================================================

@router.get("/health")
async def health_check() -> Dict[str, Any]:
    """Health check endpoint."""
    try:
        # Verify provider can be initialized
        provider = _get_provider()
        # Verify DB can be accessed
        db = _get_db()
        return success_response(
            data={
                "provider": os.getenv("WA_PROVIDER", "gupshup"),
                "db_connected": True,
            },
            message="WhatsApp service healthy"
        )
    except Exception as e:
        logger.error(f"❌ Health check failed: {e}")
        return error_response(f"Service unhealthy: {str(e)}", 503)


# ============================================================================
# PROVIDER ENDPOINTS
# ============================================================================

@router.post("/provider/init")
async def provider_init() -> Dict[str, Any]:
    """Initialize provider from WA_PROVIDER env variable.
    
    Returns: Provider name and status.
    """
    try:
        provider = _get_provider()
        return success_response(
            data={"provider": provider.name},
            message=f"Provider {provider.name} initialized"
        )
    except Exception as e:
        logger.error(f"❌ Provider init failed: {e}")
        return error_response(f"Failed to initialize provider: {str(e)}", 500)


@router.post("/provider/verify-signature")
async def provider_verify_signature(request: Request) -> Dict[str, Any]:
    """Verify inbound message signature using provider's verification method.
    
    Expects: raw body as bytes.
    Returns: {valid: bool, message: str}
    """
    try:
        provider = _get_provider()
        raw_body = await request.body()
        
        # Extract signature from headers (provider-specific)
        signature = request.headers.get("X-Gupshup-Signature") or \
                   request.headers.get("X-Twilio-Signature")
        
        if not signature:
            return error_response("Signature header missing", 400)
        
        is_valid = await provider.verify_signature(raw_body, signature)
        
        return success_response(
            data={"valid": is_valid},
            message="Signature verified" if is_valid else "Signature invalid"
        )
    except SignatureVerificationError as e:
        return error_response(str(e), 401)
    except Exception as e:
        logger.error(f"❌ Signature verification failed: {e}")
        return error_response(f"Verification error: {str(e)}", 500)


@router.post("/provider/parse-inbound")
async def provider_parse_inbound(request: Request) -> Dict[str, Any]:
    """Parse inbound message from provider webhook payload.
    
    Expects: raw body as bytes.
    Returns: Canonical InboundMessage object.
    """
    try:
        provider = _get_provider()
        raw_body = await request.body()
        
        inbound = await provider.parse_inbound(raw_body)
        
        return success_response(
            data={
                "provider": inbound.provider,
                "provider_message_id": inbound.provider_message_id,
                "from_phone": inbound.from_phone,
                "to_phone": inbound.to_phone,
                "timestamp": inbound.timestamp.isoformat(),
                "type": inbound.type,
                "text": inbound.text,
                "media_ids": inbound.media_ids,
            },
            message="Message parsed successfully"
        )
    except ValidationError as e:
        return error_response(str(e), 400)
    except Exception as e:
        logger.error(f"❌ Message parse failed: {e}")
        return error_response(f"Parse error: {str(e)}", 500)


# ============================================================================
# ROUTER ENDPOINTS
# ============================================================================

@router.post("/router/classify-sender")
async def router_classify_sender(phone: str) -> Dict[str, Any]:
    """Classify sender as 'agent' or 'customer' based on phone number.
    
    Args: phone (E.164 format, e.g., "+919876543210")
    Returns: {classification: "agent"|"customer"}
    """
    try:
        router = _get_identity_router()
        classification = await router.classify_sender(phone)
        
        return success_response(
            data={"classification": classification},
            message=f"Sender classified as {classification}"
        )
    except ValidationError as e:
        return error_response(str(e), 400)
    except Exception as e:
        logger.error(f"❌ Sender classification failed: {e}")
        return error_response(f"Classification error: {str(e)}", 500)


@router.post("/router/resolve-agent")
async def router_resolve_agent(phone: str) -> Dict[str, Any]:
    """Resolve agent details from phone number.
    
    Args: phone (E.164 format)
    Returns: Agent object {id, name, email, ...} or null if not an agent.
    """
    try:
        router = _get_identity_router()
        agent = await router.resolve_agent(phone)
        
        return success_response(
            data=agent,
            message="Agent resolved" if agent else "Phone not an agent"
        )
    except Exception as e:
        logger.error(f"❌ Agent resolution failed: {e}")
        return error_response(f"Resolution error: {str(e)}", 500)


@router.post("/router/resolve-customer")
async def router_resolve_customer(phone: str) -> Dict[str, Any]:
    """Resolve customer details from phone number.
    
    Args: phone (E.164 format)
    Returns: Customer object {id, name, email, ...} or null if not found.
    """
    try:
        router = _get_identity_router()
        customer = await router.resolve_customer(phone)
        
        return success_response(
            data=customer,
            message="Customer resolved" if customer else "Phone not a customer"
        )
    except Exception as e:
        logger.error(f"❌ Customer resolution failed: {e}")
        return error_response(f"Resolution error: {str(e)}", 500)


# ============================================================================
# SESSION ENDPOINTS
# ============================================================================

@router.post("/session/load")
async def session_load(phone: str, channel: str = "customer") -> Dict[str, Any]:
    """Load existing session or create new one.
    
    Args:
        phone (str): E.164 format phone number
        channel (str): 'customer' or 'agent'
    
    Returns: Session object.
    """
    try:
        if channel not in ("customer", "agent"):
            return error_response(f"Invalid channel: {channel}", 400)
        
        store = _get_session_store()
        session = await store.load(phone, channel)
        
        return success_response(
            data={
                "phone": session.phone,
                "channel": session.channel,
                "customer_id": session.customer_id,
                "agent_id": session.agent_id,
                "property_id": session.property_id,
                "state": session.state,
                "history_count": len(session.history),
                "service_window_expires_at": session.service_window_expires_at.isoformat() 
                    if session.service_window_expires_at else None,
                "opted_in": session.opted_in,
            },
            message="Session loaded"
        )
    except ValidationError as e:
        return error_response(str(e), 400)
    except Exception as e:
        logger.error(f"❌ Session load failed: {e}")
        return error_response(f"Load error: {str(e)}", 500)


@router.post("/session/append-inbound")
async def session_append_inbound(phone: str, text: str, message_type: str = "text") -> Dict[str, Any]:
    """Add inbound message to session history.
    
    Args:
        phone (str): E.164 format
        text (str): Message text
        message_type (str): 'text', 'image', 'document', etc.
    
    Returns: Updated session.
    """
    try:
        store = _get_session_store()
        session = await store.append_inbound(phone, text, message_type)
        
        return success_response(
            data={
                "phone": session.phone,
                "history_count": len(session.history),
                "updated_at": session.updated_at.isoformat() if session.updated_at else None,
            },
            message="Inbound message appended"
        )
    except ValidationError as e:
        return error_response(str(e), 400)
    except Exception as e:
        logger.error(f"❌ Append inbound failed: {e}")
        return error_response(f"Append error: {str(e)}", 500)


@router.post("/session/append-outbound")
async def session_append_outbound(phone: str, text: str) -> Dict[str, Any]:
    """Add outbound message to session history.
    
    Args:
        phone (str): E.164 format
        text (str): Reply text
    
    Returns: Updated session.
    """
    try:
        store = _get_session_store()
        session = await store.append_outbound(phone, text)
        
        return success_response(
            data={
                "phone": session.phone,
                "history_count": len(session.history),
                "updated_at": session.updated_at.isoformat() if session.updated_at else None,
            },
            message="Outbound message appended"
        )
    except ValidationError as e:
        return error_response(str(e), 400)
    except Exception as e:
        logger.error(f"❌ Append outbound failed: {e}")
        return error_response(f"Append error: {str(e)}", 500)


@router.post("/session/set-context")
async def session_set_context(phone: str, context: Dict[str, Any]) -> Dict[str, Any]:
    """Update session context fields (customer_id, agent_id, property_id, state, etc.).
    
    Args:
        phone (str): E.164 format
        context (dict): Fields to update {customer_id, agent_id, state, opted_in, ...}
    
    Returns: Updated session.
    """
    try:
        store = _get_session_store()
        db = _get_db()
        
        # Load current session
        session = await store.load(phone, "customer")
        
        # Update fields
        for key, value in context.items():
            if key in ("customer_id", "agent_id", "property_id", "state", "opted_in"):
                setattr(session, key, value)
        
        # Persist
        session = await db.save_conversation(session)
        
        return success_response(
            data={
                "phone": session.phone,
                "customer_id": session.customer_id,
                "agent_id": session.agent_id,
                "property_id": session.property_id,
                "state": session.state,
                "opted_in": session.opted_in,
            },
            message="Context updated"
        )
    except ValidationError as e:
        return error_response(str(e), 400)
    except Exception as e:
        logger.error(f"❌ Set context failed: {e}")
        return error_response(f"Update error: {str(e)}", 500)


# ============================================================================
# DPDP ERASURE ENDPOINT
# ============================================================================

@router.post("/dpdp/erase")
async def dpdp_erase(phone: str, bearer_token: Optional[str] = None) -> Dict[str, Any]:
    """Erase customer data for DPDP compliance (right to be forgotten).
    
    Args:
        phone (str): E.164 phone number to erase
        bearer_token (str): Bearer token for authorization (optional)
    
    Returns: {status: "success"|"error", rows_affected, message}
    """
    try:
        # TODO: Verify bearer token if needed
        # if bearer_token != os.getenv("DPDP_ERASE_TOKEN"):
        #     return error_response("Unauthorized", 401)
        
        from whatsapp.erasure import erase_customer_data
        
        db = _get_db()
        result = await erase_customer_data(phone, db.supabase)
        
        return success_response(
            data=result,
            message=f"Erased {result['rows_affected']} records"
        )
    except Exception as e:
        logger.error(f"❌ DPDP erasure failed: {e}")
        return error_response(f"Erasure error: {str(e)}", 500)


# ============================================================================
# EXPORT FOR FASTAPI
# ============================================================================

def attach_whatsapp_routes(app: FastAPI):
    """Attach WhatsApp routes to a FastAPI application."""
    app.include_router(router)
    logger.info("✓ WhatsApp routes attached to FastAPI app")
