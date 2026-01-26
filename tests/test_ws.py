import asyncio
import websockets

async def main():
    uri = "ws://127.0.0.1:8000/ws"
    try:
        async with websockets.connect(uri) as ws:
            await ws.send("Hello from test client")
            resp = await ws.recv()
            print(resp)
    except Exception as e:
        print("ERROR", e)

if __name__ == '__main__':
    asyncio.run(main())
