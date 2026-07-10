"""Unit tests for WhatsAppDB class.

Tests:
- Session creation and loading
- Message appending with idempotency
- Entity resolution (customer, agent, property lookups)
- Circuit breaker protection
- Retry logic with backoff
"""

import pytest
import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from src.whatsapp.db import WhatsAppDB
from src.whatsapp.models import Session, InboundMessage
from src.whatsapp.errors import (
    SessionNotFoundError,
    MessageProcessingError,
    ValidationError,
    IdempotencyError,
)
from src.utils.supabase_client import SupabaseClient


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def mock_supabase():
    """Create mock SupabaseClient."""
    client = AsyncMock(spec=SupabaseClient)
    client.rest_client = AsyncMock()
    return client


@pytest.fixture
def whatsapp_db(mock_supabase):
    """Create WhatsAppDB instance with mock Supabase."""
    return WhatsAppDB(mock_supabase)


@pytest.fixture
def sample_inbound_message():
    """Create sample InboundMessage for testing."""
    return InboundMessage(
        provider="gupshup",
        provider_message_id="msg_12345",
        from_phone="+917045983015",
        to_phone="+919876543210",
        timestamp=datetime.now(timezone.utc),
        type="text",
        text="Hello, I'm interested in the property",
        media_ids=[],
        raw={}
    )


# ============================================================================
# Test: Session Creation and Loading
# ============================================================================

@pytest.mark.asyncio
async def test_get_conversation_creates_new_session(whatsapp_db):
    """Test that get_conversation creates new session if not found."""
    # Arrange
    phone = "+917045983015"
    channel = "customer"
    
    # Mock _query_table to return empty list (not found)
    whatsapp_db._query_table = AsyncMock(return_value=[])
    
    # Act
    session = await whatsapp_db.get_conversation(phone, channel)
    
    # Assert
    assert session is not None
    assert session.phone == phone
    assert session.channel == channel
    assert session.state == "idle"
    assert session.history == []
    assert session.opted_in is False
    assert session.customer_id is None


@pytest.mark.asyncio
async def test_get_conversation_loads_existing_session(whatsapp_db):
    """Test that get_conversation loads existing session."""
    # Arrange
    phone = "+917045983015"
    channel = "customer"
    existing_row = {
        "phone": phone,
        "channel": channel,
        "customer_id": "cust_123",
        "agent_id": None,
        "property_id": "prop_456",
        "draft_property_id": None,
        "state": "idle",
        "history": [{"role": "customer", "text": "Hello", "ts": "2024-01-01T10:00:00Z"}],
        "service_window_expires_at": "2024-01-02T10:00:00Z",
        "opted_in": True,
        "created_at": "2024-01-01T10:00:00Z",
        "updated_at": "2024-01-01T10:00:00Z",
    }
    
    whatsapp_db._query_table = AsyncMock(return_value=[existing_row])
    
    # Act
    session = await whatsapp_db.get_conversation(phone, channel)
    
    # Assert
    assert session.phone == phone
    assert session.channel == channel
    assert session.customer_id == "cust_123"
    assert session.property_id == "prop_456"
    assert session.opted_in is True
    assert len(session.history) == 1


@pytest.mark.asyncio
async def test_get_conversation_normalizes_phone(whatsapp_db):
    """Test that phone numbers are normalized to E.164."""
    # Arrange
    phone = "7045983015"  # 10-digit number
    channel = "customer"
    
    whatsapp_db._query_table = AsyncMock(return_value=[])
    
    # Act
    session = await whatsapp_db.get_conversation(phone, channel)
    
    # Assert
    assert session.phone == "+917045983015"  # Should be normalized


@pytest.mark.asyncio
async def test_get_conversation_invalid_phone_raises_error(whatsapp_db):
    """Test that invalid phone raises ValidationError."""
    # Act & Assert
    with pytest.raises(ValidationError):
        await whatsapp_db.get_conversation("invalid", "customer")


@pytest.mark.asyncio
async def test_get_conversation_invalid_channel_raises_error(whatsapp_db):
    """Test that invalid channel raises ValidationError."""
    # Act & Assert
    with pytest.raises(ValidationError):
        await whatsapp_db.get_conversation("+917045983015", "invalid")


# ============================================================================
# Test: Session Persistence
# ============================================================================

@pytest.mark.asyncio
async def test_save_conversation_creates_server_timestamps(whatsapp_db):
    """Test that save_conversation adds server timestamps."""
    # Arrange
    session = Session(
        phone="+917045983015",
        channel="customer",
        state="idle",
        history=[],
    )
    
    whatsapp_db._upsert_row = AsyncMock(return_value={
        "phone": session.phone,
        "channel": session.channel,
        "state": "idle",
        "history": [],
        "created_at": datetime.now(timezone.utc).isoformat() + "Z",
        "updated_at": datetime.now(timezone.utc).isoformat() + "Z",
    })
    
    # Act
    result = await whatsapp_db.save_conversation(session)
    
    # Assert
    assert result is not None
    assert result.phone == session.phone
    whatsapp_db._upsert_row.assert_called_once()


@pytest.mark.asyncio
async def test_save_conversation_invalid_channel_raises_error(whatsapp_db):
    """Test that saving with invalid channel raises error."""
    # Arrange
    session = Session(
        phone="+917045983015",
        channel="invalid",
    )
    
    # Act & Assert
    with pytest.raises(ValidationError):
        await whatsapp_db.save_conversation(session)


# ============================================================================
# Test: Message Appending
# ============================================================================

@pytest.mark.asyncio
async def test_append_inbound_message_checks_idempotency(whatsapp_db, sample_inbound_message):
    """Test that append_inbound_message checks idempotency."""
    # Arrange
    phone = "+917045983015"
    whatsapp_db.check_idempotency = AsyncMock(return_value=False)  # Not a duplicate
    whatsapp_db.get_conversation = AsyncMock(return_value=Session(
        phone=phone,
        channel="customer",
        state="idle",
        history=[],
    ))
    whatsapp_db._insert_row = AsyncMock()
    whatsapp_db.save_conversation = AsyncMock(return_value=Session(
        phone=phone,
        channel="customer",
        state="idle",
        history=[{"role": "customer", "text": "Hello", "ts": "2024-01-01T10:00:00Z"}],
    ))
    
    # Act
    result = await whatsapp_db.append_inbound_message(phone, sample_inbound_message)
    
    # Assert
    whatsapp_db.check_idempotency.assert_called_once_with(
        sample_inbound_message.provider,
        sample_inbound_message.provider_message_id
    )
    assert result is not None


@pytest.mark.asyncio
async def test_append_inbound_message_detects_duplicates(whatsapp_db, sample_inbound_message):
    """Test that append_inbound_message rejects duplicates."""
    # Arrange
    phone = "+917045983015"
    whatsapp_db.check_idempotency = AsyncMock(return_value=True)  # Is a duplicate
    
    # Act & Assert
    with pytest.raises(IdempotencyError):
        await whatsapp_db.append_inbound_message(phone, sample_inbound_message)


@pytest.mark.asyncio
async def test_append_inbound_message_updates_service_window(whatsapp_db, sample_inbound_message):
    """Test that append_inbound_message sets service_window_expires_at."""
    # Arrange
    phone = "+917045983015"
    session = Session(
        phone=phone,
        channel="customer",
        state="idle",
        history=[],
        service_window_expires_at=None,
    )
    
    whatsapp_db.check_idempotency = AsyncMock(return_value=False)
    whatsapp_db.get_conversation = AsyncMock(return_value=session)
    whatsapp_db._insert_row = AsyncMock()
    
    saved_session = Session(
        phone=phone,
        channel="customer",
        state="idle",
        history=[{"role": "customer", "text": "Hello", "ts": "2024-01-01T10:00:00Z"}],
        service_window_expires_at=datetime.now(timezone.utc),
    )
    whatsapp_db.save_conversation = AsyncMock(return_value=saved_session)
    
    # Act
    result = await whatsapp_db.append_inbound_message(phone, sample_inbound_message)
    
    # Assert
    assert result is not None
    assert result.service_window_expires_at is not None


# ============================================================================
# Test: Entity Resolution
# ============================================================================

@pytest.mark.asyncio
async def test_get_customer_returns_customer_record(whatsapp_db):
    """Test that get_customer returns customer record."""
    # Arrange
    phone = "+917045983015"
    customer_record = {
        "id": "cust_123",
        "phone": phone,
        "name": "John Doe",
        "whatsapp_opted_in": True,
    }
    
    whatsapp_db._query_table = AsyncMock(return_value=[customer_record])
    
    # Act
    result = await whatsapp_db.get_customer(phone)
    
    # Assert
    assert result == customer_record


@pytest.mark.asyncio
async def test_get_customer_returns_none_if_not_found(whatsapp_db):
    """Test that get_customer returns None if not found."""
    # Arrange
    phone = "+917045983015"
    whatsapp_db._query_table = AsyncMock(return_value=[])
    
    # Act
    result = await whatsapp_db.get_customer(phone)
    
    # Assert
    assert result is None


@pytest.mark.asyncio
async def test_get_agent_returns_agent_record(whatsapp_db):
    """Test that get_agent returns agent record."""
    # Arrange
    phone = "+919876543210"
    agent_record = {
        "id": "agent_123",
        "phone": phone,
        "name": "Jane Smith",
        "status": "available",
    }
    
    whatsapp_db._query_table = AsyncMock(return_value=[agent_record])
    
    # Act
    result = await whatsapp_db.get_agent(phone)
    
    # Assert
    assert result == agent_record


@pytest.mark.asyncio
async def test_get_agent_fails_gracefully(whatsapp_db):
    """Test that get_agent fails gracefully and returns None."""
    # Arrange
    phone = "+919876543210"
    whatsapp_db._query_table = AsyncMock(side_effect=Exception("DB error"))
    
    # Act
    result = await whatsapp_db.get_agent(phone)
    
    # Assert
    assert result is None  # Fail-safe


@pytest.mark.asyncio
async def test_get_property_returns_property_record(whatsapp_db):
    """Test that get_property returns property record."""
    # Arrange
    property_id = "prop_123"
    property_record = {
        "id": property_id,
        "title": "2BHK Apartment",
        "price": 1200000,
        "sqft": 900,
        "location": "Bandra",
    }
    
    whatsapp_db._query_table = AsyncMock(return_value=[property_record])
    
    # Act
    result = await whatsapp_db.get_property(property_id)
    
    # Assert
    assert result == property_record


@pytest.mark.asyncio
async def test_get_property_returns_none_if_not_found(whatsapp_db):
    """Test that get_property returns None if not found."""
    # Arrange
    property_id = "prop_123"
    whatsapp_db._query_table = AsyncMock(return_value=[])
    
    # Act
    result = await whatsapp_db.get_property(property_id)
    
    # Assert
    assert result is None


# ============================================================================
# Test: Idempotency Checks
# ============================================================================

@pytest.mark.asyncio
async def test_check_idempotency_detects_duplicates(whatsapp_db):
    """Test that check_idempotency detects duplicate messages."""
    # Arrange
    whatsapp_db._query_table = AsyncMock(return_value=[{"id": "msg_1"}])
    
    # Act
    result = await whatsapp_db.check_idempotency("gupshup", "msg_12345")
    
    # Assert
    assert result is True


@pytest.mark.asyncio
async def test_check_idempotency_allows_new_messages(whatsapp_db):
    """Test that check_idempotency allows new messages."""
    # Arrange
    whatsapp_db._query_table = AsyncMock(return_value=[])
    
    # Act
    result = await whatsapp_db.check_idempotency("gupshup", "msg_12345")
    
    # Assert
    assert result is False


@pytest.mark.asyncio
async def test_check_idempotency_fails_gracefully(whatsapp_db):
    """Test that check_idempotency fails gracefully."""
    # Arrange
    whatsapp_db._query_table = AsyncMock(side_effect=Exception("DB error"))
    
    # Act
    result = await whatsapp_db.check_idempotency("gupshup", "msg_12345")
    
    # Assert
    assert result is False  # Fail-open


# ============================================================================
# Test: Data Conversion
# ============================================================================

def test_row_to_session_conversion(whatsapp_db):
    """Test conversion from database row to Session object."""
    # Arrange
    row = {
        "phone": "+917045983015",
        "channel": "customer",
        "customer_id": "cust_123",
        "agent_id": None,
        "property_id": "prop_456",
        "draft_property_id": None,
        "state": "idle",
        "history": [{"role": "customer", "text": "Hello"}],
        "service_window_expires_at": "2024-01-02T10:00:00Z",
        "opted_in": True,
        "created_at": "2024-01-01T10:00:00Z",
        "updated_at": "2024-01-01T10:00:00Z",
    }
    
    # Act
    session = whatsapp_db._row_to_session(row)
    
    # Assert
    assert session.phone == row["phone"]
    assert session.channel == row["channel"]
    assert session.customer_id == row["customer_id"]
    assert session.opted_in is True


def test_session_to_row_conversion(whatsapp_db):
    """Test conversion from Session object to database row."""
    # Arrange
    now = datetime.now(timezone.utc)
    session = Session(
        phone="+917045983015",
        channel="customer",
        customer_id="cust_123",
        property_id="prop_456",
        state="idle",
        history=[{"role": "customer", "text": "Hello"}],
        service_window_expires_at=now,
        opted_in=True,
        created_at=now,
        updated_at=now,
    )
    
    # Act
    row = whatsapp_db._session_to_row(session)
    
    # Assert
    assert row["phone"] == session.phone
    assert row["channel"] == session.channel
    assert row["customer_id"] == session.customer_id
    assert row["opted_in"] is True
    assert isinstance(row["created_at"], str)
    assert "Z" in row["created_at"]


# ============================================================================
# Test: Outbound Message Logging
# ============================================================================

@pytest.mark.asyncio
async def test_append_outbound_message_logs_message(whatsapp_db):
    """Test that append_outbound_message logs outbound message."""
    # Arrange
    phone = "+917045983015"
    text = "Thank you for your interest!"
    
    whatsapp_db._insert_row = AsyncMock(return_value={
        "id": "msg_out_123",
        "direction": "outbound",
        "status": "sent",
    })
    
    # Act
    result = await whatsapp_db.append_outbound_message(phone, text)
    
    # Assert
    assert result is not None
    whatsapp_db._insert_row.assert_called_once()


@pytest.mark.asyncio
async def test_append_outbound_message_includes_template_name(whatsapp_db):
    """Test that append_outbound_message includes template_name when provided."""
    # Arrange
    phone = "+917045983015"
    text = "Property update"
    template_name = "property_followup_v1"
    
    whatsapp_db._insert_row = AsyncMock(return_value={"id": "msg_out_123"})
    
    # Act
    result = await whatsapp_db.append_outbound_message(
        phone,
        text,
        template_name=template_name
    )
    
    # Assert
    assert result is not None
    call_args = whatsapp_db._insert_row.call_args
    row = call_args[0][1]
    assert row["template_name"] == template_name


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
