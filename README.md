# Alfred (AppleShortcuts) — Your Loyal Digital Butler

*Previously known as AppleShortcuts Runtime.*

This project implements a sophisticated **multi-agent system** orchestrated by **Alfred Pennyworth**, your loyal digital butler. Alfred manages specialized sub-agents to execute complex tasks on your local machine and the web.

## Architecture & Principles

- **Persona-Driven Orchestration**: The entry point is Alfred (Orchestrator), who delegates tasks to specialized workers (The Batfamily).
- **Clean Abstractions**: Built on a unified `BaseContext` offering prompt management, tool execution, and structured response parsing.
- **Strict Typing**: All responses are strictly typed using Pydantic models.
- **Modern Python**: Python 3.14+ with GIL-free threading, f-string templates, and structured concurrency.
- **Minimal Dependencies**: Only Pydantic for data validation and OpenAI client for LLM access.
- **Structured Logging**: Clean, event-based logging for debugging and observability.
- **MCP 3.0 Integration**: FastMCP 3.0 for dynamic tool loading and browser automation.

### The Team

| Agent | Role | Expertise |
|-------|------|-----------|
| **Alfred (Orchestrator)** | Coordinator | Task analysis, delegation, synthesis, user interaction. |
| **CommandLineAgent** | Field Operative | Shell commands, file management, system operations. |
| **ChromeAgent** | Intelligence Gatherer | Web browsing, research, data extraction (via Chrome DevTools MCP). |

## Environment Setup

### Prerequisites

1. **UV** (Rust-based Python package manager):
   - Install: `curl -LsSf https://astral.sh/uv/install.sh | sh`
   - Verify: `uv --version` (should be 0.5+)

2. **Python 3.14+**:
   - UV will manage Python version via `pyproject.toml`
   - Current target: Python 3.14 (free-threaded)
   - Check: `uv python --version`

3. **Local LLM Server**:
   - Example: [LM Studio](https://lmstudio.ai/) or [Ollama](https://ollama.ai/)
   - Required: OpenAI-compatible `/v1` endpoint
   - Default: `http://127.0.0.1:1234/v1`
   - Model: `gpt-oss-20b` or compatible

4. **Browser Automation (Optional)**:
   - Chrome DevTools MCP requires Node.js 18+
   - Installed automatically via `npx chrome-devtools-mcp`

### Installation

```bash
# Clone the repository
git clone https://github.com/yourusername/appleshortcuts.git
cd appleshortcuts

# Install dependencies using UV
# This will fetch Python 3.14+ and all dependencies
uv sync

# Verify installation
uv python --version
uv run main.py --help
```

### Configuration

Set environment variables to override defaults (optional):

```bash
# LLM Configuration
export MODEL_ID="lms/openai/gpt-oss-20b"          # Default model
export LMS_PROVIDER_URL="http://127.0.0.1:1234/v1"  # LLM endpoint
export AGENT_TIMEOUT="300"                         # Timeout in seconds

# Logging
export LOG_LEVEL="INFO"                            # DEBUG, INFO, WARNING, ERROR

# MCP
export MCP_ENABLED="true"                          # Enable MCP toolkit
```

Or modify `core/config.py` for static configuration.

## Running Alfred

### Interactive Mode
```bash
uv run main.py
```
Starts an interactive REPL where you can ask Alfred questions.

### Single Query
```bash
uv run main.py --query "Research the latest news on AI agents"
```
Executes a single query and prints the result.

### Debug Mode
```bash
uv run main.py --debug
```
Enables DEBUG-level logging for detailed execution traces.

### Individual Agents (Testing)
```bash
# Test CommandLineAgent directly
uv run -m team.command_line_agent

# Test ChromeAgent directly
uv run -m team.chrome_agent
```

## Project Structure

```
appleshortcuts/
├── main.py                      # CLI Entrypoint
├── pyproject.toml              # Dependencies & Python version
├── README.md                   # This file
│
├── team/                       # Agent Definitions
│   ├── orchestrator_agent.py   # Alfred initialization & composition
│   ├── command_line_agent.py   # System operations agent
│   └── chrome_agent.py         # Browser automation agent
│
├── core/                       # Framework & Infrastructure
│   ├── engine.py               # BaseContext, ReActContext, ReAct loop
│   ├── responses.py            # Pydantic models & response protocols
│   ├── tools.py                # MCP client, tool formatting, execution
│   ├── inference.py            # OpenAI client wrapper
│   ├── logger.py               # Event-based structured logging
│   ├── config.py               # Centralized configuration
│   └── __init__.py
│
├── prompts/                    # System Instructions (Markdown)
│   ├── orchestrator.md         # Alfred's system prompt
│   ├── command_line_agent.md   # CommandLineAgent prompt
│   ├── chrome_agent.md         # ChromeAgent prompt
│   └── default.md              # Fallback prompt
│
└── __pycache__/                # Python cache (auto-generated)
```

## Development

### Logging

Logs use a clean, event-based format: `[HH:MM:SS] [LEVEL] message`

```python
from core.logger import get_logger

logger = get_logger("MyAgent")
logger.info("Agent started")           # Info level
logger.debug("Detailed trace")         # Debug level (only when --debug)
logger.warning("Unusual condition")   # Warning level
logger.error("Operation failed: {e}") # Error level
```

### Adding New Agents

1. Create `team/my_agent.py`:
   ```python
   from core.engine import ReActContext
   from core.responses import ReActResponse
   from core.config import DEFAULT_MODEL_ID
   
   async def initialize_my_agent():
       agent = ReActContext(
           name="MyAgent",
           description="...",
           system_instructions="my_agent",  # Loads from prompts/my_agent.md
           model_id=DEFAULT_MODEL_ID,
           tools=[...],  # List of tools
           response_model=ReActResponse,
           response_format="json"
       )
       return agent
   ```

2. Create `prompts/my_agent.md` with system instructions.

3. Register in `team/orchestrator_agent.py`:
   ```python
   from team.my_agent import initialize_my_agent
   
   my_agent = await initialize_my_agent()
   my_agent.name = "MyAgent"
   orchestrator = ReActContext(..., tools=[..., my_agent])
   ```

### Response Protocol

All agents follow the `ReActResponse` schema:
- **rephrase**: Restatement of the request
- **reverse**: Internal reasoning / planning
- **action**: `"tool"` or `"answer"`
- **answer**: Tool call (if action=tool) or final response

Supports both JSON and TOON/1 formats (JSON is default).

### Testing the Response Protocol

Run a quick validation:
```bash
uv run python -c "
from core.responses import ReActResponse
schema = ReActResponse.get_instructions()
print(schema)
"
```

## Performance & Threading

- **GIL-Free**: Python 3.14's free-threaded mode allows true parallelism.
- **Async/Await**: All agent invocation is async-first for responsiveness.
- **Parallel Tool Execution**: Multiple tool calls are executed concurrently via `asyncio.gather()`.
- **Token Efficiency**: History is condensed to only tool calls and results, not reasoning artifacts.

## Troubleshooting

### LLM Not Responding
- Ensure local LLM server is running: `curl http://127.0.0.1:1234/v1/models`
- Check `export LMS_PROVIDER_URL="http://127.0.0.1:1234/v1"` is correct
- Logs will show: `LLM invocation failed: ...`

### MCP Connection Issues
- Chrome DevTools MCP requires Node.js 18+: `node --version`
- Logs will show: `Failed to initialize MCP toolkit: ...`
- Run without ChromeAgent: Remove it from `team/orchestrator_agent.py`

### Import Errors
- Verify UV environment: `uv run python --version`
- Rebuild cache: `uv sync --refresh`

---

*"I shall attend to that immediately, Sir."*
