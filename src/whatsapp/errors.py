"""Exception hierarchy for WhatsApp Conversational Channel.

All domain-specific errors inherit from WhatsAppError for consistent
exception handling at the orchestration layer.
"""


class WhatsAppError(Exception):
    """Base exception for WhatsApp feature.
    
    All feature-specific exceptions inherit from this to allow
    orchestrators to catch all WhatsApp errors uniformly.
    """
    pass


class ValidationError(WhatsAppError):
    """Invalid input or data validation failure.
    
    Raised when:
    - Phone number cannot be normalized to E.164
    - Message payload is malformed or incomplete
    - Field values fail type or range checks
    - LLM extraction produces invalid data
    """
    pass


class AuthorizationError(WhatsAppError):
    """Authorization or permission check failed.
    
    Raised when:
    - Sender is not a registered agent (trying command operations)
    - Agent doesn't own the target resource (lead/property)
    - Agent status is inactive/suspended (cannot issue commands)
    - Insufficient permissions for operation
    """
    pass


class ProviderError(WhatsAppError):
    """WhatsApp provider API error.
    
    Raised when:
    - Provider send fails (rate limit, invalid recipient, etc.)
    - Media fetch fails (timeout, unauthorized, etc.)
    - Provider returns non-2xx status
    - Provider configuration is invalid or missing
    """
    pass


class SignatureVerificationError(WhatsAppError):
    """Webhook signature verification failed.
    
    Raised when:
    - HMAC signature doesn't match
    - Shared secret is not configured
    - Request body tampering is detected
    
    Indicates potential security issue; webhook should be rejected (401).
    """
    pass


class MessageProcessingError(WhatsAppError):
    """Error during message processing pipeline.
    
    Raised when:
    - LLM intent classification fails
    - Message deduplication check fails
    - Session load/update fails
    - Audit log write fails
    - Side effect application fails (create visit, update lead score, etc.)
    """
    pass


class SessionNotFoundError(WhatsAppError):
    """Conversation session not found or could not be created.
    
    Raised when:
    - Session lookup from database fails
    - Session creation transaction fails
    - Session cache/store is unreachable
    """
    pass


class MediaFetchError(WhatsAppError):
    """Failed to fetch media from provider.
    
    Raised when:
    - Media ID is invalid or expired
    - Media download times out
    - Media validation fails (mime type, size, etc.)
    """
    pass


class MediaStoreError(WhatsAppError):
    """Failed to store media in Supabase Storage or local store.
    
    Raised when:
    - Storage write fails
    - Invalid media data
    - Storage quota exceeded
    """
    pass


class ConfigurationError(WhatsAppError):
    """Invalid or missing configuration.
    
    Raised when:
    - Required environment variables missing
    - Provider credentials invalid
    - Database connection string invalid
    - Feature flags misconfigured
    """
    pass


class IdempotencyError(WhatsAppError):
    """Idempotency check or storage failed.
    
    Raised when:
    - Cannot determine if message was already processed
    - Idempotency store is unreachable
    """
    pass


class WindowGateError(WhatsAppError):
    """Error in service window or template gate logic.
    
    Raised when:
    - Cannot determine if within service window
    - Template matching fails
    - Opt-in state cannot be determined
    """
    pass
