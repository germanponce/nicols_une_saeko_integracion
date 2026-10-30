# -*- coding: utf-8 -*-
"""SAEKO simulado (sin dependencias de Odoo).

Implementa el flujo OAuth2 JWT + refresh y un subconjunto de endpoints con
la forma documentada en apidoc.saeko.io. Lo usan las pruebas unitarias y el
servidor HTTP local ``tools/mock_saeko_server.py``.
"""
import json
import secrets
import time
from urllib.parse import parse_qs, urlparse

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

try:
    from ..services.jwt_auth import JWT_BEARER_GRANT, verify_assertion
except ImportError:  # modo standalone (tools/mock_saeko_server.py)
    from jwt_auth import JWT_BEARER_GRANT, verify_assertion


def generate_keypair():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption()).decode()
    public_pem = key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()
    return private_pem, public_pem


class FakeSaeko:
    CLIENT_ID = "odoo-test-client"
    USER_EMAIL = "api@universidad.test"

    def __init__(self, public_pem, students=250, token_ttl=3600):
        self.public_pem = public_pem
        self.token_ttl = token_ttl
        self.tokens = {}          # access_token -> expires_at
        self.refresh_tokens = set()
        self.calls = []
        self.fail_next = []       # lista de códigos HTTP a devolver en las próximas llamadas API
        self.schools = [{"id": 1, "name": "Plantel Centro", "logo_url": None},
                        {"id": 2, "name": "Plantel Norte", "logo_url": None}]
        self.terms = {
            1: [{"id": 10, "name": "2026-2027 A", "term_type": 4, "begins_at": "2026-08-17",
                 "ends_at": "2027-01-15", "is_current": True, "periods": []},
                {"id": 9, "name": "2025-2026 B", "term_type": 4, "begins_at": "2026-01-19",
                 "ends_at": "2026-06-30", "is_current": False, "periods": []}],
            2: [{"id": 20, "name": "2026-2027 A", "term_type": 4, "begins_at": "2026-08-17",
                 "ends_at": "2027-01-15", "is_current": True, "periods": []}],
        }
        self.programs = {1: [{"id": 100, "name": "Lic. en Derecho", "level": 2, "term_type": 4,
                              "terms_quantity": 9, "rvoe": "LOE2020"}],
                         2: [{"id": 200, "name": "Maestría en Educación", "level": 1,
                              "term_type": 4, "terms_quantity": 4}]}
        self.students = {
            10: [self._student(i, 10) for i in range(1, students + 1)],
            20: [self._student(i, 20) for i in range(5001, 5011)],
        }
        self.employees = {1: [{"id": 700, "name": "Ana", "first_surname": "López",
                               "second_surname": "Ruiz", "curp": "LORA800101MDFPZN09",
                               "rfc": "LORA800101AB1", "cost_per_hour": "350.00",
                               "professor_details": {"grade_level": "Maestría"},
                               "school_ids": [1]}],
                          2: []}

    @staticmethod
    def _student(i, term):
        return {"id": i, "name": "Alumno %s" % i, "surnames": ["Pérez", "Gómez"],
                "student_id": "A%05d" % i, "gender": 1 + i % 2, "enrollment_id": term * 100000 + i}

    # ------------------------------------------------------------------ dispatch
    def handle(self, method, url, body=None, headers=None):
        parsed = urlparse(url)
        path = parsed.path
        params = {k: v[0] for k, v in parse_qs(parsed.query).items()}
        payload = json.loads(body) if body else {}
        self.calls.append((method, path, params))
        if path.endswith("/oauth/token"):
            return self._oauth(payload)
        auth = (headers or {}).get("Authorization", "")
        token = auth.split(" ", 1)[-1]
        if self.tokens.get(token, 0) < time.time():
            return 401, {"error_description": "User unauthorized"}
        if self.fail_next:
            return self.fail_next.pop(0), {"error_description": "Server error"}
        return self._api(method, path, params)

    def _issue(self):
        access, refresh = secrets.token_hex(16), secrets.token_hex(16)
        self.tokens[access] = time.time() + self.token_ttl
        self.refresh_tokens.add(refresh)
        return 200, {"access_token": access, "token_type": "bearer", "expires_in": self.token_ttl,
                     "refresh_token": refresh, "scope": "admin", "created_at": int(time.time())}

    def _oauth(self, payload):
        if payload.get("grant_type") == JWT_BEARER_GRANT:
            claims = verify_assertion(payload.get("assertion", ""), self.public_pem)
            if not claims or claims.get("iss") != self.CLIENT_ID or \
                    claims.get("sub") != self.USER_EMAIL:
                return 401, {"error_description": "User unauthorized"}
            return self._issue()
        if payload.get("grant_type") == "refresh_token":
            if payload.get("refresh_token") not in self.refresh_tokens:
                return 401, {"error_description": "User unauthorized"}
            self.refresh_tokens.discard(payload["refresh_token"])
            return self._issue()
        return 400, {"error_description": "Bad request"}

    def _api(self, method, path, params):
        if method != "GET":
            return 405, {"error_description": "Request not allowed"}
        parts = [p for p in path.split("/") if p]
        # /api/v1/core/schools
        if parts[-1] == "schools":
            return 200, self.schools
        if len(parts) >= 6 and parts[3] == "schools" and parts[5] == "terms":
            return 200, self.terms.get(int(parts[4]), [])
        if len(parts) >= 6 and parts[3] == "schools" and parts[5] == "programs":
            return 200, self.programs.get(int(parts[4]), [])
        if len(parts) >= 6 and parts[3] == "schools" and parts[5] == "employees":
            return 200, self.employees.get(int(parts[4]), [])
        if len(parts) >= 6 and parts[3] == "terms" and parts[5] == "students":
            rows = self.students.get(int(parts[4]), [])
            if "limit" in params:
                off, lim = int(params.get("offset", 0)), int(params["limit"])
                rows = rows[off:off + lim]
            # forma envuelta, para probar autodetección
            return 200, {"students": rows}
        if len(parts) >= 5 and parts[3] == "students":
            sid = int(parts[4])
            for rows in self.students.values():
                for row in rows:
                    if row["id"] == sid:
                        return 200, dict(row, curp="CURP%014d" % sid, enrollments=[])
            return 404, {"error_description": "Resource not found"}
        return 404, {"error_description": "Invalid Path"}


class FakeResponse:
    """Respuesta mínima compatible con ``requests.Response``."""

    def __init__(self, status, data):
        self.status_code = status
        self._data = data
        self.text = json.dumps(data) if data is not None else ""
        self.content = self.text.encode()
        self.headers = {"Content-Type": "application/json"}
        self.ok = 200 <= status < 400
        self.reason = "OK" if self.ok else "Error"

    def json(self):
        return json.loads(self.text) if self.text else None


class FakeSession:
    def __init__(self, fake):
        self.fake = fake

    def request(self, method, url, params=None, data=None, headers=None, timeout=None,
                verify=None):
        from urllib.parse import urlencode
        if params:
            url = url + "?" + urlencode(params)
        status, payload = self.fake.handle(method, url, data, headers)
        return FakeResponse(status, payload)
