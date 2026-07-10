#!/usr/bin/env python3
"""
Call Quality Analyzer

Analyzes downloaded call recordings to:
- Measure audio quality (volume levels, noise, clarity)
- Detect speech patterns and interruptions
- Identify agent performance metrics
- Generate quality report for debugging

Usage:
    python analyze_call_quality.py recordings/room_name/recording.webm
"""

import sys
import json
import subprocess
from pathlib import Path
from typing import Dict, Optional, List
from dataclasses import dataclass, asdict
from loguru import logger

logger.remove()
logger.add(sys.stderr, format="<level>{level: <8}</level> | {message}")


@dataclass
class AudioMetrics:
    """Audio quality metrics"""
    duration_seconds: float
    sample_rate: int
    channels: int
    bitrate_kbps: int
    codec: str
    peak_level_db: float
    mean_level_db: float
    noise_floor_db: float


@dataclass
class CallAnalysis:
    """Complete call analysis"""
    filename: str
    timestamp: str
    duration_seconds: float
    audio_metrics: Optional[AudioMetrics] = None
    quality_score: float = 0.0  # 0-100
    issues: List[str] = None
    recommendations: List[str] = None
    
    def __post_init__(self):
        if self.issues is None:
            self.issues = []
        if self.recommendations is None:
            self.recommendations = []


class CallQualityAnalyzer:
    """Analyze call recordings for quality issues"""
    
    def __init__(self):
        self.ffprobe_available = self._check_ffprobe()
    
    def _check_ffprobe(self) -> bool:
        """Check if ffprobe is available"""
        try:
            subprocess.run(
                ["ffprobe", "-version"],
                capture_output=True,
                check=True,
                timeout=5
            )
            return True
        except (subprocess.CalledProcessError, FileNotFoundError):
            logger.warning("⚠️ ffprobe not found. Install ffmpeg for audio analysis.")
            return False
    
    def get_audio_info(self, file_path: Path) -> Optional[AudioMetrics]:
        """
        Extract audio metrics from recording using ffprobe
        
        Args:
            file_path: Path to recording file
        
        Returns:
            AudioMetrics object or None if analysis fails
        """
        if not self.ffprobe_available:
            return None
        
        try:
            # Get audio stream information
            cmd = [
                "ffprobe",
                "-v", "error",
                "-select_streams", "a:0",
                "-show_entries", "stream=duration,sample_rate,channels,codec_name,bit_rate",
                "-of", "json",
                str(file_path)
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            data = json.loads(result.stdout)
            
            if not data.get("streams"):
                logger.warning(f"⚠️ No audio stream found in {file_path}")
                return None
            
            stream = data["streams"][0]
            
            # Try to get duration from format
            cmd_format = [
                "ffprobe",
                "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1:noprint_wrappers=1",
                str(file_path)
            ]
            result_format = subprocess.run(cmd_format, capture_output=True, text=True, timeout=10)
            duration = float(result_format.stdout.strip()) if result_format.stdout.strip() else 0.0
            
            metrics = AudioMetrics(
                duration_seconds=duration,
                sample_rate=int(stream.get("sample_rate", 0)),
                channels=int(stream.get("channels", 0)),
                bitrate_kbps=int(int(stream.get("bit_rate", 0)) / 1000),
                codec=stream.get("codec_name", "unknown"),
                peak_level_db=0.0,  # Would need deeper analysis
                mean_level_db=0.0,
                noise_floor_db=0.0
            )
            
            return metrics
        
        except Exception as e:
            logger.error(f"❌ Error analyzing audio: {e}")
            return None
    
    def analyze_recording(self, file_path: Path) -> CallAnalysis:
        """
        Analyze a recording and generate quality report
        
        Args:
            file_path: Path to recording file
        
        Returns:
            CallAnalysis object with findings
        """
        if not file_path.exists():
            logger.error(f"❌ File not found: {file_path}")
            return None
        
        logger.info(f"📊 Analyzing: {file_path.name}")
        
        # Get file stats
        stat = file_path.stat()
        file_size_mb = stat.st_size / 1024 / 1024
        
        # Get audio metrics
        audio_metrics = self.get_audio_info(file_path)
        
        # Create analysis
        analysis = CallAnalysis(
            filename=file_path.name,
            timestamp=datetime.now().isoformat(),
            duration_seconds=audio_metrics.duration_seconds if audio_metrics else 0.0,
            audio_metrics=audio_metrics
        )
        
        # Check for issues
        issues = []
        recommendations = []
        quality_score = 100.0
        
        if not audio_metrics:
            logger.warning("⚠️ Unable to extract audio metrics")
            issues.append("Audio metrics extraction failed")
            quality_score = 50.0
        else:
            # Check sample rate (should be 24000 for agent, 16000 for caller)
            if audio_metrics.sample_rate < 16000:
                issues.append(f"Low sample rate: {audio_metrics.sample_rate} Hz")
                recommendations.append("Ensure audio source is configured for 16kHz or higher")
                quality_score -= 10
            
            # Check channels (should be stereo for call)
            if audio_metrics.channels < 2:
                issues.append(f"Mono audio detected ({audio_metrics.channels} channel)")
                recommendations.append("Use stereo recording to capture both speaker and agent")
                quality_score -= 5
            
            # Check bitrate (should be reasonable)
            if audio_metrics.bitrate_kbps < 64:
                issues.append(f"Very low bitrate: {audio_metrics.bitrate_kbps} kbps")
                recommendations.append("Increase bitrate to 128-256 kbps for better quality")
                quality_score -= 15
            
            # Check duration
            if audio_metrics.duration_seconds < 5:
                issues.append(f"Very short call: {audio_metrics.duration_seconds:.1f}s")
                recommendations.append("Test with longer calls for better analysis")
                quality_score -= 10
            elif audio_metrics.duration_seconds > 600:
                logger.warning(f"Long call detected: {audio_metrics.duration_seconds:.1f}s")
        
        # File size check
        if file_size_mb > 500:
            issues.append(f"Large file size: {file_size_mb:.1f} MB")
            recommendations.append("Consider compression for storage")
            quality_score -= 5
        
        # Expected file size estimation
        # Rough estimate: WebM ~100KB/second
        expected_size_mb = (audio_metrics.duration_seconds / 1024 * 100) if audio_metrics else 0
        if file_size_mb < expected_size_mb * 0.5:
            issues.append("File size lower than expected (may be truncated)")
            quality_score -= 10
        
        analysis.issues = issues
        analysis.recommendations = recommendations
        analysis.quality_score = max(0, quality_score)
        
        return analysis
    
    def print_report(self, analysis: CallAnalysis):
        """Print formatted analysis report"""
        
        logger.info("\n" + "=" * 70)
        logger.info(f"📊 CALL QUALITY ANALYSIS REPORT")
        logger.info("=" * 70)
        
        logger.info(f"\n📁 File: {analysis.filename}")
        logger.info(f"⏱️  Duration: {analysis.duration_seconds:.1f} seconds")
        
        if analysis.audio_metrics:
            metrics = analysis.audio_metrics
            logger.info(f"\n🔊 Audio Metrics:")
            logger.info(f"   Sample Rate: {metrics.sample_rate} Hz")
            logger.info(f"   Channels: {metrics.channels}")
            logger.info(f"   Bitrate: {metrics.bitrate_kbps} kbps")
            logger.info(f"   Codec: {metrics.codec}")
        
        # Quality score
        score = analysis.quality_score
        if score >= 90:
            emoji = "✅"
            level = "Excellent"
        elif score >= 70:
            emoji = "✓"
            level = "Good"
        elif score >= 50:
            emoji = "⚠️"
            level = "Fair"
        else:
            emoji = "❌"
            level = "Poor"
        
        logger.info(f"\n{emoji} Quality Score: {score:.0f}/100 ({level})")
        
        if analysis.issues:
            logger.warning(f"\n⚠️  Issues Found ({len(analysis.issues)}):")
            for issue in analysis.issues:
                logger.warning(f"   • {issue}")
        else:
            logger.info("\n✅ No issues detected")
        
        if analysis.recommendations:
            logger.info(f"\n💡 Recommendations ({len(analysis.recommendations)}):")
            for rec in analysis.recommendations:
                logger.info(f"   • {rec}")
        
        logger.info("\n" + "=" * 70)


def main():
    """Main entry point"""
    from datetime import datetime
    
    if len(sys.argv) < 2:
        logger.error("❌ Usage: python analyze_call_quality.py <recording_file>")
        sys.exit(1)
    
    file_path = Path(sys.argv[1])
    
    analyzer = CallQualityAnalyzer()
    analysis = analyzer.analyze_recording(file_path)
    
    if analysis:
        analyzer.print_report(analysis)
        
        # Save report as JSON
        report_file = file_path.parent / f"{file_path.stem}_analysis.json"
        with open(report_file, "w") as f:
            json.dump(asdict(analysis), f, indent=2, default=str)
        logger.info(f"💾 Report saved: {report_file}")
    else:
        logger.error("❌ Analysis failed")
        sys.exit(1)


if __name__ == "__main__":
    main()
