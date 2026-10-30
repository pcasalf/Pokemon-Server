import asyncio
import json
import os
import struct
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server import RelayServer, MAX_FRAME


class RelayTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent)
        self.audit = Path(self.tmp.name) / 'audit.jsonl'
        self.rooms = {code: {'player': 'a' * 48, 'coach': 'b' * 48}
                      for code in ('PRUEBA01', 'PRUEBA02')}
        self.server = RelayServer(self.rooms, self.audit, pair_timeout=1, io_timeout=1)
        self.port = await self.server.start(port=0)
        self.writers = []

    async def asyncTearDown(self):
        for writer in self.writers:
            writer.close()
        await self.server.close()
        self.tmp.cleanup()

    async def client(self, role, room='PRUEBA01', token=None, version='0.5.9'):
        reader, writer = await asyncio.open_connection('127.0.0.1', self.port)
        self.writers.append(writer)
        token = token if token is not None else self.rooms[room][role]
        writer.write(f'PZRELAY 1 {room} {role} {version} 4a756761646f72 {token} END\n'.encode())
        await writer.drain()
        line = await asyncio.wait_for(reader.readline(), 2)
        return reader, writer, line

    async def pair(self, room='PRUEBA01'):
        a = await self.client('player', room)
        b = await self.client('coach', room)
        self.assertEqual(a[2], b'WAIT\n')
        self.assertEqual(b[2], b'WAIT\n')
        self.assertEqual(await a[0].readline(), b'READY\n')
        self.assertEqual(await b[0].readline(), b'READY\n')
        return a, b

    async def frame(self, source, dest, payload):
        source[1].write(struct.pack('!I', len(payload)) + payload)
        await source[1].drain()
        n = struct.unpack('!I', await asyncio.wait_for(dest[0].readexactly(4), 2))[0]
        self.assertEqual(await dest[0].readexactly(n), payload)

    async def test_bidirectional_binary_and_order(self):
        a, b = await self.pair()
        for i in range(20):
            await self.frame(a, b, b'\x04\x08\x00' + bytes([i]))
            await self.frame(b, a, b'\xff\x00' + bytes([i]))

    async def test_fragmented_frame(self):
        a, b = await self.pair()
        wire = struct.pack('!I', 7) + b'payload'
        for byte in wire:
            a[1].write(bytes([byte]))
            await a[1].drain()
            await asyncio.sleep(0)
        self.assertEqual(await asyncio.wait_for(b[0].readexactly(len(wire)), 2), wire)

    async def test_wrong_token(self):
        a = await self.client('player', token='c' * 48)
        self.assertEqual(a[2], b'ERROR ACCESS\n')

    async def test_wrong_role_token(self):
        a = await self.client('coach', token=self.rooms['PRUEBA01']['player'])
        self.assertEqual(a[2], b'ERROR ACCESS\n')

    async def test_duplicate_role_keeps_original(self):
        a = await self.client('player')
        intruder = await self.client('player')
        self.assertEqual(intruder[2], b'ERROR ROLE_BUSY\n')
        b = await self.client('coach')
        self.assertEqual(await a[0].readline(), b'READY\n')
        self.assertEqual(await b[0].readline(), b'READY\n')
        await self.frame(a, b, b'original')

    async def test_version_mismatch(self):
        await self.client('player')
        b = await self.client('coach', version='different')
        self.assertEqual(b[2], b'ERROR VERSION\n')

    async def test_rooms_isolated(self):
        a, b = await self.pair()
        c, d = await self.pair('PRUEBA02')
        await self.frame(a, b, b'room-one')
        await self.frame(c, d, b'room-two')
        with self.assertRaises(asyncio.TimeoutError):
            await asyncio.wait_for(d[0].readexactly(1), .05)

    async def test_disconnect_closes_pair(self):
        a, b = await self.pair()
        a[1].close()
        self.assertEqual(await asyncio.wait_for(b[0].read(), 2), b'')

    async def test_waiting_disconnect_releases_role(self):
        a = await self.client('player')
        a[1].close()
        await a[1].wait_closed()
        for _ in range(50):
            if not self.server.slots:
                break
            await asyncio.sleep(.01)
        b = await self.client('player')
        self.assertEqual(b[2], b'WAIT\n')

    async def test_oversized_header_closes_pair_without_reading_body(self):
        a, b = await self.pair()
        a[1].write(struct.pack('!I', MAX_FRAME + 1))
        await a[1].drain()
        self.assertEqual(await asyncio.wait_for(b[0].read(), 2), b'')

    async def test_early_data_rejected(self):
        a = await self.client('player')
        a[1].write(struct.pack('!I', 1) + b'x')
        await a[1].drain()
        self.assertEqual(await asyncio.wait_for(a[0].readline(), 2), b'ERROR EARLY_DATA\n')

    async def test_audit_contains_no_tokens_or_payload(self):
        a, b = await self.pair()
        await self.frame(a, b, b'PRIVATE_POKEMON_PAYLOAD')
        audit = self.audit.read_text()
        self.assertNotIn('a' * 48, audit)
        self.assertNotIn('b' * 48, audit)
        self.assertNotIn('PRIVATE_POKEMON_PAYLOAD', audit)
        self.assertTrue(any(json.loads(line)['event'] == 'frame' for line in audit.splitlines()))

    async def test_pair_timeout_releases_slot(self):
        self.server.pair_timeout = .05
        a = await self.client('player')
        self.assertEqual(await asyncio.wait_for(a[0].readline(), 2), b'ERROR PAIR_TIMEOUT\n')

    @unittest.skipUnless(os.environ.get('RUBY_QA'), 'RUBY_QA no configurado')
    async def test_two_real_ruby_clients_with_game_adapter(self):
        script = Path(__file__).with_name('ruby_peer.rb')
        # Este caso abre dos procesos Ruby con el adaptador y Marshal del juego.
        self.server.io_timeout = 5
        self.server.pair_timeout = 5
        processes = []
        try:
            for role in ('player', 'coach'):
                processes.append(await asyncio.create_subprocess_exec(
                    os.environ['RUBY_QA'], '--disable-gems', str(script), role,
                    str(self.port), self.rooms['PRUEBA01'][role],
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE))
            results = await asyncio.wait_for(asyncio.gather(
                *(proc.communicate() for proc in processes)), 15)
            for proc, (out, err) in zip(processes, results):
                self.assertEqual(proc.returncode, 0, (out + err).decode(errors='replace'))
                self.assertIn(b'PASS', out)
        finally:
            for proc in processes:
                if proc.returncode is None:
                    proc.kill()
                    await proc.wait()


if __name__ == '__main__':
    unittest.main()
