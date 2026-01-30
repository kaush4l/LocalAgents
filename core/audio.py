"""
Mock audio transcription worker for testing without actual audio transcription.
"""
import logging

logger = logging.getLogger(__name__)


class TranscriptionWorker:
    """Mock transcription worker."""
    
    def __init__(self):
        self.status = "idle"
        self.model_path = "mock-model"
        self._running = False
    
    def start(self):
        """Start the worker."""
        self._running = True
        logger.info("TranscriptionWorker started (mock)")
    
    def stop(self):
        """Stop the worker."""
        self._running = False
        logger.info("TranscriptionWorker stopped (mock)")
    
    def preload_models(self, models):
        """Preload models."""
        logger.info(f"Preloading models: {models}")
    
    def get_result(self):
        """Get transcription result."""
        return None
    
    def push_audio(self, data):
        """Push audio data for transcription."""
        pass
    
    def set_model(self, model_id):
        """Set the transcription model."""
        self.model_path = model_id


# Global instance
transcription_worker = TranscriptionWorker()
