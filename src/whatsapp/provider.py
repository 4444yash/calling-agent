"""Provider abstraction for WhatsApp Business API.

This module defines the WhatsAppProvider protocol (interface) using Python's
typing.Protocol pattern. This allows Gupshup, Twilio, and other providers
to be swapped without changing business logic.

The protocol is used as a type hint for dependency injection, enabling
multiple implementations to be registered and selected at runtime via
the make_provider() factory function.

Components:
- WhatsAppProvider: Protocol defining the complete WhatsApp provider interface
- MediaBlob: Dataclass representing fetched media binary
- SendResult: Dataclass representing the result of a send attempt
- TemplateRef: Dataclass representing an HSM template reference
- make_provider(): Factory function to instantiate providers by name
"""

from dataclasses import dataclass, field
from typing import Optional, List, Protocol, runtime_checkable, Dict
from datetime import datetime

from .models import InboundMessage
from .errors import (
    ProviderError,
    SignatureVerificationError,
    MediaFetchError,
    ConfigurationError,
)


@dataclass
class MediaBlob:
    """Binary media data fetched from provider.
    
    Represents a single media item (image, document, audio) returned by
    WhatsAppProvider.fetch_media(). Contains raw bytes, MIME type, and
    optional metadata.
    
    **Pre-condition**: mime_type MUST be one of the whitelisted types
    (image/jpeg, image/png, application/pdf, audio/ogg, audio/mpeg, etc.)
    
    **Post-condition**: data is the raw binary content, size <= max_media_size
    """
    
    mime_type: str
    """MIME type of the media: 'image/jpeg', 'image/png', 'application/pdf',
    'audio/ogg', 'audio/mpeg', etc.
    
    Validated against provider's supported types before storage.
    """
    
    data: bytes
    """Raw binary content of the media file."""
    
    filename: Optional[str] = None
    """Original filename if available from provider.
    
    May be None if the provider does not return a filename.
    """
    
    size_bytes: int = 0
    """Size of the binary data in bytes (for validation and quotas).
    
    Automatically set by provider when fetching.
    """
    
    def __post_init__(self):
        """Calculate size_bytes if not provided."""
        if self.size_bytes == 0 and self.data:
            self.size_bytes = len(self.data)


@dataclass
class SendResult:
    """Result of a send attempt (text, template, or media).
    
    Returned by send_text(), send_template(), and send_media() methods
    to indicate success or failure.
    
    **Pre-condition**: None (always constructed by provider)
    
    **Post-condition**: message_id is set iff status is 'sent' or 'delivered';
    error is set iff status is 'failed'
    """
    
    message_id: str
    """Provider's unique message ID for this send.
    
    Used for delivery tracking, idempotency, and audit logging.
    Empty string if send failed and no message_id was assigned.
    """
    
    status: str
    """Send status: 'sent', 'queued', 'failed', or provider-specific status.
    
    Standard statuses: 'sent' (accepted by provider), 'queued' (rate-limited),
    'failed' (error occurred).
    
    Must be one of the values in config.MESSAGE_STATUS.
    """
    
    error: Optional[str] = None
    """Error message if status is 'failed'.
    
    None if status is 'sent' or 'queued'.
    """


@dataclass
class TemplateRef:
    """Reference to a pre-approved WhatsApp Business HSM template.
    
    Used when sending template (business-initiated) messages outside
    the 24-hour service window.
    
    **Pre-condition**: template_name MUST be registered in HSM_TEMPLATES
    
    **Post-condition**: parameters list length MUST match template's parameter
    count (provider will validate during send)
    """
    
    template_name: str
    """Name of the template (e.g., 'property_followup_v1').
    
    Must match a pre-approved template name from WhatsApp DLT/HSM registry.
    """
    
    parameters: List[str] = field(default_factory=list)
    """Parameter values to substitute in the template.
    
    Order matters: parameters[0] substitutes {{1}}, parameters[1] → {{2}}, etc.
    Length must match the template's parameter count.
    """


@runtime_checkable
class WhatsAppProvider(Protocol):
    """Provider abstraction protocol for WhatsApp Business API.
    
    This is a Protocol (structural subtyping), not an ABC. Implementations
    only need to define the methods below; they do not inherit from this class.
    
    Concrete implementations:
    - GupshupProvider (src/whatsapp/providers/gupshup.py)
    - TwilioProvider (src/whatsapp/providers/twilio.py)
    
    **Design Note**: Using Protocol allows implementations to be added without
    tight coupling to a base class. New providers can be plugged in via the
    make_provider() factory.
    
    **Thread Safety**: All methods are async. Implementations MAY be called
    concurrently and MUST be thread-safe (or use asyncio locks as needed).
    
    **Idempotency**: send_text/send_template/send_media implementations SHOULD
    use provider-specific message_ids and idempotency keys to prevent duplicates
    on retry.
    
    **Error Recovery**: Implementations SHOULD use exponential backoff for
    transient failures (5xx, timeouts). Permanent failures (4xx, invalid recipient)
    should fail fast.
    """
    
    async def verify_signature(
        self,
        headers: Dict[str, str],
        raw_body: bytes,
    ) -> bool:
        """Verify webhook signature (HMAC-SHA256 or provider-specific scheme).
        
        Authenticates the webhook payload to ensure it came from the WhatsApp
        provider and was not tampered with. MUST be called before processing
        any webhook.
        
        **Pre-condition**:
        - Provider shared secret is configured (env vars or config)
        - raw_body is the exact bytes received on the HTTP request
        - headers dict contains all HTTP headers from the request
        
        **Post-condition**:
        - Returns True iff the signature is valid for this provider
        - Returns False iff the signature is invalid or cannot be verified
        - MUST NOT modify any state (pure function for security)
        - MUST NOT log the raw_body (PII/security)
        
        **Raises**:
        - SignatureVerificationError if shared secret is missing or misconfigured
        
        **Example**:
            headers = request.headers  # dict-like
            raw_body = request.body    # bytes
            is_valid = await provider.verify_signature(headers, raw_body)
            if not is_valid:
                return Response(status=401)  # reject unauthorized webhook
        """
        ...
    
    async def parse_inbound(self, raw_body: bytes) -> InboundMessage:
        """Parse inbound webhook payload into canonical InboundMessage.
        
        Converts provider-specific JSON format to a normalized, provider-agnostic
        InboundMessage. This is the first normalization step for all inbound traffic.
        
        **Pre-condition**:
        - raw_body is valid JSON (MUST have been verified by verify_signature)
        - JSON structure matches provider's webhook schema
        
        **Post-condition**:
        - Returns an InboundMessage with:
          - from_phone normalized to E.164 format
          - provider_message_id populated (used for idempotency)
          - timestamp converted to UTC datetime
          - type set to one of: 'text', 'image', 'document', 'audio', 'interactive'
          - text populated for text messages (None for media)
          - media_ids populated for media messages (empty list for text)
          - raw dict preserved (for audit if needed)
        
        **Raises**:
        - ProviderError if JSON is malformed or missing required fields
        - ValidationError if normalization fails (e.g., invalid phone)
        
        **Provider-Specific Notes**:
        - Gupshup sends messages in 'messages' array; extract first element
        - Twilio sends single message object; map 'From'/'To' to from_phone/to_phone
        - Both: media IDs are provider-specific tokens; retain as-is in media_ids
        
        **Example**:
            msg = await provider.parse_inbound(request.body)
            assert msg.from_phone.startswith('+')  # E.164
        """
        ...
    
    async def fetch_media(self, media_id: str) -> MediaBlob:
        """Fetch media binary from provider using media ID.
        
        Downloads the actual media file (image, document, audio) from the
        provider's media server. Used when processing inbound messages that
        contain media.
        
        **Pre-condition**:
        - media_id is a valid provider media token (from parse_inbound)
        - Provider API credentials are configured (env vars or config)
        - media_id has not expired (provider-specific TTL, usually 7 days)
        
        **Post-condition**:
        - Returns MediaBlob with:
          - data: raw binary content (< max_media_size, default 5MB)
          - mime_type: validated against provider's supported types
          - filename: original filename (may be None)
          - size_bytes: calculated from len(data)
        
        **Raises**:
        - MediaFetchError if media_id is invalid or expired
        - MediaFetchError if download times out (provider unreachable)
        - MediaFetchError if MIME type is not whitelisted
        - MediaFetchError if file size exceeds max_media_size
        
        **Retry Behavior**:
        - Implementation SHOULD use exponential backoff for transient failures
        - Permanent failures (404 media_id expired, 403 unauthorized) should fail fast
        
        **Example**:
            blob = await provider.fetch_media(media_id)
            assert blob.mime_type in ALLOWED_MIME_TYPES
            with open(f"media/{media_id}", "wb") as f:
                f.write(blob.data)
        """
        ...
    
    async def send_text(self, to_phone: str, text: str) -> SendResult:
        """Send a free-form text message (within service window only).
        
        Sends a free-form message to a customer or agent. This is used within
        the 24-hour service window; outside that window, use send_template().
        
        **Pre-condition**:
        - to_phone is valid E.164 format (normalized by caller)
        - text is non-empty and <= 4096 characters (WhatsApp limit)
        - Recipient has opted-in OR we are within service window
        
        **Post-condition**:
        - Returns SendResult with:
          - message_id: provider's unique ID for this send
          - status: 'sent' if accepted by provider, 'failed' if error
          - error: populated iff status is 'failed'
        - Message is delivered via provider's API
        - If send fails, caller SHOULD retry with backoff
        
        **Raises**:
        - ProviderError if API call fails (rate limit, 5xx, invalid credentials)
        - ProviderError if to_phone is invalid or unserviceable
        
        **Text Formatting**:
        - Emojis, line breaks, Unicode (Hinglish) are supported
        - No URL shortening or link wrapping by this method
        - Text is sent as-is
        
        **Idempotency**:
        - Implementation SHOULD use a deduplication key (e.g., hash of to_phone + timestamp)
        - Resending the same message within 60 seconds SHOULD return cached result
        
        **Example**:
            result = await provider.send_text(
                to_phone="+917045983015",
                text="Das crore ke aas paas hai ₹₹₹ ✅"
            )
            if result.status == 'failed':
                logger.error(f"Send failed: {result.error}")
        """
        ...
    
    async def send_template(
        self,
        to_phone: str,
        template: TemplateRef,
    ) -> SendResult:
        """Send pre-approved HSM template message (outside service window).
        
        Sends a business-initiated (HSM) template message when outside the
        24-hour service window. Template must be pre-registered with WhatsApp
        DLT and included in the HSM_TEMPLATES registry.
        
        **Pre-condition**:
        - to_phone is valid E.164 format
        - template.template_name is in HSM_TEMPLATES registry
        - template.parameters length matches template parameter count
        - Recipient has whatsapp_opted_in = true
        - We are outside the 24-hour service window (or using template anyway)
        
        **Post-condition**:
        - Returns SendResult with:
          - message_id: provider's message ID
          - status: 'sent' if accepted, 'failed' if error
          - error: populated iff status is 'failed'
        - Template is substituted with parameters and sent
        - Audit log records template_name for compliance
        
        **Raises**:
        - ProviderError if template is not registered or approved
        - ProviderError if parameter count mismatch
        - ProviderError if to_phone is invalid or opted-out
        
        **HSM_TEMPLATES Format**:
        - Each template has 'params' list defining parameter slots
        - template.parameters[i] is substituted for {{i+1}} in template body
        
        **Example**:
            template = TemplateRef(
                template_name="property_followup_v1",
                parameters=["Bandra Sea Face", "kal 5 baje"]
            )
            result = await provider.send_template(
                to_phone="+917045983015",
                template=template
            )
        """
        ...
    
    async def send_media(
        self,
        to_phone: str,
        media_url: str,
        caption: Optional[str] = None,
    ) -> SendResult:
        """Send media (image, document, audio) with optional caption.
        
        Sends a media message with an optional text caption. Used for sharing
        property photos, documents, audio recordings, etc.
        
        **Pre-condition**:
        - to_phone is valid E.164 format
        - media_url is a valid, publicly accessible or signed URL
        - URL points to a media file within size limits
        - caption (if provided) is <= 1024 characters
        - We are within service window OR have opt-in (for captions)
        
        **Post-condition**:
        - Returns SendResult with:
          - message_id: provider's message ID
          - status: 'sent' if accepted, 'failed' if error
          - error: populated iff status is 'failed'
        - Media is downloaded by provider from media_url and forwarded to recipient
        
        **Raises**:
        - ProviderError if media_url is invalid or inaccessible
        - ProviderError if media content-type is not whitelisted
        - ProviderError if media file is too large
        
        **Media URL Requirements**:
        - MUST be HTTPS
        - MUST be publicly accessible OR include valid auth headers
        - MUST have correct Content-Type header
        - Provider typically fetches and caches; do not rely on URL persistence
        
        **Example**:
            result = await provider.send_media(
                to_phone="+917045983015",
                media_url="https://storage.example.com/properties/photo1.jpg",
                caption="2BHK Bandra, 1.2 cr"
            )
        """
        ...


def make_provider(provider_name: Optional[str] = None) -> WhatsAppProvider:
    """Factory function to instantiate a WhatsApp provider.
    
    Creates and returns a concrete provider implementation (Gupshup, Twilio, etc.)
    based on the provider_name argument or the WA_PROVIDER environment variable.
    
    Performs lazy imports to avoid circular dependencies and provides
    clear error messages for misconfiguration.
    
    **Pre-condition**:
    - provider_name is 'gupshup', 'twilio', or None (use env)
    - If None, WA_PROVIDER env var is set to a valid provider name
    - Provider credentials (API keys, secrets) are configured via env vars
    
    **Post-condition**:
    - Returns an initialized provider instance that implements WhatsAppProvider
    - Provider is ready for use (credentials validated if applicable)
    - All required environment variables are present
    
    **Raises**:
    - ConfigurationError if provider_name is unknown
    - ConfigurationError if required credentials are missing
    - ConfigurationError if provider initialization fails
    
    **Environment Variables**:
    - WA_PROVIDER: 'gupshup' | 'twilio' (default: 'gupshup')
    
    For Gupshup:
    - GUPSHUP_API_KEY: API key for authentication
    - GUPSHUP_APP_ID: Application ID
    - GUPSHUP_APP_NAME: Application name
    - GUPSHUP_WEBHOOK_SECRET: Shared secret for webhook signature verification
    - GUPSHUP_BUSINESS_PHONE: Business WhatsApp number (E.164)
    
    For Twilio:
    - TWILIO_ACCOUNT_SID: Twilio Account SID
    - TWILIO_AUTH_TOKEN: Twilio Auth Token
    - TWILIO_BUSINESS_PHONE: Business WhatsApp number (E.164)
    
    **Example**:
        # Use default provider from env (WA_PROVIDER=gupshup)
        provider = make_provider()
        
        # Or specify provider explicitly
        provider = make_provider("gupshup")
        
        # Use in webhook handler
        async def handle_webhook(body, headers):
            provider = make_provider()
            if await provider.verify_signature(headers, body):
                msg = await provider.parse_inbound(body)
                # ... process message
    """
    import os
    from loguru import logger
    
    # Read provider name from argument or environment (default: gupshup)
    provider_name = provider_name or os.getenv("WA_PROVIDER", "gupshup")
    provider_name_lower = provider_name.lower().strip()
    
    try:
        if provider_name_lower == "gupshup":
            # Lazy import to avoid circular dependencies
            from .providers.gupshup import GupshupProvider
            provider = GupshupProvider()
            logger.info("✓ Created Gupshup provider")
            return provider
        
        elif provider_name_lower == "twilio":
            # Lazy import
            from .providers.twilio import TwilioProvider
            provider = TwilioProvider()
            logger.info("✓ Created Twilio provider")
            return provider
        
        else:
            logger.error(f"❌ Unknown WhatsApp provider: {provider_name}")
            raise ConfigurationError(
                f"Unknown WhatsApp provider: '{provider_name}'. "
                f"Expected 'gupshup' or 'twilio'. "
                f"Set WA_PROVIDER environment variable to one of these values."
            )
    
    except ConfigurationError:
        # Re-raise configuration errors with context
        raise
    except Exception as e:
        logger.error(f"❌ Failed to initialize WhatsApp provider: {e}")
        raise ConfigurationError(
            f"Failed to initialize WhatsApp provider '{provider_name}': {e}"
        )
