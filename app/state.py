"""
Server-side state management for the UI.
Stores user preferences, agent states, and event history.
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Any
from enum import Enum
import json
from core.responses import Message


class ThemeMode(str, Enum):
    LIGHT = "light"
    DARK = "dark"


class AgentStatus(str, Enum):
    IDLE = "idle"
    THINKING = "thinking"
    EXECUTING = "executing"
    COMPLETED = "completed"
    ERROR = "error"


@dataclass
class Event:
    type: str  # query, thought, tool_call, tool_result, response, error, status, log
    timestamp: str
    content: str
    metadata: dict = field(default_factory=dict)
    
    def to_dict(self) -> dict:
        return {
            "type": self.type,
            "timestamp": self.timestamp,
            "content": self.content,
            "metadata": self.metadata
        }


# The Message class is now imported from core.responses


class UIState:
    """Global UI state manager - stores all state server-side."""
    
    def __init__(self):
        self.theme: ThemeMode = ThemeMode.DARK
        self.sidebar_open: bool = True
        self.events_panel_open: bool = True
        
        # Event log (limited to last 100)
        self.events: list[Event] = []
        
        # Chat messages
        self.messages: list[Message] = []
        
        # Processing state
        self.is_processing: bool = False
        self.current_query: str = ""
    
    def add_event(self, event_type: str, content: str, metadata: dict = None) -> Event:
        """Add an event to the log."""
        event = Event(
            type=event_type,
            timestamp=datetime.utcnow().isoformat() + "Z",
            content=content,
            metadata=metadata or {}
        )
        self.events.append(event)
        # Keep only last 100 events
        if len(self.events) > 100:
            self.events = self.events[-100:]
        return event
    
    def add_message(self, role: str, content: str) -> Message:
        """Add a chat message."""
        message = Message(
            role=role,
            content=content
        )
        self.messages.append(message)
        return message
    
    def clear_messages(self):
        """Clear all chat messages."""
        self.messages = []
        self.add_event("system", "Chat history cleared")
    
    def clear_events(self):
        """Clear event log."""
        self.events = []
    
    def toggle_theme(self) -> ThemeMode:
        """Toggle between light and dark mode."""
        self.theme = ThemeMode.LIGHT if self.theme == ThemeMode.DARK else ThemeMode.DARK
        return self.theme
    
    def get_full_state(self) -> dict:
        """Get the complete UI state as a dictionary."""
        return {
            "theme": self.theme.value,
            "sidebar_open": self.sidebar_open,
            "events_panel_open": self.events_panel_open,
            "events": [e.to_dict() for e in self.events[-50:]],  # Last 50 events
            "messages": [m.model_dump() for m in self.messages],
            "is_processing": self.is_processing,
            "current_query": self.current_query
        }


# Global UI state instance
ui_state = UIState()
