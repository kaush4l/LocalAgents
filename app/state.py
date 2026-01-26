"""
Server-side state management for the UI.
Stores user preferences, agent states, and event history.
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Any
from enum import Enum
import json


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
class AgentState:
    id: str
    name: str
    description: str
    status: AgentStatus = AgentStatus.IDLE
    current_task: str = ""
    tools: list = field(default_factory=list)
    
    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "status": self.status.value,
            "current_task": self.current_task,
            "tools": self.tools
        }


@dataclass
class ToolState:
    name: str
    description: str
    parameters: str
    call_count: int = 0
    last_used: str | None = None
    
    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
            "call_count": self.call_count,
            "last_used": self.last_used
        }


@dataclass
class Event:
    id: int
    type: str  # query, thought, tool_call, tool_result, response, error
    timestamp: str
    agent: str
    content: str
    metadata: dict = field(default_factory=dict)
    
    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "type": self.type,
            "timestamp": self.timestamp,
            "agent": self.agent,
            "content": self.content,
            "metadata": self.metadata
        }


@dataclass 
class Message:
    id: int
    role: Literal["user", "assistant", "system"]
    content: str
    timestamp: str
    agent: str | None = None
    
    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "role": self.role,
            "content": self.content,
            "timestamp": self.timestamp,
            "agent": self.agent
        }


class UIState:
    """Global UI state manager - stores all state server-side."""
    
    def __init__(self):
        self.theme: ThemeMode = ThemeMode.DARK
        self.sidebar_open: bool = True
        self.events_panel_open: bool = True
        
        # Agent registry
        self.agents: dict[str, AgentState] = {}
        self.active_agent: str | None = None
        
        # Tool registry
        self.tools: dict[str, ToolState] = {}
        
        # Event log (limited to last 100)
        self.events: list[Event] = []
        self.event_counter: int = 0
        
        # Chat messages
        self.messages: list[Message] = []
        self.message_counter: int = 0
        
        # Processing state
        self.is_processing: bool = False
        self.current_query: str = ""
    
    def register_agent(self, agent_id: str, name: str, description: str, tools: list = None):
        """Register an agent with the UI state."""
        self.agents[agent_id] = AgentState(
            id=agent_id,
            name=name,
            description=description,
            tools=tools or []
        )
    
    def register_tool(self, name: str, description: str, parameters: str = ""):
        """Register a tool with the UI state."""
        self.tools[name] = ToolState(
            name=name,
            description=description,
            parameters=parameters
        )
    
    def set_agent_status(self, agent_id: str, status: AgentStatus, task: str = ""):
        """Update an agent's status."""
        if agent_id in self.agents:
            self.agents[agent_id].status = status
            self.agents[agent_id].current_task = task
            if status in [AgentStatus.THINKING, AgentStatus.EXECUTING]:
                self.active_agent = agent_id
            elif status in [AgentStatus.COMPLETED, AgentStatus.IDLE]:
                if self.active_agent == agent_id:
                    self.active_agent = None
    
    def record_tool_use(self, tool_name: str):
        """Record that a tool was used."""
        if tool_name in self.tools:
            self.tools[tool_name].call_count += 1
            self.tools[tool_name].last_used = datetime.utcnow().isoformat() + "Z"
    
    def add_event(self, event_type: str, agent: str, content: str, metadata: dict = None) -> Event:
        """Add an event to the log."""
        self.event_counter += 1
        event = Event(
            id=self.event_counter,
            type=event_type,
            timestamp=datetime.utcnow().isoformat() + "Z",
            agent=agent,
            content=content,
            metadata=metadata or {}
        )
        self.events.append(event)
        # Keep only last 100 events
        if len(self.events) > 100:
            self.events = self.events[-100:]
        return event
    
    def add_message(self, role: str, content: str, agent: str = None) -> Message:
        """Add a chat message."""
        self.message_counter += 1
        message = Message(
            id=self.message_counter,
            role=role,
            content=content,
            timestamp=datetime.utcnow().isoformat() + "Z",
            agent=agent
        )
        self.messages.append(message)
        return message
    
    def clear_messages(self):
        """Clear all chat messages."""
        self.messages = []
        self.add_event("system", "System", "Chat history cleared")
    
    def clear_events(self):
        """Clear event log."""
        self.events = []
        self.event_counter = 0
    
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
            "agents": {k: v.to_dict() for k, v in self.agents.items()},
            "active_agent": self.active_agent,
            "tools": {k: v.to_dict() for k, v in self.tools.items()},
            "events": [e.to_dict() for e in self.events[-50:]],  # Last 50 events
            "messages": [m.to_dict() for m in self.messages],
            "is_processing": self.is_processing,
            "current_query": self.current_query
        }


# Global UI state instance
ui_state = UIState()
