#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Servidor SAEKO simulado para pruebas locales (sin credenciales reales).

Uso:
    python3 tools/mock_saeko_server.py --port 8765

Al iniciar imprime un bloque ``service_account`` listo para pegar en
Odoo → SAEKO → Conexiones → "Importar Service Account" (con el usuario
delegado indicado). Las llaves se guardan en ``tools/.mock_keys`` para que
sobrevivan reinicios. Solo para entornos de prueba: usa HTTP sin TLS.
"""
import argparse
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "services"))
sys.path.insert(0, os.path.join(HERE, "..", "tests"))

from fake_saeko import FakeSaeko, generate_keypair  # noqa: E402


def load_keys():
    path = os.path.join(HERE, ".mock_keys")
    if os.path.exists(path):
        with open(path) as fh:
            data = json.load(fh)
        return data["private"], data["public"]
    private, public = generate_keypair()
    with open(path, "w") as fh:
        json.dump({"private": private, "public": public}, fh)
    os.chmod(path, 0o600)
    return private, public


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--students", type=int, default=250)
    args = parser.parse_args()

    private, public = load_keys()
    fake = FakeSaeko(public, students=args.students)
    base = "http://%s:%s" % (args.host, args.port)

    class Handler(BaseHTTPRequestHandler):
        def _dispatch(self, method):
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length).decode() if length else None
            status, payload = fake.handle(method, self.path, body, dict(self.headers))
            raw = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self):  # noqa: N802
            self._dispatch("GET")

        def do_POST(self):  # noqa: N802
            self._dispatch("POST")

    print("service_account:")
    print('  auth_url: "%s/oauth/token"' % base)
    print('  api_url: "%s"' % base)
    print('  client_id: "%s"' % FakeSaeko.CLIENT_ID)
    print('  private_key_id: "mock-key-1"')
    print('  private_key: "%s"' % private.strip().replace("\n", "\\n"))
    print('  expires_at: "2030-01-01T00:00:00Z"')
    print("# usuario delegado: %s" % FakeSaeko.USER_EMAIL)
    print("Escuchando en %s ..." % base, flush=True)
    ThreadingHTTPServer((args.host, args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
