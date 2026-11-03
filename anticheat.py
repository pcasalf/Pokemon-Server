"""Auditoria inicial de Pokemon Z: alertas, NO autoridad de combate.

Solo el administrador debe inscribir los Pokemon de referencia. Los informes del
cliente se tratan como indicios no confiables: nunca legalizan una captura.
"""
import json
import re
import sqlite3
import time
from pathlib import Path

ROOM_RE = re.compile(r"[A-Z0-9]{6,16}\Z")
ID_RE = re.compile(r"[A-Za-z0-9_:-]{1,64}\Z")
STATS = ("hp", "attack", "defense", "sp_attack", "sp_defense", "speed")
MAX_REPORT = 3000


class ValidationError(ValueError):
    pass


def _text(value, field):
    if not isinstance(value, str) or not 1 <= len(value) <= 64 or any(ord(c) < 32 for c in value):
        raise ValidationError(f"{field} invalido")
    return value


def _stat_values(values, field, maximum):
    if not isinstance(values, dict) or set(values) != set(STATS):
        raise ValidationError(f"{field} requiere seis estadisticas")
    if any(type(values[k]) is not int or not 0 <= values[k] <= maximum for k in STATS):
        raise ValidationError(f"{field} fuera de rango")
    return {k: values[k] for k in STATS}


def validate_pokemon(p):
    if not isinstance(p, dict) or set(p) != {"uid", "species", "ability", "nature", "ivs", "evs", "level", "dead"}:
        raise ValidationError("campos de Pokemon incorrectos")
    uid = p["uid"]
    if not isinstance(uid, str) or not ID_RE.fullmatch(uid):
        raise ValidationError("uid invalido")
    level = p["level"]
    if type(level) is not int or not 1 <= level <= 100:
        raise ValidationError("nivel invalido")
    if type(p["dead"]) is not bool:
        raise ValidationError("estado de muerte invalido")
    ivs = _stat_values(p["ivs"], "ivs", 31)
    evs = _stat_values(p["evs"], "evs", 252)
    if sum(evs.values()) > 510:
        raise ValidationError("EV total superior a 510")
    return {"uid": uid, "species": _text(p["species"], "species"),
            "ability": _text(p["ability"], "ability"),
            "nature": _text(p["nature"], "nature"), "ivs": ivs,
            "evs": evs, "level": level, "dead": p["dead"]}


def _check_room_role(room, role=None):
    if not isinstance(room, str) or not ROOM_RE.fullmatch(room):
        raise ValidationError("codigo de sala invalido")
    if role is not None and role not in ("player", "coach"):
        raise ValidationError("rol invalido")


class AntiCheat:
    """Almacena referencias de confianza e informes de clientes en SQLite."""

    def __init__(self, path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path), timeout=10, check_same_thread=False)
        self.db.execute("PRAGMA busy_timeout = 10000")
        self.db.execute("PRAGMA journal_mode = WAL")
        self.db.execute("PRAGMA foreign_keys = ON")
        with self.db:
            self.db.executescript("""
                CREATE TABLE IF NOT EXISTS pokemon (
                    room TEXT NOT NULL, role TEXT NOT NULL, uid TEXT NOT NULL,
                    baseline TEXT NOT NULL, highest_level INTEGER NOT NULL,
                    dead_seen INTEGER NOT NULL,
                    PRIMARY KEY (room, uid)
                );
                CREATE TABLE IF NOT EXISTS reports (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, room TEXT NOT NULL,
                    role TEXT NOT NULL, created REAL NOT NULL,
                    count INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS alerts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    report_id INTEGER NOT NULL REFERENCES reports(id),
                    room TEXT NOT NULL, role TEXT NOT NULL, uid TEXT NOT NULL,
                    code TEXT NOT NULL, details TEXT NOT NULL,
                    created REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_alerts_room ON alerts(room, id);
                CREATE TABLE IF NOT EXISTS gym_wins (
                    room TEXT NOT NULL, gym_id TEXT NOT NULL,
                    created REAL NOT NULL, PRIMARY KEY (room, gym_id)
                );
                CREATE TABLE IF NOT EXISTS revivals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    room TEXT NOT NULL, uid TEXT NOT NULL, created REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS evolutions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    room TEXT NOT NULL, uid TEXT NOT NULL,
                    old_species TEXT NOT NULL, new_species TEXT NOT NULL,
                    old_ability TEXT NOT NULL, new_ability TEXT NOT NULL,
                    created REAL NOT NULL
                );
            """)

    def close(self):
        self.db.close()

    def enroll(self, room, role, pokemon):
        """Solo llamar desde una operacion de ADMIN autenticada, nunca desde un cliente."""
        _check_room_role(room, role)
        p = validate_pokemon(pokemon)
        try:
            with self.db:
                self.db.execute(
                    "INSERT INTO pokemon(room,role,uid,baseline,highest_level,dead_seen) VALUES(?,?,?,?,?,?)",
                    (room, role, p["uid"], json.dumps(p, sort_keys=True), p["level"], int(p["dead"])))
        except sqlite3.IntegrityError as exc:
            raise ValidationError("uid ya inscrito: requiere revision administrativa") from exc
        return {"room": room, "role": role, "uid": p["uid"], "enrolled": True}

    def observe(self, room, role, pokemon):
        """Informes del cliente: detecta discrepancias, NO valida autenticidad."""
        _check_room_role(room, role)
        if not isinstance(pokemon, list) or len(pokemon) > MAX_REPORT:
            raise ValidationError("lista de Pokemon invalida")
        validated = [validate_pokemon(p) for p in pokemon]
        uids = [p["uid"] for p in validated]
        if len(uids) != len(set(uids)):
            raise ValidationError("UID repetido en el informe")
        now = time.time()
        flags = []
        with self.db:
            cur = self.db.execute("INSERT INTO reports(room,role,created,count) VALUES(?,?,?,?)",
                                  (room, role, now, len(validated)))
            report_id = cur.lastrowid
            for p in validated:
                previous = self.db.execute(
                    "SELECT role,baseline,highest_level,dead_seen FROM pokemon WHERE room=? AND uid=?",
                    (room, p["uid"])).fetchone()
                if previous is None:
                    flags.append((p["uid"], "UNKNOWN_POKEMON", "Pokemon sin inscripcion autorizada"))
                    continue
                owner, raw, highest, dead_seen = previous
                base = json.loads(raw)
                if owner != role:
                    flags.append((p["uid"], "WRONG_OWNER", f"Inscrito para {owner}"))
                # Evolucion es una mecanica normal. Sin evento autorizado se
                # registra para revision, no como prueba de manipulacion.
                if p["species"] != base["species"]:
                    flags.append((p["uid"], "UNVERIFIED_EVOLUTION",
                                  f"Especie {base['species']} -> {p['species']}; revisar evolucion"))
                for key in ("ability", "nature", "ivs"):
                    if p[key] != base[key]:
                        flags.append((p["uid"], "IMMUTABLE_CHANGED", f"Cambio no autorizado en {key}"))
                if p["level"] < highest:
                    flags.append((p["uid"], "LEVEL_REGRESSION", f"Nivel {highest} -> {p['level']}"))
                if dead_seen and not p["dead"]:
                    flags.append((p["uid"], "UNAUTHORIZED_REVIVAL", "Pokemon marcado muerto vuelve vivo"))
                # Solo actualizar progreso si no hubo discrepancias: no normalizar trampas.
                if not any(flag[0] == p["uid"] for flag in flags):
                    self.db.execute("UPDATE pokemon SET highest_level=?,dead_seen=? WHERE room=? AND uid=?",
                                    (max(highest, p["level"]), int(bool(dead_seen or p["dead"])), room, p["uid"]))
            self.db.executemany(
                "INSERT INTO alerts(report_id,room,role,uid,code,details,created) VALUES(?,?,?,?,?,?,?)",
                [(report_id, room, role, uid, code, details, now) for uid, code, details in flags])
        return {"report_id": report_id, "checked": len(validated), "alerts": [
            {"uid": uid, "code": code, "details": details} for uid, code, details in flags]}

    def authorize_evolution(self, room, uid, species, ability=None):
        """Solo administrador: registra y aprueba una evolucion ya verificada.

        No determina si la especie es evolucion legal: se requiere comprobarlo
        independientemente contra el randomizador y reglas del torneo.
        """
        _check_room_role(room)
        if not isinstance(uid, str) or not ID_RE.fullmatch(uid):
            raise ValidationError("uid invalido")
        species = _text(species, "species")
        if ability is not None:
            ability = _text(ability, "ability")
        with self.db:
            previous = self.db.execute(
                "SELECT baseline,dead_seen FROM pokemon WHERE room=? AND uid=?",
                (room, uid)).fetchone()
            if previous is None:
                raise ValidationError("Pokemon no inscrito")
            if previous[1]:
                raise ValidationError("No se puede evolucionar un Pokemon muerto")
            old = json.loads(previous[0])
            next_ability = ability if ability is not None else old["ability"]
            if species == old["species"] and next_ability == old["ability"]:
                raise ValidationError("No hay cambio de evolucion")
            new = dict(old, species=species, ability=next_ability)
            self.db.execute("UPDATE pokemon SET baseline=? WHERE room=? AND uid=?",
                            (json.dumps(new, sort_keys=True), room, uid))
            self.db.execute(
                "INSERT INTO evolutions(room,uid,old_species,new_species,old_ability,new_ability,created) "
                "VALUES(?,?,?,?,?,?,?)",
                (room, uid, old["species"], species, old["ability"], next_ability, time.time()))
        return {"room": room, "uid": uid, "old_species": old["species"],
                "new_species": species, "ability": next_ability, "approved": True}

    def grant_gym_win(self, room, gym_id):
        """Solo administrador: confirmar una victoria permite UNA resurreccion."""
        _check_room_role(room)
        if not isinstance(gym_id, str) or not ID_RE.fullmatch(gym_id):
            raise ValidationError("gimnasio invalido")
        try:
            with self.db:
                self.db.execute("INSERT INTO gym_wins(room,gym_id,created) VALUES(?,?,?)",
                                (room, gym_id, time.time()))
        except sqlite3.IntegrityError as exc:
            raise ValidationError("victoria ya registrada") from exc
        return {"room": room, "gym_id": gym_id, "credit_granted": 1}

    def authorize_revive(self, room, uid):
        """Solo administrador: consume un credito y permite revivir al Pokemon."""
        _check_room_role(room)
        if not isinstance(uid, str) or not ID_RE.fullmatch(uid):
            raise ValidationError("uid invalido")
        with self.db:
            dead = self.db.execute("SELECT dead_seen FROM pokemon WHERE room=? AND uid=?",
                                   (room, uid)).fetchone()
            if dead is None or not dead[0]:
                raise ValidationError("Pokemon no figura como muerto")
            wins = self.db.execute("SELECT COUNT(*) FROM gym_wins WHERE room=?", (room,)).fetchone()[0]
            used = self.db.execute("SELECT COUNT(*) FROM revivals WHERE room=?", (room,)).fetchone()[0]
            if used >= wins:
                raise ValidationError("no quedan resurrecciones disponibles")
            self.db.execute("INSERT INTO revivals(room,uid,created) VALUES(?,?,?)", (room, uid, time.time()))
            self.db.execute("UPDATE pokemon SET dead_seen=0 WHERE room=? AND uid=?", (room, uid))
        return {"room": room, "uid": uid, "revive_authorized": True, "credits_left": wins - used - 1}

    def get_alerts(self, room=None, limit=100):
        if room is not None:
            _check_room_role(room)
        if type(limit) is not int or not 1 <= limit <= 500:
            raise ValidationError("limite invalido")
        rows = self.db.execute(
            "SELECT id,report_id,room,role,uid,code,details,created FROM alerts "
            + ("WHERE room=? " if room else "") + "ORDER BY id DESC LIMIT ?",
            ((room, limit) if room else (limit,))).fetchall()
        return [dict(zip(("id", "report_id", "room", "role", "uid", "code", "details", "created"), row))
                for row in rows]
