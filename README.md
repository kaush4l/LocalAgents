# AppleShortcuts - ReAct Agent System

A modular multi-agent system built on a ReAct-style loop with a FastAPI + WebSocket UI. The orchestrator delegates work to specialized agents (shell, browser, web search) and synthesizes the final response.

## Quick Start

Prerequisites:
- Python 3.14
- uv package manager
- Node.js + npm (for the Chrome DevTools MCP server)
- Chrome or Chromium installed

Install dependencies:

```bash
uv sync
```

Run the server:

```bash
uv run python main.py
```

Development (auto-reload):

```bash
uv run python main.py --reload
```

Open the UI at `http://127.0.0.1:8000`.

## Self Page

The `/self` page includes a weekly calendar heatmap (Sunday-start), day markers, and click-to-drilldown event list, plus local task/todo management.

- Weekly heatmap intensity reflects calendar load by day/hour
- Day headers show event count markers
- Clicking a day (or heatmap cell) opens that day's event list
- Calendar data requires macOS Calendar permission (`System Settings > Privacy & Security > Calendars`)

## Configuration

Create a `.env` file (optional) or export environment variables:

```env
MODEL_ID="lms/qwen/qwen3-vl-30b"
LMS_PROVIDER_URL="http://127.0.0.1:1234/v1"
OPENAI_API_KEY=""
LOG_LEVEL="INFO"
AGENT_TIMEOUT_SECONDS="300"
HOST="0.0.0.0"
PORT="8000"

# Telegram (optional — set token to enable)
TELEGRAM_BOT_TOKEN=""
TELEGRAM_NOTIFY_CHAT_ID=""

# Speech-to-Speech (optional)
STS_TRANSCRIBE_BACKEND="macos_native_bridge"   # or whisper_api, qwen3_asr
STS_TTS_BACKEND="qwen3_tts"
WHISPER_API_URL="http://127.0.0.1:1234/v1"
WHISPER_MODEL="whisper-large-v3-turbo"
TTS_MODELS_DIR="models/tts"
TTS_DEVICE="auto"
TTS_QWEN_VOICE="english"
```

## Agents

- **orchestrator**: routes tasks to specialized agents
- **command_line_agent**: safe shell execution (`execute_command`)
- **chrome_agent**: browser automation via Chrome DevTools MCP
- **web_search_agent**: DuckDuckGo web search (`web_search`)

Agent instruction prompts live in `agents/prompts/`.

## Speech-to-Speech (STS)

The STS page provides a voice-driven interface: **Speak → Transcribe → LLM → Respond**.

### STT Backends (plug-and-play)
| Backend | ID | Description |
|---|---|---|
| Whisper API | `whisper_api` | Upload audio to OpenAI-compatible endpoint |
| macOS Native | `macos_native_bridge` | Live on-device recognition via Apple Speech framework |
| Qwen3-ASR | `qwen3_asr` | Local transcription with Qwen/Qwen3-ASR |

### TTS Backends (plug-and-play)
| Backend | ID | Description |
|---|---|---|
| Qwen3-TTS-12Hz-0.6B | `qwen3_tts` | Local model from `Qwen/Qwen3-TTS-12Hz-0.6B-Base` |

Set `STS_TRANSCRIBE_BACKEND` and `STS_TTS_BACKEND` to switch backends.
On startup, the STS service warms and downloads required TTS model snapshots; if warmup fails, application startup fails.

## Telegram Integration

Set `TELEGRAM_BOT_TOKEN` to enable the Telegram bot. It polls for messages and routes them through the orchestrator.

- Chat history is stored per-user in `bot logs/`
- Set `TELEGRAM_NOTIFY_CHAT_ID` for owner notifications
- The bot starts automatically if the token is set

## Response Contract (ReActResponse)

Agents respond using `ReActResponse` in TOON/1 format by default:

```
observation: <string>
plan: <list>
action: <tool|answer>
response: <tool call(s) or final answer>
```

## Project Structure

```
AppleShortcuts/
├── agents/               # Agent implementations
│   └── prompts/          # Behavior prompts (system instructions)
├── app/                  # FastAPI server and UI assets
│   ├── modules/          # Integration modules (Telegram)
│   └── templates/        # Jinja2 templates (chat, STS)
├── core/                 # Engine, responses, tools, inference
│   ├── sts*.py           # STS service, backends, registry
│   └── integrations.py   # Integration ABC
├── experimental/         # Experimental backends (qwen3_asr, mlx_tts, macos_native)
├── main.py               # Entry point
└── pyproject.toml        # uv-managed dependencies
```
