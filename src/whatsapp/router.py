"""Sender identity router for WhatsApp channel.

Classifies incoming messages as AGENT or CUSTOMER based on phone lookup.
Determines message permissions and routing based on sender type.

Task 12: SenderIdentityRouter
- classify_sender(phone) → queries agents table, returns AGENT if found else CUSTOMER
- resolve_agent(phone) → returns Agent record or None
- resolve_customer(phone) → returns Customer record or None
- On DB error, fail safe to CUSTOMER (never grants command rights)
"""

from typing import Optional, Dict, Any, Literal
from loguru import logger
from .db import WhatsAppDB
from .errors import ValidationError
from ..utils.validation import validate_phone_number


class SenderIdentityRouter:
    """Routes incoming messages based on sender identity (agent vs customer).
    
    Queries agents table to classify sender as AGENT or CUSTOMER.
    On database error, fails safe to CUSTOMER (never grants command rights).
    """
    
    # Constants
    AGENT = "agent"
    """Sender is a registered agent (command permissions)"""
    
    CUSTOMER = "customer"
    """Sender is a customer or unknown (no command permissions)"""
    
    def __init__(self, db: WhatsAppDB):
        """Initialize with WhatsAppDB instance.
        
        Args:
            db: WhatsAppDB instance for entity lookups
        """
        self.db = db
        logger.info("SenderIdentityRouter initialized")
    
    async def classify_sender(self, phone: str) -> Literal["agent", "customer"]:
        """Classify sender as AGENT or CUSTOMER based on phone lookup.
        
        Queries agents table for the phone number.
        If agent found → returns AGENT (grants command execution rights).
        If agent not found → returns CUSTOMER (no command rights).
        On database error → fails safe to CUSTOMER.
        
        Preconditions:
            - phone must be E.164 format (or will be normalized)
        
        Postconditions:
            - Returns AGENT or CUSTOMER
            - Never raises exception (fails safe to CUSTOMER on error)
        
        Args:
            phone: E.164 phone number (or will be normalized)
        
        Returns:
            'agent' if sender is registered agent, else 'customer'
        """
        try:
            # Normalize phone to E.164
            phone = validate_phone_number(phone)
        except Exception as e:
            logger.warning(f"Failed to normalize phone {phone}: {e}, treating as customer")
            return self.CUSTOMER
        
        try:
            # Query agents table
            agent = await self.db.get_agent(phone)
            
            if agent:
                logger.debug(f"✓ Classified as AGENT: {phone}")
                return self.AGENT
            else:
                logger.debug(f"✓ Classified as CUSTOMER (no agent record): {phone}")
                return self.CUSTOMER
        
        except Exception as e:
            # Fail safe to CUSTOMER on any DB error
            logger.warning(
                f"Database error classifying sender {phone}, "
                f"failing safe to CUSTOMER: {e}"
            )
            return self.CUSTOMER
    
    async def resolve_agent(self, phone: str) -> Optional[Dict[str, Any]]:
        """Look up agent by phone.
        
        Returns full Agent record if found, None otherwise.
        On database error, returns None (never raises exception).
        
        Preconditions:
            - phone must be E.164 format (or will be normalized)
        
        Postconditions:
            - Returns Agent dict or None
            - Never raises exception
        
        Args:
            phone: E.164 phone number
        
        Returns:
            Agent record dict (id, name, status, etc.) or None
        """
        try:
            # Normalize phone to E.164
            phone = validate_phone_number(phone)
        except Exception as e:
            logger.warning(f"Failed to normalize phone {phone}: {e}")
            return None
        
        try:
            # Query agents table
            agent = await self.db.get_agent(phone)
            
            if agent:
                logger.debug(f"✓ Resolved agent: {phone}")
                return agent
            else:
                logger.debug(f"Agent not found: {phone}")
                return None
        
        except Exception as e:
            # Fail safe: return None, never raise
            logger.warning(f"Failed to resolve agent {phone}: {e}")
            return None
    
    async def resolve_customer(self, phone: str) -> Optional[Dict[str, Any]]:
        """Look up customer by phone.
        
        Returns full Customer record if found, None otherwise.
        On database error, returns None (never raises exception).
        
        Preconditions:
            - phone must be E.164 format (or will be normalized)
        
        Postconditions:
            - Returns Customer dict or None
            - Never raises exception
        
        Args:
            phone: E.164 phone number
        
        Returns:
            Customer record dict (id, name, whatsapp_opted_in, etc.) or None
        """
        try:
            # Normalize phone to E.164
            phone = validate_phone_number(phone)
        except Exception as e:
            logger.warning(f"Failed to normalize phone {phone}: {e}")
            return None
        
        try:
            # Query customers table
            customer = await self.db.get_customer(phone)
            
            if customer:
                logger.debug(f"✓ Resolved customer: {phone}")
                return customer
            else:
                logger.debug(f"Customer not found: {phone}")
                return None
        
        except Exception as e:
            # Fail safe: return None, never raise
            logger.warning(f"Failed to resolve customer {phone}: {e}")
            return None
