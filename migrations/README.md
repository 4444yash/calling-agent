# WhatsApp Conversational Channel Migrations

## Overview

This directory contains SQL migration files for the WhatsApp Conversational Channel feature. Each migration is designed to be applied sequentially to evolve the database schema.

---

## Migration: 001_whatsapp_schema.sql

**Status**: Initial schema for Wave 0  
**Created**: WhatsApp Conversational Channel - Wave 0  
**Tables**: `wa_conversations`, `wa_messages`  
**Storage**: `whatsapp-media` bucket  

### Tables Created

#### 1. `wa_conversations`

Stores multi-turn conversation state per `(phone, channel)` pair. This is the session store that maintains context across asynchronous WhatsApp messages.

**Columns**:
- `id` (UUID, primary key) — Unique conversation identifier
- `phone` (TEXT, indexed) — E.164 format phone number (+91XXXXXXXXXX)
- `channel` (TEXT) — `'customer'` or `'agent'` (customer-facing AI vs. agent command)
- `customer_id` (UUID, FK) — Reference to `customers.id` (NULL for agent channels)
- `agent_id` (UUID, FK) — Reference to `agents.id` (NULL for customer channels)
- `property_id` (UUID, FK) — Active property being discussed
- `draft_property_id` (UUID) — In-progress property upload (no FK, ephemeral)
- `state` (TEXT) — Conversation substates: `'idle'`, `'collecting_media'`, `'awaiting_confirmation'`
- `history` (JSONB) — Bounded array of turns (default max 12): `[{role, text, ts, type}, ...]`
- `service_window_expires_at` (TIMESTAMPTZ) — Last inbound customer message + 24h (WhatsApp Business window)
- `opted_in` (BOOLEAN) — Customer consent for business-initiated (template) messages
- `created_at`, `updated_at` (TIMESTAMPTZ) — Audit timestamps

**Indexes**:
- `(phone, channel)` — Primary lookup key for router
- `(customer_id)`, `(agent_id)` — Entity resolution
- `(updated_at)` — Stale session cleanup queries

**Triggers**:
- `truncate_conversation_history()` — Auto-truncate history to max 12 turns on each update
- `update_wa_conversations_timestamp()` — Auto-update `updated_at` on modify

**Purpose**: 
- Maintain multi-turn context for an inherently stateless channel
- Track service window for 24-hour compliance
- Manage opt-in state for DPDP/regulatory compliance
- Sub-states for media accumulation workflow

#### 2. `wa_messages`

Immutable audit log of all inbound and outbound WhatsApp messages. This is the primary DPDP compliance record.

**Columns**:
- `id` (UUID, primary key) — Unique message identifier
- `conversation_id` (UUID, FK) — Reference to `wa_conversations.id` (CASCADE delete)
- `direction` (TEXT) — `'inbound'` or `'outbound'`
- `provider` (TEXT) — `'gupshup'` or `'twilio'`
- `provider_message_id` (TEXT, unique per provider) — Provider's message ID (idempotency key)
- `from_phone`, `to_phone` (TEXT) — E.164 format
- `type` (TEXT) — Message type: `'text'`, `'image'`, `'document'`, `'audio'`, `'interactive'`
- `body` (TEXT) — Message text (NULL for media-only messages)
- `media_urls` (TEXT[]) — Array of signed/public URLs for attachments
- `template_name` (TEXT) — HSM template name if business-initiated (for compliance audit)
- `status` (TEXT) — `'received'`, `'sent'`, `'delivered'`, `'read'`, `'failed'`
- `error` (TEXT) — Error reason if status is `'failed'`
- `created_at` (TIMESTAMPTZ) — Message creation/receipt timestamp

**Indexes**:
- `(provider, provider_message_id)` — Unique, enforces idempotency
- `(conversation_id, created_at)` — Efficient audit trail queries
- `(direction)` — Filter inbound vs. outbound
- `(status)` — Find failed sends for retry
- `(created_at)` — DPDP retention policy queries

**Purpose**:
- Immutable audit trail for DPDP compliance (right-to-erasure, retention queries)
- Idempotency enforcement: webhook retries don't create duplicates
- Compliance evidence: template usage logged for TRAI DLT regulations
- Message delivery tracking: status progression for monitoring

---

### Supabase Storage Bucket: `whatsapp-media`

**Purpose**: Store uploaded media (property images, documents, audio) from agents and customers.

**Access Policy**: Public read, authenticated write.

**How to Create**:

Using Supabase CLI:
```bash
supabase storage create-bucket whatsapp-media --public
```

Or via SQL (with Supabase RLS functions):
```sql
SELECT storage.create_bucket('whatsapp-media');
SELECT storage.create_default_public_bucket_policy('whatsapp-media');
```

**Paths**:
- Properties: `properties/{draft_id}/image_001.jpg`, `image_002.jpg`, ...
- Media files are named with sequence numbers to preserve order

---

## Indexing Strategy

### `wa_conversations` Indexes

| Index | Purpose |
|-------|---------|
| `(phone, channel)` | Fast lookup for session load/create by router |
| `(customer_id)`, `(agent_id)` | Entity resolution and analytics |
| `(updated_at)` | Stale session cleanup (expire sessions older than N days) |

**Query Patterns**:
```sql
-- Load session by sender
SELECT * FROM wa_conversations 
WHERE phone = '+917045983015' AND channel = 'customer';

-- Resolve customer entity
SELECT * FROM wa_conversations 
WHERE customer_id = '...' LIMIT 1;

-- Find stale sessions
SELECT id FROM wa_conversations 
WHERE updated_at < now() - INTERVAL '30 days';
```

### `wa_messages` Indexes

| Index | Purpose |
|-------|---------|
| `(provider, provider_message_id)` | Unique constraint for idempotency |
| `(conversation_id, created_at)` | Efficient audit trail retrieval |
| `(direction)` | Separate inbound from outbound |
| `(status)` | Find failed sends for retry/alerts |
| `(created_at)` | DPDP retention policy queries |

**Query Patterns**:
```sql
-- Dedup check (before processing)
SELECT id FROM wa_messages 
WHERE provider = 'gupshup' AND provider_message_id = '...';

-- Audit trail for a conversation
SELECT * FROM wa_messages 
WHERE conversation_id = '...' 
ORDER BY created_at DESC LIMIT 100;

-- Find failed sends (retry)
SELECT * FROM wa_messages 
WHERE status = 'failed' AND direction = 'outbound' 
ORDER BY created_at ASC;

-- DPDP retention: delete old messages
SELECT COUNT(*) FROM wa_messages 
WHERE created_at < now() - INTERVAL '90 days';
```

---

## Data Models Summary

### `wa_conversations` Sample Row

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "phone": "+917045983015",
  "channel": "customer",
  "customer_id": "c0c0c0c0-c0c0-c0c0-c0c0-c0c0c0c0c0c0",
  "agent_id": null,
  "property_id": "d1111111-1111-1111-1111-111111111111",
  "draft_property_id": null,
  "state": "idle",
  "history": [
    {
      "role": "customer",
      "text": "Bandra ka 2bhk dikha na?",
      "ts": "2026-07-01T10:30:00Z",
      "type": "text"
    },
    {
      "role": "agent",
      "text": "Haan! 1.2 crore ke around hai.",
      "ts": "2026-07-01T10:31:00Z",
      "type": "text"
    }
  ],
  "service_window_expires_at": "2026-07-02T10:30:00Z",
  "opted_in": true,
  "created_at": "2026-07-01T10:30:00Z",
  "updated_at": "2026-07-01T10:31:00Z"
}
```

### `wa_messages` Sample Rows

**Inbound (customer asks a question)**:
```json
{
  "id": "660e8400-e29b-41d4-a716-446655440000",
  "conversation_id": "550e8400-e29b-41d4-a716-446655440000",
  "direction": "inbound",
  "provider": "gupshup",
  "provider_message_id": "gupshup_msg_12345",
  "from_phone": "+917045983015",
  "to_phone": "+919876543210",
  "type": "text",
  "body": "Property ka price kya hai?",
  "media_urls": [],
  "template_name": null,
  "status": "received",
  "error": null,
  "created_at": "2026-07-01T10:30:00Z"
}
```

**Outbound (Priya replies with free-form within window)**:
```json
{
  "id": "770e8400-e29b-41d4-a716-446655440000",
  "conversation_id": "550e8400-e29b-41d4-a716-446655440000",
  "direction": "outbound",
  "provider": "gupshup",
  "provider_message_id": "gupshup_msg_12346",
  "from_phone": "+919876543210",
  "to_phone": "+917045983015",
  "type": "text",
  "body": "Das crore ke aas paas hai 🏠",
  "media_urls": [],
  "template_name": null,
  "status": "delivered",
  "error": null,
  "created_at": "2026-07-01T10:31:00Z"
}
```

**Outbound (template message outside service window)**:
```json
{
  "id": "880e8400-e29b-41d4-a716-446655440000",
  "conversation_id": "550e8400-e29b-41d4-a716-446655440000",
  "direction": "outbound",
  "provider": "gupshup",
  "provider_message_id": "gupshup_msg_12347",
  "from_phone": "+919876543210",
  "to_phone": "+917045983015",
  "type": "text",
  "body": null,
  "media_urls": [],
  "template_name": "property_followup_v1",
  "status": "sent",
  "error": null,
  "created_at": "2026-07-02T15:00:00Z"
}
```

**Outbound with media (agent uploads property)**:
```json
{
  "id": "990e8400-e29b-41d4-a716-446655440001",
  "conversation_id": "550e8400-e29b-41d4-a716-446655440001",
  "direction": "outbound",
  "provider": "gupshup",
  "provider_message_id": "gupshup_msg_12348",
  "from_phone": "+919876543210",
  "to_phone": "+918765432100",
  "type": "image",
  "body": "Property photos uploaded",
  "media_urls": [
    "https://storage.supabase.co/properties/draft-uuid/image_001.jpg",
    "https://storage.supabase.co/properties/draft-uuid/image_002.jpg"
  ],
  "template_name": null,
  "status": "delivered",
  "error": null,
  "created_at": "2026-07-01T14:00:00Z"
}
```

---

## DPDP Compliance

### Audit Trail
Every message (inbound and outbound) is logged to `wa_messages` with timestamps, direction, and status. This creates an immutable audit trail per DPDP Article 7-9.

### Right-to-Erasure (DPDP Article 17)
When a customer requests deletion:
1. Anonymize or delete rows in `wa_conversations` WHERE `phone = X`
2. Anonymize or delete rows in `wa_messages` WHERE `from_phone = X` OR `to_phone = X`
3. Mark corresponding `customers` row with `deleted_at` (soft delete)
4. Log the erasure request with timestamp and authorization
5. Complete within 30 days as per DPDP

### Retention Policy
- Retain `wa_messages` indefinitely (or per documented policy)
- Encrypt message bodies at rest via Supabase settings
- No unencrypted PII in application logs

---

## Testing & Validation

### Verify Schema
```sql
-- Check tables exist
SELECT tablename FROM pg_tables 
WHERE schemaname = 'public' 
AND tablename LIKE 'wa_%';

-- Check indexes
SELECT indexname FROM pg_indexes 
WHERE tablename LIKE 'wa_%';

-- Verify unique constraint
SELECT constraint_name FROM information_schema.table_constraints 
WHERE table_name = 'wa_messages' 
AND constraint_type = 'UNIQUE';
```

### Sample Queries for Operations

**Load a conversation**:
```sql
SELECT * FROM wa_conversations 
WHERE phone = '+917045983015' AND channel = 'customer'
LIMIT 1;
```

**Append a message to history**:
```sql
UPDATE wa_conversations 
SET history = history || jsonb_build_array(
    jsonb_build_object(
        'role', 'customer',
        'text', 'New message here',
        'ts', now()::text,
        'type', 'text'
    )
),
updated_at = now()
WHERE id = '550e8400-e29b-41d4-a716-446655440000';
```

**Check idempotency before processing**:
```sql
SELECT COUNT(*) as already_processed 
FROM wa_messages 
WHERE provider = 'gupshup' 
AND provider_message_id = 'gupshup_msg_12345';
```

**Audit trail for support**:
```sql
SELECT * FROM wa_messages 
WHERE conversation_id = '550e8400-e29b-41d4-a716-446655440000'
ORDER BY created_at DESC;
```

---

## Migration Application

### Supabase SQL Editor
1. Log into your Supabase project
2. Go to SQL Editor
3. Copy the entire contents of `001_whatsapp_schema.sql`
4. Paste and execute
5. Verify tables and indexes are created

### Local Development (with Supabase CLI)
```bash
cd migrations
supabase db push
# Or run manually:
psql "postgresql://user:pass@localhost:5432/db" < 001_whatsapp_schema.sql
```

### Production Deployment
Follow your standard database migration procedure (e.g., via Supabase CLI or Hasura migrations).

---

## Next Steps

- **Task 2** (in progress): Create Python module structure and data models
- **Task 3**: Implement database layer (`db.py`)
- **Task 4**: Build provider abstraction (`provider.py`)
- **Task 5+**: Implement Gupshup and Twilio providers, session store, etc.
