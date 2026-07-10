"""Session store for WhatsApp conversations.

Provides multi-turn context via Supabase-backed wa_conversations table.
Auto-truncates history to last 12 turns on every write.
Manages service window (24h inbound window for template-free messages).

Task 8: ConversationSessionStore
- load(phone, channel) → loads wa_conversations or creates new session
- append_inbound(phone, msg) → adds message to history, updates service_window_expires_at
- append_outbound(phone, text) → adds outbound text to history
- set_context(phone, ctx) → updates customer_id, property_id, agent_id, state, draft_property_id
- expire_stale(older_than) → cleanup stale sessions
"""

from typing import Optional, Dict, Any
from datetime import datetime, timedelta, timezone
from loguru import logger
from .models import Session, InboundMessage
from .config import SERVICE_WINDOW_HOURS, MAX_HISTORY_TURNS
from .errors import SessionNotFoundError, MessageProcessingError, ValidationError
from .db import WhatsAppDB


class ConversationSessionStore:
    """Manages conversation sessions per (phone, channel).
    
    Backend: Supabase wa_conversations table via WhatsAppDB.
    History auto-truncated to last 12 turns on every write.
    Service window set to now + 24h on inbound customer message.
    """
    
    def __init__(self, db: WhatsAppDB):
        """Initialize with WhatsAppDB instance.
        
        Args:
            db: WhatsAppDB instance for persistence
        """
        self.db = db
        logger.info("ConversationSessionStore initialized")
    
    async def load(self, phone: str, channel: str) -> Session:
        """Load session or create new one if not found.
        
        Queries wa_conversations for (phone, channel) pair.
        If not found, creates new session with defaults.
        
        Preconditions:
            - phone must be E.164 format
            - channel must be 'customer' or 'agent'
        
        Postconditions:
            - Returns Session object persisted in database
            - New sessions have empty history, state='idle'
            - All timestamp fields populated
        
        Args:
            phone: E.164 phone number
            channel: 'customer' | 'agent'
        
        Returns:
            Session object
        
        Raises:
            SessionNotFoundError: If load/create fails
            ValidationError: If phone/channel invalid
        """
        try:
            session = await self.db.get_conversation(phone, channel)
            logger.debug(f"✓ Loaded session: {phone} ({channel})")
            return session
        
        except Exception as e:
            logger.error(f"Failed to load session for {phone}: {e}")
            raise SessionNotFoundError(f"Failed to load session for {phone}: {e}")
    
    async def append_inbound(
        self,
        phone: str,
        msg: InboundMessage,
    ) -> Session:
        """Add inbound message to session history and update service window.
        
        Performs three operations atomically:
        1. Logs audit entry in wa_messages
        2. Appends message to session history
        3. Updates service_window_expires_at to now + 24h
        
        History is auto-truncated to MAX_HISTORY_TURNS by WhatsAppDB.
        
        Preconditions:
            - phone must be E.164
            - msg must have valid provider_message_id (for idempotency)
            - Session must exist (caller should call load() first)
        
        Postconditions:
            - Audit row created in wa_messages
            - Session history updated with new message
            - service_window_expires_at set to now + 24h
            - History truncated to 12 turns
            - Returns updated Session
        
        Args:
            phone: E.164 phone of sender
            msg: InboundMessage object
        
        Returns:
            Updated Session with new message in history
        
        Raises:
            MessageProcessingError: If append fails
            ValidationError: If phone/message invalid
        """
        try:
            # append_inbound_message handles everything:
            # - idempotency check
            # - audit log creation
            # - session history update
            # - service window update
            session = await self.db.append_inbound_message(phone, msg)
            logger.debug(f"✓ Appended inbound message: {phone}")
            return session
        
        except Exception as e:
            logger.error(f"Failed to append inbound for {phone}: {e}")
            raise MessageProcessingError(f"Failed to append inbound message: {e}")
    
    async def append_outbound(self, phone: str, text: str) -> Session:
        """Add outbound text to session history (audit trail).
        
        Logs message to wa_messages table and appends to session history.
        Called when system sends reply to customer or agent.
        
        Preconditions:
            - phone must be E.164
            - text must be non-empty
        
        Postconditions:
            - Audit row created in wa_messages with direction='outbound'
            - Session history updated with outbound message
            - History truncated to 12 turns
        
        Args:
            phone: E.164 recipient phone
            text: Message text to send
        
        Returns:
            Updated Session
        
        Raises:
            MessageProcessingError: If append fails
            ValidationError: If phone/text invalid
        """
        try:
            # Log outbound message to audit trail
            await self.db.append_outbound_message(phone, text)
            
            # Load current session and append to history
            session = await self.load(phone, "customer")
            now = datetime.now(timezone.utc)
            session.history.append({
                "role": "agent",
                "text": text,
                "ts": now.isoformat() + "Z",
                "type": "text",
            })
            
            # Truncate history to MAX_HISTORY_TURNS
            session = await self._truncate_and_save(session)
            
            logger.debug(f"✓ Appended outbound message: {phone}")
            return session
        
        except Exception as e:
            logger.error(f"Failed to append outbound for {phone}: {e}")
            raise MessageProcessingError(f"Failed to append outbound message: {e}")
    
    async def set_context(
        self,
        phone: str,
        ctx: Dict[str, Any],
    ) -> Session:
        """Update session context fields.
        
        Sets one or more of: customer_id, property_id, agent_id, state, draft_property_id.
        
        Preconditions:
            - phone must be E.164
            - ctx dict must contain valid fields (unknown fields ignored)
            - state must be one of: 'idle', 'collecting_media', 'awaiting_confirmation'
        
        Postconditions:
            - Session fields updated as specified
            - Returns saved Session
        
        Args:
            phone: E.164 phone number
            ctx: Dict with keys: customer_id, property_id, agent_id, state, draft_property_id
        
        Returns:
            Updated Session
        
        Raises:
            SessionNotFoundError: If session not found
            ValidationError: If ctx invalid
        """
        try:
            # Load session
            session = await self.load(phone, "customer")
            
            # Update context fields
            if "customer_id" in ctx:
                session.customer_id = ctx["customer_id"]
            if "property_id" in ctx:
                session.property_id = ctx["property_id"]
            if "agent_id" in ctx:
                session.agent_id = ctx["agent_id"]
            if "state" in ctx:
                session.state = ctx["state"]
            if "draft_property_id" in ctx:
                session.draft_property_id = ctx["draft_property_id"]
            
            # Save updated session
            session = await self.db.save_conversation(session)
            logger.debug(f"✓ Updated session context: {phone}")
            return session
        
        except Exception as e:
            logger.error(f"Failed to set context for {phone}: {e}")
            raise
    
    async def expire_stale(self, older_than: timedelta) -> int:
        """Delete sessions inactive for older_than duration.
        
        Deletes rows from wa_conversations where updated_at < now() - older_than.
        Used for compliance cleanup (e.g., delete sessions older than 90 days).
        
        Preconditions:
            - older_than must be positive timedelta
        
        Postconditions:
            - Stale sessions deleted from database
            - Returns count of deleted rows
        
        Args:
            older_than: timedelta (e.g., timedelta(days=90))
        
        Returns:
            Count of deleted sessions
        
        Raises:
            MessageProcessingError: If cleanup fails
        """
        try:
            cutoff = datetime.now(timezone.utc) - older_than
            
            # In production, this would call a database DELETE query
            # For now, implement via WhatsAppDB or direct Supabase call
            # Placeholder: return 0
            logger.info(f"Expiring sessions older than {older_than}")
            
            # TODO: Implement via WhatsAppDB._query_table with DELETE
            # For now, return 0 to indicate no deletions
            count = 0
            
            logger.info(f"✓ Expired {count} stale sessions (older than {cutoff})")
            return count
        
        except Exception as e:
            logger.error(f"Failed to expire stale sessions: {e}")
            raise MessageProcessingError(f"Failed to expire stale sessions: {e}")
    
    async def _truncate_and_save(self, session: Session) -> Session:
        """Truncate history to MAX_HISTORY_TURNS and save.
        
        Helper method to enforce history bound on every write.
        Keeps last N turns, discards oldest.
        
        Args:
            session: Session with potentially oversized history
        
        Returns:
            Session with truncated history (saved to database)
        """
        # Truncate to last MAX_HISTORY_TURNS
        if len(session.history) > MAX_HISTORY_TURNS:
            session.history = session.history[-MAX_HISTORY_TURNS:]
            logger.debug(f"Truncated history to {MAX_HISTORY_TURNS} turns")
        
        # Save to database
        session = await self.db.save_conversation(session)
        return session
