# -*- coding: utf-8 -*-
from unittest.mock import patch

from odoo.tests import TransactionCase, tagged

from ..services import jwt_auth
from .fake_saeko import FakeSaeko, FakeSession, generate_keypair

CLIENT_PATH = "odoo.addons.saeko_connector.services.saeko_client.requests.Session"


@tagged("post_install", "-at_install", "saeko")
class TestSaekoConnector(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.private_pem, cls.public_pem = generate_keypair()
        cls.backend = cls.env["saeko.backend"].create({
            "name": "SAEKO Test",
            "auth_url": "https://auth.saeko.test/oauth/token",
            "api_url": "https://api.saeko.test",
            "client_id": FakeSaeko.CLIENT_ID,
            "private_key_id": "key-1",
            "private_key": cls.private_pem.replace("\n", "\\n"),  # como viene en el YAML
            "user_email": FakeSaeko.USER_EMAIL,
            "backoff": 0,
        })

    def setUp(self):
        super().setUp()
        self.fake = FakeSaeko(self.public_pem)
        patcher = patch(CLIENT_PATH, return_value=FakeSession(self.fake))
        patcher.start()
        self.addCleanup(patcher.stop)

    def _res(self, *codes):
        Resource = self.env["saeko.resource"]
        return Resource.search([("code", "in", list(codes))])

    def _logs(self):
        return self.env["saeko.api.log"].search([("backend_id", "=", self.backend.id)])

    # ------------------------------------------------------------------ JWT
    def test_01_jwt_signature_and_claims(self):
        token, payload = jwt_auth.build_assertion(
            "cid", "u@x.mx", "kid", self.private_pem, iat=1700000000)
        claims = jwt_auth.verify_assertion(token, self.public_pem)
        self.assertEqual(claims, payload)
        import hashlib
        self.assertEqual(claims["jti"], hashlib.md5(b"kid:1700000000").hexdigest())
        self.assertEqual(claims["iat"], 1700000000)
        self.assertEqual(claims["scope"], "admin")
        self.assertTrue(self.backend.key_fingerprint)

    # ------------------------------------------------------------------ conexión
    def test_02_connection_ok_and_secrets_masked(self):
        action = self.backend.action_test_connection()
        self.assertEqual(action["params"]["type"], "success", action["params"]["message"])
        self.assertEqual(self.backend.state, "connected")
        self.assertEqual(self.backend.token_status, "valid")
        logs = self._logs()
        self.assertEqual(set(logs.mapped("operation")), {"auth", "test"})
        everything = "".join((l.request_body or "") + (l.request_headers or "") +
                             (l.response_body or "") for l in logs)
        token = self.env["saeko.token"].search([("backend_id", "=", self.backend.id)])
        self.assertNotIn(token.access_token, everything)
        self.assertNotIn(token.refresh_token, everything)
        self.assertNotIn("PRIVATE KEY", everything)
        self.assertIn("jwt_claims", everything)  # claims auditables, firma enmascarada

    def test_03_connection_rejected(self):
        self.fake.USER_EMAIL = "otro@universidad.test"
        action = self.backend.action_test_connection()
        self.assertEqual(action["params"]["type"], "danger")
        self.assertEqual(self.backend.state, "error")
        self.assertIn("401", self.backend.last_error)
        self.assertTrue(self._logs().filtered(lambda l: l.status_code == 401))

    def test_04_expired_token_is_refreshed(self):
        self.backend.action_test_connection()
        self.fake.tokens.clear()  # SAEKO invalida el access token
        client = self.backend._get_client()
        data = client.get("/api/v1/core/schools")
        self.assertEqual(len(data), 2)
        self.assertIn("refresh", self._logs().mapped("operation"))

    def test_05_retry_on_5xx(self):
        self.backend.action_test_connection()
        self.fake.fail_next = [503, 502]
        client = self.backend._get_client()
        self.assertEqual(len(client.get("/api/v1/core/schools")), 2)
        self.assertEqual(len(self._logs().filtered(lambda l: l.status_code in (502, 503))), 2)

    # ------------------------------------------------------------------ sync
    def test_06_sync_landing_history_missing(self):
        self.backend.action_test_connection()
        student = self._res("student")
        student.write({"paginate": True, "page_size": 100})
        job = self.backend._run_sync(self._res("student", "employee", "program"))
        self.assertEqual(job.state, "done", job.message)
        Raw = self.env["saeko.raw.record"]
        dom = [("backend_id", "=", self.backend.id)]
        count = lambda code: Raw.search_count(dom + [("resource_code", "=", code)])  # noqa: E731
        self.assertEqual(count("school"), 2)       # padre agregado automáticamente
        self.assertEqual(count("term"), 3)
        self.assertEqual(count("student"), 260)    # solo ciclos vigentes (10 y 20)
        self.assertEqual(count("employee"), 1)
        self.assertEqual(count("program"), 2)
        # 3 páginas para el ciclo 10 (250 alumnos / 100) + 1 para el ciclo 20
        pages = [c for c in self.fake.calls if c[1].endswith("/students")]
        self.assertEqual(len(pages), 4)
        self.assertEqual(job.created_count, 2 + 3 + 2 + 260 + 1)

        # Cambio en SAEKO + baja de un alumno
        self.fake.students[10][0]["name"] = "Alumno Uno Renombrado"
        self.fake.students[10].pop()
        job2 = self.backend._run_sync(student)
        self.assertEqual(job2.updated_count, 1)
        self.assertEqual(job2.missing_count, 1)
        changed = Raw.search(dom + [("resource_code", "=", "student"), ("saeko_id", "=", "1")])
        self.assertEqual(changed.version, 2)
        self.assertEqual(changed.change_type, "updated")
        self.assertEqual(len(changed.history_ids), 1)
        self.assertIn("Alumno 1", changed.history_ids.payload)
        self.assertEqual(Raw.search_count(dom + [("missing", "=", True)]), 1)
        # Las llamadas del job quedan correlacionadas
        self.assertTrue(job2.log_count > 0)

    def test_07_resource_failure_is_isolated(self):
        self.backend.action_test_connection()
        job = self.backend._run_sync(self._res("school", "country"))
        self.assertEqual(job.state, "partial")   # country → 404 en el simulador
        self.assertEqual(job.error_count, 1)
        line = self.backend.resource_line_ids.filtered(lambda l: l.resource_id.code == "country")
        self.assertEqual(line.last_state, "error")

    def test_08_detail_fetch(self):
        self.backend.action_test_connection()
        student = self._res("student")
        student.fetch_detail = True
        self.fake.students[10] = self.fake.students[10][:3]
        self.backend._run_sync(student)
        raw = self.env["saeko.raw.record"].search([
            ("backend_id", "=", self.backend.id), ("resource_code", "=", "student"),
            ("saeko_id", "=", "2")])
        self.assertIn("curp", raw._get_payload())

    def test_09_cron_respects_schedule(self):
        self.backend.action_test_connection()
        self.backend.sync_enabled = True
        self.backend.resource_line_ids.write({"scheduled": False})
        line = self.backend.resource_line_ids.filtered(lambda l: l.resource_id.code == "school")
        line.write({"scheduled": True, "next_run": False})
        self.env["saeko.backend"]._cron_sync()
        self.assertEqual(line.last_state, "ok")
        self.assertTrue(line.next_run)
        calls = len(self.fake.calls)
        self.env["saeko.backend"]._cron_sync()     # no vence aún: no hay nuevas llamadas
        self.assertEqual(len(self.fake.calls), calls)

    def test_10_credentials_import(self):
        backend = self.env["saeko.backend"].create({"name": "Import"})
        yaml = (
            'service_account:\n'
            '  auth_url: "https://auth.saeko.test/oauth/token"\n'
            '  api_url: "https://api.saeko.test"\n'
            '  client_id: "%s"\n'
            '  private_key_id: "key-2"\n'
            '  private_key: "%s"\n'
            '  expires_at: "2030-01-01T00:00:00Z"\n'
        ) % (FakeSaeko.CLIENT_ID, self.private_pem.replace("\n", "\\n"))
        wizard = self.env["saeko.credentials.import"].create({
            "backend_id": backend.id, "content": yaml, "user_email": FakeSaeko.USER_EMAIL})
        wizard.action_import()
        self.assertEqual(backend.private_key_id, "key-2")
        self.assertEqual(str(backend.key_expires_at), "2030-01-01 00:00:00")
        self.assertEqual(backend.key_fingerprint, self.backend.key_fingerprint)
        backend.action_test_connection()
        self.assertEqual(backend.state, "connected")

    def test_11_explorer(self):
        self.backend.action_test_connection()
        wiz = self.env["saeko.api.explorer"].create({
            "backend_id": self.backend.id, "path": "/api/v1/core/terms/{parent_id}/students",
            "parent_value": "20", "query": "limit=5&offset=0"})
        wiz.action_execute()
        self.assertEqual(wiz.status_code, 200)
        self.assertEqual(wiz.item_count, 5)
        self.assertIn("student_id", wiz.keys_summary)
        self.assertTrue(self._logs().filtered(lambda l: l.operation == "explorer"))
