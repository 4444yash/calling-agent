"""
DTLN (Deep Temporal Latency Normalization) noise suppression wrapper for LiveKit.

Integrates the open-source DTLN model as a custom audio frame processor.
Runs locally, no cloud dependency, no metering.

Usage:
    from src.utils.dtln_processor import DTLNProcessor
    
    dtln = DTLNProcessor(sample_rate=24000)
    
    room_options = RoomOptions(
        audio_input=AudioInputOptions(
            sample_rate=24000,
            noise_cancellation=dtln.process_frame,  # Pass as frame processor
        )
    )
"""

import numpy as np
from loguru import logger
from typing import Optional
from livekit.rtc import AudioFrame


class DTLNProcessor:
    """
    DTLN noise suppression processor for LiveKit audio frames.
    
    Converts incoming audio frames to the DTLN model's expected format,
    processes them, and returns cleaned audio.
    """
    
    def __init__(self, sample_rate: int = 24000, model_path: Optional[str] = None):
        """
        Initialize DTLN processor.
        
        Args:
            sample_rate: Audio sample rate (typically 24000 for LiveKit)
            model_path: Path to custom DTLN model (optional, uses default)
        """
        self.sample_rate = sample_rate
        self.model_path = model_path
        
        try:
            from dtln_speech_enhancement import DTLN_interpreter
            self.dtln = DTLN_interpreter(
                frame_length=sample_rate // 50,  # 20ms frames @ 24kHz = 480 samples
                model_path=model_path
            )
            logger.info(f"✓ DTLN initialized (sample_rate={sample_rate}Hz, frame_length={self.dtln.frame_length})")
        except ImportError:
            logger.error("❌ DTLN not installed. Run: pip install dtln-speech-enhancement")
            raise
        except Exception as e:
            logger.error(f"❌ Failed to initialize DTLN: {e}")
            raise
    
    def process_frame(self, frame: AudioFrame) -> AudioFrame:
        """
        Process an audio frame through DTLN noise suppression.
        
        Args:
            frame: LiveKit AudioFrame (mono, 16-bit PCM)
            
        Returns:
            AudioFrame with noise-suppressed audio
        """
        try:
            # Convert PCM bytes to numpy float32
            audio_np = np.frombuffer(frame.data, dtype=np.int16).astype(np.float32) / 32768.0
            
            # Process through DTLN
            enhanced = self.dtln(audio_np)
            
            # Convert back to int16 PCM
            enhanced_int16 = (enhanced * 32768.0).astype(np.int16)
            enhanced_bytes = enhanced_int16.tobytes()
            
            # Return new frame with enhanced audio
            return AudioFrame(
                data=enhanced_bytes,
                sample_rate=frame.sample_rate,
                num_channels=frame.num_channels,
                samples_per_channel=frame.samples_per_channel
            )
        except Exception as e:
            logger.warning(f"⚠️ DTLN processing failed, returning original frame: {e}")
            return frame  # Fallback to original if processing fails


# Singleton instance (lazy-loaded)
_dtln_processor: Optional[DTLNProcessor] = None


def get_dtln_processor(sample_rate: int = 24000) -> DTLNProcessor:
    """
    Get or create a singleton DTLN processor instance.
    
    Args:
        sample_rate: Audio sample rate
        
    Returns:
        DTLNProcessor instance
    """
    global _dtln_processor
    if _dtln_processor is None:
        _dtln_processor = DTLNProcessor(sample_rate=sample_rate)
    return _dtln_processor
