# LocalAgents

A minimal, local-first AI agent system. A ReAct orchestrator delegates to specialised sub-agents (shell, browser, web search, self) over a FastAPI + WebSocket backbone. Every component follows an **abstract → concrete** pattern so swapping backends never requires touching business logic.

> **Design principle:** Lines of code are a liability, not an asset. Every line must earn its place by mapping directly to an abstract concept. The architecture is the value — concrete implementations are interchangeable.

---

## Quick Start

**Prerequisites**
- Python 3.14+
- [`uv`](https://docs.astral.sh/uv/) package manager
- Chrome or Chromium (for the Chrome DevTools agent)
- Node.js + npm (for the Chrome DevTools MCP server)

**Install**
```bash
uv sync
cp .env.example .env     # configure model endpoint + optional keys
```

**Run**
```bash
uv run python main.py
```

**Development (auto-reload)**
```bash
uv run python main.py --reload
```

Open `http://127.0.0.1:8000`.

> **Models are auto-downloaded.** On first startup, all required HuggingFace model weights (TTS, ASR) are fetched via `huggingface_hub` into `models/` and cached locally. No manual download step is needed.

---

## Configuration

Copy `.env.example` and set the values you need:

```env
# LLM backend
MODEL_ID="lms/qwen/qwen3-vl-30b"
LMS_PROVIDER_URL="http://127.0.0.1:1234/v1"
OPENAI_API_KEY=""

# Server
HOST="0.0.0.0"
PORT="8000"
LOG_LEVEL="INFO"
AGENT_TIMEOUT_SECONDS="300"

# Telegram (set token to enable)
TELEGRAM_BOT_TOKEN=""
TELEGRAM_NOTIFY_CHAT_ID=""

# Speech-to-Speech
STS_TRANSCRIBE_BACKEND="macos_native_bridge"   # whisper_api | qwen3_asr | macos_native_bridge
STS_TTS_BACKEND="qwen3_tts"
WHISPER_API_URL="http://127.0.0.1:1234/v1"
WHISPER_MODEL="whisper-large-v3-turbo"
TTS_MODELS_DIR="models/tts"
TTS_DEVICE="auto"
TTS_QWEN_VOICE="english"
QWEN3_ASR_MODEL="models/qwen3-asr-0.6b"
```

`MODEL_ID` prefix drives provider selection automatically:
- `lms/…` → LM Studio at `LMS_PROVIDER_URL`
- `openai/…` → OpenAI API
- bare `model-name` → defaults to `openai`

---

## Architecture

```
main.py                       # CLI entry — loads .env, starts uvicorn
├── app/                      # Composition root
│   ├── main.py               # FastAPI app, lifespan, routes, WebSocket endpoint
│   ├── protocol.py           # WSMessage factory functions (never construct directly)
│   ├── state.py              # AppState singleton + OrchestratorQueue
│   ├── modules/              # Runtime integrations (Telegram polling)
│   └── templates/            # Jinja2 SSR pages (chat, sts, observability, self)
├── agents/                   # Orchestrator + sub-agents
│   ├── orchestrator.py       # Wires _SUB_AGENTS list into a ReActAgent
│   ├── prompts/              # Markdown system-instruction files per agent
│   └── sub_agents/           # command_line, web_search, chrome, self
├── channels/                 # Transport adapters
│   ├── base.py               # BaseChannel ABC
│   ├── websocket_channel.py  # Browser WebSocket connections
│   └── telegram_channel.py   # Telegram bot polling
└── core/                     # Inner layer — no app/ or agents/ imports
    ├── engine.py             # BaseAgent, ReActAgent, RuntimeObject
    ├── inference.py          # BaseInference → OpenAIInference (provider-agnostic)
    ├── responses.py          # BaseResponse → ReActResponse, Message
    ├── observability.py      # Pure-function event logging + sinks
    ├── tools.py              # MCP tool wrappers
    ├── sts.py                # STSService facade (STT → LLM → TTS)
    ├── stt.py / stt_backends.py / stt_registry.py
    ├── tts.py / tts_backends.py / tts_registry.py
    └── sts_models.py         # Shared Pydantic models for STS pipeline
```

**Strict import layering (violations fail the build):**

| Layer | May import | Must NOT import |
|---|---|---|
| `core/` | stdlib, `utils/` | `agents/`, `app/`, `channels/` |
| `agents/` | `core/` | `app/` |
| `channels/` | `core/` | `agents/` |
| `app/` | everything | — |

---

## Agents

| Agent | Capability |
|---|---|
| `orchestrator` | Routes tasks, synthesises answers |
| `command_line_agent` | Safe shell with blocked-command list |
| `web_search_agent` | DuckDuckGo search |
| `chrome_agent` | Browser automation via Chrome DevTools MCP |
| `self_agent` | macOS calendar, tasks, local data |

**Adding a sub-agent:** create `agents/sub_agents/my_agent.py`, add it to `_SUB_AGENTS` in `agents/orchestrator.py`, and add `agents/prompts/my_agent.md`.

---

## Speech-to-Speech (STS)

Voice pipeline at `/sts`: **Speak → STT → LLM → TTS → Play**.

### STT Backends

| ID | Description |
|---|---|
| `macos_native_bridge` | On-device live recognition via Apple Speech framework |
| `whisper_api` | Stream audio to any OpenAI-compatible Whisper endpoint |
| `qwen3_asr` | Local transcription — auto-downloads `Qwen/Qwen3-ASR-0.6B` |

### TTS Backends

| ID | Model | Auto-download |
|---|---|---|
| `qwen3_tts` | `Qwen/Qwen3-TTS-12Hz-0.6B-Base` | ✓ HuggingFace on first run |

Switch backends at runtime via `STS_TRANSCRIBE_BACKEND` / `STS_TTS_BACKEND`. On startup the STS service warms all local models; missing weights are fetched automatically from HuggingFace.

---

## Model Bootstrap

Models are **not tracked in git** (`models/` is gitignored). The startup sequence handles everything:

1. `STSService.initialize()` triggers `TTSService.initialize()` → `warmup_tts_models()`.
2. Each `LocalModelSynthesizerBase` subclass calls `ensure_ready()` → `_download_hf_snapshot(repo_id, local_dir)`.
3. `huggingface_hub.snapshot_download` fetches weights into `models/tts/` and caches them via the HuggingFace Hub cache.
4. A warmup synthesis validates the loaded model before the server accepts traffic.

For ASR: set `QWEN3_ASR_MODEL` to point to a pre-populated directory, or use `whisper_api` / `macos_native_bridge` to skip local downloads entirely.

---

## Pages

| Route | Description |
|---|---|
| `/` | Main chat interface |
| `/sts` | Voice-driven speech-to-speech |
| `/observability` | Real-time trace viewer |
| `/self` | macOS calendar heatmap + local task manager |

---

## Telegram

Set `TELEGRAM_BOT_TOKEN` to enable bot polling. Messages route through the orchestrator. Per-user history is stored in `bot logs/`. Set `TELEGRAM_NOTIFY_CHAT_ID` for owner notifications.

---

## Code Quality

```bash
uv run ruff format .
uv run ruff check .
uv run ruff check --fix .
```

---

## Response Format (ReAct / TOON-1)

```
observation: <what was observed>
plan: [step 1, step 2, ...]
action: tool | answer
response: <tool call JSON or final answer text>
```
