# LocalAgents — Copilot Agent Instructions

Before writing code, read and follow the architecture rules below.
This document is the **single source of truth** for project conventions.

---

## Table of Contents

1. [Non-Negotiables](#non-negotiables)
2. [Project Structure](#project-structure)
3. [Architecture Rules (Layering)](#architecture-rules-layering)
4. [Functional vs Object-Oriented Approach](#functional-vs-object-oriented-approach)
5. [Inference Layer](#inference-layer)
6. [Agent System](#agent-system)
7. [Channels (Communication)](#channels-communication)
8. [Protocol & State](#protocol--state)
9. [Tools / Sub-Agents](#tools--sub-agents)
10. [Adding New Components](#adding-new-components)
11. [Developer Workflow](#developer-workflow)
12. [Before Finishing](#before-finishing)

---

## Non-Negotiables

- **Server-first logic; SSR-first UI.** Templates render initial state; WebSocket pushes live updates.
- **State is server-authoritative** (`app/state.py` → `AppState` singleton).
- **Transport uses** `app/protocol.py::WSMessage` for all WebSocket messages.
- **Do not introduce new frameworks.** The stack is FastAPI + Jinja2 + vanilla JS.
- **Python 3.14+** — use modern syntax (`X | Y` unions, `list[T]` generics).

---

## Project Structure

```
├── core/               # Engine, inference, config, observability — NO app/agents imports
│   ├── config.py       # Pydantic Settings (single `settings` singleton)
│   ├── engine.py       # BaseAgent, ReActAgent, RuntimeObject
│   ├── inference.py    # BaseInference → LMStudioInference, OpenAIInference
│   ├── responses.py    # BaseResponse → ReActResponse, Message
│   ├── observability.py
│   └── tools.py        # MCP tool wrappers
│
├── agents/             # Orchestrator + auto-discovered sub-agents
│   ├── orchestrator.py # Central coordinator (build_orchestrator)
│   ├── utils.py        # Auto-discovery: scans sub_agents/, builds orchestrator
│   └── sub_agents/     # One file per sub-agent
│       ├── command_line_agent.py
│       ├── web_search_agent.py
│       └── chrome_agent.py
│
├── channels/           # Communication adapters (BaseChannel interface)
│   ├── base.py         # Abstract BaseChannel (connect/disconnect/send/broadcast)
│   ├── websocket_channel.py  # Browser WebSocket connections
│   └── telegram_channel.py   # Telegram bot polling adapter
│
├── app/                # Composition root — wires everything together
│   ├── main.py         # FastAPI app, lifespan, routes, WebSocket endpoint
│   ├── protocol.py     # WSMessage types (ChatResponse, StatusUpdate, etc.)
│   ├── state.py        # AppState singleton + OrchestratorQueue
│   ├── modules/        # Runtime integrations (telegram polling, etc.)
│   └── templates/      # Jinja2 SSR templates
│
├── channels/           # Channel implementations
├── experimental/       # macOS bridge, MLX TTS, native STT (unstable)
├── models/             # Local model weights (gitignored)
└── data/               # Observability logs
```

---

## Architecture Rules (Layering)

Strict import direction — violations break the build:

| Package      | May import                             | Must NOT import          |
| ------------ | -------------------------------------- | ------------------------ |
| `utils/`     | stdlib only                            | `core/`, `agents/`, `app/`, `channels/` |
| `core/`      | `utils/`, stdlib                       | `agents/`, `app/`, `channels/` |
| `agents/`    | `core/`, `utils/`                      | `app/`                   |
| `channels/`  | `core/`, `app.modules` (lazy imports)  | `agents/`                |
| `app/`       | everything (composition root)          | —                        |

**Key principle:** dependencies flow inward. `core/` is the innermost layer.

---

## Functional vs Object-Oriented Approach

This codebase uses **both** paradigms with clear boundaries:

### Functional (stateless utilities)
- **Observability** — `log_event()`, `trace_scope()`, `register_sink()` are pure functions.
- **Protocol helpers** — `chat_response()`, `status_update()`, `step_event()` are factory functions.
- **Tool functions** — `execute_command(inputs)`, `web_search(inputs)` are plain callables.

### Object-Oriented (stateful components with lifecycle)
- **Inference** — `BaseInference` → `LMStudioInference`, `OpenAIInference`.
  Provider is resolved once at startup; instance is a singleton.
- **Agents** — `BaseAgent` → `ReActAgent`. Each agent owns its tools map,
  history, and prompt renderer.
- **Channels** — `BaseChannel` → `WebSocketChannel`, `TelegramChannel`.
  Each channel owns its connections and transport logic.
- **State** — `AppState` (Pydantic model), `OrchestratorQueue` (async queue with worker).
- **Runtime objects** — `RuntimeObject` (Pydantic model with `initialize()`/`shutdown()` lifecycle).

**Rule of thumb:** If it has state or lifecycle, make it a class.
If it's a pure transformation, make it a function.

---

## Inference Layer

```
core/inference.py
    BaseInference (ABC)        # Abstract: _call_llm(messages, model) → str
    ├─ LMStudioInference       # OpenAI-compat via local LM Studio server
    └─ OpenAIInference         # Direct OpenAI API

    get_inference() → BaseInference   # Singleton factory (resolved from settings.model_id)
    invoke(...)                       # Module-level convenience (backward compat)
```

### How provider selection works

1. `settings.model_id` is inspected for known prefixes (e.g. `lms/...`).
2. `_REGISTRY` maps prefix → class: `{"lms": LMStudioInference, "openai": OpenAIInference}`.
3. `get_inference()` creates the singleton on first call.

### Adding a new inference provider

1. Subclass `BaseInference` in `core/inference.py`.
2. Implement `_call_llm(self, messages, model) → str`.
3. Add entry to `_REGISTRY`.
4. Done — the rest (async wrapping, multimodal, response parsing) is inherited.

---

## Agent System

```
agents/
    orchestrator.py              # build_orchestrator(extra_agents) → ReActAgent
    utils.py                     # discover_sync_agents(), build_orchestrator_with_all()
    sub_agents/
        command_line_agent.py    # Module-level singleton
        web_search_agent.py      # Module-level singleton
        chrome_agent.py          # Async factory: create_chrome_agent()
```

### Auto-discovery (`agents/utils.py`)

At startup, `build_orchestrator_with_all()`:
1. Scans `agents/sub_agents/*.py` for `BaseAgent` instances (sync agents).
2. Scans for `create_*_agent()` factories (async agents — called with `await`).
3. Combines all discovered agents and passes them to `build_orchestrator()`.

### Adding a new sub-agent

1. Create `agents/sub_agents/my_agent.py`.
2. Export either:
   - A module-level `BaseAgent` instance (for sync agents), **or**
   - An `async def create_my_agent() → ReActAgent` factory (for async init).
3. It will be picked up automatically — **no manual registration needed**.

---

## Channels (Communication)

```
channels/
    base.py                  # BaseChannel (ABC)
    websocket_channel.py     # WebSocketChannel — browser connections
    telegram_channel.py      # TelegramChannel — bot polling
```

### BaseChannel contract

```python
class BaseChannel(ABC):
    name: str                               # "websocket", "telegram"
    async connect(**kwargs) → None
    async disconnect() → None
    async send(payload, **kwargs) → None
    async broadcast(payload, scope?) → None
    async receive() → AsyncIterator[dict]   # optional
```

### Adding a new channel

1. Create `channels/my_channel.py`.
2. Subclass `BaseChannel`, implement all abstract methods.
3. Wire it in `app/main.py` lifespan (connect on startup, disconnect on shutdown).

---

## Protocol & State

### Protocol (`app/protocol.py`)

All WebSocket messages inherit from `WSMessage(type, timestamp, data)`.
Use the factory functions — never construct `WSMessage` directly:

| Factory                       | When to use                    |
| ----------------------------- | ------------------------------ |
| `chat_response(content)`      | Final assistant answer         |
| `status_update(status, detail)` | Processing state change      |
| `step_event(type, content)`   | Activity feed item             |
| `error_event(message)`        | Error notification             |
| `observability_event(event)`  | Raw trace event                |

### State (`app/state.py`)

`AppState` is the **single source of truth** for runtime state:
- `messages` — conversation history
- `events` — system event log
- `observability_events` — trace events
- `is_processing` / `current_query` — UI status
- `active_stt_backend` / `active_tts_backend` — hot-reloadable backend selection

---

## Tools / Sub-Agents

- Tools must follow: `tool(inputs: dict) -> str | awaitable[str]`.
- Sub-agent calls must use `{"query": "..."}` format.
- Tool safety: `command_line_agent` blocks dangerous commands (rm -rf, sudo, dd, etc.).

---

## Adding New Components

| What               | Where                          | Pattern                                |
| ------------------- | ------------------------------ | -------------------------------------- |
| Inference provider  | `core/inference.py`            | Subclass `BaseInference` + registry    |
| Sub-agent           | `agents/sub_agents/*.py`       | Export singleton or `create_*` factory |
| Channel             | `channels/*.py`                | Subclass `BaseChannel`                 |
| Tool function       | Inside sub-agent file          | `def tool(inputs: dict) -> str`        |
| API route           | `app/main.py`                  | FastAPI decorator                      |
| UI page             | `app/templates/*.j2`           | Extend `base.j2` + add route           |

---

## Developer Workflow

### Environment setup
```bash
uv sync                    # Install dependencies
cp .env.example .env       # Configure API keys / model settings
```

### Running the server
```bash
uv run python main.py              # Production
uv run python main.py --reload     # Development with auto-reload
```

### Code quality
```bash
uv run ruff format .               # Format
uv run ruff check .                # Lint
uv run ruff check --fix .          # Auto-fix lint issues
```

### Mandatory Pre-Finish Gate (Required)
Before claiming a task is complete, run this exact sequence in order:

```bash
uv run python -m compileall -q core agents app channels main.py
uv run ruff format .
uv run ruff check .
uv run python main.py --host 127.0.0.1 --port 8000
```

After startup, verify the app is reachable at:
- `http://127.0.0.1:8000/`
- `http://127.0.0.1:8000/sts`

Then stop the app process cleanly.

Do not report a task as completed if any required step above was skipped or failed.

### Key environment variables
| Variable              | Purpose                          | Example                        |
| --------------------- | -------------------------------- | ------------------------------ |
| `MODEL_ID`            | LLM model identifier             | `lms/qwen/qwen3-vl-30b`       |
| `LMS_PROVIDER_URL`    | LM Studio base URL               | `http://127.0.0.1:1234/v1`    |
| `OPENAI_API_KEY`      | OpenAI API key (if using OpenAI) | `sk-...`                       |
| `TELEGRAM_BOT_TOKEN`  | Telegram bot token               | `123456:ABC...`                |
| `LOG_LEVEL`           | Logging verbosity                | `DEBUG`, `INFO`, `WARNING`     |

---

## Before Finishing

Run this required checklist before committing:

```bash
uv run python -m compileall -q core agents app channels main.py
uv run ruff format .
uv run ruff check .
uv run python main.py --host 127.0.0.1 --port 8000
```

Manual happy-path validation is mandatory after app startup:
1. Chat path (`/`): send one message, confirm user message appears, confirm assistant response appears.
2. STS path (`/sts`): mic-based end-to-end flow, speak one request, confirm transcript/user turn appears, confirm assistant response appears.

If STS is blocked by mic/device/permissions, report:
- exact failure reason,
- remediation steps,
- status as blocked/pending manual verification.

Do not mark success in that case.
