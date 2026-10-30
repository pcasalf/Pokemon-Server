"""Puente local para el motor antiguo: TCP loopback -> WebSocket con TLS verificado."""
import argparse
import asyncio
from urllib.parse import urlsplit
from websockets.asyncio.client import connect

from web_transport import CHUNK, forward


def validate_url(url):
    p = urlsplit(url)
    if p.username or p.password or p.query or p.fragment or p.path != '/relay':
        raise ValueError('Usa una URL wss://servidor/relay sin claves ni parametros')
    if p.scheme == 'wss' and p.hostname:
        return url
    if p.scheme == 'ws' and p.hostname in ('127.0.0.1', 'localhost', '::1'):
        return url
    raise ValueError('Se requiere wss://; ws:// solo se permite en localhost')


class LocalBridge:
    def __init__(self, url):
        self.url = validate_url(url)
        self.server = None
        self.tasks = set()

    async def handle(self, reader, writer):
        task = asyncio.current_task()
        self.tasks.add(task)
        try:
            # Un proceso puede atender las dos copias locales del juego.
            if len(self.tasks) > 8:
                writer.write(b'ERROR FULL\n')
                await writer.drain()
                return
            async with connect(
                self.url, open_timeout=90, max_size=CHUNK, max_queue=4,
                compression=None, ping_interval=20, ping_timeout=20, close_timeout=3,
            ) as websocket:
                await forward(websocket, reader, writer)
        except (OSError, TimeoutError):
            # No escribir errores textuales despues del saludo binario.
            pass
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except OSError:
                pass
            self.tasks.discard(task)

    async def start(self, port=27017):
        self.server = await asyncio.start_server(self.handle, '127.0.0.1', port)
        return self.server.sockets[0].getsockname()[1]

    async def close(self):
        if self.server:
            self.server.close()
            await self.server.wait_closed()
        tasks = list(self.tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)


async def main(args):
    bridge = LocalBridge(args.url)
    port = await bridge.start(args.port)
    print(f'Puente listo en 127.0.0.1:{port}', flush=True)
    try:
        await bridge.server.serve_forever()
    finally:
        await bridge.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', required=True)
    parser.add_argument('--port', type=int, default=27017)
    args = parser.parse_args()
    validate_url(args.url)
    try:
        asyncio.run(main(args))
    except KeyboardInterrupt:
        pass
