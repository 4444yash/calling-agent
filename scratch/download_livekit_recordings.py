#!/usr/bin/env python3
"""
LiveKit Recording Downloader & Analyzer

Downloads call recordings from LiveKit Cloud for testing and analysis.
Saves audio files and generates metadata about each recording.

Features:
- List all recordings in LiveKit account
- Download specific recordings by room name or recording ID
- Auto-organize recordings by date and room name
- Extract metadata: duration, quality, codec
- Generate call summary with transcript (if available)
- Batch download with progress tracking

Usage:
    python download_livekit_recordings.py --list
    python download_livekit_recordings.py --download ROOM_NAME
    python download_livekit_recordings.py --download-id RECORDING_ID
    python download_livekit_recordings.py --recent 5
"""

import os
import sys
import json
import asyncio
import httpx
import base64
import argparse
import time
import hmac
import hashlib
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, List, Dict
from dataclasses import dataclass
from urllib.parse import urljoin
from loguru import logger

# Configure logging
logger.remove()
logger.add(sys.stderr, format="<level>{level: <8}</level> | {message}")


@dataclass
class RecordingInfo:
    """Information about a single recording"""
    id: str
    room_name: str
    start_time: str
    duration: float
    size_bytes: int
    codec: str
    filename: str
    egress_id: Optional[str] = None


class LiveKitRecordingManager:
    """Manage LiveKit recording downloads"""
    
    def __init__(self, livekit_url: str, api_key: str, api_secret: str):
        """
        Initialize LiveKit recording manager
        
        Args:
            livekit_url: LiveKit server URL (e.g., ws://localhost:7880)
            api_key: LiveKit API key
            api_secret: LiveKit API secret
        """
        # Convert WebSocket URL to HTTP for REST API
        self.livekit_url = livekit_url.replace("wss://", "https://").replace("ws://", "http://")
        self.api_key = api_key
        self.api_secret = api_secret
        
        # Create HTTP client
        self.client = httpx.AsyncClient(timeout=30.0)
        
        # Create recordings directory
        self.recordings_dir = Path("recordings")
        self.recordings_dir.mkdir(exist_ok=True)
        logger.info(f"📁 Recordings directory: {self.recordings_dir.absolute()}")
    
    def _create_jwt_token(self) -> str:
        """
        Create a JWT token for LiveKit API authentication
        
        Returns:
            JWT token string
        """
        # Header
        header = {
            "alg": "HS256",
            "typ": "JWT"
        }
        
        # Payload
        now = int(time.time())
        payload = {
            "iss": self.api_key,
            "sub": self.api_key,
            "aud": "livekit",
            "iat": now,
            "exp": now + 3600,  # 1 hour expiry
            "grants": {
                "admin": True
            }
        }
        
        # Encode header and payload
        header_encoded = base64.urlsafe_b64encode(json.dumps(header).encode()).rstrip(b'=').decode()
        payload_encoded = base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b'=').decode()
        
        # Create signature
        message = f"{header_encoded}.{payload_encoded}"
        signature = base64.urlsafe_b64encode(
            hmac.new(self.api_secret.encode(), message.encode(), hashlib.sha256).digest()
        ).rstrip(b'=').decode()
        
        return f"{message}.{signature}"
    
    async def close(self):
        """Close HTTP client"""
        await self.client.aclose()
    
    async def list_recordings(self) -> List[RecordingInfo]:
        """
        List all recordings in LiveKit account
        
        Returns:
            List of RecordingInfo objects
        """
        try:
            jwt_token = self._create_jwt_token()
            # Try multiple endpoints as the API may have changed
            endpoints = [
                "/api/egress",  # Modern LiveKit uses egress for recordings
                "/api/recordings",
            ]
            
            for endpoint in endpoints:
                url = urljoin(self.livekit_url, endpoint)
                logger.debug(f"Trying endpoint: {endpoint}")
                
                try:
                    resp = await self.client.get(
                        url,
                        headers={"Authorization": f"Bearer {jwt_token}"}
                    )
                    resp.raise_for_status()
                    
                    # Handle empty response or "OK" response
                    if not resp.text or resp.text == "OK":
                        logger.info(f"📽️ Found 0 recordings (empty response from {endpoint})")
                        return []
                    
                    data = resp.json()
                    recordings = []
                    
                    for item in data.get("items", []) or data.get("egress_list", []):
                        # Parse metadata
                        metadata = item.get("metadata", {})
                        if isinstance(metadata, str):
                            try:
                                metadata = json.loads(metadata)
                            except json.JSONDecodeError:
                                metadata = {}
                        
                        recording = RecordingInfo(
                            id=item.get("egress_id", item.get("id", "unknown")),
                            room_name=item.get("room_name", "unknown"),
                            start_time=item.get("started_at", ""),
                            duration=float(item.get("duration", 0)),
                            size_bytes=int(item.get("size", 0)),
                            codec=item.get("codec", "unknown"),
                            filename=item.get("filename", ""),
                            egress_id=item.get("egress_id"),
                        )
                        recordings.append(recording)
                    
                    logger.info(f"📽️ Found {len(recordings)} recordings using endpoint: {endpoint}")
                    return recordings
                
                except Exception as e:
                    logger.debug(f"Endpoint {endpoint} failed: {e}")
                    continue
            
            # No endpoint worked
            logger.warning("📭 Could not find active recordings")
            return []
        
        except Exception as e:
            logger.error(f"❌ Error listing recordings: {e}")
            return []
    
    async def download_recording(
        self,
        recording_id: str,
        filename: Optional[str] = None,
        room_name: Optional[str] = None
    ) -> Optional[Path]:
        """
        Download a specific recording
        
        Args:
            recording_id: Recording/Egress ID
            filename: Custom filename (optional)
            room_name: Room name for directory organization
        
        Returns:
            Path to downloaded file, or None if failed
        """
        try:
            jwt_token = self._create_jwt_token()
            # Construct API URL for download
            url = urljoin(self.livekit_url, f"/api/recordings/{recording_id}")
            
            logger.info(f"🔽 Downloading recording {recording_id}...")
            resp = await self.client.get(
                url,
                headers={"Authorization": f"Bearer {jwt_token}"},
                follow_redirects=True
            )
            resp.raise_for_status()
            
            # Determine file path
            if not filename:
                filename = f"recording_{recording_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.webm"
            
            if room_name:
                save_dir = self.recordings_dir / room_name
            else:
                save_dir = self.recordings_dir
            
            save_dir.mkdir(parents=True, exist_ok=True)
            save_path = save_dir / filename
            
            # Write file with progress
            total_size = int(resp.headers.get("content-length", 0))
            downloaded = 0
            
            with open(save_path, "wb") as f:
                async for chunk in resp.aiter_bytes(chunk_size=8192):
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total_size > 0:
                        pct = (downloaded / total_size) * 100
                        logger.debug(f"  {pct:.1f}% ({downloaded / 1024 / 1024:.1f} MB)")
            
            logger.info(f"✅ Downloaded to {save_path}")
            logger.info(f"   Size: {save_path.stat().st_size / 1024 / 1024:.2f} MB")
            
            return save_path
        
        except Exception as e:
            logger.error(f"❌ Download failed for {recording_id}: {e}")
            return None
    
    async def download_recent(self, count: int = 5) -> List[Path]:
        """
        Download the most recent recordings
        
        Args:
            count: Number of recent recordings to download
        
        Returns:
            List of paths to downloaded files
        """
        recordings = await self.list_recordings()
        
        if not recordings:
            logger.warning("⚠️ No recordings found")
            return []
        
        # Sort by start time (newest first)
        sorted_recordings = sorted(
            recordings,
            key=lambda r: r.start_time,
            reverse=True
        )[:count]
        
        downloaded_files = []
        for recording in sorted_recordings:
            logger.info(f"\n📽️ Recording: {recording.room_name}")
            logger.info(f"   Started: {recording.start_time}")
            logger.info(f"   Duration: {recording.duration:.1f}s")
            logger.info(f"   Size: {recording.size_bytes / 1024 / 1024:.2f} MB")
            
            file_path = await self.download_recording(
                recording.id,
                room_name=recording.room_name
            )
            if file_path:
                downloaded_files.append(file_path)
        
        return downloaded_files
    
    async def download_by_room(self, room_name: str) -> List[Path]:
        """
        Download all recordings for a specific room
        
        Args:
            room_name: Name of the room
        
        Returns:
            List of paths to downloaded files
        """
        recordings = await self.list_recordings()
        room_recordings = [r for r in recordings if r.room_name == room_name]
        
        if not room_recordings:
            logger.warning(f"⚠️ No recordings found for room: {room_name}")
            return []
        
        logger.info(f"📽️ Found {len(room_recordings)} recordings for room '{room_name}'")
        
        downloaded_files = []
        for recording in room_recordings:
            file_path = await self.download_recording(
                recording.id,
                room_name=room_name
            )
            if file_path:
                downloaded_files.append(file_path)
        
        return downloaded_files
    
    def save_metadata(self, recordings: List[RecordingInfo]):
        """
        Save recordings metadata as JSON for reference
        
        Args:
            recordings: List of RecordingInfo objects
        """
        metadata_file = self.recordings_dir / "recordings_metadata.json"
        
        data = {
            "generated_at": datetime.now().isoformat(),
            "total_recordings": len(recordings),
            "recordings": [
                {
                    "id": r.id,
                    "room_name": r.room_name,
                    "start_time": r.start_time,
                    "duration_seconds": r.duration,
                    "size_mb": r.size_bytes / 1024 / 1024,
                    "codec": r.codec,
                    "filename": r.filename,
                }
                for r in recordings
            ]
        }
        
        with open(metadata_file, "w") as f:
            json.dump(data, f, indent=2)
        
        logger.info(f"💾 Metadata saved to {metadata_file}")
    
    def print_recordings_table(self, recordings: List[RecordingInfo]):
        """Print recordings in a nice table format"""
        if not recordings:
            logger.info("📋 No recordings to display")
            return
        
        logger.info("\n📋 AVAILABLE RECORDINGS:")
        logger.info("┌─────────────────────┬──────────────┬──────────┬──────────┐")
        logger.info("│ Room Name           │ Start Time   │ Duration │ Size (MB)│")
        logger.info("├─────────────────────┼──────────────┼──────────┼──────────┤")
        
        for r in recordings:
            room_name = r.room_name[:19].ljust(19)
            start_time = r.start_time[-12:] if r.start_time else "N/A".ljust(12)
            duration = f"{r.duration:.1f}s".ljust(8)
            size_mb = f"{r.size_bytes / 1024 / 1024:.1f}".ljust(8)
            
            logger.info(f"│ {room_name} │ {start_time} │ {duration} │ {size_mb} │")
        
        logger.info("└─────────────────────┴──────────────┴──────────┴──────────┘")
        logger.info(f"\nTotal: {len(recordings)} recordings")


async def main():
    """Main entry point"""
    
    parser = argparse.ArgumentParser(
        description="Download and manage LiveKit call recordings"
    )
    parser.add_argument("--list", action="store_true", help="List all recordings")
    parser.add_argument("--download", type=str, help="Download recordings for a room name")
    parser.add_argument("--download-id", type=str, help="Download specific recording by ID")
    parser.add_argument("--recent", type=int, default=5, help="Download N most recent recordings")
    
    args = parser.parse_args()
    
    # Load environment
    from dotenv import load_dotenv
    load_dotenv()
    
    livekit_url = os.getenv("LIVEKIT_URL")
    api_key = os.getenv("LIVEKIT_API_KEY")
    api_secret = os.getenv("LIVEKIT_API_SECRET")
    
    if not all([livekit_url, api_key, api_secret]):
        logger.error("❌ Missing environment variables:")
        logger.error("   LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET")
        sys.exit(1)
    
    # Initialize manager
    manager = LiveKitRecordingManager(livekit_url, api_key, api_secret)
    
    try:
        if args.list:
            # List all recordings
            recordings = await manager.list_recordings()
            manager.print_recordings_table(recordings)
            manager.save_metadata(recordings)
        
        elif args.download_id:
            # Download specific recording by ID
            file_path = await manager.download_recording(args.download_id)
            if file_path:
                logger.info(f"✅ Recording saved: {file_path}")
        
        elif args.download:
            # Download all recordings for a room
            file_paths = await manager.download_by_room(args.download)
            logger.info(f"\n✅ Downloaded {len(file_paths)} file(s)")
        
        else:
            # Default: Download recent recordings
            file_paths = await manager.download_recent(args.recent)
            logger.info(f"\n✅ Downloaded {len(file_paths)} most recent recording(s)")
    
    finally:
        await manager.close()


if __name__ == "__main__":
    asyncio.run(main())
