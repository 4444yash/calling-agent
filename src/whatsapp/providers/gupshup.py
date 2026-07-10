"""Gupshup WhatsApp Business API provider.

Handles:
- HMAC SHA-256 signature verification (timing-safe)
- Inbound message parsing with E.164 normalization
- Media fetching with retry logic
- Outbound sends (text, template, media) with retry logic
"""

import hmac
import hashlib
import json
import os
from typing import Optional, List
from datetime import datetime
import httpx
from loguru import logger

from ..provider import WhatsAppProvider, MediaBlob, SendResult
from ..models import InboundMessage
from ..errors import (
    ProviderError,
    SignatureVerificationError,
    MediaFetchError,
    ConfigurationError,
    ValidationError,
)
from ..config import PROVIDER_CONFIG
from ...utils.validation import validate_phone_number
from ...utils.resilience import retry_with_backoff


class GupshupProvider(WhatsAppProvider):
    """Gupshup WhatsApp Business API implementation.
    
    API documentation: https://www.gupshup.io/developer/docs/bot-platform/
    
    Implements WhatsAppProvider protocol for Gupshup's WhatsApp Business solution.
    Features:
    - HMAC-SHA256 webhook verification with timing-safe comparison
    - E.164 phone normalization for all inbound/outbound
    - Exponential backoff retry for transient failures
    - Proper error classification and exception handling
    """
    
    def __init__(self):
        """Initialize Gupshup provider from environment variables.
        
        Required env vars:
        - GUPSHUP_API_KEY: API key for authentication
        - GUPSHUP_APP_ID: Application ID
        - GUPSHUP_APP_NAME: Application name
        - GUPSHUP_WEBHOOK_SECRET: Shared secret for signature verification
        - GUPSHUP_BUSINESS_PHONE: Business phone number (E.164)
        
        Raises:
            ConfigurationError: If required credentials are missing
        """
        self.api_key = os.getenv("GUPSHUP_API_KEY")
        self.app_id = os.getenv("GUPSHUP_APP_ID")
        self.app_name = os.getenv("GUPSHUP_APP_NAME")
        self.shared_secret = os.getenv("GUPSHUP_WEBHOOK_SECRET")
        self.business_phone = os.getenv("GUPSHUP_BUSINESS_PHONE", "")
        
        if not all([self.api_key, self.app_id, self.app_name, self.shared_secret]):
            raise ConfigurationError(
                "Missing Gupshup credentials. "
                "Required env vars: GUPSHUP_API_KEY, GUPSHUP_APP_ID, "
                "GUPSHUP_APP_NAME, GUPSHUP_WEBHOOK_SECRET"
            )
        
        self.base_url = PROVIDER_CONFIG["gupshup"]["base_url"]
        self.client = httpx.AsyncClient(
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=10.0
        )
        logger.info("✓ GupshupProvider initialized")
    
    async def verify_signature(
        self,
        headers: dict,
        raw_body: bytes,
    ) -> bool:
        """Verify HMAC-SHA256 webhook signature using timing-safe comparison.
        
        Gupshup sends signature in X-Gupshup-Signature header as hex-encoded
        HMAC-SHA256 of the request body using the shared webhook secret.
        
        Args:
            headers: HTTP headers dict (case-insensitive)
            raw_body: Raw request body bytes (exact bytes from HTTP request)
        
        Returns:
            True if signature is valid
        
        Raises:
            SignatureVerificationError: If signature is invalid or missing
        """
        try:
            # Extract signature header (case-insensitive)
            signature_header = None
            for key, value in headers.items():
                if key.lower() == "x-gupshup-signature":
                    signature_header = value
                    break
            
            if not signature_header:
                logger.error("❌ Missing X-Gupshup-Signature header")
                raise SignatureVerificationError("Missing X-Gupshup-Signature header")
            
            # Compute HMAC SHA-256
            computed_signature = hmac.new(
                self.shared_secret.encode(),
                raw_body,
                hashlib.sha256
            ).hexdigest()
            
            # Use timing-safe comparison to prevent timing attacks
            if not hmac.compare_digest(computed_signature, signature_header):
                logger.error("❌ Signature verification failed (mismatch)")
                raise SignatureVerificationError("Signature mismatch")
            
            logger.debug("✓ Webhook signature verified")
            return True
        
        except SignatureVerificationError:
            raise
        except Exception as e:
            logger.error(f"❌ Signature verification error: {e}")
            raise SignatureVerificationError(f"Verification failed: {e}")
    
    async def parse_inbound(self, raw_body: bytes) -> InboundMessage:
        """Parse Gupshup webhook JSON into canonical InboundMessage.
        
        Gupshup webhook format:
        {
            "app": "app-name",
            "timestamp": "2024-01-15T10:30:00Z",
            "type": "message",
            "message": {
                "id": "gupshup-message-id",
                "from": "917045983015",  # phone without +
                "type": "text|image|document|audio",
                "text": "message text",  # for text messages
                "image": {"url": "..."},  # for image
                "document": {"url": "..."},  # for document
                "audio": {"url": "..."}  # for audio
            }
        }
        
        Args:
            raw_body: Raw JSON bytes from webhook
        
        Returns:
            InboundMessage with E.164 normalized phones
        
        Raises:
            ProviderError: If JSON parsing or normalization fails
        """
        try:
            payload = json.loads(raw_body)
            msg = payload.get("message", {})
            
            # Extract and normalize sender phone to E.164
            from_phone_raw = msg.get("from", "")
            if not from_phone_raw:
                raise ValidationError("Missing 'from' field in message")
            
            # Ensure E.164 format
            if not from_phone_raw.startswith("+"):
                from_phone = f"+{from_phone_raw}"
            else:
                from_phone = from_phone_raw
            
            from_phone = validate_phone_number(from_phone)  # Normalize & validate
            
            # Parse message type and extract content
            msg_type = msg.get("type", "text")
            text = msg.get("text")
            media_ids = []
            
            if msg_type == "image":
                image_data = msg.get("image", {})
                if image_data.get("url"):
                    media_ids.append(image_data["url"])
            
            elif msg_type == "document":
                doc_data = msg.get("document", {})
                if doc_data.get("url"):
                    media_ids.append(doc_data["url"])
            
            elif msg_type == "audio":
                audio_data = msg.get("audio", {})
                if audio_data.get("url"):
                    media_ids.append(audio_data["url"])
            
            # Parse timestamp
            timestamp_str = payload.get("timestamp", datetime.utcnow().isoformat())
            try:
                timestamp = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
            except Exception:
                timestamp = datetime.utcnow()
            
            inbound_msg = InboundMessage(
                provider="gupshup",
                provider_message_id=msg.get("id", ""),
                from_phone=from_phone,
                to_phone=self.business_phone,
                timestamp=timestamp,
                type=msg_type,
                text=text,
                media_ids=media_ids,
                raw=payload
            )
            
            logger.debug(f"✓ Parsed inbound message: {inbound_msg.provider_message_id}")
            return inbound_msg
        
        except (ValidationError, ValueError) as e:
            raise ProviderError(f"Failed to parse Gupshup webhook: {e}")
        except Exception as e:
            logger.error(f"❌ Parse inbound error: {e}")
            raise ProviderError(f"Failed to parse Gupshup webhook: {e}")
    
    async def fetch_media(self, media_id: str) -> MediaBlob:
        """Fetch media binary from Gupshup using media URL with retry logic.
        
        For Gupshup, media_id is typically a direct HTTPS URL from the webhook.
        
        Args:
            media_id: Media URL (from parse_inbound media_ids)
        
        Returns:
            MediaBlob with binary data, MIME type, and metadata
        
        Raises:
            MediaFetchError: If fetch fails or media is invalid
        """
        try:
            # Fetch with exponential backoff retry
            response = await retry_with_backoff(
                lambda: self.client.get(media_id),
                max_retries=3,
                backoff_factor=2.0,
                initial_delay=0.5,
                name="gupshup_fetch_media"
            )
            
            if response.status_code != 200:
                logger.error(f"❌ Media fetch failed: {response.status_code}")
                raise MediaFetchError(
                    f"Failed to fetch media: HTTP {response.status_code}"
                )
            
            mime_type = response.headers.get("content-type", "application/octet-stream")
            filename = media_id.split("/")[-1] if "/" in media_id else media_id
            
            blob = MediaBlob(
                data=response.content,
                mime_type=mime_type,
                filename=filename
            )
            
            logger.debug(f"✓ Fetched media: {len(blob.data)} bytes, {mime_type}")
            return blob
        
        except Exception as e:
            logger.error(f"❌ Media fetch error: {e}")
            raise MediaFetchError(f"Failed to fetch media from Gupshup: {e}")
    
    async def send_text(self, to_phone: str, text: str) -> SendResult:
        """Send free-form text message via Gupshup with retry logic.
        
        Args:
            to_phone: Recipient phone (E.164 format)
            text: Message text (max 4096 chars per WhatsApp)
        
        Returns:
            SendResult with message_id and status
        
        Raises:
            ProviderError: If send fails permanently
        """
        try:
            # Normalize phone
            to_phone = validate_phone_number(to_phone)
            to_raw = to_phone.lstrip("+")  # Gupshup expects digits only
            
            payload = {
                "phone": to_raw,
                "message": text,
                "type": "text"
            }
            
            # Send with retry
            response = await retry_with_backoff(
                lambda: self.client.post(
                    f"{self.base_url}/msg/send/",
                    json=payload
                ),
                max_retries=3,
                backoff_factor=2.0,
                name="gupshup_send_text"
            )
            
            response_data = response.json()
            
            if response.status_code == 200 and response_data.get("status") == "submitted":
                msg_id = response_data.get("messageId", "")
                logger.info(f"✓ Text sent: {msg_id}")
                return SendResult(
                    message_id=msg_id,
                    status="sent"
                )
            else:
                error_msg = response_data.get("message", "Unknown error")
                logger.error(f"❌ Send failed: {error_msg}")
                return SendResult(
                    message_id="",
                    status="failed",
                    error=error_msg
                )
        
        except Exception as e:
            logger.error(f"❌ Send text error: {e}")
            return SendResult(
                message_id="",
                status="failed",
                error=str(e)
            )
    
    async def send_template(
        self,
        to_phone: str,
        template: "TemplateRef",
    ) -> SendResult:
        """Send HSM template message via Gupshup with retry logic.
        
        Args:
            to_phone: Recipient phone (E.164)
            template: TemplateRef with name and parameters
        
        Returns:
            SendResult with message_id and status
        """
        try:
            # Normalize phone
            to_phone = validate_phone_number(to_phone)
            to_raw = to_phone.lstrip("+")
            
            payload = {
                "phone": to_raw,
                "template": {
                    "id": template.template_name,
                    "params": template.parameters
                }
            }
            
            response = await retry_with_backoff(
                lambda: self.client.post(
                    f"{self.base_url}/template/send/",
                    json=payload
                ),
                max_retries=3,
                backoff_factor=2.0,
                name="gupshup_send_template"
            )
            
            response_data = response.json()
            
            if response.status_code == 200 and response_data.get("status") == "submitted":
                msg_id = response_data.get("messageId", "")
                logger.info(f"✓ Template sent: {template.template_name}")
                return SendResult(
                    message_id=msg_id,
                    status="sent"
                )
            else:
                error_msg = response_data.get("message", "Unknown error")
                logger.error(f"❌ Template send failed: {error_msg}")
                return SendResult(
                    message_id="",
                    status="failed",
                    error=error_msg
                )
        
        except Exception as e:
            logger.error(f"❌ Send template error: {e}")
            return SendResult(
                message_id="",
                status="failed",
                error=str(e)
            )
    
    async def send_media(
        self,
        to_phone: str,
        media_url: str,
        caption: Optional[str] = None,
    ) -> SendResult:
        """Send media (image, document, audio) via Gupshup with retry logic.
        
        Args:
            to_phone: Recipient phone (E.164)
            media_url: URL to media file (must be publicly accessible)
            caption: Optional caption text
        
        Returns:
            SendResult with message_id and status
        """
        try:
            # Normalize phone
            to_phone = validate_phone_number(to_phone)
            to_raw = to_phone.lstrip("+")
            
            # Detect media type from URL extension
            media_type = "image"
            if ".pdf" in media_url.lower():
                media_type = "document"
            elif ".mp3" in media_url.lower() or ".ogg" in media_url.lower():
                media_type = "audio"
            
            payload = {
                "phone": to_raw,
                "media": {
                    "type": media_type,
                    "url": media_url,
                }
            }
            
            if caption:
                payload["media"]["caption"] = caption
            
            response = await retry_with_backoff(
                lambda: self.client.post(
                    f"{self.base_url}/media/send/",
                    json=payload
                ),
                max_retries=3,
                backoff_factor=2.0,
                name="gupshup_send_media"
            )
            
            response_data = response.json()
            
            if response.status_code == 200 and response_data.get("status") == "submitted":
                msg_id = response_data.get("messageId", "")
                logger.info(f"✓ Media sent ({media_type}): {msg_id}")
                return SendResult(
                    message_id=msg_id,
                    status="sent"
                )
            else:
                error_msg = response_data.get("message", "Unknown error")
                logger.error(f"❌ Media send failed: {error_msg}")
                return SendResult(
                    message_id="",
                    status="failed",
                    error=error_msg
                )
        
        except Exception as e:
            logger.error(f"❌ Send media error: {e}")
            return SendResult(
                message_id="",
                status="failed",
                error=str(e)
            )
