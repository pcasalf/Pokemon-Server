"""Rutas HTTP de auditoria; el relay Marshal sigue aislado e intacto."""
import hmac
import json
from http import HTTPStatus
from urllib.parse import parse_qs, urlsplit

from anticheat import ValidationError

MAX_BODY = 512 * 1024


def _reply(connection, status, obj):
    response = connection.respond(status, json.dumps(obj, ensure_ascii=False) + "\n")
    response.headers["Content-Type"] = "application/json; charset=utf-8"
    response.headers["Cache-Control"] = "no-store"
    return response


def _authorized(request, expected):
    given = request.headers.get("Authorization", "")
    return (isinstance(expected, str) and len(expected) >= 32
            and hmac.compare_digest(given, "Bearer " + expected))


def dispatch_anticheat(connection, request, rooms, store, admin_token):
    """Devuelve Response en /anticheat/*; None si la ruta es ajena.

    Las observaciones del cliente NO son prueba de legalidad de una captura.
    """
    parsed = urlsplit(request.path)
    path = parsed.path
    if not path.startswith("/anticheat/"):
        return None
    if store is None or not _authorized_token_configured(admin_token):
        return _reply(connection, HTTPStatus.SERVICE_UNAVAILABLE,
                      {"error": "Antitrampas no configurado"})
    try:
        if path == "/anticheat/alerts":
            if request.method != "GET":
                return _reply(connection, HTTPStatus.METHOD_NOT_ALLOWED, {"error": "Metodo no permitido"})
            if not _authorized(request, admin_token):
                return _reply(connection, HTTPStatus.UNAUTHORIZED, {"error": "No autorizado"})
            args = parse_qs(parsed.query, keep_blank_values=True)
            if set(args) - {"room", "limit"} or any(len(v) != 1 for v in args.values()):
                raise ValidationError("Parametros invalidos")
            room = args.get("room", [None])[0]
            limit = int(args.get("limit", ["100"])[0])
            return _reply(connection, HTTPStatus.OK, {"alerts": store.get_alerts(room, limit)})

        if path not in ("/anticheat/enroll", "/anticheat/observe", "/anticheat/gym", "/anticheat/revive"):
            return _reply(connection, HTTPStatus.NOT_FOUND, {"error": "No existe"})
        if request.method != "POST":
            return _reply(connection, HTTPStatus.METHOD_NOT_ALLOWED, {"error": "Metodo no permitido"})
        if len(request.body) > MAX_BODY or not request.body:
            return _reply(connection, HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {"error": "Cuerpo invalido"})
        payload = json.loads(request.body)
        if not isinstance(payload, dict):
            raise ValidationError("Objeto JSON obligatorio")
        if path in ("/anticheat/enroll", "/anticheat/gym", "/anticheat/revive"):
            if not _authorized(request, admin_token):
                return _reply(connection, HTTPStatus.UNAUTHORIZED, {"error": "No autorizado"})
            if path == "/anticheat/gym":
                if set(payload) != {"room", "gym_id"}:
                    raise ValidationError("Campos incorrectos")
                return _reply(connection, HTTPStatus.CREATED,
                              store.grant_gym_win(payload["room"], payload["gym_id"]))
            if path == "/anticheat/revive":
                if set(payload) != {"room", "uid"}:
                    raise ValidationError("Campos incorrectos")
                return _reply(connection, HTTPStatus.OK,
                              store.authorize_revive(payload["room"], payload["uid"]))
            # Enroll con referencias solo aportadas y revisadas por el administrador.
            if set(payload) != {"room", "role", "pokemon"}:
                raise ValidationError("Campos incorrectos")
            result = store.enroll(payload["room"], payload["role"], payload["pokemon"])
            return _reply(connection, HTTPStatus.CREATED, result)
        if set(payload) != {"room", "role", "pokemon"}:
            raise ValidationError("Campos incorrectos")
        room, role = payload["room"], payload["role"]
        if not isinstance(room, str) or not isinstance(role, str):
            raise ValidationError("Sala o rol invalido")
        token = rooms.get(room, {}).get(role)
        if not _authorized(request, token):
            return _reply(connection, HTTPStatus.UNAUTHORIZED, {"error": "No autorizado"})
        return _reply(connection, HTTPStatus.OK, store.observe(room, role, payload["pokemon"]))
    except (ValueError, TypeError, KeyError, json.JSONDecodeError):
        return _reply(connection, HTTPStatus.BAD_REQUEST, {"error": "Datos invalidos"})


def _authorized_token_configured(token):
    return isinstance(token, str) and len(token) >= 32
