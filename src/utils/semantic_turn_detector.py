"""
Semantic Turn Detection for LiveKit using Pipecat Smart Turn v2.

Smart Turn v2 analyzes raw audio waveforms to detect when a speaker has finished
their turn using a small neural network. Unlike basic VAD (Voice Activity Detection),
it understands:
- Intonation patterns (falling pitch = end of thought)
- Sentence structure (prosody)
- Language-specific speech patterns (supports 14 languages including Hindi)

This prevents false turn-ending at mid-sentence pauses.

Reference: https://huggingface.co/pipecat-ai/smart-turn-v2
"""

import numpy as np
from loguru import logger
from typing import Optional
import onnxruntime as ort
from pathlib import Path
import urllib.request
import os


class SmartTurnDetectorV2:
    """
    Semantic turn detection using Pipecat Smart Turn v2 ONNX model.
    
    Runs locally, detects end-of-turn based on audio prosody + acoustic features,
    not just silence. Supports 14 languages including Hindi.
    """
    
    # Model URLs (Hugging Face)
    MODEL_REPO = "pipecat-ai/smart-turn-v2"
    MODEL_NAMES = {
        "english": "smartturn_en.onnx",
        "hindi": "smartturn_hi.onnx",
        "multilingual": "smartturn_multilingual.onnx",
    }
    
    def __init__(self, language: str = "multilingual", model_dir: Optional[str] = None):
        """
        Initialize Smart Turn v2 detector.
        
        Args:
            language: Language model ("english", "hindi", or "multilingual")
            model_dir: Directory to cache the ONNX model (default: ~/.cache/pipecat)
        """
        self.language = language
        self.model_dir = Path(model_dir or os.path.expanduser("~/.cache/pipecat"))
        self.model_dir.mkdir(parents=True, exist_ok=True)
        
        # Load ONNX model
        model_name = self.MODEL_NAMES.get(language, self.MODEL_NAMES["multilingual"])
        model_path = self.model_dir / model_name
        
        try:
            if not model_path.exists():
                logger.info(f"📥 Downloading Smart Turn v2 ({language}) model...")
                self._download_model(model_name, model_path)
            
            self.session = ort.InferenceSession(
                str(model_path),
                providers=["CPUExecutionProvider"]  # Use CPU only for consistency
            )
            logger.info(f"✓ Smart Turn v2 ({language}) loaded. Model: {model_path.name}")
        except Exception as e:
            logger.error(f"❌ Failed to initialize Smart Turn v2: {e}")
            raise
    
    def _download_model(self, model_name: str, target_path: Path) -> None:
        """Download ONNX model from Hugging Face."""
        url = f"https://huggingface.co/{self.MODEL_REPO}/resolve/main/{model_name}"
        try:
            urllib.request.urlretrieve(url, target_path)
            logger.info(f"✓ Downloaded: {target_path.name}")
        except Exception as e:
            logger.error(f"❌ Failed to download model from {url}: {e}")
            raise
    
    def is_turn_complete(
        self,
        audio: np.ndarray,
        sample_rate: int = 24000,
        threshold: float = 0.5,
    ) -> bool:
        """
        Determine if a turn (utterance) has completed based on audio prosody.
        
        Args:
            audio: Raw audio as float32 [-1.0, 1.0] or int16 [-32768, 32767]
            sample_rate: Sample rate (24000 Hz typical for LiveKit)
            threshold: Confidence threshold (0.0-1.0). Higher = more conservative.
                      Default 0.5 = 50% confidence speaker is done
        
        Returns:
            True if turn appears complete, False otherwise
        """
        try:
            # Normalize audio to float32 [-1.0, 1.0]
            if audio.dtype == np.int16:
                audio = audio.astype(np.float32) / 32768.0
            elif audio.dtype != np.float32:
                audio = audio.astype(np.float32)
            
            # Resample if needed
            if sample_rate != 16000:
                audio = self._resample(audio, sample_rate, 16000)
            
            # Pad to minimum frame length if needed
            min_samples = 16000 // 50  # 20ms @ 16kHz = 320 samples
            if len(audio) < min_samples:
                audio = np.pad(audio, (0, min_samples - len(audio)))
            
            # Run inference
            input_name = self.session.get_inputs()[0].name
            output_name = self.session.get_outputs()[0].name
            
            # Model expects 3D input: [batch=1, samples, channels=1]
            input_data = audio.reshape(1, -1, 1).astype(np.float32)
            
            outputs = self.session.run([output_name], {input_name: input_data})
            turn_complete_score = float(outputs[0][0][0])  # [batch, time, prob]
            
            is_complete = turn_complete_score >= threshold
            
            return is_complete
            
        except Exception as e:
            logger.warning(f"⚠️ Turn detection inference failed: {e}. Defaulting to False.")
            return False
    
    def _resample(self, audio: np.ndarray, orig_sr: int, target_sr: int) -> np.ndarray:
        """Simple linear interpolation resampling."""
        if orig_sr == target_sr:
            return audio
        
        ratio = target_sr / orig_sr
        new_length = int(len(audio) * ratio)
        
        # Use numpy's simple linear interpolation
        indices = np.linspace(0, len(audio) - 1, new_length)
        resampled = np.interp(indices, np.arange(len(audio)), audio)
        
        return resampled.astype(np.float32)


# Singleton instance
_turn_detector: Optional[SmartTurnDetectorV2] = None


def get_turn_detector(language: str = "multilingual") -> SmartTurnDetectorV2:
    """Get or create singleton turn detector."""
    global _turn_detector
    if _turn_detector is None:
        _turn_detector = SmartTurnDetectorV2(language=language)
    return _turn_detector
