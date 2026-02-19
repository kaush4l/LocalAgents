"""Experimental local audio backends for STS.

Provides warm in-process model singletons for:
- Qwen3-ASR (speech-to-text)
- MLX-TTS (text-to-speech via mlx-audio)

Call ``warmup()`` on each module at server startup to pre-load models.
"""
