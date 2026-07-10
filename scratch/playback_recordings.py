#!/usr/bin/env python3
"""
Recording Playback Manager

Browse, play, and manage downloaded call recordings.
Provides utilities to:
- List recordings with metadata
- Play recordings with audio player
- Extract audio information
- Generate listening notes
- Delete recordings to save space

Usage:
    python playback_recordings.py --list
    python playback_recordings.py --play FILENAME
    python playback_recordings.py --convert FILENAME  # Convert to MP3
    python playback_recordings.py --export FILENAME   # Extract metadata
"""

import sys
import json
import subprocess
from pathlib import Path
from typing import Optional, List
from datetime import datetime
from loguru import logger

logger.remove()
logger.add(sys.stderr, format="<level>{level: <8}</level> | {message}")


class RecordingManager:
    """Manage recording playback and export"""
    
    def __init__(self, recordings_dir: Path = Path("recordings")):
        self.recordings_dir = recordings_dir
        if not self.recordings_dir.exists():
            self.recordings_dir.mkdir(exist_ok=True)
            logger.info(f"📁 Created recordings directory: {self.recordings_dir}")
    
    def list_recordings(self) -> List[Path]:
        """List all recording files"""
        files = list(self.recordings_dir.rglob("*.webm"))
        files.extend(self.recordings_dir.rglob("*.mp4"))
        files.extend(self.recordings_dir.rglob("*.mp3"))
        
        return sorted(files, key=lambda p: p.stat().st_mtime, reverse=True)
    
    def print_recordings_list(self):
        """Print formatted list of recordings"""
        files = self.list_recordings()
        
        if not files:
            logger.warning("📭 No recordings found")
            return
        
        logger.info("\n📁 AVAILABLE RECORDINGS:")
        logger.info("┌──────┬──────────────────────────┬─────────────┬──────────┐")
        logger.info("│ #    │ Filename                 │ Size (MB)   │ Date     │")
        logger.info("├──────┼──────────────────────────┼─────────────┼──────────┤")
        
        for idx, file in enumerate(files, 1):
            name = file.name[:23].ljust(23)
            size_mb = f"{file.stat().st_size / 1024 / 1024:.1f}".ljust(11)
            mtime = datetime.fromtimestamp(file.stat().st_mtime).strftime("%Y-%m-%d")
            
            logger.info(f"│ {idx:<4} │ {name} │ {size_mb} │ {mtime} │")
        
        logger.info("└──────┴──────────────────────────┴─────────────┴──────────┘")
        logger.info(f"\nTotal: {len(files)} recording(s)")
    
    def play_recording(self, filename: str) -> bool:
        """
        Play a recording using system audio player
        
        Args:
            filename: Name or path of recording
        
        Returns:
            True if successful, False otherwise
        """
        file_path = self._find_file(filename)
        
        if not file_path:
            logger.error(f"❌ Recording not found: {filename}")
            return False
        
        logger.info(f"🎵 Playing: {file_path.name}")
        
        # Try different players
        players = [
            ["vlc", str(file_path)],
            ["mpv", str(file_path)],
            ["ffplay", str(file_path)],
            ["play", str(file_path)],  # SoX
        ]
        
        for player_cmd in players:
            try:
                subprocess.run(player_cmd, timeout=3600)
                return True
            except FileNotFoundError:
                continue
            except subprocess.TimeoutExpired:
                logger.warning("⚠️ Playback timeout")
                return False
            except Exception as e:
                logger.debug(f"Player {player_cmd[0]} failed: {e}")
                continue
        
        logger.error("❌ No audio player found. Install vlc, mpv, or ffplay.")
        return False
    
    def convert_to_mp3(self, filename: str, output_bitrate: int = 128) -> Optional[Path]:
        """
        Convert WebM recording to MP3 for easier sharing
        
        Args:
            filename: Source recording name
            output_bitrate: Output bitrate in kbps
        
        Returns:
            Path to converted file, or None if failed
        """
        file_path = self._find_file(filename)
        
        if not file_path:
            logger.error(f"❌ Recording not found: {filename}")
            return None
        
        output_path = file_path.with_suffix(".mp3")
        
        if output_path.exists():
            logger.warning(f"⚠️ Output file already exists: {output_path}")
            return output_path
        
        logger.info(f"🔄 Converting {file_path.name} to MP3...")
        
        try:
            cmd = [
                "ffmpeg",
                "-i", str(file_path),
                "-b:a", f"{output_bitrate}k",
                "-y",  # Overwrite
                str(output_path)
            ]
            
            subprocess.run(cmd, capture_output=True, check=True, timeout=300)
            
            size_mb = output_path.stat().st_size / 1024 / 1024
            logger.info(f"✅ Converted to {output_path.name} ({size_mb:.1f} MB)")
            
            return output_path
        
        except FileNotFoundError:
            logger.error("❌ ffmpeg not found. Install ffmpeg to convert recordings.")
            return None
        except subprocess.CalledProcessError as e:
            logger.error(f"❌ Conversion failed: {e}")
            return None
    
    def export_metadata(self, filename: str) -> Optional[Path]:
        """
        Export recording metadata to JSON
        
        Args:
            filename: Recording name
        
        Returns:
            Path to JSON file, or None if failed
        """
        file_path = self._find_file(filename)
        
        if not file_path:
            logger.error(f"❌ Recording not found: {filename}")
            return None
        
        metadata = {
            "filename": file_path.name,
            "path": str(file_path),
            "size_bytes": file_path.stat().st_size,
            "size_mb": file_path.stat().st_size / 1024 / 1024,
            "created_at": datetime.fromtimestamp(file_path.stat().st_ctime).isoformat(),
            "modified_at": datetime.fromtimestamp(file_path.stat().st_mtime).isoformat(),
        }
        
        # Try to get audio info with ffprobe
        try:
            cmd = [
                "ffprobe",
                "-v", "error",
                "-show_format",
                "-show_streams",
                "-of", "json",
                str(file_path)
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            ffprobe_data = json.loads(result.stdout)
            
            if ffprobe_data.get("streams"):
                stream = ffprobe_data["streams"][0]
                metadata["audio"] = {
                    "duration": stream.get("duration"),
                    "sample_rate": stream.get("sample_rate"),
                    "channels": stream.get("channels"),
                    "codec": stream.get("codec_name"),
                }
            
            if ffprobe_data.get("format"):
                fmt = ffprobe_data["format"]
                metadata["format"] = {
                    "duration": fmt.get("duration"),
                    "bitrate": fmt.get("bit_rate"),
                }
        
        except Exception as e:
            logger.debug(f"⚠️ Could not extract audio metadata: {e}")
        
        # Save to JSON
        json_path = file_path.with_suffix(".json")
        with open(json_path, "w") as f:
            json.dump(metadata, f, indent=2)
        
        logger.info(f"💾 Metadata exported to {json_path}")
        return json_path
    
    def delete_recording(self, filename: str) -> bool:
        """
        Delete a recording to save space
        
        Args:
            filename: Recording name
        
        Returns:
            True if successful
        """
        file_path = self._find_file(filename)
        
        if not file_path:
            logger.error(f"❌ Recording not found: {filename}")
            return False
        
        # Confirm deletion
        size_mb = file_path.stat().st_size / 1024 / 1024
        logger.warning(f"⚠️ About to delete {file_path.name} ({size_mb:.1f} MB)")
        
        response = input("Are you sure? (yes/no): ").strip().lower()
        if response != "yes":
            logger.info("❌ Deletion cancelled")
            return False
        
        file_path.unlink()
        logger.info(f"✅ Deleted {file_path.name}")
        
        # Also delete associated files
        for ext in [".json", ".mp3"]:
            alt_path = file_path.with_suffix(ext)
            if alt_path.exists():
                alt_path.unlink()
                logger.info(f"✅ Deleted {alt_path.name}")
        
        return True
    
    def get_storage_summary(self) -> dict:
        """Get storage summary of all recordings"""
        files = self.list_recordings()
        
        total_size = sum(f.stat().st_size for f in files)
        total_duration_estimate = len(files) * 60  # Rough estimate
        
        return {
            "total_files": len(files),
            "total_size_mb": total_size / 1024 / 1024,
            "estimated_hours": total_duration_estimate / 3600,
        }
    
    def _find_file(self, filename: str) -> Optional[Path]:
        """Find a recording file by name (fuzzy matching)"""
        files = self.list_recordings()
        
        # Exact match
        for f in files:
            if f.name == filename or str(f) == filename:
                return f
        
        # Partial match
        filename_lower = filename.lower()
        for f in files:
            if filename_lower in f.name.lower():
                return f
        
        return None


def main():
    """Main entry point"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Manage call recordings")
    parser.add_argument("--list", action="store_true", help="List all recordings")
    parser.add_argument("--play", type=str, help="Play a recording")
    parser.add_argument("--convert", type=str, help="Convert WebM to MP3")
    parser.add_argument("--export", type=str, help="Export metadata to JSON")
    parser.add_argument("--delete", type=str, help="Delete a recording")
    parser.add_argument("--storage", action="store_true", help="Show storage summary")
    parser.add_argument("--dir", type=Path, default=Path("recordings"), help="Recordings directory")
    
    args = parser.parse_args()
    
    manager = RecordingManager(args.dir)
    
    if args.list:
        manager.print_recordings_list()
    
    elif args.play:
        manager.play_recording(args.play)
    
    elif args.convert:
        manager.convert_to_mp3(args.convert)
    
    elif args.export:
        manager.export_metadata(args.export)
    
    elif args.delete:
        manager.delete_recording(args.delete)
    
    elif args.storage:
        summary = manager.get_storage_summary()
        logger.info("\n💾 STORAGE SUMMARY:")
        logger.info(f"   Files: {summary['total_files']}")
        logger.info(f"   Total: {summary['total_size_mb']:.1f} MB")
        logger.info(f"   Est. Duration: {summary['estimated_hours']:.1f} hours")
    
    else:
        manager.print_recordings_list()


if __name__ == "__main__":
    main()
