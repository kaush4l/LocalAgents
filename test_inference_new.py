import asyncio
import logging
from core import inference
from core.responses import ReActResponse

logging.basicConfig(level=logging.INFO)

async def test_inference():
    print("Testing regular completion...")
    res = await inference.invoke("Say 'Hello, test!'")
    print(f"Result: {res}")
    
    print("\nTesting structured completion (ReActResponse)...")
    res_struct = await inference.invoke(
        "Who are you? Respond in ReAct format.",
        response_model=ReActResponse
    )
    print(f"Result Type: {type(res_struct)}")
    print(f"Result: {res_struct}")

if __name__ == "__main__":
    asyncio.run(test_inference())
