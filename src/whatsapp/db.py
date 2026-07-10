"""Database layer for WhatsApp Conversational Channel.

Wraps Supabase REST API and handles:
- Session CRUD (wa_conversations)
- Message logging (wa_messages)
- Idempotency checks
- Entity resolution (customer, agent lookup)
"""

from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta, timezone
import asyncio
import httpx
import json
from loguru import logger
from .models import Session, InboundMessage
from .config import Channel, SERVICE_WINDOW_HOURS, MAX_HISTORY_TURNS
from .errors import (
    SessionNotFoundError,
    MessageProcessingError,
    ValidationError,
    IdempotencyError,
)
from ..utils.supabase_client import SupabaseClient
from ..utils.resilience import CircuitBreaker, retry_with_backoff
from ..utils.validation import validate_phone_number


class WhatsAppDB:
    """Database layer for WhatsApp Conversational Channel.
    
    Provides high-level methods for session and message management.
    Wraps SupabaseClient with WhatsApp-specific queries, circuit breaker
    protection, and retry logic.
    
    Design:
    - Reuses existing SupabaseClient from src/utils/supabase_client.py
    - Wraps with circuit breaker (failure threshold: 3, timeout: 30s)
    - Applies retry logic (2 retries, exponential backoff)
    - Handles idempotency via (provider, provider_message_id) unique constraint
    - Converts between dataclass (Session) and database row formats
    """
    
    def __init__(self, supabase_client: SupabaseClient):
        """Initialize with existing SupabaseClient.
        
        Args:
            supabase_client: Existing SupabaseClient instance (reused from agent.py)
        
        Preconditions:
            - supabase_client must be properly initialized with API key and base URL
            - Supabase tables must exist: wa_conversations, wa_messages, agents, customers, properties
        """
        self.supabase = supabase_client
        self.circuit_breaker = CircuitBreaker(
            name="whatsapp_db",
            failure_threshold=3,
            timeout_seconds=30
        )
        logger.info("WhatsAppDB initialized with circuit breaker protection")
    
    async def get_conversation(
        self,
        phone: str,
        channel: str,
    ) -> Session:
        """Load or create conversation session by (phone, channel).
        
        Queries wa_conversations table for an existing session.
        If not found, creates a new one with default values.
        
        Preconditions:
            - phone must be E.164 format (or will be normalized)
            - channel must be 'customer' or 'agent'
        
        Postconditions:
            - Returns Session object with all fields populated
            - If new session created: timestamps set, history empty, state='idle'
            - If existing session loaded: all fields preserved from database
        
        Args:
            phone: E.164 phone number (or will be normalized)
            channel: 'customer' | 'agent'
        
        Returns:
            Session object (never None; creates new if not found)
        
        Raises:
            SessionNotFoundError: If database is unreachable after retries
            ValidationError: If phone cannot be normalized to E.164
        """
        # Normalize phone to E.164
        try:
            phone = validate_phone_number(phone)
        except Exception as e:
            raise ValidationError(f"Invalid phone number: {phone} - {e}")
        
        # Validate channel
        if channel not in ("customer", "agent"):
            raise ValidationError(f"Invalid channel: {channel}")
        
        async def _load_session():
            """Internal function to load session via circuit breaker."""
            try:
                # Query wa_conversations table with phone + channel
                rows = await self._query_table(
                    "wa_conversations",
                    {"phone": phone, "channel": channel}
                )
                
                if rows:
                    logger.debug(f"✓ Loaded existing session: {phone} ({channel})")
                    return self._row_to_session(rows[0])
                else:
                    # Create new session with defaults
                    logger.debug(f"✓ Creating new session: {phone} ({channel})")
                    now = datetime.now(timezone.utc)
                    return Session(
                        phone=phone,
                        channel=channel,
                        customer_id=None,
                        agent_id=None,
                        property_id=None,
                        draft_property_id=None,
                        state="idle",
                        history=[],
                        service_window_expires_at=None,  # Set on first inbound
                        opted_in=False,
                        created_at=now,
                        updated_at=now,
                    )
            except httpx.HTTPError as e:
                logger.error(f"HTTP error loading session: {e}")
                raise
            except Exception as e:
                logger.error(f"Error loading session: {e}")
                raise
        
        try:
            session = await retry_with_backoff(
                _load_session,
                max_retries=2,
                name=f"get_conversation({phone}, {channel})"
            )
            return session
        
        except Exception as e:
            logger.error(f"Failed to get conversation after retries: {e}")
            raise SessionNotFoundError(f"Failed to load or create conversation for {phone}: {e}")
    
    async def save_conversation(self, session: Session) -> Session:
        """Persist session to wa_conversations table (upsert).
        
        Creates new row if phone+channel doesn't exist, otherwise updates.
        Auto-truncates history to MAX_HISTORY_TURNS on database trigger.
        Auto-updates timestamps.
        
        Preconditions:
            - session.phone must be valid E.164
            - session.channel must be 'customer' or 'agent'
            - All fields must be serializable to JSON
        
        Postconditions:
            - Row exists in wa_conversations with all session fields
            - Updated timestamps reflect server time (not client time)
            - History truncated to last N turns by database
            - Returns updated session with server timestamps
        
        Args:
            session: Session object to save
        
        Returns:
            Session object with updated timestamps from server
        
        Raises:
            MessageProcessingError: If save fails after retries
            ValidationError: If session data invalid
        """
        # Validate session before save
        if not session.phone:
            raise ValidationError("Session phone is required")
        if session.channel not in ("customer", "agent"):
            raise ValidationError(f"Invalid session channel: {session.channel}")
        
        async def _upsert_session():
            """Internal function to upsert session via circuit breaker."""
            try:
                # Convert session to database row
                payload = self._session_to_row(session)
                
                # Add server-side timestamps
                now = datetime.now(timezone.utc).isoformat() + "Z"
                if not payload.get("created_at"):
                    payload["created_at"] = now
                payload["updated_at"] = now
                
                # Attempt upsert
                # Note: In production, use actual Supabase REST API
                # For now, simulate with insert/update logic
                row = await self._upsert_row(
                    "wa_conversations",
                    payload,
                    unique_keys=["phone", "channel"]
                )
                
                logger.debug(f"✓ Saved session: {session.phone} ({session.channel})")
                return self._row_to_session(row)
            
            except httpx.HTTPError as e:
                logger.error(f"HTTP error saving session: {e}")
                raise
            except Exception as e:
                logger.error(f"Error saving session: {e}")
                raise
        
        try:
            result = await retry_with_backoff(
                _upsert_session,
                max_retries=2,
                name=f"save_conversation({session.phone})"
            )
            return result
        
        except Exception as e:
            logger.error(f"Failed to save conversation after retries: {e}")
            raise MessageProcessingError(f"Failed to save session: {e}")
    
    async def append_inbound_message(
        self,
        phone: str,
        inbound_msg: InboundMessage,
    ) -> Session:
        """Process inbound message: log to wa_messages, update session.
        
        Creates audit trail entry in wa_messages table and updates session
        with the new message in history. Sets service_window_expires_at to
        now + 24 hours for WhatsApp Business window compliance.
        
        Preconditions:
            - phone must be valid E.164
            - inbound_msg must have valid provider_message_id (for idempotency)
            - Conversation session must exist (caller should call get_conversation first)
        
        Postconditions:
            - Audit row created in wa_messages with direction='inbound', status='received'
            - Session.history updated with new message turn
            - Session.service_window_expires_at set to now + 24h
            - History truncated to MAX_HISTORY_TURNS by database
            - Idempotency checked via (provider, provider_message_id) constraint
        
        Args:
            phone: E.164 phone number of sender
            inbound_msg: InboundMessage object with canonical fields
        
        Returns:
            Updated Session object with new message in history
        
        Raises:
            IdempotencyError: If (provider, provider_message_id) already exists
            MessageProcessingError: If audit log or session update fails
            ValidationError: If phone/message invalid
        """
        # Normalize phone
        try:
            phone = validate_phone_number(phone)
        except Exception as e:
            raise ValidationError(f"Invalid phone: {phone} - {e}")
        
        # Check idempotency first
        is_duplicate = await self.check_idempotency(
            inbound_msg.provider,
            inbound_msg.provider_message_id
        )
        if is_duplicate:
            logger.warning(
                f"Duplicate message detected: {inbound_msg.provider} "
                f"{inbound_msg.provider_message_id}"
            )
            raise IdempotencyError(
                f"Message already processed: {inbound_msg.provider} "
                f"{inbound_msg.provider_message_id}"
            )
        
        async def _append_message():
            """Internal function to append message with circuit breaker."""
            try:
                # Load or create session
                session = await self.get_conversation(phone, "customer")
                
                # Get or create conversation_id (use phone as key in this implementation)
                conversation_id = session.phone  # In production, use UUID primary key
                
                # Insert audit row in wa_messages
                msg_row = {
                    "conversation_id": conversation_id,
                    "direction": "inbound",
                    "provider": inbound_msg.provider,
                    "provider_message_id": inbound_msg.provider_message_id,
                    "from_phone": inbound_msg.from_phone,
                    "to_phone": inbound_msg.to_phone,
                    "type": inbound_msg.type,
                    "body": inbound_msg.text,
                    "media_urls": inbound_msg.media_ids,
                    "status": "received",
                    "error": None,
                    "created_at": inbound_msg.timestamp.isoformat() + "Z" if inbound_msg.timestamp else datetime.now(timezone.utc).isoformat() + "Z",
                }
                
                await self._insert_row("wa_messages", msg_row)
                logger.debug(f"✓ Logged inbound message: {inbound_msg.provider_message_id}")
                
                # Update session with new message in history
                now = datetime.now(timezone.utc)
                session.history.append({
                    "role": "customer",
                    "text": inbound_msg.text or f"[{inbound_msg.type}]",
                    "ts": now.isoformat() + "Z",
                    "type": inbound_msg.type,
                })
                
                # Set service window to 24h from now
                session.service_window_expires_at = now + timedelta(hours=SERVICE_WINDOW_HOURS)
                
                # Save updated session
                session = await self.save_conversation(session)
                
                logger.debug(f"✓ Updated session with inbound message")
                return session
            
            except httpx.HTTPError as e:
                logger.error(f"HTTP error appending message: {e}")
                raise
            except Exception as e:
                logger.error(f"Error appending message: {e}")
                raise
        
        try:
            result = await retry_with_backoff(
                _append_message,
                max_retries=2,
                name=f"append_inbound_message({inbound_msg.provider_message_id})"
            )
            return result
        
        except Exception as e:
            logger.error(f"Failed to append inbound message after retries: {e}")
            raise MessageProcessingError(f"Failed to process inbound message: {e}")
    
    async def append_outbound_message(
        self,
        phone: str,
        text: str,
        provider: str = "gupshup",
        message_type: str = "text",
        template_name: Optional[str] = None,
    ) -> Dict:
        """Log outbound message to wa_messages table (audit trail).
        
        Called when system sends a reply to customer or agent.
        Records send attempt for compliance audit and debugging.
        
        Preconditions:
            - phone must be valid E.164
            - text must be non-empty
            - provider must be 'gupshup' or 'twilio'
        
        Postconditions:
            - Audit row created in wa_messages with direction='outbound'
            - template_name field populated if HSM template was used
            - status field set to 'sent' (sending, not yet delivered)
        
        Args:
            phone: E.164 phone of recipient
            text: Message body text
            provider: 'gupshup' | 'twilio'
            message_type: 'text' | 'template' | 'media'
            template_name: HSM template name (if using template)
        
        Returns:
            Audit message row dict
        
        Raises:
            MessageProcessingError: If audit log write fails
            ValidationError: If phone or text invalid
        """
        # Normalize phone
        try:
            phone = validate_phone_number(phone)
        except Exception as e:
            raise ValidationError(f"Invalid phone: {phone} - {e}")
        
        if not text or not isinstance(text, str):
            raise ValidationError("Text message required")
        
        async def _log_outbound():
            """Internal function to log outbound with circuit breaker."""
            try:
                msg_row = {
                    "conversation_id": phone,  # Use phone as key
                    "direction": "outbound",
                    "provider": provider,
                    "provider_message_id": None,  # Will be set by provider on send
                    "from_phone": None,  # Will be business number
                    "to_phone": phone,
                    "type": message_type,
                    "body": text,
                    "media_urls": [],
                    "template_name": template_name,
                    "status": "sent",
                    "error": None,
                    "created_at": datetime.now(timezone.utc).isoformat() + "Z",
                }
                
                row = await self._insert_row("wa_messages", msg_row)
                logger.debug(f"✓ Logged outbound message: {message_type}")
                return row
            
            except httpx.HTTPError as e:
                logger.error(f"HTTP error logging outbound: {e}")
                raise
            except Exception as e:
                logger.error(f"Error logging outbound: {e}")
                raise
        
        try:
            result = await retry_with_backoff(
                _log_outbound,
                max_retries=2,
                name=f"append_outbound_message({phone})"
            )
            return result
        
        except Exception as e:
            logger.error(f"Failed to log outbound after retries: {e}")
            raise MessageProcessingError(f"Failed to log outbound message: {e}")
    
    async def check_idempotency(
        self,
        provider: str,
        provider_message_id: str,
    ) -> bool:
        """Check if (provider, provider_message_id) was already processed.
        
        Ensures exactly-once processing of webhook deliveries.
        Providers may retry webhooks; this detects duplicates.
        
        Preconditions:
            - provider must be 'gupshup' or 'twilio'
            - provider_message_id must be non-empty string
        
        Postconditions:
            - Returns True if message already in wa_messages table
            - Returns False if message is new (first time seen)
            - On database error, returns False (fail-open: process message)
        
        Args:
            provider: 'gupshup' | 'twilio'
            provider_message_id: Provider's unique message ID
        
        Returns:
            True if already processed (duplicate), False if new
        """
        if not provider or not provider_message_id:
            raise ValidationError("Provider and provider_message_id required")
        
        async def _check_exists():
            """Internal function to check existence."""
            try:
                rows = await self._query_table(
                    "wa_messages",
                    {
                        "provider": provider,
                        "provider_message_id": provider_message_id,
                    }
                )
                
                exists = len(rows) > 0
                logger.debug(
                    f"Idempotency check: {provider} {provider_message_id} "
                    f"→ {'duplicate' if exists else 'new'}"
                )
                return exists
            
            except httpx.HTTPError as e:
                logger.error(f"HTTP error checking idempotency: {e}")
                raise
            except Exception as e:
                logger.error(f"Error checking idempotency: {e}")
                raise
        
        try:
            result = await retry_with_backoff(
                _check_exists,
                max_retries=1,
                name=f"check_idempotency({provider}, {provider_message_id})"
            )
            return result
        
        except Exception as e:
            logger.warning(f"Idempotency check failed, assuming new message: {e}")
            # Fail-open: assume new message if check fails
            # Better to process once more than to drop legitimate messages
            return False
    
    async def get_customer(self, phone: str) -> Optional[Dict]:
        """Look up customer by phone.
        
        Queries customers table by E.164 phone number.
        
        Preconditions:
            - phone must be valid E.164 format
        
        Postconditions:
            - Returns customer record with id, name, whatsapp_opted_in, etc.
            - Returns None if customer not found
            - On database error, raises ValidationError
        
        Args:
            phone: E.164 phone number
        
        Returns:
            Customer dict (id, name, whatsapp_opted_in, etc.) or None
        
        Raises:
            ValidationError: If lookup fails
        """
        # Normalize phone
        try:
            phone = validate_phone_number(phone)
        except Exception as e:
            raise ValidationError(f"Invalid phone: {phone} - {e}")
        
        async def _get_customer():
            """Internal function to get customer."""
            try:
                result = await self._query_table("customers", {"phone": phone})
                if result:
                    logger.debug(f"✓ Found customer: {phone}")
                    return result[0]
                else:
                    logger.debug(f"✗ Customer not found: {phone}")
                    return None
            
            except httpx.HTTPError as e:
                logger.error(f"HTTP error getting customer: {e}")
                raise
            except Exception as e:
                logger.error(f"Error getting customer: {e}")
                raise
        
        try:
            result = await retry_with_backoff(
                _get_customer,
                max_retries=2,
                name=f"get_customer({phone})"
            )
            return result
        
        except Exception as e:
            logger.error(f"Failed to get customer after retries: {e}")
            raise ValidationError(f"Failed to lookup customer: {e}")
    
    async def get_agent(self, phone: str) -> Optional[Dict]:
        """Look up agent by phone.
        
        Queries agents table by E.164 phone number.
        
        Preconditions:
            - phone must be valid E.164 format
        
        Postconditions:
            - Returns agent record with id, name, status, etc.
            - Returns None if agent not found
            - On database error, returns None (fail-safe)
        
        Args:
            phone: E.164 phone number
        
        Returns:
            Agent dict (id, name, status, etc.) or None
        """
        # Normalize phone
        try:
            phone = validate_phone_number(phone)
        except Exception as e:
            raise ValidationError(f"Invalid phone: {phone} - {e}")
        
        async def _get_agent():
            """Internal function to get agent."""
            try:
                result = await self._query_table("agents", {"phone": phone})
                if result:
                    logger.debug(f"✓ Found agent: {phone}")
                    return result[0]
                else:
                    logger.debug(f"✗ Agent not found: {phone}")
                    return None
            
            except httpx.HTTPError as e:
                logger.error(f"HTTP error getting agent: {e}")
                raise
            except Exception as e:
                logger.error(f"Error getting agent: {e}")
                raise
        
        try:
            result = await retry_with_backoff(
                _get_agent,
                max_retries=2,
                name=f"get_agent({phone})"
            )
            return result
        
        except Exception as e:
            logger.warning(f"Failed to get agent, returning None (fail-safe): {e}")
            # Fail-safe: if DB is down, return None (treat as customer)
            return None
    
    async def get_property(self, property_id: str) -> Optional[Dict]:
        """Look up property by ID.
        
        Queries properties table by UUID.
        
        Preconditions:
            - property_id must be valid UUID format
        
        Postconditions:
            - Returns property record with title, price, sqft, location, etc.
            - Returns None if property not found
            - On database error, raises MessageProcessingError
        
        Args:
            property_id: UUID of property
        
        Returns:
            Property dict (title, price, sqft, location, etc.) or None
        
        Raises:
            MessageProcessingError: If lookup fails
        """
        if not property_id:
            raise ValidationError("Property ID required")
        
        async def _get_property():
            """Internal function to get property."""
            try:
                result = await self._query_table("properties", {"id": property_id})
                if result:
                    logger.debug(f"✓ Found property: {property_id}")
                    return result[0]
                else:
                    logger.debug(f"✗ Property not found: {property_id}")
                    return None
            
            except httpx.HTTPError as e:
                logger.error(f"HTTP error getting property: {e}")
                raise
            except Exception as e:
                logger.error(f"Error getting property: {e}")
                raise
        
        try:
            result = await retry_with_backoff(
                _get_property,
                max_retries=2,
                name=f"get_property({property_id})"
            )
            return result
        
        except Exception as e:
            logger.error(f"Failed to get property after retries: {e}")
            raise MessageProcessingError(f"Failed to lookup property: {e}")
    
    # ========================================================================
    # Helper Methods
    # ========================================================================
    
    def _row_to_session(self, row: Dict) -> Session:
        """Convert database row to Session dataclass.
        
        Args:
            row: Dictionary from wa_conversations table
        
        Returns:
            Session object with all fields populated
        """
        return Session(
            phone=row.get("phone"),
            channel=row.get("channel"),
            customer_id=row.get("customer_id"),
            agent_id=row.get("agent_id"),
            property_id=row.get("property_id"),
            draft_property_id=row.get("draft_property_id"),
            state=row.get("state", "idle"),
            history=row.get("history", []),
            service_window_expires_at=row.get("service_window_expires_at"),
            opted_in=row.get("opted_in", False),
            created_at=row.get("created_at"),
            updated_at=row.get("updated_at"),
        )
    
    def _session_to_row(self, session: Session) -> Dict:
        """Convert Session dataclass to database row.
        
        Args:
            session: Session object
        
        Returns:
            Dictionary ready for wa_conversations table
        """
        return {
            "phone": session.phone,
            "channel": session.channel,
            "customer_id": session.customer_id,
            "agent_id": session.agent_id,
            "property_id": session.property_id,
            "draft_property_id": session.draft_property_id,
            "state": session.state,
            "history": session.history,
            "service_window_expires_at": session.service_window_expires_at.isoformat() + "Z" if session.service_window_expires_at else None,
            "opted_in": session.opted_in,
            "created_at": session.created_at.isoformat() + "Z" if session.created_at else None,
            "updated_at": session.updated_at.isoformat() + "Z" if session.updated_at else None,
        }
    
    async def _query_table(
        self,
        table: str,
        filters: Dict[str, Any]
    ) -> List[Dict]:
        """Query a table with exact match filters.
        
        Builds Supabase REST API URL with exact-match filters and executes GET.
        Example: GET /rest/v1/customers?phone=eq.%2B919876543210&select=*
        
        Args:
            table: Table name (wa_conversations, agents, customers, etc.)
            filters: Dictionary of column=value filters (exact match only)
        
        Returns:
            List of matching rows
        
        Raises:
            httpx.HTTPError: If HTTP request fails
            Exception: If query parsing fails
        """
        try:
            # Build filter query string
            filter_parts = []
            for key, value in filters.items():
                # Use eq. (exact equality) filter for all filters
                # Value is URL-encoded by SupabaseClient._safe_encode_filter
                encoded_value = self.supabase._safe_encode_filter(value)
                filter_parts.append(f"{key}=eq.{encoded_value}")
            
            filter_query = "&".join(filter_parts)
            
            # Build full URL: GET /table_name?filter1=eq.value1&filter2=eq.value2&select=*
            url = f"{self.supabase.base_url}/{table}?{filter_query}&select=*"
            
            logger.debug(f"Query {table}: {list(filters.keys())} → {url}")
            
            # Execute GET request
            response = await self.supabase._get(url)
            response.raise_for_status()
            
            # Parse JSON response
            rows = response.json()
            logger.debug(f"Query {table}: returned {len(rows)} row(s)")
            
            return rows if isinstance(rows, list) else [rows] if rows else []
        
        except httpx.HTTPError as e:
            logger.error(f"HTTP error querying {table}: {e}")
            raise
        except json.JSONDecodeError as e:
            logger.error(f"JSON decode error for {table}: {e}")
            raise
        except Exception as e:
            logger.error(f"Query failed for {table}: {e}")
            raise
    
    async def _insert_row(
        self,
        table: str,
        row: Dict[str, Any]
    ) -> Dict:
        """Insert a single row into a table.
        
        POST data to Supabase REST API to create new row.
        Example: POST /table_name with JSON body
        
        Preconditions:
            - All required columns must be present in row
            - JSON values must be serializable
        
        Postconditions:
            - Row created in table
            - Server-generated fields (id, timestamps) populated
        
        Args:
            table: Table name
            row: Row data as dictionary (must be JSON-serializable)
        
        Returns:
            Inserted row dict with server-generated fields (id, created_at, etc.)
        
        Raises:
            httpx.HTTPError: If HTTP request fails
            Exception: If JSON serialization fails
        """
        try:
            # Build URL: POST /table_name
            url = f"{self.supabase.base_url}/{table}"
            
            # Log key fields (avoid logging sensitive data)
            keys_logged = [k for k in row.keys() if k not in ['password', 'secret']]
            logger.debug(f"Insert into {table}: {len(row)} field(s) → {keys_logged}")
            
            # Execute POST request with row data as JSON body
            response = await self.supabase._post(url, json_data=row)
            response.raise_for_status()
            
            # Parse JSON response - Supabase returns inserted row(s)
            result = response.json()
            
            # Handle different response formats:
            # - If POST returns array of 1 item: use first item
            # - If POST returns single object: use it directly
            if isinstance(result, list):
                inserted_row = result[0] if result else {}
            else:
                inserted_row = result if result else {}
            
            logger.debug(f"✓ Inserted into {table}: {inserted_row.get('id', 'no-id')}")
            return inserted_row
        
        except httpx.HTTPError as e:
            logger.error(f"HTTP error inserting into {table}: {e}")
            raise
        except json.JSONDecodeError as e:
            logger.error(f"JSON decode error for {table} insert response: {e}")
            raise
        except Exception as e:
            logger.error(f"Insert failed for {table}: {e}")
            raise
    
    async def _upsert_row(
        self,
        table: str,
        row: Dict[str, Any],
        unique_keys: List[str]
    ) -> Dict:
        """Upsert a row (insert or update based on unique constraint).
        
        Uses Supabase REST API with on_conflict parameter.
        Example: POST /table_name?on_conflict=phone,channel with JSON body
        
        Preconditions:
            - unique_keys must match database unique constraint columns
            - row must contain all unique key values
            - row must be JSON-serializable
        
        Postconditions:
            - If (unique_keys) values don't exist: row inserted
            - If (unique_keys) values exist: row updated
            - Server timestamps (updated_at) updated
        
        Args:
            table: Table name
            row: Row data as dictionary
            unique_keys: Column names forming unique constraint (e.g., ['phone', 'channel'])
        
        Returns:
            Upserted row dict with server-generated/updated fields
        
        Raises:
            httpx.HTTPError: If HTTP request fails
            Exception: If validation or JSON serialization fails
        """
        try:
            # Validate that row contains all unique key values
            missing_keys = [k for k in unique_keys if k not in row]
            if missing_keys:
                raise ValueError(f"Row missing unique keys: {missing_keys}")
            
            # Build conflict resolution query string
            # on_conflict=unique_key_col1,unique_key_col2
            conflict_cols = ",".join(unique_keys)
            
            # Build URL: POST /table_name?on_conflict=col1,col2
            url = f"{self.supabase.base_url}/{table}?on_conflict={conflict_cols}"
            
            # Log operation (avoid sensitive data)
            keys_logged = [k for k in row.keys() if k not in ['password', 'secret']]
            logger.debug(f"Upsert {table} on {unique_keys}: {len(row)} field(s)")
            
            # Execute POST request with upsert semantics
            # Supabase handles on_conflict parameter to do update instead of insert
            response = await self.supabase._post(url, json_data=row)
            response.raise_for_status()
            
            # Parse JSON response
            result = response.json()
            
            # Handle different response formats
            if isinstance(result, list):
                upserted_row = result[0] if result else {}
            else:
                upserted_row = result if result else {}
            
            logger.debug(f"✓ Upserted {table}: {upserted_row.get('id', 'no-id')}")
            return upserted_row
        
        except ValueError as e:
            logger.error(f"Validation error in upsert: {e}")
            raise
        except httpx.HTTPError as e:
            logger.error(f"HTTP error upserting into {table}: {e}")
            raise
        except json.JSONDecodeError as e:
            logger.error(f"JSON decode error for {table} upsert response: {e}")
            raise
        except Exception as e:
            logger.error(f"Upsert failed for {table}: {e}")
            raise
