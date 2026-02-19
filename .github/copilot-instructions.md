# LocalAgents — Copilot Agent Instructions

Before writing code, read and follow the architecture rules below.
This document is the **single source of truth** for project conventions.

---

## Table of Contents

1. [Non-Negotiables](#non-negotiables)
2. [Design Philosophy](#design-philosophy)
3. [Project Structure](#project-structure)
4. [Architecture Rules (Layering)](#architecture-rules-layering)
5. [Functional vs Object-Oriented Approach](#functional-vs-object-oriented-approach)
6. [Inference Layer](#inference-layer)
7. [Agent System](#agent-system)
8. [STS / STT / TTS Layer](#sts--stt--tts-layer)
9. [Channels (Communication)](#channels-communication)
10. [Protocol & State](#protocol--state)
11. [Tools / Sub-Agents](#tools--sub-agents)
12. [Model Bootstrap](#model-bootstrap)
13. [Adding New Components](#adding-new-components)
14. [Developer Workflow](#developer-workflow)
15. [Before Finishing](#before-finishing)

---

## Non-Negotiables

- **Server-first logic; SSR-first UI.** Templates render initial state; WebSocket pushes live updates.
- **State is server-authoritative** (`app/state.py` → `AppState` singleton).
- **Transport uses** `app/protocol.py` factory functions for all WebSocket messages. Never construct `WSMessage` directly.
- **Do not introduce new frameworks.** The stack is FastAPI + Jinja2 + vanilla JS.
- **Python 3.14+** — use modern syntax (`X | Y` unions, `list[T]` generics, `match` statements).
- **No app-layer imports in core.** `core/` must never import from `agents/`, `app/`, or `channels/`.
- **Models are not in git.** All HuggingFace weights live in `models/` (gitignored) and are auto-downloaded at startup via `huggingface_hub`.

---

## Design Philosophy

> Lines of code are a liability, not an asset. Every line must map to an abstract concept. Prefer fewer, more expressive lines over many narrow ones.

**The three-layer pattern for every subsystem:**

```
Abstract (ABC)          — defines the contract, zero implementation detail
Implementation          — one concrete class per provider/backend
Registry / Factory      — selects the right implementation at runtime
```

Examples already in the codebase:
- `BaseInference` → `OpenAIInference` → `get_implementation(model_id)`
- `AudioTranscriberBaseModel` → `WhisperAPITranscriber`, `MacOSNativeBridgeTranscriber` → `STTRegistry`
- `SpeechSynthesizerBaseModel` → `Qwen3TTSSynthesizer` → `TTSRegistry`
- `BaseChannel` → `WebSocketChannel`, `TelegramChannel`
- `BaseAgent` → `ReActAgent`

**Keep technical constraints updatable.** Version pins, model IDs, and backend IDs must all be overridable via environment variables. Never hardcode deployment details in logic.

---

## Project Structure

```
main.py                       # CLI entry — argparse, load_dotenv, uvicorn
├── app/                      # Composition root
│   ├── main.py               # FastAPI app, lifespan, all routes + WS endpoint
│   ├── protocol.py           # WSMessage + factory functions
│   ├── state.py              # AppState singleton + OrchestratorQueue
│   ├── modules/              # Runtime integrations (telegram.py)
│   └── templates/            # Jinja2 SSR templates (base, chat, sts, …)
├── agents/                   # Orchestrator + sub-agents
│   ├── orchestrator.py       # _SUB_AGENTS list → build_orchestrator() → singleton
│   ├── prompts/              # One .md file per agent (system instructions)
│   └── sub_agents/           # command_line_agent, web_search_agent, chrome_agent, self_agent
├── channels/                 # Transport adapters
│   ├── base.py               # BaseChannel ABC
│   ├── websocket_channel.py  # WebSocketChannel
│   └── telegram_channel.py   # TelegramChannel
└── core/                     # Inner layer — no app/ or agents/ imports
    ├── engine.py             # BaseAgent, ReActAgent, RuntimeObject
    ├── inference.py          # BaseInference → OpenAIInference, provider registry
    ├── responses.py          # BaseResponse → ReActResponse, Message
    ├── observability.py      # Pure-function event log + pluggable sinks
    ├── tools.py              # MCP tool wrappers
    ├── utils.py              # Shared pure utilities
    ├── logging_core.py       # Logging configuration
    ├── sts.py                # STSService facade (STT → LLM → TTS)
    ├── sts_models.py         # Shared Pydantic models: request/result/error
    ├── sts_ffmpeg.py         # ffprobe audio probing helpers
    ├── stt.py                # STTService (default backend, list, health)
    ├── stt_backends.py       # AudioTranscriberBaseModel + concrete backends
    ├── stt_registry.py       # STTRegistry (RuntimeObject)
    ├── tts.py                # TTSService (default backend, speak, health)
    ├── tts_backends.py       # SpeechSynthesizerBaseModel + LocalModelSynthesizerBase + Qwen3TTSSynthesizer
    └── tts_registry.py       # TTSRegistry (RuntimeObject, warmup, model download)
```

---

## Architecture Rules (Layering)

Strict import direction — violations break the build:

| Package | May import | Must NOT import |
|---|---|---|
| `core/` | stdlib, `core/` submodules | `agents/`, `app/`, `channels/` |
| `agents/` | `core/`, stdlib | `app/` |
| `channels/` | `core/`, lazy `app.modules` | `agents/` |
| `app/` | everything (composition root) | — |
| `experimental/` | `core/`, stdlib | `app/`, `agents/` |

**Key principle:** dependencies flow inward. `core/` is the innermost layer.

---

## Functional vs Object-Oriented Approach

### Functional (stateless)
- **Observability** — `log_event()`, `trace_scope()`, `register_sink()` are pure functions.
- **Protocol helpers** — `chat_response()`, `status_update()`, `step_event()` are factory functions.
- **Tool functions** — `execute_command(inputs)`, `web_search(inputs)` are plain callables.
- **Utilities** — `compact_reason()`, audio helpers in `tts_backends.py`.

### Object-Oriented (stateful / lifecycle)
- **Inference** — `BaseInference` → `OpenAIInference`. Singleton resolved per provider/model combo.
- **Agents** — `BaseAgent` → `ReActAgent`. Each owns its tools map, history, and prompt renderer.
- **Channels** — `BaseChannel` → `WebSocketChannel`, `TelegramChannel`. Each owns connections and transport.
- **STS pipeline** — `RuntimeObject` subclasses: `STSService`, `STTService`, `TTSService`, `STTRegistry`, `TTSRegistry`.
- **State** — `AppState` (Pydantic BaseModel), `OrchestratorQueue` (async queue + worker).

**Rule of thumb:** If it has state or lifecycle, make it a class.
If it's a pure transformation, make it a function.

---

## Inference Layer

```
core/inference.py
    BaseInference (ABC)      — shared normalization + invoke pipeline
    └── OpenAIInference      — any OpenAI-compatible endpoint (LM Studio, OpenAI, etc.)

    get_implementation(model_id) → BaseInference   # singleton per provider
    invoke(...)                                    # module-level convenience
```

### Provider selection

`model_id` format: `<prefix>/<model-name>`

| Prefix | Provider | Env vars |
|---|---|---|
| `lms` | LM Studio | `LMS_PROVIDER_URL`, `LMS_API_KEY` |
| `openai` | OpenAI | `OPENAI_API_KEY` |
| _(bare name)_ | OpenAI | `OPENAI_API_KEY` |

`_REGISTRY: dict[str, type[BaseInference]]` maps prefix → class.

### Adding a new inference provider

1. Subclass `BaseInference` in `core/inference.py`.
2. Implement `_call_llm(self, messages, model) → str`.
3. Add prefix → class to `_REGISTRY`.
4. All async wrapping, multimodal handling, and response parsing is inherited.

---

## Agent System

```
agents/orchestrator.py
    _SUB_AGENTS: list[BaseAgent]   # register new agents here
    build_orchestrator() → ReActAgent   # called from app/main.py lifespan
    orchestrator: ReActAgent | None     # module-level singleton

agents/sub_agents/
    command_line_agent.py   # module-level singleton
    web_search_agent.py     # module-level singleton
    self_agent.py           # module-level singleton
    chrome_agent.py         # async factory: create_chrome_agent()

agents/prompts/
    <agent_name>.md         # system instruction for each agent
```

### Adding a new sub-agent

1. Create `agents/sub_agents/my_agent.py` — export a `BaseAgent` singleton.
2. Add a `my_agent.md` to `agents/prompts/`.
3. Append the instance to `_SUB_AGENTS` in `agents/orchestrator.py`.
4. No other registration required.

---

## STS / STT / TTS Layer

The speech pipeline is a three-stage facade:

```
core/sts.py  STSService (RuntimeObject)
├── stt: STTService
│   └── stt_registry: STTRegistry   ← holds AudioTranscriberBaseModel instances
│       ├── WhisperAPITranscriber
│       ├── MacOSNativeBridgeTranscriber
│       └── Qwen3ASRTranscriber (experimental)
└── tts: TTSService
    └── tts_registry: TTSRegistry   ← holds SpeechSynthesizerBaseModel instances
        └── Qwen3TTSSynthesizer (LocalModelSynthesizerBase)
```

**Pattern for new STT backend:**
1. Subclass `AudioTranscriberBaseModel` in `core/stt_backends.py`.
2. Implement `transcribe()` + `health_check()`.
3. Register an instance in `STTRegistry.transcribers` in `core/stt_registry.py`.
4. Add a `BackendOptionModel` entry to `STTRegistry.stt_options`.

**Pattern for new TTS backend:**
1. Subclass `SpeechSynthesizerBaseModel` (or `LocalModelSynthesizerBase` for HuggingFace models) in `core/tts_backends.py`.
2. Implement `synthesize()` + `health_check()`.
3. Register in `TTSRegistry.synthesizers` + `TTSRegistry.tts_options`.

---

## Channels (Communication)

```
channels/base.py
    BaseChannel (ABC)
        name: str
        async connect(**kwargs) → None
        async disconnect() → None
        async send(payload, **kwargs) → None
        async broadcast(payload, scope?) → None
        async receive() → AsyncIterator[dict]   # optional
```

Adding a new channel:
1. Create `channels/my_channel.py`, subclass `BaseChannel`.
2. Wire `connect()` / `disconnect()` into `app/main.py` lifespan.

---

## Protocol & State

### Protocol (`app/protocol.py`)

Use factory functions — never construct `WSMessage` directly:

| Factory | When to use |
|---|---|
| `chat_response(content)` | Final assistant answer |
| `status_update(status, detail)` | Processing state change |
| `step_event(type, content)` | Activity feed item |
| `error_event(message)` | Error notification |
| `observability_event(event)` | Raw trace event |

### State (`app/state.py`)

`AppState` is the single source of truth for UI-visible runtime state:
- `messages` — conversation history
- `events` — system event log
- `observability_events` — trace events
- `is_processing` / `current_query` — UI busy signal
- `active_stt_backend` / `active_tts_backend` — hot-reloadable backend IDs

---

## Tools / Sub-Agents

- Tool signature: `tool(inputs: dict) -> str | Awaitable[str]`
- Sub-agent tool calls must use `{"query": "..."}` format.
- `command_line_agent` blocks dangerous patterns: `rm -rf`, `sudo`, `dd`, etc.

---

## Model Bootstrap

Models are **not tracked in git** (`models/` is gitignored).

**Startup sequence (automatic):**
1. `app/main.py` lifespan calls `await sts_service.initialize()`.
2. `STSService._initialize_services()` calls `tts.initialize()` which calls `TTSRegistry.warmup_tts_models()`.
3. Each `LocalModelSynthesizerBase.ensure_ready()` calls `_download_hf_snapshot(repo_id, local_dir)` — uses `huggingface_hub.snapshot_download`.
4. A warmup synthesis run validates the model before requests are accepted.
5. ASR model path is verified; missing local ASR models are logged as warnings (not fatal — `whisper_api` / `macos_native_bridge` need no local files).

**Adding a new local model:**
- Subclass `LocalModelSynthesizerBase`, set `repo_id` field.
- `ensure_ready()` is inherited — it handles download, caching, and path resolution automatically.

---

## Adding New Components

| What | Where | Pattern |
|---|---|---|
| Inference provider | `core/inference.py` | Subclass `BaseInference` + `_REGISTRY` entry |
| Sub-agent | `agents/sub_agents/*.py` + `_SUB_AGENTS` | Export singleton |
| Channel | `channels/*.py` | Subclass `BaseChannel` |
| STT backend | `core/stt_backends.py` + `STTRegistry` | Subclass `AudioTranscriberBaseModel` |
| TTS backend | `core/tts_backends.py` + `TTSRegistry` | Subclass `SpeechSynthesizerBaseModel` |
| Tool function | Inside sub-agent file | `def tool(inputs: dict) -> str` |
| API route | `app/main.py` | FastAPI decorator |
| UI page | `app/templates/*.j2` | Extend `base.j2` + add route |

---

## Developer Workflow

### Environment setup
```bash
uv sync
cp .env.example .env
```

### Running the server
```bash
uv run python main.py              # production
uv run python main.py --reload     # development with auto-reload
```

### Code quality
```bash
uv run ruff format .
uv run ruff check .
uv run ruff check --fix .
```

### Key environment variables

| Variable | Purpose | Example |
|---|---|---|
| `MODEL_ID` | LLM model identifier | `lms/qwen/qwen3-vl-30b` |
| `LMS_PROVIDER_URL` | LM Studio base URL | `http://127.0.0.1:1234/v1` |
| `OPENAI_API_KEY` | OpenAI API key | `sk-…` |
| `TELEGRAM_BOT_TOKEN` | Telegram bot token | `123456:ABC…` |
| `LOG_LEVEL` | Logging verbosity | `DEBUG` / `INFO` / `WARNING` |
| `STS_TRANSCRIBE_BACKEND` | Active STT backend | `macos_native_bridge` |
| `STS_TTS_BACKEND` | Active TTS backend | `qwen3_tts` |
| `TTS_MODELS_DIR` | HuggingFace model cache root | `models/tts` |
| `TTS_DEVICE` | Torch device | `auto` / `cpu` / `mps` / `cuda` |
| `QWEN3_ASR_MODEL` | Path to local ASR weights | `models/qwen3-asr-0.6b` |

---

## Before Finishing

Run this required checklist before committing:

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

Manual happy-path validation is mandatory:
1. **Chat** (`/`): send one message, confirm user message appears, confirm assistant response appears.
2. **STS** (`/sts`): speak one request, confirm transcript appears, confirm assistant response and audio playback.

If STS is blocked by mic/device/permissions, report the exact failure reason, remediation steps, and mark as blocked/pending manual verification.

Do not report a task as completed if any required step above was skipped or failed.
