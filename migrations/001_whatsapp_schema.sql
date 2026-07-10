-- Migration 001: WhatsApp Conversational Channel Schema
-- Created for Wave 0 of the WhatsApp feature
-- Tables: wa_conversations, wa_messages
-- Storage: whatsapp-media bucket

-- ============================================================================
-- Table: wa_conversations
-- Purpose: Stores multi-turn conversation state per (phone, channel) pair
-- Compliance: DPDP audit trail, service window tracking, opt-in management
-- ============================================================================

CREATE TABLE IF NOT EXISTS wa_conversations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    
    -- Identity & routing
    phone TEXT NOT NULL,                      -- E.164 format, indexed
    channel TEXT NOT NULL,                    -- 'customer' | 'agent'
    
    -- Entity references (resolved during conversation)
    customer_id UUID REFERENCES customers(id) ON DELETE SET NULL,
    agent_id UUID REFERENCES agents(id) ON DELETE SET NULL,
    property_id UUID REFERENCES properties(id) ON DELETE SET NULL,
    draft_property_id UUID,                   -- ephemeral draft property UUID (no FK to allow deletion)
    
    -- Conversation state
    state TEXT DEFAULT 'idle',                -- 'idle', 'collecting_media', 'awaiting_confirmation'
    history JSONB DEFAULT '[]'::jsonb,        -- bounded array of turns: [{role, text, ts, type}, ...]
    
    -- Service window & compliance
    service_window_expires_at TIMESTAMPTZ,    -- last customer inbound + 24h (NULL for agents)
    opted_in BOOLEAN DEFAULT FALSE,           -- customer consent for business-initiated messages
    
    -- Audit
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

-- Indexes for efficient lookups
CREATE INDEX idx_wa_conversations_phone_channel 
    ON wa_conversations(phone, channel);
CREATE INDEX idx_wa_conversations_customer_id 
    ON wa_conversations(customer_id);
CREATE INDEX idx_wa_conversations_agent_id 
    ON wa_conversations(agent_id);
CREATE INDEX idx_wa_conversations_updated_at 
    ON wa_conversations(updated_at);

-- ============================================================================
-- Table: wa_messages
-- Purpose: Immutable audit log of all inbound & outbound WhatsApp messages
-- Compliance: DPDP retention, TRAI template audit, message idempotency
-- ============================================================================

CREATE TABLE IF NOT EXISTS wa_messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    
    -- Conversation reference
    conversation_id UUID REFERENCES wa_conversations(id) ON DELETE CASCADE,
    
    -- Direction & provider
    direction TEXT NOT NULL,                  -- 'inbound' | 'outbound'
    provider TEXT NOT NULL,                   -- 'gupshup' | 'twilio'
    
    -- Idempotency: (provider, provider_message_id) is unique per provider
    provider_message_id TEXT NOT NULL,        -- provider's message ID
    
    -- Endpoints
    from_phone TEXT NOT NULL,                 -- E.164
    to_phone TEXT NOT NULL,                   -- E.164 (business number)
    
    -- Message content
    type TEXT NOT NULL,                       -- 'text', 'image', 'document', 'audio', 'interactive'
    body TEXT,                                -- message text (NULL for media-only)
    media_urls TEXT[] DEFAULT ARRAY[]::TEXT[], -- array of signed/public URLs
    
    -- Template & compliance evidence
    template_name TEXT,                       -- HSM template used (if business-initiated)
    
    -- Status & error tracking
    status TEXT DEFAULT 'received',           -- 'received', 'sent', 'delivered', 'read', 'failed'
    error TEXT,                               -- error reason if status='failed'
    
    -- Audit
    created_at TIMESTAMPTZ DEFAULT now()
);

-- Unique constraint for idempotency: (provider, provider_message_id)
CREATE UNIQUE INDEX idx_wa_messages_provider_idempotency 
    ON wa_messages(provider, provider_message_id);

-- Indexes for audit queries
CREATE INDEX idx_wa_messages_conversation_id 
    ON wa_messages(conversation_id);
CREATE INDEX idx_wa_messages_conversation_created 
    ON wa_messages(conversation_id, created_at);
CREATE INDEX idx_wa_messages_direction 
    ON wa_messages(direction);
CREATE INDEX idx_wa_messages_status 
    ON wa_messages(status);
CREATE INDEX idx_wa_messages_created_at 
    ON wa_messages(created_at);

-- ============================================================================
-- Supabase Storage Bucket: whatsapp-media
-- Purpose: Store uploaded property images, documents, audio from WhatsApp
-- Access: Public read (signed URLs); agent write (authentication required)
-- ============================================================================

-- Note: Supabase Storage buckets are created via the Supabase dashboard or CLI.
-- To create via SQL (if using Supabase): 
--   SELECT storage.create_bucket('whatsapp-media');
-- 
-- Alternatively, run:
--   supabase storage create-bucket whatsapp-media --public
--
-- Then set a public read policy:
--   SELECT storage.create_default_public_bucket_policy('whatsapp-media');

-- ============================================================================
-- Helper: Truncate history to latest N turns (for bounded context)
-- ============================================================================

CREATE OR REPLACE FUNCTION truncate_conversation_history()
RETURNS TRIGGER AS $$
DECLARE
    max_turns INT := 12;
BEGIN
    IF array_length(NEW.history, 1) > max_turns THEN
        NEW.history := NEW.history[(array_length(NEW.history, 1) - max_turns + 1):];
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_truncate_wa_conversation_history
BEFORE INSERT OR UPDATE ON wa_conversations
FOR EACH ROW
EXECUTE FUNCTION truncate_conversation_history();

-- ============================================================================
-- Helper: Auto-update updated_at on wa_conversations
-- ============================================================================

CREATE OR REPLACE FUNCTION update_wa_conversations_timestamp()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_update_wa_conversations_timestamp
BEFORE UPDATE ON wa_conversations
FOR EACH ROW
EXECUTE FUNCTION update_wa_conversations_timestamp();

-- ============================================================================
-- Migration notes
-- ============================================================================

-- 1. DPDP Compliance (Digital Personal Data Protection Act, India)
--    - wa_messages rows are the primary audit trail per DPDP Article 7-9
--    - Right-to-erasure: DELETE/anonymize rows WHERE phone = X within 30 days
--    - Retention: Keep indefinitely (or per written policy)
--    - Encryption: Message bodies can be encrypted at rest via Supabase settings

-- 2. Service Window Lifecycle
--    - service_window_expires_at is updated by application logic:
--      When a customer sends inbound → set to now() + 24 hours
--      When subsequent inbound arrives within window → extend by 24h from new timestamp
--    - Used by window_gate to decide: free-form send allowed or template required

-- 3. Message Idempotency
--    - Webhook retries from provider must be deduplicated via (provider, provider_message_id)
--    - Unique constraint enforces exactly-once processing
--    - If same provider_message_id is received, insert fails (application catches & ignores)

-- 4. Photo URLs for Property Uploads
--    - Stored in media_urls ARRAY for audit; also persisted to properties.photo_urls
--    - Signed URLs are generated per provider (Gupshup, Twilio)
--    - URLs are immutable once a draft is confirmed to live status

-- 5. Storage Bucket Creation
--    - Bucket 'whatsapp-media' must be created separately (see comment above)
--    - Public read policy allows frontend to display images
--    - Paths: properties/{draft_id}/image_001.jpg, image_002.jpg, etc.
