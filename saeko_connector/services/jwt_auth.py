# -*- coding: utf-8 -*-
"""Construcción del JWT (RS256) para el flujo OAuth2 "JWT Bearer" de SAEKO.

No depende del ORM de Odoo para poder probarse de forma aislada.
Solo requiere la librería ``cryptography`` (dependencia estándar de Odoo).

Payload según https://apidoc.saeko.io/#how-to-create-access-token-delegate-authority::

    {
      "iss": client_id,
      "sub": user_email,
      "scope": "admin",
      "iat": <epoch>,
      "jti": MD5("<private_key_id>:<epoch>")
    }
"""
import base64
import hashlib
import json
import time

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

JWT_BEARER_GRANT = "urn:ietf:params:oauth:grant-type:jwt-bearer"


class SaekoKeyError(ValueError):
    """La llave privada no es válida o no pudo cargarse."""


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(data: str) -> bytes:
    padding_len = -len(data) % 4
    return base64.urlsafe_b64decode(data + "=" * padding_len)


def normalize_pem(private_key: str) -> str:
    """Acepta la llave tal como viene en el YAML de SAEKO (con ``\\n`` literales,
    comillas, espacios) y devuelve un PEM válido."""
    if not private_key:
        raise SaekoKeyError("La llave privada está vacía.")
    pem = private_key.strip().strip('"').strip("'")
    pem = pem.replace("\\r\\n", "\n").replace("\\n", "\n").replace("\r\n", "\n")
    return pem.strip() + "\n"


def load_private_key(private_key: str):
    pem = normalize_pem(private_key)
    try:
        return serialization.load_pem_private_key(pem.encode("utf-8"), password=None)
    except Exception as exc:  # noqa: BLE001 - re-lanzamos con mensaje claro
        raise SaekoKeyError(
            "No se pudo cargar la llave privada RSA (formato PEM esperado): %s" % exc
        ) from exc


def build_payload(client_id, user_email, private_key_id, scope="admin", iat=None):
    iat = int(iat if iat is not None else time.time())
    jti = hashlib.md5(("%s:%s" % (private_key_id, iat)).encode("utf-8")).hexdigest()
    return {
        "iss": client_id,
        "sub": user_email,
        "scope": scope or "admin",
        "iat": iat,
        "jti": jti,
    }


def build_assertion(client_id, user_email, private_key_id, private_key,
                    scope="admin", iat=None):
    """Devuelve ``(jwt_string, payload_dict)`` firmado con RS256."""
    if not client_id or not user_email or not private_key_id:
        raise SaekoKeyError(
            "client_id, private_key_id y el correo del usuario delegado son obligatorios."
        )
    key = load_private_key(private_key)
    header = {"typ": "JWT", "alg": "RS256"}
    payload = build_payload(client_id, user_email, private_key_id, scope, iat)
    signing_input = "%s.%s" % (
        _b64url(json.dumps(header, separators=(",", ":")).encode("utf-8")),
        _b64url(json.dumps(payload, separators=(",", ":")).encode("utf-8")),
    )
    signature = key.sign(signing_input.encode("ascii"), padding.PKCS1v15(), hashes.SHA256())
    return "%s.%s" % (signing_input, _b64url(signature)), payload


def verify_assertion(token, public_key_pem):
    """Verifica la firma (útil en pruebas y en el servidor simulado)."""
    header_b64, payload_b64, sig_b64 = token.split(".")
    public_key = serialization.load_pem_public_key(public_key_pem.encode("utf-8"))
    try:
        public_key.verify(
            _b64url_decode(sig_b64),
            ("%s.%s" % (header_b64, payload_b64)).encode("ascii"),
            padding.PKCS1v15(),
            hashes.SHA256(),
        )
    except InvalidSignature:
        return None
    return json.loads(_b64url_decode(payload_b64))


def key_fingerprint(private_key):
    """Huella SHA-256 (corta) de la llave pública derivada; sirve para auditar
    qué llave se usó sin exponerla."""
    key = load_private_key(private_key)
    der = key.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    digest = hashlib.sha256(der).hexdigest()
    return ":".join(digest[i:i + 2] for i in range(0, 32, 2)).upper()
