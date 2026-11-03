import http.client
import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from anticheat import AntiCheat, ValidationError, STATS
from anticheat_service import AuditHTTPServer

ROOM = "PRUEBA01"
ADMIN = "A" * 48
PLAYER = "b" * 48
COACH = "c" * 48
ROOMS = {ROOM: {"player": PLAYER, "coach": COACH}}


def pokemon(uid="p001", **changes):
    result = {"uid": uid, "species": "Gengar", "ability": "Levitate", "nature": "Modest",
              "ivs": {name: 12 for name in STATS}, "evs": {name: 0 for name in STATS},
              "level": 30, "dead": False}
    result.update(changes)
    return result


class AntiCheatTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "audit.sqlite3"
        self.store = AntiCheat(self.path)

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def test_enrollment_and_valid_leveling(self):
        self.store.enroll(ROOM, "player", pokemon())
        self.assertEqual(self.store.observe(ROOM, "player", [pokemon(level=31)])["alerts"], [])
        self.assertEqual(self.store.get_alerts(), [])

    def test_modified_iv_and_ability_are_flagged(self):
        self.store.enroll(ROOM, "player", pokemon())
        ivs = dict(pokemon()["ivs"], attack=31)
        result = self.store.observe(ROOM, "player", [pokemon(ivs=ivs, ability="Wonder Guard")])
        self.assertEqual([f["code"] for f in result["alerts"]], ["IMMUTABLE_CHANGED"] * 2)

    def test_unknown_pokemon_wrong_owner_and_level_regression(self):
        self.store.enroll(ROOM, "player", pokemon())
        self.assertEqual(self.store.observe(ROOM, "coach", [pokemon()])["alerts"][0]["code"], "WRONG_OWNER")
        self.assertEqual(self.store.observe(ROOM, "player", [pokemon(uid="fake")])["alerts"][0]["code"], "UNKNOWN_POKEMON")
        self.store.observe(ROOM, "player", [pokemon(level=40)])
        self.assertEqual(self.store.observe(ROOM, "player", [pokemon(level=29)])["alerts"][0]["code"], "LEVEL_REGRESSION")

    def test_revival_requires_unique_gym_credit(self):
        self.store.enroll(ROOM, "player", pokemon())
        self.store.observe(ROOM, "player", [pokemon(dead=True)])
        self.assertEqual(self.store.observe(ROOM, "player", [pokemon()])["alerts"][0]["code"], "UNAUTHORIZED_REVIVAL")
        with self.assertRaises(ValidationError):
            self.store.authorize_revive(ROOM, "p001")
        self.store.grant_gym_win(ROOM, "gym01")
        with self.assertRaises(ValidationError):
            self.store.grant_gym_win(ROOM, "gym01")
        self.assertEqual(self.store.authorize_revive(ROOM, "p001")["credits_left"], 0)
        self.assertEqual(self.store.observe(ROOM, "player", [pokemon()])["alerts"], [])
        self.store.observe(ROOM, "player", [pokemon(dead=True)])
        with self.assertRaises(ValidationError):
            self.store.authorize_revive(ROOM, "p001")

    def test_rejects_duplicate_unknown_or_invalid_data(self):
        self.store.enroll(ROOM, "player", pokemon())
        with self.assertRaises(ValidationError):
            self.store.enroll(ROOM, "player", pokemon())
        with self.assertRaises(ValidationError):
            self.store.observe(ROOM, "player", [pokemon(), pokemon()])
        with self.assertRaises(ValidationError):
            self.store.observe(ROOM, "player", [pokemon(level=True)])
        with self.assertRaises(ValidationError):
            self.store.observe(ROOM, "player", [pokemon(ivs={k: 32 for k in STATS})])
        with self.assertRaises(ValidationError):
            self.store.observe(ROOM, "player", [pokemon(evs={k: 100 for k in STATS})])

    def test_persistence_and_room_isolation(self):
        self.store.enroll(ROOM, "player", pokemon())
        self.store.close()
        self.store = AntiCheat(self.path)
        self.assertEqual(self.store.observe(ROOM, "player", [pokemon()])["alerts"], [])
        self.assertEqual(self.store.observe("PRUEBA02", "player", [pokemon()])["alerts"][0]["code"], "UNKNOWN_POKEMON")
        self.assertEqual(len(self.store.get_alerts("PRUEBA02")), 1)


class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = AntiCheat(Path(self.tmp.name) / "http.sqlite")
        self.http = AuditHTTPServer(("127.0.0.1", 0), ROOMS, self.store, ADMIN)
        self.thread = threading.Thread(target=self.http.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.http.shutdown()
        self.http.server_close()
        self.thread.join(timeout=2)
        self.store.close()
        self.tmp.cleanup()

    def request(self, method, path, data=None, token=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.http.server_port, timeout=2)
        headers = {"Authorization": "Bearer " + token} if token else {}
        if data is not None:
            headers["Content-Type"] = "application/json"
        conn.request(method, path, json.dumps(data) if data is not None else None, headers)
        response = conn.getresponse()
        result = response.status, response.read()
        conn.close()
        return result

    def test_end_to_end_http_detection_and_authentication(self):
        data = {"room": ROOM, "role": "player", "pokemon": pokemon()}
        self.assertEqual(self.request("POST", "/anticheat/enroll", data, PLAYER)[0], 401)
        self.assertEqual(self.request("POST", "/anticheat/enroll", data, ADMIN)[0], 201)
        self.assertEqual(self.request("POST", "/anticheat/observe",
                                      dict(data, pokemon=[pokemon(ability="Illegal")]), ADMIN)[0], 401)
        self.assertEqual(self.request("POST", "/anticheat/observe",
                                      dict(data, pokemon=[pokemon(ability="Illegal")]), PLAYER)[0], 200)
        self.assertEqual(self.request("GET", "/anticheat/alerts", token=PLAYER)[0], 401)
        status, raw = self.request("GET", "/anticheat/alerts?room=PRUEBA01", token=ADMIN)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(raw)["alerts"][0]["code"], "IMMUTABLE_CHANGED")

    def test_admin_revive_and_gym_endpoints(self):
        data = {"room": ROOM, "role": "player", "pokemon": pokemon()}
        self.request("POST", "/anticheat/enroll", data, ADMIN)
        self.request("POST", "/anticheat/observe", dict(data, pokemon=[pokemon(dead=True)]), PLAYER)
        gym = {"room": ROOM, "gym_id": "gym01"}
        self.assertEqual(self.request("POST", "/anticheat/gym", gym, PLAYER)[0], 401)
        self.assertEqual(self.request("POST", "/anticheat/gym", gym, ADMIN)[0], 201)
        self.assertEqual(self.request("POST", "/anticheat/revive",
                                      {"room": ROOM, "uid": "p001"}, ADMIN)[0], 200)


if __name__ == "__main__":
    unittest.main()
