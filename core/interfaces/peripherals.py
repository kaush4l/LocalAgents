from abc import ABC, abstractmethod


class BaseSTTProvider(ABC):
    """Abstract base class for Speech-to-Text inference."""

    @abstractmethod
    async def transcribe(self, audio_bytes: bytes) -> str:
        """
        Transcribes binary audio data into a string of text.

        Args:
            audio_bytes (bytes): The raw audio bytes from the client.

        Returns:
            str: The transcribed text.
        """
        pass


class BaseTTSProvider(ABC):
    """Abstract base class for Text-to-Speech synthesis."""

    @abstractmethod
    async def synthesize(self, text: str) -> bytes:
        """
        Synthesizes text into binary audio data.

        Args:
            text (str): The text to be converted to speech.

        Returns:
            bytes: The synthesized audio bytes.
        """
        pass
