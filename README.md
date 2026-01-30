# LocalAgents - Multi-Agent Orchestration System

A modular, extensible multi-agent system built on the **Observe-Plan-Act** reasoning pattern. Agents delegate tasks, execute tools, and synthesize results through a unified architecture.

## 🚀 Quick Start

### Prerequisites

- Python 3.14+
- [uv](https://github.com/astral-sh/uv) package manager
- A local or remote LLM provider (Ollama, LM Studio, or OpenAI-compatible API)

### Installation

```bash
# Clone and enter the project
git clone <repository-url>
cd LocalAgents

# Sync dependencies with uv
uv sync
```

### Configuration

Create a `.env` file in the project root:

```env
MODEL_ID=gpt-4o-mini        # Your model identifier
BASE_URL=http://localhost:1234/v1  # LLM API endpoint (optional)
API_KEY=your-api-key        # API key if required
LOG_LEVEL=INFO              # DEBUG, INFO, WARNING, ERROR
MAX_ITERATIONS=10           # Max reasoning loops per request
```

### Running

```bash
# Start the application
uv run python main.py

# With auto-reload for development
uv run python main.py --reload
```

Open [http://localhost:8000](http://localhost:8000) to access the Neural Link HUD.

---

## 🏗 Architecture Overview

### Core Components

```
┌─────────────────────────────────────────────────────────────────┐
│                         ORCHESTRATOR                             │
│  (ReActContext - coordinates all sub-agents)                     │
└──────────────┬───────────────────────────┬──────────────────────┘
               │                           │
               ▼                           ▼
┌──────────────────────────┐   ┌───────────────────────────────────┐
│  command_line_agent      │   │  chrome_agent                     │
│  (function tools)        │   │  (MCP tools)                      │
│  └─ execute_command()    │   │  └─ navigate_page()               │
└──────────────────────────┘   │  └─ click()                       │
                               │  └─ take_screenshot()              │
                               └───────────────────────────────────┘
```

### Observe-Plan-Act Loop

Every agent response follows this structured reasoning pattern:

```json
{
    "observation": "What do I see? Current context, tool results, constraints.",
    "plan": ["Step 1: ...", "Step 2: ...", "Step 3: ..."],
    "action": "tool",
    "response": "tool_name({\"param\": \"value\"})"
}
```

| Field | Purpose |
|-------|---------|
| `observation` | Analyze current state, previous results, conversation context |
| `plan` | 2-5 concrete, actionable steps to achieve the goal |
| `action` | Either `"tool"` (invoke a tool) or `"answer"` (final response) |
| `response` | Tool invocation string OR final answer to user |

**Memory Rule**: Only `action` and `response` are preserved in conversation history. The `observation` and `plan` fields are discarded after each turn to reduce context size.

---

## 📁 Project Structure

```
LocalAgents/
├── agents/                    # Agent implementations
│   ├── orchestrator.py           # Main coordinator agent
│   ├── command_line_agent.py     # Shell command execution
│   └── chrome_agent.py           # Browser automation (MCP)
├── core/                      # Core engine and utilities
│   ├── engine.py                 # ReActContext, BaseContext classes
│   ├── responses.py              # Observe-Plan-Act response model
│   ├── tools.py                  # Tool utilities, MCPToolkit
│   ├── config.py                 # Environment configuration
│   └── inference.py              # LLM invocation layer
├── prompts/                   # Agent system prompts & templates
│   ├── orchestrator.md           # Orchestrator identity & guidelines
│   ├── command_line_agent.md     # CLI agent identity & guidelines
│   ├── chrome_agent.md           # Browser agent identity & guidelines
│   ├── default.md                # Fallback prompt
│   ├── render_template.j2        # Master prompt assembly template
│   └── tools_instructions.j2     # Tool documentation template
├── app/                       # FastAPI web application
│   ├── main.py                   # Routes and WebSocket handlers
│   ├── state.py                  # UI state management
│   ├── templates/                # Jinja2 HTML templates
│   └── static/                   # CSS, JS assets
└── tests/                     # Test suite
```

---

## 🛠 Development Guide

### Creating a New Agent

Follow these steps to add a new specialized agent:

#### 1. Create the Agent File

Create `agents/my_agent.py`:

```python
"""
My Agent - Description of what this agent does.
"""
from core.engine import ReActContext
from core.responses import ReActResponse
from core import config

# Define tools (functions or MCP tools)
from core.tools import execute_command  # or your custom tools

tools = [execute_command]

# Initialize the agent
my_agent = ReActContext(
    name="my_agent",                    # MUST match prompt filename
    description="Brief description used when this agent is a tool for others.",
    system_instructions="my_agent",     # Loads prompts/my_agent.md
    model_id=config.MODEL_ID,
    tools=tools,
    response_model=ReActResponse,
    response_format="json",
    max_iterations=config.MAX_ITERATIONS,
)
```

#### 2. Create the Prompt File

Create `prompts/my_agent.md`:

```markdown
# My Agent

You are a specialized agent for [domain]. Your purpose is to [primary function].

## Your Identity

- **Name**: [Descriptive Name]
- **Role**: [Role Description]
- **Expertise**: [List of capabilities]

## Guidelines

### [Category 1]
- Guideline 1
- Guideline 2

### [Category 2]
- Guideline 3
- Guideline 4

## Behavior Guidelines

- **Be [Trait]**: Description
- **Be [Trait]**: Description
```

**Important**: Do NOT include tool call formats or response structures in the prompt file. These are injected dynamically by the template system.

#### 3. Register with Orchestrator (if needed)

Update `agents/orchestrator.py` to include your agent:

```python
from .my_agent import my_agent

orchestrator = ReActContext(
    ...
    tools=[command_line_agent, chrome_agent, my_agent],
    ...
)
```

#### 4. For MCP-Based Agents

If your agent uses MCP tools:

```python
from core.tools import get_mcp_toolkit, format_tool_for_engine

async def _setup_my_agent():
    server_config = {
        "command": "npx",
        "args": ["-y", "my-mcp-server"]
    }
    
    toolkit = get_mcp_toolkit(server_config)
    await toolkit.initialize()
    
    selected_tools = toolkit.get_tools(["tool1", "tool2"])
    formatted_tools = [format_tool_for_engine(t) for t in selected_tools]
    
    agent = ReActContext(
        name="my_agent",
        tools=formatted_tools,
        ...
    )
    
    # Register the MCP toolkit
    agent.set_mcp_toolkit(toolkit)
    agent.register_cleanup(toolkit.close)
    
    return agent
```

---

## 📋 Design Rules & Guidelines

### Naming Conventions

| Item | Convention | Example |
|------|------------|---------|
| Agent name | `snake_case` | `command_line_agent` |
| Prompt file | `{agent_name}.md` | `command_line_agent.md` |
| Agent variable | Same as name | `command_line_agent = ReActContext(...)` |

### Prompt/Template Separation

| Component | Location | Contains |
|-----------|----------|----------|
| **Agent Identity** | `prompts/{agent}.md` | Personality, capabilities, behavioral guidelines |
| **Tool Instructions** | `prompts/tools_instructions.j2` | Tool names, parameters, invocation syntax |
| **Response Format** | `core/responses.py` | JSON schema, field descriptions |
| **Assembly** | `prompts/render_template.j2` | Combines all components into final prompt |

**Key Rule**: Prompt files should NOT know about tools or response formats. These are injected dynamically.

### Tool Registry Pattern

The engine maintains a unified tool registry: `{tool_name: invoke_function}`

| Tool Type | Detection | Invocation |
|-----------|-----------|------------|
| **Agent (sub-agent)** | `isinstance(t, BaseContext)` | `await agent.invoke(query)` |
| **MCP Tool** | `isinstance(t, dict)` with `mcp_tool` | `await toolkit.call_tool(name, args)` |
| **Function** | `callable(t)` | `await func(**args)` or `func(**args)` |

### Parallel Tool Execution

Multiple tool calls on separate lines execute concurrently:

```json
{
    "action": "tool",
    "response": "tool_a({\"x\": 1})\ntool_b({\"y\": 2})"
}
```

### Memory Management

1. **History Preservation**: Only `action` + `response` go into history
2. **Sub-agent Capping**: Non-orchestrator agents cap history at 10 items
3. **Condensed Format**: `[action=tool] tool_call_preview...`

---

## 🔄 Expected Flow

### 1. User Request → Orchestrator

```
User: "List all Python files and count lines of code"
     ↓
Orchestrator receives request
```

### 2. Orchestrator Observe-Plan-Act

```json
{
    "observation": "User wants to find Python files and count LOC.",
    "plan": [
        "1. Delegate file search to command_line_agent",
        "2. Parse results to count lines",
        "3. Synthesize final answer"
    ],
    "action": "tool",
    "response": "command_line_agent({\"query\": \"Find all .py files recursively and count total lines of code\"})"
}
```

### 3. Sub-Agent Execution

```
command_line_agent receives: "Find all .py files..."
     ↓
Runs execute_command({"command": "find . -name '*.py' | xargs wc -l"})
     ↓
Returns result to orchestrator
```

### 4. Orchestrator Synthesizes

```json
{
    "observation": "command_line_agent returned: 1,234 total lines across 15 files",
    "plan": ["Format the result for the user"],
    "action": "answer",
    "response": "Found 15 Python files with 1,234 total lines of code."
}
```

---

## 🧪 Testing

```bash
# Run all tests
uv run pytest

# Run specific test file
uv run pytest tests/test_ws.py

# Verify orchestrator setup
uv run python tests/verify_orchestrator.py
```

---

## 📚 API Reference

### ReActContext

```python
ReActContext(
    name: str,                    # Agent identifier (matches prompt file)
    description: str,             # Tool description when used by other agents
    system_instructions: str,     # Prompt file name (without .md)
    model_id: str,                # LLM model identifier
    tools: list,                  # List of tools (functions, dicts, or agents)
    response_model: type,         # Response class (default: ReActResponse)
    response_format: str,         # "json" or "toon"
    max_iterations: int,          # Max reasoning loops
)
```

**Key Methods**:
- `await agent.invoke(query)` - Run the Observe-Plan-Act loop
- `await agent.chat(query, history)` - Chat interface with history
- `agent.set_mcp_toolkit(toolkit)` - Register MCP toolkit for MCP tools
- `agent.register_cleanup(callback)` - Register cleanup function
- `await agent.close()` - Clean up resources

### ReActResponse

```python
ReActResponse(
    observation: str,             # Current context analysis
    plan: list[str],              # Reasoning steps
    action: Literal["tool", "answer"],
    response: str,                # Tool call or final answer
)
```

---

## 🔌 Requirements

- **Chrome Automation**: Requires `npx` and `chrome-devtools-mcp`
- **LLM Provider**: Any OpenAI-compatible API endpoint
