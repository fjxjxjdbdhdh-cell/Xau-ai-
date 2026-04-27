import asyncio, json, logging

logger = logging.getLogger(__name__)
_clients = set()

async def handler(ws):
    _clients.add(ws)
    try:
        while True:
            await ws.send(json.dumps({"price": 2600.00, "bid": 2600.00, "ask": 2600.50}))
            await asyncio.sleep(1)
    except:
        pass
    finally:
        _clients.discard(ws)

async def start_ws():
    import websockets
    async with websockets.serve(handler, "0.0.0.0", 8000):
        await asyncio.Future()
