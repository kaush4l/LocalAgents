# Alfred AI - Local Agent Orchestrator

Alfred is a high-performance local AI assistant platform featuring a real-time "Neural Link" HUD, ReAct orchestration, and direct system integration. It allows you to interact with multiple specialized agents through a unified web interface.

## 🚀 Features

- **Neural Link HUD**: A sophisticated 3-column web interface for real-time interaction.
  - **Agents Panel**: Monitor status and active tools for all workers.
  - **Live Messages**: Persistent chat interface with the Orchestrator.
  - **Events Stream**: Real-time visibility into the agent's thoughts, tool calls, and results.
- **ReAct Orchestration**: Intelligent task planning and delegation using the ReAct (Reasoning + Acting) pattern.
- **Specialized Agents**:
  - **Orchestrator (Alfred)**: The main brain that handles planning and coordination.
  - **CommandLineAgent**: Full access to the local system for file management and shell commands.
  - **ChromeAgent**: Web automation using Chrome DevTools (MCP).
- **Extensible Toolkit**: Easy integration with Model Context Protocol (MCP) servers.

## ⚡️ Quick Start

### Prerequisites

- Python 3.14+
- A local or remote LLM provider (Ollama, LM Studio, or OpenAI-compatible API)
- [uv](https://github.com/astral-sh/uv) (recommended) or pip

### Installation

1. **Clone the repository** (if you haven't already):
   ```bash
   git clone <repository-url>
   cd AppleShortcuts
   ```

2. **Sync dependencies**:
   Using `uv`:
   ```bash
   uv sync
   ```
   Or using `pip`:
   ```bash
   pip install -r requirements.txt
   ```

3. **Configure Environment**:
   Create a `.env` file (see `core/config.py` for available settings).
   ```env
   MODEL_ID=gpt-4o-mini # or your local model
   LOG_LEVEL=INFO
   ```

### Running the System

Start the unified backend and UI:

```bash
python main.py
```

For development with auto-reload:
```bash
python main.py --reload
```

Open [http://localhost:8000](http://localhost:8000) in your browser to access the HUD.

## 🏗 Architecture

The project follows a modular architecture:

- **Frontend**: Server-Side Rendered (Jinja2) with vanilla JavaScript and WebSocket streaming for low latency.
- **Backend**: FastAPI for the web server and WebSocket management.
- **Agent Core**: 
  - `ReActContext`: The engine that drives the reasoning and tool execution loop.
  - `MCPToolkit`: Integration layer for Model Context Protocol servers.

## 📁 Project Structure

```text
├── agents/             # Specialized agent implementations
│   ├── orchestrator.py    # Main coordinator
│   ├── command_line_agent.py
│   └── chrome_agent.py
├── app/                # FastAPI application
│   ├── main.py            # API and WebSocket routes
│   ├── state.py           # UI state management
│   ├── templates/         # Jinja2 HTML templates
│   └── static/            # Static assets
├── core/               # Core logic and engine
│   ├── engine.py          # ReAct execution engine
│   ├── tools.py           # Tool registration and MCP logic
│   ├── config.py          # Settings and environment
│   └── workers/           # Background processing threads
├── prompts/            # System instructions for agents
└── tests/              # Test suite
```

## 🔌 Requirements

- **Chrome Automation**: Requires `npx` and `chrome-devtools-mcp` (automatic via agents).
- **Transcription**: Requires `mlx` and `mlx-audio` for local Apple Silicon acceleration.
