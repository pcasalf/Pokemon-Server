"""Entrada HTTP/WebSocket para Render. Las salas se cargan de una variable privada."""
import asyncio
import json
import logging
import os
import signal
from http import HTTPStatus
from websockets.asyncio.server import serve

from server import RelayServer, validate_rooms
from web_transport import CHUNK, forward


class WebRelay:
    def __init__(self, rooms, audit, max_clients=64):
        self.relay = RelayServer(rooms, audit, max_clients=max_clients)
        self.ws_server = None
        self.port = None
        self.tcp_port = None
        self.active = 0

    async def request(self, connection, request):
        if request.path == '/health':
            return connection.respond(HTTPStatus.OK, 'ok\n')
        if request.path != '/relay':
            return connection.respond(HTTPStatus.NOT_FOUND, 'Not found\n')
        if self.active >= self.relay.max_clients:
            return connection.respond(HTTPStatus.SERVICE_UNAVAILABLE, 'Busy\n')
        return None

    async def handle(self, websocket):
        if self.active >= self.relay.max_clients:
            await websocket.close(1013, 'Busy')
            return
        self.active += 1
        try:
            reader, writer = await asyncio.open_connection('127.0.0.1', self.tcp_port)
            await forward(websocket, reader, writer)
        finally:
            self.active -= 1

    async def start(self, host='0.0.0.0', port=10000):
        # El puerto TCP antiguo no se expone: solo es accesible desde este proceso/VM.
        self.tcp_port = await self.relay.start('127.0.0.1', 0)
        try:
            self.ws_server = await serve(
                self.handle, host, port, process_request=self.request,
                max_size=CHUNK, max_queue=4, compression=None,
                ping_interval=20, ping_timeout=20, close_timeout=3,
            )
        except BaseException:
            await self.relay.close()
            raise
        self.port = self.ws_server.sockets[0].getsockname()[1]
        return self.port

    async def close(self):
        if self.ws_server:
            self.ws_server.close()
            await self.ws_server.wait_closed()
        await self.relay.close()


async def main():
    raw = os.environ.get('PZ_ROOMS_JSON')
    if not raw:
        raise SystemExit('Falta PZ_ROOMS_JSON: configura las claves como variable privada de Render.')
    try:
        rooms = validate_rooms(json.loads(raw))
    except (ValueError, TypeError):
        raise SystemExit('PZ_ROOMS_JSON no tiene un formato de salas valido.') from None
    relay = WebRelay(rooms, os.environ.get('PZ_AUDIT_PATH', 'data/audit.jsonl'))
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:
            pass  # Windows: asyncio.run trata Ctrl+C.
    await relay.start(port=int(os.environ.get('PORT', '10000')))
    print(f'HTTP/WebSocket listo, puerto {relay.port}; /health y /relay', flush=True)
    try:
        await stop.wait()
    finally:
        await relay.close()


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
