"""Túnel WebSocket binario <-> TCP, con buffers limitados y cierre de ambos extremos."""
import asyncio
from websockets.exceptions import ConnectionClosed

CHUNK = 64 * 1024


async def forward(websocket, reader, writer):
    async def to_tcp():
        async for message in websocket:
            if not isinstance(message, bytes):
                await websocket.close(1003, "Binary messages required")
                return
            writer.write(message)
            await asyncio.wait_for(writer.drain(), 30)

    async def to_websocket():
        while True:
            data = await reader.read(CHUNK)
            if not data:
                return
            await websocket.send(data)

    tasks = [asyncio.create_task(to_tcp()), asyncio.create_task(to_websocket())]
    try:
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        results = await asyncio.gather(*tasks, return_exceptions=True)
        writer.close()
        try:
            await writer.wait_closed()
        except (OSError, ConnectionError):
            pass
        await websocket.close()
        for result in results:
            if isinstance(result, BaseException) and not isinstance(
                result, (asyncio.CancelledError, ConnectionClosed, OSError, asyncio.TimeoutError)
            ):
                raise result
