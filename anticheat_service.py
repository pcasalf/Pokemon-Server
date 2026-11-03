"""Servicio HTTP separado para auditoria; solo usar tras HTTPS si es remoto.

websockets gestiona exclusivamente GET de handshake y no soporta cuerpos POST;
por ello esta API es un proceso HTTP independiente, no una ruta del relay.
"""
import json
import os
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, HTTPServer
from types import SimpleNamespace

from anticheat import AntiCheat
from anticheat_web import MAX_BODY, dispatch_anticheat
from server import validate_rooms


class AuditHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self._dispatch()

    def do_POST(self):
        self._dispatch()

    def _dispatch(self):
        raw = b""
        if self.command == "POST":
            try:
                size = int(self.headers.get("Content-Length", "-1"))
            except ValueError:
                size = -1
            if not 0 < size <= MAX_BODY:
                self.send_error(HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
                self.close_connection = True
                return
            raw = self.rfile.read(size)
            if len(raw) != size:
                self.send_error(HTTPStatus.BAD_REQUEST)
                return
        req = SimpleNamespace(path=self.path, method=self.command, headers=self.headers, body=raw)
        response = dispatch_anticheat(self, req, self.server.rooms,
                                      self.server.store, self.server.admin_token)
        if response is None:
            response = self.respond(HTTPStatus.NOT_FOUND, '{"error":"No existe"}\n')
        encoded = response.body.encode("utf-8")
        self.send_response(response.status)
        for key, value in response.headers.items():
            self.send_header(key, value)
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def respond(self, status, body):
        return SimpleNamespace(status=status, body=body, headers={})


class AuditHTTPServer(HTTPServer):
    def __init__(self, address, rooms, store, admin_token):
        super().__init__(address, AuditHandler)
        self.rooms = rooms
        self.store = store
        self.admin_token = admin_token


def main():
    db_path = os.environ.get("PZ_ANTICHEAT_DB")
    admin_token = os.environ.get("PZ_ADMIN_TOKEN")
    rooms_json = os.environ.get("PZ_ROOMS_JSON")
    if not db_path or not admin_token or len(admin_token) < 32 or not rooms_json:
        raise SystemExit("Faltan PZ_ANTICHEAT_DB, PZ_ADMIN_TOKEN (32+), PZ_ROOMS_JSON")
    try:
        rooms = validate_rooms(json.loads(rooms_json))
    except (ValueError, TypeError) as exc:
        raise SystemExit("PZ_ROOMS_JSON invalido") from exc
    host = os.environ.get("PZ_ANTICHEAT_HOST", "127.0.0.1")
    port = int(os.environ.get("PZ_ANTICHEAT_PORT", "27018"))
    if host not in ("127.0.0.1", "localhost", "::1"):
        print("AVISO: HTTP sin TLS. Publicar solo detras de un proxy HTTPS seguro.", flush=True)
    store = AntiCheat(db_path)
    try:
        with AuditHTTPServer((host, port), rooms, store, admin_token) as server:
            print(f"Auditoria HTTP escuchando en {host}:{server.server_port}", flush=True)
            server.serve_forever()
    finally:
        store.close()


if __name__ == "__main__":
    main()
