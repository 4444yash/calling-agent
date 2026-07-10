"""Twilio WhatsApp Business API provider.

Handles:
- Twilio request validation (auth token verification)
- Inbound message parsing with E.164 normalization
- Media fetching with retry logic
- Outbound sends (text, template, media) with retry logic
"""

import hmac
import hashlib
import json
import os
from typing import Optional, Dict
from datetime import datetime
import httpx
from base64 import b64encode
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


class TwilioProvider(WhatsAppProvider):
    """Twilio WhatsApp Business API implementation.
    
    API documentation: https://www.twilio.com/docs/whatsapp/
    
    Implements WhatsAppProvider protocol for Twilio's WhatsApp Business solution.
    Features:
    - Twilio request validation using auth token
    - E.164 phone normalization for all inbound/outbound
    - Exponential backoff retry for transient failures
    - Proper error classification and exception handling
    """
    
    def __init__(self):
        """Initialize Twilio provider from environment variables.
        
        Required env vars:
        - TWILIO_ACCOUNT_SID: Twilio Account SID
        - TWILIO_AUTH_TOKEN: Twilio Auth Token
        - TWILIO_BUSINESS_PHONE: Business WhatsApp number (E.164)
        
        Raises:
            ConfigurationError: If required credentials are missing
        """
        self.account_sid = os.getenv("TWILIO_ACCOUNT_SID")
        self.auth_token = os.getenv("TWILIO_AUTH_TOKEN")
        self.business_phone = os.getenv("TWILIO_BUSINESS_PHONE", "")
        
        if not all([self.account_sid, self.auth_token]):
            raise ConfigurationError(
                "Missing Twilio credentials. "
                "Required env vars: TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN"
            )
        
        self.base_url = PROVIDER_CONFIG["twilio"]["base_url"]
        
        # Create basic auth header for Twilio API
        auth_string = f"{self.account_sid}:{self.auth_token}"
        auth_bytes = auth_string.encode("utf-8")
        auth_b64 = b64encode(auth_bytes).decode("utf-8")
        
        self.client = httpx.AsyncClient(
            headers={
                "Authorization": f"Basic {auth_b64}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            timeout=10.0
        )
        logger.info("✓ TwilioProvider initialized")
    
    async def verify_signature(
        self,
        headers: dict,
        raw_body: bytes,
    ) -> bool:
        """Verify Twilio request signature using auth token.
        
        Twilio signs requests using auth token. The signature is computed as:
        HMAC-SHA1(auth_token, url + request_body) in base64
        
        Args:
            headers: HTTP headers dict (includes X-Twilio-Signature)
            raw_body: Raw request body bytes
        
        Returns:
            True if signature is valid
        
        Raises:
            SignatureVerificationError: If signature is invalid
        """
        try:
            # Extract Twilio signature header
            signature_header = None
            for key, value in headers.items():
                if key.lower() == "x-twilio-signature":
                    signature_header = value
                    break
            
            if not signature_header:
                logger.error("❌ Missing X-Twilio-Signature header")
                raise SignatureVerificationError("Missing X-Twilio-Signature header")
            
            # Compute HMAC-SHA1 using auth token
            # Note: Twilio uses SHA1, not SHA256
            computed_signature = hmac.new(
                self.auth_token.encode(),
                raw_body,
                hashlib.sha1
            ).digest()
            
            # Encode to base64 for comparison
            computed_b64 = b64encode(computed_signature).decode("utf-8")
            
            # Use timing-safe comparison
            if not hmac.compare_digest(computed_b64, signature_header):
                logger.error("❌ Twilio signature verification failed")
                raise SignatureVerificationError("Signature mismatch")
            
            logger.debug("✓ Twilio webhook signature verified")
            return True
        
        except SignatureVerificationError:
            raise
        except Exception as e:
            logger.error(f"❌ Signature verification error: {e}")
            raise SignatureVerificationError(f"Verification failed: {e}")
    
    async def parse_inbound(self, raw_body: bytes) -> InboundMessage:
        """Parse Twilio webhook form data into canonical InboundMessage.
        
        Twilio sends form-encoded data (not JSON):
        - From: sender WhatsApp number
        - To: recipient WhatsApp number (business)
        - Body: message text
        - MediaUrl0, MediaUrl1, ...: media URLs for attachments
        - MessageSid: Twilio message ID
        - Timestamp: milliseconds since epoch
        
        Args:
            raw_body: Raw form-encoded bytes from webhook
        
        Returns:
            InboundMessage with E.164 normalized phones
        
        Raises:
            ProviderError: If parsing or normalization fails
        """
        try:
            # Parse form data
            body_str = raw_body.decode("utf-8")
            form_data = {}
            for pair in body_str.split("&"):
                if "=" in pair:
                    key, value = pair.split("=", 1)
                    # URL decode
                    form_data[key] = value.replace("+", " ").replace("%20", " ")
            
            # Extract sender and recipient (Twilio sends as E.164 or +1234567890)
            from_phone_raw = form_data.get("From", "")
            if not from_phone_raw:
                raise ValidationError("Missing 'From' field in webhook")
            
            from_phone = validate_phone_number(from_phone_raw)
            
            # Extract message content
            text = form_data.get("Body", "")
            msg_type = "text"
            media_ids = []
            
            # Extract media URLs (Twilio sends MediaUrl0, MediaUrl1, etc.)
            if text:  # If there's body text, it's a text message with optional media
                pass  # Media can be present alongside text
            else:
                msg_type = "image"  # If no body text, it's media-only
            
            # Collect media URLs
            i = 0
            while f"MediaUrl{i}" in form_data:
                media_url = form_data.get(f"MediaUrl{i}")
                if media_url:
                    media_ids.append(media_url)
                    if not text:
                        msg_type = "image"  # Default to image for media-only
                i += 1
            
            # Parse timestamp (Twilio sends Unix timestamp in seconds or the raw format)
            timestamp_str = form_data.get("Timestamp", datetime.utcnow().isoformat())
            try:
                timestamp = datetime.fromisoformat(timestamp_str)
            except Exception:
                timestamp = datetime.utcnow()
            
            inbound_msg = InboundMessage(
                provider="twilio",
                provider_message_id=form_data.get("MessageSid", ""),
                from_phone=from_phone,
                to_phone=self.business_phone,
                timestamp=timestamp,
                type=msg_type,
                text=text if text else None,
                media_ids=media_ids,
                raw=form_data
            )
            
            logger.debug(f"✓ Parsed inbound message: {inbound_msg.provider_message_id}")
            return inbound_msg
        
        except (ValidationError, ValueError) as e:
            raise ProviderError(f"Failed to parse Twilio webhook: {e}")
        except Exception as e:
            logger.error(f"❌ Parse inbound error: {e}")
            raise ProviderError(f"Failed to parse Twilio webhook: {e}")
    
    async def fetch_media(self, media_id: str) -> MediaBlob:
        """Fetch media binary from Twilio using media URL with retry logic.
        
        For Twilio, media_id is a direct HTTPS URL that requires
        Twilio credentials for authentication.
        
        Args:
            media_id: Media URL from parse_inbound
        
        Returns:
            MediaBlob with binary data and MIME type
        
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
                name="twilio_fetch_media"
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
            raise MediaFetchError(f"Failed to fetch media from Twilio: {e}")
    
    async def send_text(self, to_phone: str, text: str) -> SendResult:
        """Send free-form text message via Twilio with retry logic.
        
        Args:
            to_phone: Recipient phone (E.164 format)
            text: Message text
        
        Returns:
            SendResult with message_id and status
        """
        try:
            # Normalize phone
            to_phone = validate_phone_number(to_phone)
            
            # Twilio API: POST /Services/{sid}/Messages
            url = (
                f"{self.base_url}/Services/{self.account_sid}/Messages"
            )
            
            # Form-encoded payload for Twilio
            payload = {
                "To": to_phone,
                "From": self.business_phone,
                "Body": text,
            }
            
            response = await retry_with_backoff(
                lambda: self.client.post(url, data=payload),
                max_retries=3,
                backoff_factor=2.0,
                name="twilio_send_text"
            )
            
            response_data = response.json() if response.headers.get("content-type") == "application/json" else {}
            
            if response.status_code == 200 or response.status_code == 201:
                msg_id = response_data.get("sid", "")
                logger.info(f"✓ Text sent via Twilio: {msg_id}")
                return SendResult(
                    message_id=msg_id,
                    status="sent"
                )
            else:
                error_msg = response_data.get("message", f"HTTP {response.status_code}")
                logger.error(f"❌ Twilio send failed: {error_msg}")
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
        """Send HSM template message via Twilio with retry logic.
        
        Args:
            to_phone: Recipient phone (E.164)
            template: TemplateRef with name and parameters
        
        Returns:
            SendResult with message_id and status
        """
        try:
            # Normalize phone
            to_phone = validate_phone_number(to_phone)
            
            # Twilio API endpoint for messages
            url = (
                f"{self.base_url}/Services/{self.account_sid}/Messages"
            )
            
            # Build payload with template
            payload = {
                "To": to_phone,
                "From": self.business_phone,
                "ContentSid": template.template_name,  # Twilio uses ContentSid for templates
            }
            
            # Add template parameters
            for i, param in enumerate(template.parameters):
                payload[f"ContentVariables"] = json.dumps({f"1": param for i, param in enumerate(template.parameters)})
            
            response = await retry_with_backoff(
                lambda: self.client.post(url, data=payload),
                max_retries=3,
                backoff_factor=2.0,
                name="twilio_send_template"
            )
            
            response_data = response.json() if response.headers.get("content-type") == "application/json" else {}
            
            if response.status_code == 200 or response.status_code == 201:
                msg_id = response_data.get("sid", "")
                logger.info(f"✓ Template sent via Twilio: {template.template_name}")
                return SendResult(
                    message_id=msg_id,
                    status="sent"
                )
            else:
                error_msg = response_data.get("message", f"HTTP {response.status_code}")
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
        """Send media via Twilio with retry logic.
        
        Args:
            to_phone: Recipient phone (E.164)
            media_url: URL to media file
            caption: Optional caption text
        
        Returns:
            SendResult with message_id and status
        """
        try:
            # Normalize phone
            to_phone = validate_phone_number(to_phone)
            
            # Twilio API endpoint
            url = (
                f"{self.base_url}/Services/{self.account_sid}/Messages"
            )
            
            # Build payload
            payload = {
                "To": to_phone,
                "From": self.business_phone,
                "MediaUrl": media_url,
            }
            
            if caption:
                payload["Body"] = caption
            
            response = await retry_with_backoff(
                lambda: self.client.post(url, data=payload),
                max_retries=3,
                backoff_factor=2.0,
                name="twilio_send_media"
            )
            
            response_data = response.json() if response.headers.get("content-type") == "application/json" else {}
            
            if response.status_code == 200 or response.status_code == 201:
                msg_id = response_data.get("sid", "")
                logger.info(f"✓ Media sent via Twilio: {msg_id}")
                return SendResult(
                    message_id=msg_id,
                    status="sent"
                )
            else:
                error_msg = response_data.get("message", f"HTTP {response.status_code}")
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
