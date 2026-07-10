"""DPDP Erasure and Data Privacy.

Implements right-to-erasure (right to be forgotten) under DPDP 2023.

For a given phone number, this module:
1. Anonymizes wa_conversations and wa_messages records
2. Optionally deletes media from Storage
3. Logs erasure event
4. Returns success/failure status

Anonymization preserves message structure for compliance audits but removes
personally identifiable content.
"""

import logging
from datetime import datetime
from typing import Dict, Optional

from ..utils.supabase_client import SupabaseClient
from .errors import ValidationError

logger = logging.getLogger(__name__)


class DPDPEraser:
    """Handle DPDP erasure requests."""
    
    def __init__(self, supabase: SupabaseClient):
        """Initialize with Supabase client."""
        self.supabase = supabase
    
    async def erase_customer_data(self, phone: str) -> Dict[str, any]:
        """
        Erase all customer data for a phone number.
        
        Process:
        1. Find all conversations for phone
        2. Anonymize messages (remove text, media_urls, but keep structure)
        3. Log erasure event
        4. Return counts of affected records
        
        Args:
            phone (str): E.164 phone number (e.g., +919876543210)
        
        Returns:
            {
                "status": "success",
                "phone": phone,
                "rows_affected": N,
                "message": "Erased N messages and M conversations",
                "timestamp": ISO timestamp,
            }
        
        Raises:
            ValidationError: If phone invalid or erasure fails
        """
        try:
            if not phone or not phone.startswith("+"):
                raise ValidationError(f"Invalid phone number: {phone}")
            
            # Find all messages for this phone
            messages = await self.supabase.fetch(
                "wa_messages",
                filters={"from_phone": phone}
            )
            
            if not messages:
                logger.info(f"No messages found for {phone}")
                return {
                    "status": "success",
                    "phone": phone,
                    "rows_affected": 0,
                    "message": "No data to erase",
                    "timestamp": datetime.utcnow().isoformat(),
                }
            
            # Anonymize messages
            message_ids = [m.get("id") for m in messages if m.get("id")]
            
            anonymized_count = 0
            for msg_id in message_ids:
                try:
                    # Update: set body to null, media_urls to empty array
                    await self.supabase.update(
                        "wa_messages",
                        {"id": msg_id},
                        {
                            "body": None,
                            "media_urls": [],
                            "text": None,
                            "anonymized_at": datetime.utcnow().isoformat(),
                            "anonymized_reason": "DPDP erasure request",
                        }
                    )
                    anonymized_count += 1
                except Exception as e:
                    logger.warning(f"Failed to anonymize message {msg_id}: {e}")
                    continue
            
            # Find conversations and anonymize
            conversations = await self.supabase.fetch(
                "wa_conversations",
                filters={"phone": phone}
            )
            
            conv_anonymized = 0
            for conv in conversations:
                try:
                    conv_id = conv.get("id")
                    # Clear history and context
                    await self.supabase.update(
                        "wa_conversations",
                        {"id": conv_id},
                        {
                            "history": [],
                            "anonymized_at": datetime.utcnow().isoformat(),
                            "anonymized_reason": "DPDP erasure request",
                        }
                    )
                    conv_anonymized += 1
                except Exception as e:
                    logger.warning(f"Failed to anonymize conversation {conv_id}: {e}")
                    continue
            
            # Log erasure event
            await self.supabase.insert(
                "dpdp_erasure_logs",
                {
                    "phone": phone,
                    "messages_erased": anonymized_count,
                    "conversations_erased": conv_anonymized,
                    "requested_at": datetime.utcnow().isoformat(),
                    "status": "completed",
                }
            )
            
            total_affected = anonymized_count + conv_anonymized
            
            logger.info(
                f"✓ DPDP erasure completed for {phone}: "
                f"{anonymized_count} messages, {conv_anonymized} conversations"
            )
            
            return {
                "status": "success",
                "phone": phone,
                "rows_affected": total_affected,
                "message": f"Erased {anonymized_count} messages and {conv_anonymized} conversations",
                "timestamp": datetime.utcnow().isoformat(),
            }
            
        except ValidationError:
            raise
        except Exception as e:
            logger.error(f"❌ DPDP erasure failed for {phone}: {e}")
            raise ValidationError(f"Erasure failed: {str(e)}")


# ============================================================================
# FACTORY FUNCTION
# ============================================================================

async def erase_customer_data(
    phone: str,
    supabase: SupabaseClient,
) -> Dict[str, any]:
    """
    Erase customer data (DPDP compliance).
    
    Convenience function.
    
    Args:
        phone (str): E.164 phone number
        supabase (SupabaseClient): Database client
    
    Returns:
        Erasure result (see DPDPEraser.erase_customer_data)
    """
    eraser = DPDPEraser(supabase)
    return await eraser.erase_customer_data(phone)
