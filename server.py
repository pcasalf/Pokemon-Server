"""Relay TCP de Pokémon Z. No interpreta ni deserializa Marshal del juego."""
import argparse
import asyncio
import hashlib
import hmac
import json
import logging
import re
import secrets
import struct
import time
from dataclasses import dataclass, field
from pathlib import Path

CODE = re.compile(r"[A-Z0-9]{6,16}\Z")
VERSION = re.compile(r"[A-Za-z0-9_.-]{1,32}\Z")
MAX_FRAME = 8 * 1024 * 1024
ROLES = ("player", "coach")


@dataclass
class Peer:
    reader: asyncio.StreamReader
    writer: asyncio.StreamWriter
    room: str
    role: str
    version: str
    ready: asyncio.Event = field(default_factory=asyncio.Event)
    other: "Peer | None" = None
    closed: bool = False


class RelayServer:
    def __init__(self, rooms, audit, pair_timeout=180, io_timeout=30, max_clients=64):
        self.rooms = rooms
        self.audit_path = Path(audit)
        self.audit_path.parent.mkdir(parents=True, exist_ok=True)
        self.pair_timeout = pair_timeout
        self.io_timeout = io_timeout
        self.max_clients = max_clients
        self.clients = 0
        self.slots = {}
        self.listener = None
        self.tasks = set()

    def audit(self, event, **values):
        # Nunca escribir claves, nombres de jugadores ni payloads en el registro.
        record = {"time": time.time(), "event": event, **values}
        try:
            if self.audit_path.exists() and self.audit_path.stat().st_size >= 10 * 1024 * 1024:
                older = self.audit_path.with_name(self.audit_path.name + ".1")
                oldest = self.audit_path.with_name(self.audit_path.name + ".2")
                if older.exists():
                    older.replace(oldest)
                self.audit_path.replace(older)
            with self.audit_path.open("a", encoding="utf-8") as out:
                out.write(json.dumps(record, ensure_ascii=True) + "\n")
        except OSError:
            logging.exception("No se pudo escribir el registro")

    async def start(self, host="127.0.0.1", port=27016):
        self.listener = await asyncio.start_server(self.handle, host, port, limit=4096)
        return self.listener.sockets[0].getsockname()[1]

    async def close(self):
        if self.listener:
            self.listener.close()
            await self.listener.wait_closed()
        tasks = list(self.tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def control(self, writer, line):
        writer.write((line + "\n").encode("ascii"))
        await asyncio.wait_for(writer.drain(), self.io_timeout)

    async def authenticate(self, reader):
        raw = await asyncio.wait_for(reader.readline(), 10)
        if len(raw) > 1024 or not raw.endswith(b"\n"):
            raise ValueError("HEADER")
        fields = raw.decode("ascii").strip().split(" ")
        if len(fields) != 8 or fields[:2] != ["PZRELAY", "1"]:
            raise ValueError("PROTOCOL")
        _, _, room, role, version, name_hex, token, _end = fields
        if _end != "END" or not CODE.fullmatch(room) or role not in ROLES:
            raise ValueError("HEADER")
        if not VERSION.fullmatch(version):
            raise ValueError("VERSION")
        if not re.fullmatch(r"[0-9a-f]{2,192}", name_hex) or len(name_hex) % 2:
            raise ValueError("NAME")
        bytes.fromhex(name_hex).decode("utf-8")
        secret = self.rooms.get(room, {}).get(role)
        if not secret or not hmac.compare_digest(token, secret):
            raise ValueError("ACCESS")
        return room, role, version

    async def handle(self, reader, writer):
        task = asyncio.current_task()
        self.tasks.add(task)
        peer = None
        counted = False
        paired = False
        try:
            if self.clients >= self.max_clients:
                await self.control(writer, "ERROR FULL")
                return
            self.clients += 1
            counted = True
            room, role, version = await self.authenticate(reader)
            slots = self.slots.setdefault(room, {})
            if role in slots:
                raise ValueError("ROLE_BUSY")
            other_role = "coach" if role == "player" else "player"
            other = slots.get(other_role)
            if other and other.version != version:
                raise ValueError("VERSION")
            peer = Peer(reader, writer, room, role, version)
            slots[role] = peer
            self.audit("joined", room=room, role=role, version=version)
            await self.control(writer, "WAIT")
            if other:
                peer.other = other
                other.other = peer
                # Antes de reenviar datos, ambos reciben READY en orden TCP.
                await self.control(other.writer, "READY")
                await self.control(writer, "READY")
                other.ready.set()
                peer.ready.set()
                self.audit("paired", room=room, version=version)
            # Se mantiene una lectura para detectar una salida incluso sin pareja.
            pending = asyncio.create_task(reader.readexactly(4))
            waiting = asyncio.create_task(peer.ready.wait())
            try:
                done, _ = await asyncio.wait(
                    [pending, waiting], timeout=self.pair_timeout,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if not done:
                    raise ValueError("PAIR_TIMEOUT")
                if pending in done and not peer.ready.is_set() and peer.other is None:
                    pending.result()  # EOF se registra como desconexión.
                    raise ValueError("EARLY_DATA")
                await asyncio.wait_for(waiting, self.io_timeout)
                paired = True
                header = await asyncio.wait_for(pending, self.io_timeout)
            finally:
                for sub in (pending, waiting):
                    if not sub.done():
                        sub.cancel()
                await asyncio.gather(pending, waiting, return_exceptions=True)
            sequence = 0
            window = time.monotonic()
            frames = size = 0
            while True:
                length = struct.unpack("!I", header)[0]
                if not 1 <= length <= MAX_FRAME:
                    raise ValueError("FRAME_SIZE")
                now = time.monotonic()
                if now - window >= 1:
                    frames = size = 0
                    window = now
                frames += 1
                size += length
                if frames > 240 or size > 16 * 1024 * 1024:
                    raise ValueError("RATE")
                payload = await asyncio.wait_for(reader.readexactly(length), self.io_timeout)
                if peer.other.closed:
                    break
                peer.other.writer.write(header + payload)
                await asyncio.wait_for(peer.other.writer.drain(), self.io_timeout)
                sequence += 1
                self.audit("frame", room=room, role=role, seq=sequence,
                           size=length, sha256=hashlib.sha256(payload).hexdigest())
                header = await asyncio.wait_for(reader.readexactly(4), self.io_timeout)
        except (ValueError, UnicodeError) as exc:
            reason = str(exc) if isinstance(exc, ValueError) else "ENCODING"
            # No reenviar mensajes de excepciones que puedan contener credenciales.
            if reason not in {"HEADER", "PROTOCOL", "VERSION", "NAME", "ACCESS",
                              "ROLE_BUSY", "PAIR_TIMEOUT", "EARLY_DATA", "FRAME_SIZE", "RATE"}:
                reason = "HEADER"
            self.audit("rejected", reason=reason,
                       **({"room": peer.room, "role": peer.role} if peer else {}))
            if not paired:
                try:
                    await self.control(writer, "ERROR " + reason)
                except (ConnectionError, asyncio.TimeoutError):
                    pass
        except (asyncio.IncompleteReadError, ConnectionError, asyncio.TimeoutError, OSError):
            pass
        finally:
            if peer:
                peer.closed = True
                slots = self.slots.get(peer.room, {})
                if slots.get(peer.role) is peer:
                    del slots[peer.role]
                if not slots:
                    self.slots.pop(peer.room, None)
                self.audit("left", room=peer.room, role=peer.role)
                if peer.other:
                    # Cerrar ambos: reconectar no reutiliza el estado de una partida vieja.
                    peer.other.closed = True
                    peer.other.writer.close()
            writer.close()
            try:
                await writer.wait_closed()
            except (ConnectionError, OSError):
                pass
            if counted:
                self.clients -= 1
            self.tasks.discard(task)


def validate_rooms(data):
    if not isinstance(data, dict) or not data:
        raise ValueError("El archivo de salas está vacío o no es válido")
    for code, roles in data.items():
        if not CODE.fullmatch(code) or not isinstance(roles, dict):
            raise ValueError("Sala inválida")
        for role in ROLES:
            if not isinstance(roles.get(role), str) or not re.fullmatch(r"[0-9a-f]{48}", roles[role]):
                raise ValueError("Clave de rol inválida")
        if roles["player"] == roles["coach"]:
            raise ValueError("Cada rol necesita una clave distinta")
    return data


def load_rooms(path):
    return validate_rooms(json.loads(Path(path).read_text(encoding="utf-8")))


async def serve(args):
    relay = RelayServer(load_rooms(args.rooms), args.audit)
    port = await relay.start(args.host, args.port)
    print(f"Servidor local listo en {args.host}:{port}", flush=True)
    try:
        await relay.listener.serve_forever()
    finally:
        await relay.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init-room")
    init.add_argument("--code", default="PRUEBA01")
    init.add_argument("--rooms", default="data/rooms.json")
    init.add_argument("--ip", default="127.0.0.1")
    init.add_argument("--port", type=int, default=27016)
    run = commands.add_parser("serve")
    run.add_argument("--host", default="127.0.0.1")
    run.add_argument("--port", type=int, default=27016)
    run.add_argument("--rooms", default="data/rooms.json")
    run.add_argument("--audit", default="data/audit.jsonl")
    args = parser.parse_args()
    if args.command == "init-room":
        if not CODE.fullmatch(args.code):
            parser.error("Código: 6 a 16 letras mayúsculas o números")
        path = Path(args.rooms)
        rooms = load_rooms(path) if path.exists() else {}
        if args.code in rooms:
            parser.error("La sala ya existe; no se han cambiado sus claves")
        roles = {r: secrets.token_hex(24) for r in ROLES}
        rooms[args.code] = roles
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(rooms, indent=2) + "\n", encoding="utf-8")
        for role in ROLES:
            profile = path.parent / "profiles" / args.code / role / "Mods" / "torneo_relay.cfg"
            profile.parent.mkdir(parents=True, exist_ok=True)
            profile.write_text(f"ip={args.ip}\nport={args.port}\nroom={args.code}\nrole={role}\ntoken={roles[role]}\n", encoding="ascii")
        print(f"Sala {args.code} creada. Perfiles separados en {path.parent / 'profiles'}")
    else:
        try:
            asyncio.run(serve(args))
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
