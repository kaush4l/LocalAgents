import base64
import logging
from typing import AsyncGenerator, Dict

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import TypeAdapter, ValidationError

from core.interfaces.peripherals import BaseSTTProvider, BaseTTSProvider
from core.schemas.events import (
    ClientEvent,
    ClientEventType,
    ServerErrorEvent,
    ServerEvent,
    ServerAudioEvent,
    ServerStatusEvent,
    ServerTextEvent,
)

logger = logging.getLogger(__name__)

router = APIRouter()

# ----------------------------------------------------------------------
# Mock Components
# ----------------------------------------------------------------------

class MockSTTProvider(BaseSTTProvider):
    async def transcribe(self, audio_bytes: bytes) -> str:
        # Simply return a mock transcription
        return f"Mock transcribed {len(audio_bytes)} bytes of audio."


class MockTTSProvider(BaseTTSProvider):
    async def synthesize(self, text: str) -> bytes:
        # Simply return mock bytes representing the text
        return f"mock_audio_bytes_for: {text}".encode("utf-8")


class MockOrchestrator:
    async def process(self, text: str) -> AsyncGenerator[str, None]:
        """
        Mocks the core LLM / Agent loop.
        Yields status updates first, then the final text.
        """
        yield "thinking"
        yield "tool_running"
        yield f"This is the orchestrator response to: {text}"


# ----------------------------------------------------------------------
# Connection Manager
# ----------------------------------------------------------------------

class ConnectionManager:
    def __init__(self) -> None:
        self.active_connections: Dict[str, WebSocket] = {}
        
        # Injectable pipeline services
        self.stt_provider: BaseSTTProvider = MockSTTProvider()
        self.tts_provider: BaseTTSProvider = MockTTSProvider()
        self.orchestrator = MockOrchestrator()
        
        # Pydantic v2 TypeAdapter for discriminated unions
        self.client_event_adapter = TypeAdapter(ClientEvent)

    async def connect(self, session_id: str, websocket: WebSocket) -> None:
        await websocket.accept()
        self.active_connections[session_id] = websocket
        logger.info(f"Session {session_id} connected")

    def disconnect(self, session_id: str) -> None:
        if session_id in self.active_connections:
            del self.active_connections[session_id]
            logger.info(f"Session {session_id} disconnected")

    async def send_event(self, session_id: str, event: ServerEvent) -> None:
        """Sends a strongly-typed Pydantic ServerEvent over WebSocket."""
        if session_id in self.active_connections:
            websocket = self.active_connections[session_id]
            # Emit standard JSON back to the UI
            await websocket.send_text(event.model_dump_json())


manager = ConnectionManager()


# ----------------------------------------------------------------------
# WebSocket Route
# ----------------------------------------------------------------------

@router.websocket("/ws/session/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str) -> None:
    await manager.connect(session_id, websocket)
    try:
        while True:
            # 1. Wait for ClientEvent
            data = await websocket.receive_text()

            try:
                # 2. Validate the JSON via Pydantic
                client_event = manager.client_event_adapter.validate_json(data)
                
                # Check session mapping
                if getattr(client_event, "session_id", None) != session_id:
                    error_event = ServerErrorEvent(
                        error=f"Session ID mismatch: expected {session_id}, got {client_event.session_id}"
                    )
                    await manager.send_event(session_id, error_event)
                    continue

                text_input = ""

                # 3. If audio is present, route to STT provider to get text
                if client_event.type == ClientEventType.AUDIO:
                    try:
                        audio_bytes = base64.b64decode(client_event.audio_base64)
                        text_input = await manager.stt_provider.transcribe(audio_bytes)
                    except Exception as e:
                        await manager.send_event(
                            session_id, ServerErrorEvent(error=f"STT Error: {str(e)}")
                        )
                        continue
                elif client_event.type == ClientEventType.TEXT:
                    text_input = client_event.text
                elif client_event.type == ClientEventType.SYSTEM:
                    text_input = f"<system_command> {client_event.command}"

                # 4. Pass the text to Orchestrator, Stream ServerEvents back
                async for chunk in manager.orchestrator.process(text_input):
                    # We arbitrarily decide that "thinking" and "tool_running" are statuses
                    if chunk in ("thinking", "tool_running"):
                        await manager.send_event(
                            session_id, ServerStatusEvent(status=chunk)
                        )
                    else:
                        # Full text response
                        await manager.send_event(
                            session_id, ServerTextEvent(text=chunk)
                        )

                        # Provide binary audio (TTS) as part of pipeline
                        try:
                            audio_output_bytes = await manager.tts_provider.synthesize(chunk)
                            b64_audio = base64.b64encode(audio_output_bytes).decode("utf-8")
                            await manager.send_event(
                                session_id, ServerAudioEvent(audio_base64=b64_audio)
                            )
                        except Exception as e:
                            logger.error(f"TTS Synthesis failed: {e}")
                            # Audio isn't strictly fatal, could just log or send an error event
                            # depending on strictness requirements.

            except ValidationError as e:
                # Invalid JSON structure or missing fields
                await manager.send_event(
                    session_id, ServerErrorEvent(error=f"Invalid event schema: {str(e)}")
                )

    except WebSocketDisconnect:
        manager.disconnect(session_id)
    except Exception as e:
        logger.error(f"Unexpected error in websocket for {session_id}: {e}")
        manager.disconnect(session_id)
