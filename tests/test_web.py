import asyncio
import os
import struct
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bridge import LocalBridge, validate_url
from web_server import WebRelay
from websockets.asyncio.client import connect


class WebTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.rooms = {'PRUEBA01': {'player': 'a' * 48, 'coach': 'b' * 48}}
        self.server = WebRelay(self.rooms, Path(self.tmp.name) / 'audit.jsonl')
        self.port = await self.server.start('127.0.0.1', 0)
        self.bridge = LocalBridge(f'ws://127.0.0.1:{self.port}/relay')
        self.bridge_port = await self.bridge.start(0)
        self.clients = []

    async def asyncTearDown(self):
        for writer in self.clients:
            writer.close()
        await self.bridge.close()
        await self.server.close()
        self.tmp.cleanup()

    async def tcp_client(self, role, token=None):
        r, w = await asyncio.open_connection('127.0.0.1', self.bridge_port)
        self.clients.append(w)
        token = token or self.rooms['PRUEBA01'][role]
        w.write(f'PZRELAY 1 PRUEBA01 {role} webtest 5141 {token} END\n'.encode())
        await w.drain()
        return r, w, await asyncio.wait_for(r.readline(), 3)

    async def pair(self):
        a = await self.tcp_client('player')
        b = await self.tcp_client('coach')
        self.assertEqual(a[2], b'WAIT\n')
        self.assertEqual(b[2], b'WAIT\n')
        self.assertEqual(await asyncio.wait_for(a[0].readline(), 3), b'READY\n')
        self.assertEqual(await asyncio.wait_for(b[0].readline(), 3), b'READY\n')
        return a, b

    async def test_health_http(self):
        r, w = await asyncio.open_connection('127.0.0.1', self.port)
        self.clients.append(w)
        w.write(b'GET /health HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n')
        await w.drain()
        response = await asyncio.wait_for(r.read(), 3)
        self.assertIn(b'200 OK', response)
        self.assertTrue(response.endswith(b'ok\n'))

    async def test_bridge_binary_roundtrip(self):
        a, b = await self.pair()
        for source, dest in ((a, b), (b, a)):
            wire = struct.pack('!I', 7) + b'\x04\x08\x00test'
            source[1].write(wire)
            await source[1].drain()
            self.assertEqual(await asyncio.wait_for(dest[0].readexactly(len(wire)), 3), wire)

    async def test_stream_larger_than_websocket_message(self):
        a, b = await self.pair()
        payload = bytes(range(256)) * 1024
        wire = struct.pack('!I', len(payload)) + payload
        a[1].write(wire)
        await a[1].drain()
        self.assertEqual(await asyncio.wait_for(b[0].readexactly(len(wire)), 5), wire)

    async def test_invalid_access_through_bridge(self):
        a = await self.tcp_client('player', token='c' * 48)
        self.assertEqual(a[2], b'ERROR ACCESS\n')

    async def test_disconnect_propagates_through_bridge(self):
        a, b = await self.pair()
        a[1].close()
        await a[1].wait_closed()
        self.assertEqual(await asyncio.wait_for(b[0].read(), 5), b'')

    async def test_text_websocket_rejected(self):
        async with connect(f'ws://127.0.0.1:{self.port}/relay') as ws:
            await ws.send('not binary')
            await asyncio.wait_for(ws.wait_closed(), 3)
            self.assertEqual(ws.close_code, 1003)

    def test_cleartext_remote_rejected(self):
        with self.assertRaises(ValueError):
            validate_url('ws://example.com/relay')
        self.assertEqual(validate_url('wss://example.com/relay'), 'wss://example.com/relay')

    @unittest.skipUnless(os.environ.get('RUBY_QA'), 'RUBY_QA no configurado')
    async def test_two_game_adapters_through_websocket_bridge(self):
        script = Path(__file__).with_name('ruby_peer.rb')
        processes = []
        try:
            for role in ('player', 'coach'):
                processes.append(await asyncio.create_subprocess_exec(
                    os.environ['RUBY_QA'], '--disable-gems', str(script), role,
                    str(self.bridge_port), self.rooms['PRUEBA01'][role],
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE))
            results = await asyncio.wait_for(asyncio.gather(
                *(proc.communicate() for proc in processes)), 15)
            for proc, (out, err) in zip(processes, results):
                self.assertEqual(proc.returncode, 0, (out + err).decode(errors='replace'))
        finally:
            for proc in processes:
                if proc.returncode is None:
                    proc.kill()
                    await proc.wait()
