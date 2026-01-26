import queue
import threading
import logging
import numpy as np
try:
    import mlx.core as mx
    from mlx_audio.stt.utils import load_model
    MLX_AVAILABLE = True
except ImportError:
    MLX_AVAILABLE = False

logger = logging.getLogger(__name__)

class TranscriberWorker(threading.Thread):
    def __init__(self, audio_queue: queue.Queue, result_callback):
        super().__init__(daemon=True)
        self.audio_queue = audio_queue
        self.result_callback = result_callback
        self.model = None
        self.model_id = "animaslabs/parakeet-tdt-0.6b-v3-mlx-8bit"

    def _load_model(self):
        if not MLX_AVAILABLE:
            logger.error("MLX or mlx-audio not installed. Transcription disabled.")
            return

        logger.info(f"Loading transcription model: {self.model_id}")
        try:
            self.model = load_model(self.model_id)
            logger.info("Transcription model loaded successfully.")
        except Exception as e:
            logger.error(f"Error loading transcription model: {e}")

    def run(self):
        if not MLX_AVAILABLE:
            return

        self._load_model()
        if not self.model:
            return
        
        # Buffer to accumulate audio
        audio_buffer = np.array([], dtype=np.float32)
        sample_rate = 16000 # Parakeet standard
        
        while True:
            try:
                audio_chunk = self.audio_queue.get()
                if audio_chunk is None:
                    break
                
                # Convert bytes (assuming 16-bit PCM) to float32
                new_data = np.frombuffer(audio_chunk, dtype=np.int16).astype(np.float32) / 32768.0
                audio_buffer = np.concatenate([audio_buffer, new_data])
                
                # Process if we have more than 0.5 seconds of audio
                if len(audio_buffer) >= (sample_rate * 0.5):
                    # Convert to mlx array
                    mx_audio = mx.array(audio_buffer)
                    
                    # Use decode_chunk for low-latency feedback
                    result = self.model.decode_chunk(mx_audio)
                    
                    if result and result.text.strip():
                        self.result_callback(result.text.strip())
                        # Clear buffer after successful transcription
                        audio_buffer = np.array([], dtype=np.float32)
                    
                    # Prevent buffer from growing infinitely
                    if len(audio_buffer) > (sample_rate * 10):
                        audio_buffer = np.array([], dtype=np.float32)

            except Exception as e:
                logger.error(f"Transcription error: {e}")
            finally:
                self.audio_queue.task_done()
