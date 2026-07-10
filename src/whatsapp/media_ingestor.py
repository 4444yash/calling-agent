"""Media Upload and Storage Management.

Stores WhatsApp media (photos, videos, documents) to Supabase Storage.
Validates MIME types and file sizes.
Returns signed URLs for later retrieval.

Supported types:
- Images: JPEG, PNG, WebP (high-quality photos from modern phones)
- Videos: MP4, MOV, WebM (property walkthroughs, virtual tours)
- Documents: PDF (floor plans, property details)
- Max file size: 100 MB per file (increased from 5MB for modern device quality)
- Max files per upload: 30 media items (photos + videos combined)

Modern phone considerations:
- High-res photos (4K): 15-30 MB typical
- Video clips (30-60 sec): 50-100 MB typical
- Comprehensive property documentation: multiple angles + walkthrough video
"""

import os
import logging
from typing import List, Dict, Optional
from dataclasses import dataclass

from .config import (
    ALLOWED_IMAGE_MIME_TYPES,
    ALLOWED_DOCUMENT_MIME_TYPES,
    ALLOWED_VIDEO_MIME_TYPES,
    MAX_MEDIA_FILE_SIZE_MB,
    MAX_PROPERTY_PHOTOS,
)
from .errors import ValidationError
from ..utils.supabase_client import SupabaseClient

logger = logging.getLogger(__name__)


@dataclass
class MediaBlob:
    """In-memory media blob ready for upload."""
    data: bytes
    mime_type: str
    filename: str


class MediaIngestor:
    """Upload media to Supabase Storage and return signed URLs."""
    
    def __init__(self, supabase: SupabaseClient):
        """Initialize with Supabase client."""
        self.supabase = supabase
        self.storage_bucket = "whatsapp-media"
    
    async def store(
        self,
        blobs: List[MediaBlob],
        draft_id: str,
    ) -> List[str]:
        """
        Store media blobs and return signed URLs.
        
        Args:
            blobs (list): List of MediaBlob objects
            draft_id (str): UUID of property draft (for organizing paths)
        
        Returns:
            List of signed URLs: ["https://...", "https://..."]
        
        Raises:
            ValidationError: If MIME type or file size invalid
        """
        if not blobs:
            return []
        
        if len(blobs) > MAX_PROPERTY_PHOTOS:
            raise ValidationError(
                f"Too many files (max {MAX_PROPERTY_PHOTOS}): {len(blobs)}"
            )
        
        urls = []
        
        for i, blob in enumerate(blobs):
            try:
                # Validate MIME type
                allowed_types = (
                    ALLOWED_IMAGE_MIME_TYPES 
                    | ALLOWED_DOCUMENT_MIME_TYPES 
                    | ALLOWED_VIDEO_MIME_TYPES
                )
                if blob.mime_type not in allowed_types:
                    raise ValidationError(
                        f"Invalid MIME type: {blob.mime_type}. "
                        f"Allowed: Images (JPEG, PNG, WebP), "
                        f"Videos (MP4, MOV, WebM), Documents (PDF)"
                    )
                
                # Validate file size
                size_mb = len(blob.data) / (1024 * 1024)
                if size_mb > MAX_MEDIA_FILE_SIZE_MB:
                    raise ValidationError(
                        f"File too large: {size_mb:.1f} MB "
                        f"(max {MAX_MEDIA_FILE_SIZE_MB} MB). "
                        f"Modern phones produce 4K images (15-30MB) and videos (50-100MB)."
                    )
                
                # Generate storage path
                # Format: whatsapp-media/{draft_id}/image_001.jpg
                ext = self._get_extension(blob.mime_type)
                filename = f"media_{i+1:03d}{ext}"
                path = f"{draft_id}/{filename}"
                
                # Upload to Supabase Storage
                url = await self.supabase.upload_file(
                    self.storage_bucket,
                    path,
                    blob.data,
                    content_type=blob.mime_type,
                )
                
                logger.info(f"✓ Uploaded: {path} ({size_mb:.2f} MB)")
                urls.append(url)
                
            except ValidationError:
                raise
            except Exception as e:
                logger.error(f"❌ Upload failed for blob {i}: {e}")
                raise ValidationError(f"Upload failed: {str(e)}")
        
        logger.info(f"✓ Stored {len(urls)} media files for draft {draft_id}")
        return urls
    
    def _get_extension(self, mime_type: str) -> str:
        """Get file extension from MIME type."""
        extensions = {
            # Images
            "image/jpeg": ".jpg",
            "image/png": ".png",
            "image/webp": ".webp",
            # Documents
            "application/pdf": ".pdf",
            # Videos
            "video/mp4": ".mp4",
            "video/quicktime": ".mov",
            "video/mpeg": ".mpeg",
            "video/webm": ".webm",
        }
        return extensions.get(mime_type, ".bin")


# ============================================================================
# FACTORY FUNCTION
# ============================================================================

async def store_media(
    blobs: List[MediaBlob],
    draft_id: str,
    supabase: SupabaseClient,
) -> List[str]:
    """
    Store media blobs and return signed URLs.
    
    Convenience function.
    
    Args:
        blobs (list): MediaBlob objects
        draft_id (str): UUID of property draft
        supabase (SupabaseClient): Database client
    
    Returns:
        List of signed URLs
    """
    ingestor = MediaIngestor(supabase)
    return await ingestor.store(blobs, draft_id)
