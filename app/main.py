"""
FastAPI backend for the AI Agent Chatbot.
Provides WebSocket-based real-time communication with the orchestrator.
"""
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path
import sys

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from agents.orchestrator import initialize_orchestrator
from core.config import settings
from app.state import ui_state, AgentStatus

# Configure logging
logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL if hasattr(settings, 'LOG_LEVEL') else 'INFO'),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = FastAPI(title="AI Agent Chatbot", version="2.0.0")

# CORS middleware for development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Templates and static files
templates = Jinja2Templates(directory="app/templates")
app.mount("/static", StaticFiles(directory="app/static"), name="static")

# Global orchestrator
orchestrator = None

# Active WebSocket connections
active_websockets: set[WebSocket] = set()


async def broadcast_event(event: dict):
    """Broadcast an event to all connected WebSocket clients."""
    # Also record event in UI state
    event_type = event.get("type", "log")
    data = event.get("data", {})
    agent = data.get("agent", "System")
    content = data.get("content", data.get("message", ""))
    
    # Map event types for UI state
    type_mapping = {
        "status": "status",
        "thought": "thought", 
        "tool_call_start": "tool_call",
        "tool_call_end": "tool_result",
        "response": "response",
        "error": "error",
        "log": "log"
    }
    
    mapped_type = type_mapping.get(event_type, event_type)
    
    # Update agent status based on event
    if event_type == "status":
        state = data.get("state", "")
        if "thinking" in state.lower():
            ui_state.set_agent_status(agent, AgentStatus.THINKING, data.get("message", ""))
        elif "tool:" in state.lower() or "executing" in state.lower():
            ui_state.set_agent_status(agent, AgentStatus.EXECUTING, data.get("message", ""))
        elif "idle" in state.lower():
            ui_state.set_agent_status(agent, AgentStatus.IDLE)
    
    if event_type == "tool_call_start":
        tool_name = data.get("tool_name", "")
        ui_state.record_tool_use(tool_name)
        content = f"Calling {tool_name}"
    
    if event_type == "tool_call_end":
        tool_name = data.get("tool_name", "")
        success = data.get("success", False)
        content = f"{tool_name}: {'Success' if success else 'Failed'}"
    
    # Record event
    if content:
        recorded_event = ui_state.add_event(mapped_type, agent, str(content)[:500], data)
        event["data"]["event_id"] = recorded_event.id
    
    # Broadcast to all clients
    message = json.dumps(event)
    disconnected = set()
    
    for ws in active_websockets:
        try:
            await ws.send_text(message)
        except Exception as e:
            logger.warning(f"Failed to broadcast to client: {e}")
            disconnected.add(ws)
    
    # Clean up disconnected clients
    for ws in disconnected:
        active_websockets.discard(ws)


@app.on_event("startup")
async def startup_event():
    """Initialize the orchestrator on startup."""
    global orchestrator
    try:
        orchestrator = await initialize_orchestrator()
        orchestrator.set_event_callback(broadcast_event)
        logger.info("Orchestrator initialized and event callback set.")
        
        # Register agents in UI state
        ui_state.register_agent(
            "Orchestrator",
            "Alfred (Orchestrator)",
            "Main coordinator that delegates tasks to specialized agents",
            tools=["CommandLineAgent", "ChromeAgent"]
        )
        ui_state.register_agent(
            "CommandLineAgent", 
            "Terminal Agent",
            "Executes shell commands and manages files",
            tools=["execute_command", "read_file", "write_file", "list_directory"]
        )
        ui_state.register_agent(
            "ChromeAgent",
            "Browser Agent",
            "Controls a web browser via Chrome DevTools",
            tools=["navigate_page", "take_screenshot", "click", "evaluate_script"]
        )
        
        # Register tools in UI state
        ui_state.register_tool(
            "execute_command",
            "Execute a shell command",
            "command: str, timeout: int = 60"
        )
        ui_state.register_tool(
            "read_file",
            "Read contents of a file",
            "path: str"
        )
        ui_state.register_tool(
            "write_file",
            "Write content to a file",
            "path: str, content: str"
        )
        ui_state.register_tool(
            "list_directory",
            "List directory contents",
            "path: str = '.'"
        )
        ui_state.register_tool(
            "navigate_page",
            "Navigate to a URL",
            "url: str"
        )
        ui_state.register_tool(
            "take_screenshot",
            "Take a screenshot of the current page",
            ""
        )
        ui_state.register_tool(
            "click",
            "Click on an element",
            "selector: str"
        )
        ui_state.register_tool(
            "evaluate_script",
            "Run JavaScript in the page",
            "script: str"
        )
        
        # Add initial event
        ui_state.add_event("system", "System", "Orchestrator initialized successfully")
        
    except Exception as e:
        logger.error(f"Failed to initialize orchestrator: {e}")
        from core.engine import ReActContext
        orchestrator = ReActContext(
            name="Orchestrator",
            system_instructions="orchestrator"
        )
        orchestrator.set_event_callback(broadcast_event)
        ui_state.add_event("error", "System", f"Orchestrator initialization failed: {e}")


@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on shutdown."""
    logger.info("Shutting down...")
    
    if orchestrator:
        if hasattr(orchestrator, "close"):
            await orchestrator.close()
            
    for ws in list(active_websockets):
        try:
            await ws.close()
        except Exception:
            pass
    active_websockets.clear()


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """Serve the main chatbot UI."""
    return templates.TemplateResponse("index.j2", {
        "request": request,
        "state": ui_state.get_full_state()
    })


@app.get("/api/state")
async def get_state():
    """Get the complete UI state."""
    return ui_state.get_full_state()


@app.post("/api/theme/toggle")
async def toggle_theme():
    """Toggle light/dark mode."""
    new_theme = ui_state.toggle_theme()
    # Broadcast theme change
    await broadcast_event({
        "type": "theme_change",
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "data": {"theme": new_theme.value}
    })
    return {"theme": new_theme.value}


@app.post("/api/clear/messages")
async def clear_messages():
    """Clear chat messages."""
    ui_state.clear_messages()
    if orchestrator:
        orchestrator.history = []
    await broadcast_event({
        "type": "messages_cleared",
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "data": {}
    })
    return {"status": "cleared"}


@app.post("/api/clear/events")
async def clear_events():
    """Clear event log."""
    ui_state.clear_events()
    await broadcast_event({
        "type": "events_cleared",
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "data": {}
    })
    return {"status": "cleared"}


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "orchestrator": orchestrator is not None,
        "active_connections": len(active_websockets),
        "agents": len(ui_state.agents),
        "tools": len(ui_state.tools)
    }


@app.get("/api/agents")
async def get_agents():
    """Return list of active agents with their status."""
    return {"agents": [a.to_dict() for a in ui_state.agents.values()]}


@app.get("/api/tools")
async def get_tools():
    """Return list of available tools."""
    return {"tools": [t.to_dict() for t in ui_state.tools.values()]}


@app.get("/health/lmstudio")
async def health_lmstudio():
    """Check LM Studio connectivity."""
    from core.inference import check_lmstudio_health
    return await check_lmstudio_health()


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for real-time chat communication."""
    await websocket.accept()
    active_websockets.add(websocket)
    logger.info(f"Client connected. Total connections: {len(active_websockets)}")
    
    try:
        # Send full state on connection
        await websocket.send_json({
            "type": "state_sync",
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "data": ui_state.get_full_state()
        })
        
        ui_state.add_event("system", "System", "Client connected")
        
        while True:
            data = await websocket.receive()
            
            if "text" in data:
                try:
                    msg = json.loads(data["text"])
                except json.JSONDecodeError:
                    msg = {"type": "message", "content": data["text"]}
                
                command = msg.get("type", "message")
                
                if command == "message":
                    user_text = msg.get("content", "")
                    
                    if not user_text:
                        continue
                    
                    # Record user message
                    ui_state.add_message("user", user_text)
                    ui_state.is_processing = True
                    ui_state.current_query = user_text
                    
                    # Add query event
                    ui_state.add_event("query", "User", user_text)
                    
                    # Broadcast user message
                    await broadcast_event({
                        "type": "user_message",
                        "timestamp": datetime.utcnow().isoformat() + "Z",
                        "data": {"content": user_text}
                    })
                    
                    # Update orchestrator status
                    ui_state.set_agent_status("Orchestrator", AgentStatus.THINKING, "Processing query...")
                    
                    await broadcast_event({
                        "type": "status",
                        "timestamp": datetime.utcnow().isoformat() + "Z",
                        "data": {
                            "agent": "Orchestrator",
                            "state": "thinking",
                            "message": "Processing your request..."
                        }
                    })
                    
                    try:
                        # Get response from orchestrator
                        response = await orchestrator.chat(user_text)
                        
                        # Record assistant message
                        ui_state.add_message("assistant", response, "Orchestrator")
                        ui_state.is_processing = False
                        ui_state.current_query = ""
                        
                        # Update agent status
                        ui_state.set_agent_status("Orchestrator", AgentStatus.COMPLETED)
                        
                        # Send final response
                        await broadcast_event({
                            "type": "response",
                            "timestamp": datetime.utcnow().isoformat() + "Z",
                            "data": {
                                "content": response,
                                "agent": "Orchestrator"
                            }
                        })
                        
                        # Reset to idle after a moment
                        await asyncio.sleep(0.5)
                        ui_state.set_agent_status("Orchestrator", AgentStatus.IDLE)
                        ui_state.set_agent_status("CommandLineAgent", AgentStatus.IDLE)
                        
                    except Exception as e:
                        logger.error(f"Orchestrator error: {e}")
                        ui_state.is_processing = False
                        ui_state.set_agent_status("Orchestrator", AgentStatus.ERROR, str(e))
                        ui_state.add_event("error", "Orchestrator", str(e))
                        
                        await broadcast_event({
                            "type": "error",
                            "timestamp": datetime.utcnow().isoformat() + "Z",
                            "data": {
                                "content": f"Error processing request: {str(e)}",
                                "agent": "Orchestrator"
                            }
                        })
                
                elif command == "ping":
                    await websocket.send_json({
                        "type": "pong",
                        "timestamp": datetime.utcnow().isoformat() + "Z"
                    })
                
                elif command == "get_state":
                    await websocket.send_json({
                        "type": "state_sync",
                        "timestamp": datetime.utcnow().isoformat() + "Z",
                        "data": ui_state.get_full_state()
                    })
    
    except WebSocketDisconnect:
        logger.info("Client disconnected normally")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
    finally:
        active_websockets.discard(websocket)
        logger.info(f"Client removed. Total connections: {len(active_websockets)}")


# Run with: uvicorn app.main:app --reload --port 8000
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
