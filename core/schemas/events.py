from enum import Enum
from typing import Any, Dict, Literal, Optional, Union, Annotated

from pydantic import BaseModel, ConfigDict, Field


class ClientEventType(str, Enum):
    TEXT = "text"
    AUDIO = "audio"
    SYSTEM = "system"


class BaseClientEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_id: str


class ClientTextEvent(BaseClientEvent):
    type: Literal[ClientEventType.TEXT] = ClientEventType.TEXT
    text: str


class ClientAudioEvent(BaseClientEvent):
    type: Literal[ClientEventType.AUDIO] = ClientEventType.AUDIO
    audio_base64: str


class ClientSystemEvent(BaseClientEvent):
    type: Literal[ClientEventType.SYSTEM] = ClientEventType.SYSTEM
    command: str
    payload: Optional[Dict[str, Any]] = None


ClientEvent = Annotated[
    Union[ClientTextEvent, ClientAudioEvent, ClientSystemEvent], Field(discriminator="type")
]


class ServerEventType(str, Enum):
    STATUS = "status"
    TOKEN = "token"
    TEXT = "text"
    AUDIO = "audio"
    ERROR = "error"


class BaseServerEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pass


class ServerStatusEvent(BaseServerEvent):
    type: Literal[ServerEventType.STATUS] = ServerEventType.STATUS
    status: str  # e.g., "thinking", "tool_running"
    details: Optional[Dict[str, Any]] = None


class ServerTokenEvent(BaseServerEvent):
    type: Literal[ServerEventType.TOKEN] = ServerEventType.TOKEN
    token: str


class ServerTextEvent(BaseServerEvent):
    type: Literal[ServerEventType.TEXT] = ServerEventType.TEXT
    text: str


class ServerAudioEvent(BaseServerEvent):
    type: Literal[ServerEventType.AUDIO] = ServerEventType.AUDIO
    audio_base64: str


class ServerErrorEvent(BaseServerEvent):
    type: Literal[ServerEventType.ERROR] = ServerEventType.ERROR
    error: str


# Create the union type for parsing/dumping
ServerEvent = Annotated[
    Union[ServerStatusEvent, ServerTokenEvent, ServerTextEvent, ServerAudioEvent, ServerErrorEvent],
    Field(discriminator="type"),
]
