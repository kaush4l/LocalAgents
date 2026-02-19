"""CLI entrypoint — run the server."""

import argparse

from dotenv import load_dotenv

load_dotenv()  # Load .env into os.environ before anything else

import uvicorn


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the LocalAgents system")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind to")
    parser.add_argument("--port", type=int, default=8000, help="Port to bind to")
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload")
    args = parser.parse_args()

    print(f"🚀 Starting LocalAgents on http://{args.host}:{args.port}")

    uvicorn.run(
        "app.main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info",
    )


if __name__ == "__main__":
    main()
