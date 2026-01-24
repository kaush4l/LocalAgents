import argparse
import asyncio
import sys
import logging
from pathlib import Path

# Add project root to path
sys.path.append(str(Path(__file__).parent))

from team.orchestrator_agent import initialize_orchestrator
from core.logger import get_logger

logger = get_logger("Main")

async def _run_interactive(orchestrator):
    logger.info("Orchestrator ready. Enter queries (type 'exit' to quit).")
    print("\n" + "="*40 + "\n") # Visual separator
    
    while True:
        try:
            query = input("User> ").strip()
        except EOFError:
            logger.info("Exiting.")
            break

        if not query:
            continue
        if query.lower() in {"exit", "quit"}:
            logger.info("Exiting.")
            break

        try:
            result = await orchestrator.invoke(query)
            
            # Print the final result clearly for the user (in addition to logs)
            print("\n" + "=" * 20 + " RESULT " + "=" * 20)
            print(f"Mission: {getattr(result, 'rephrase', '')}")
            print(f"Action: {getattr(result, 'action', '')}")
            print(f"Answer: {getattr(result, 'answer', '')}\n")
            
        except Exception as e:
            logger.error(f"Error during invocation: {e}")


async def main():
    parser = argparse.ArgumentParser(description="AppleShortcuts orchestrator entrypoint")
    parser.add_argument("--query", type=str, help="Run a single query and exit")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    args = parser.parse_args()

    # Configure logging level based on flag
    if args.debug:
        logger.setLevel(logging.DEBUG)
    
    orchestrator = None
    chrome_toolkit = None
    
    try:
        orchestrator, chrome_toolkit = await initialize_orchestrator()
        
        if args.query:
            result = await orchestrator.invoke(args.query)
            print(f"Mission: {getattr(result, 'rephrase', '')}")
            print(f"Action: {getattr(result, 'action', '')}")
            print(f"Answer: {getattr(result, 'answer', '')}")
        else:
            await _run_interactive(orchestrator)
            
    except Exception as e:
        logger.critical(f"Fatal error: {e}")
    finally:
        if chrome_toolkit:
            logger.info("Closing Chrome toolkit...")
            await chrome_toolkit.close()

if __name__ == "__main__":
    asyncio.run(main())
