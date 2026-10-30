# -*- coding: utf-8 -*-
"""Cliente HTTP para la API REST de SAEKO.

Diseñado para ser independiente del ORM: recibe la configuración como dict y
callbacks para (a) persistir el token y (b) registrar cada llamada en la
bitácora. Así puede probarse aislado y reutilizarse desde crons, wizards o
scripts.

Características:
* OAuth2 JWT Bearer (RS256) + refresh_token, con renovación anticipada.
* Reintento automático ante 401 (refresh → re-autenticación).
* Reintentos con backoff exponencial ante 429/5xx/timeouts (respeta Retry-After).
* Paginación ``limit``/``offset`` + ``sort_by`` para resultados consistentes.
* Enmascarado de secretos en todo lo que se registra.
"""
import json
import logging
import time
import uuid
from urllib.parse import urlencode

import requests

from .jwt_auth import JWT_BEARER_GRANT, build_assertion

_logger = logging.getLogger(__name__)

SECRET_KEYS = {
    "assertion", "access_token", "refresh_token", "private_key", "password",
    "password_v1", "client_secret", "authorization", "token",
}
RETRY_STATUS = {408, 425, 429, 500, 502, 503, 504}
TOKEN_SAFETY_MARGIN = 120  # segundos antes de expirar en los que se renueva
MAX_LOG_BODY = 2 * 1024 * 1024  # 2 MB por cuerpo registrado


class SaekoError(Exception):
    def __init__(self, message, status_code=None, response_body=None, url=None):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.response_body = response_body
        self.url = url

    def __str__(self):
        if self.status_code:
            return "[HTTP %s] %s" % (self.status_code, self.message)
        return self.message


class SaekoAuthError(SaekoError):
    """Credenciales inválidas, usuario delegado inexistente o token revocado."""


class SaekoConnectionError(SaekoError):
    """Timeout, DNS, TLS u otro problema de red."""


# --------------------------------------------------------------------------- #
# Utilidades
# --------------------------------------------------------------------------- #
def mask_value(value, keep=4):
    if value is None:
        return None
    value = str(value)
    if len(value) <= keep:
        return "***"
    return "***" + value[-keep:]


def mask_secrets(data):
    """Enmascara recursivamente claves sensibles en dicts/listas."""
    if isinstance(data, dict):
        out = {}
        for key, val in data.items():
            if str(key).lower() in SECRET_KEYS:
                out[key] = mask_value(val)
            else:
                out[key] = mask_secrets(val)
        return out
    if isinstance(data, list):
        return [mask_secrets(v) for v in data]
    return data


def mask_headers(headers):
    out = {}
    for key, val in (headers or {}).items():
        if key.lower() in ("authorization", "authentication"):
            parts = str(val).split(" ", 1)
            out[key] = "%s %s" % (parts[0], mask_value(parts[-1])) if len(parts) == 2 else "***"
        else:
            out[key] = val
    return out


def to_text(data):
    if data is None:
        return False
    if isinstance(data, (dict, list)):
        text = json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True, default=str)
    else:
        text = str(data)
    if len(text) > MAX_LOG_BODY:
        text = text[:MAX_LOG_BODY] + "\n... [truncado: %s caracteres en total]" % len(text)
    return text


def extract_items(data, response_key=None):
    """Normaliza la respuesta de un listado SAEKO a ``list[dict]``.

    SAEKO puede responder con un arreglo directo o con un objeto envolvente
    (``{"students": [...]}``). Si se configuró ``response_key`` se usa; si no,
    se toma la primera lista de objetos encontrada. Un objeto con ``id`` se
    interpreta como un único registro.
    """
    if data is None:
        return []
    if isinstance(data, list):
        return [d for d in data if isinstance(d, dict)]
    if isinstance(data, dict):
        if response_key:
            node = data
            for part in response_key.split("."):
                node = node.get(part) if isinstance(node, dict) else None
            if isinstance(node, list):
                return [d for d in node if isinstance(d, dict)]
            if isinstance(node, dict):
                return [node]
            return []
        for val in data.values():
            if isinstance(val, list) and (not val or isinstance(val[0], dict)):
                return [d for d in val if isinstance(d, dict)]
        if "id" in data:
            return [data]
    return []


# --------------------------------------------------------------------------- #
# Cliente
# --------------------------------------------------------------------------- #
class SaekoClient:
    """
    :param config: dict con ``auth_url, api_url, client_id, private_key_id,
        private_key, user_email, scope, timeout, max_retries, backoff,
        verify_ssl, user_agent``.
    :param token_state: dict ``access_token, refresh_token, expires_at`` (epoch).
    :param on_token: callback(dict) al obtener/renovar/invalidar el token.
    :param on_log: callback(dict) por cada intento HTTP (bitácora).
    """

    def __init__(self, config, token_state=None, on_token=None, on_log=None,
                 session=None, correlation_id=None):
        self.config = dict(config)
        self.token = dict(token_state or {})
        self.on_token = on_token
        self.on_log = on_log
        self.session = session or requests.Session()
        self.correlation_id = correlation_id or uuid.uuid4().hex
        self.timeout = float(self.config.get("timeout") or 30)
        self.max_retries = int(self.config.get("max_retries") if self.config.get("max_retries") is not None else 3)
        self.backoff = float(self.config.get("backoff") or 1.0)
        self.verify = self.config.get("verify_ssl", True)
        self.operation = "api"

    # ------------------------------------------------------------- helpers
    def _url(self, path):
        if path.startswith("http://") or path.startswith("https://"):
            return path
        base = (self.config.get("api_url") or "").rstrip("/")
        return "%s/%s" % (base, path.lstrip("/"))

    def _base_headers(self):
        return {
            "Accept": "application/json",
            "Content-Type": "application/json; charset=utf-8",
            "User-Agent": self.config.get("user_agent") or "Odoo-SAEKO-Connector/20.0",
            "X-Correlation-Id": self.correlation_id,
        }

    def _emit_log(self, **entry):
        entry.setdefault("correlation_id", self.correlation_id)
        entry.setdefault("operation", self.operation)
        if self.on_log:
            try:
                self.on_log(entry)
            except Exception:  # noqa: BLE001 - la bitácora nunca debe romper la sync
                _logger.exception("SAEKO: no se pudo registrar la bitácora")

    def _set_token(self, data):
        now = int(time.time())
        expires_in = int(data.get("expires_in") or 3600)
        self.token = {
            "access_token": data.get("access_token"),
            "refresh_token": data.get("refresh_token") or self.token.get("refresh_token"),
            "expires_at": int(data.get("created_at") or now) + expires_in,
            "token_type": data.get("token_type") or "bearer",
            "scope": data.get("scope"),
        }
        if self.on_token:
            self.on_token(dict(self.token))

    def clear_token(self):
        self.token = {}
        if self.on_token:
            self.on_token({})

    @property
    def token_valid(self):
        return bool(
            self.token.get("access_token")
            and int(self.token.get("expires_at") or 0) - TOKEN_SAFETY_MARGIN > time.time()
        )

    # ------------------------------------------------------------- raw HTTP
    def _send(self, method, url, params=None, body=None, headers=None, log_body=None,
              operation=None, endpoint=None):
        """Un intento HTTP + registro en bitácora. No reintenta."""
        headers = headers or {}
        full_url = url + ("?" + urlencode(params, doseq=True) if params else "")
        start = time.monotonic()
        response, error, status = None, None, None
        try:
            response = self.session.request(
                method, url, params=params,
                data=json.dumps(body) if body is not None else None,
                headers=headers, timeout=self.timeout, verify=self.verify,
            )
            status = response.status_code
        except requests.exceptions.RequestException as exc:
            error = exc
        duration = int((time.monotonic() - start) * 1000)

        resp_data, resp_text = None, None
        if response is not None:
            resp_text = response.text
            try:
                resp_data = response.json() if resp_text else None
            except ValueError:
                resp_data = None
        logged_resp = mask_secrets(resp_data) if resp_data is not None else resp_text
        self._emit_log(
            operation=operation or self.operation,
            method=method,
            url=full_url,
            endpoint=endpoint or url,
            params=params or {},
            request_headers=mask_headers(headers),
            request_body=mask_secrets(log_body if log_body is not None else body),
            status_code=status,
            response_headers=dict(response.headers) if response is not None else {},
            response_body=logged_resp,
            response_size=len(response.content) if response is not None else 0,
            duration_ms=duration,
            success=bool(response is not None and response.ok),
            error_message=(str(error) if error else (
                None if response is not None and response.ok else
                (resp_data or {}).get("error_description") if isinstance(resp_data, dict) else resp_text
            )),
        )
        if error is not None:
            raise SaekoConnectionError("Error de conexión: %s" % error, url=full_url) from error
        return response, resp_data

    # ------------------------------------------------------------- auth
    def authenticate(self):
        """Solicita un access token con un JWT firmado (delegación de autoridad)."""
        cfg = self.config
        assertion, payload = build_assertion(
            cfg.get("client_id"), cfg.get("user_email"), cfg.get("private_key_id"),
            cfg.get("private_key"), scope=cfg.get("scope") or "admin",
        )
        body = {"grant_type": JWT_BEARER_GRANT, "assertion": assertion}
        log_body = {"grant_type": JWT_BEARER_GRANT, "assertion": assertion, "jwt_claims": payload}
        response, data = self._send(
            "POST", cfg.get("auth_url"), body=body, headers=self._base_headers(),
            log_body=log_body, operation="auth", endpoint="oauth/token (jwt-bearer)",
        )
        if response.status_code == 401:
            raise SaekoAuthError(
                "SAEKO rechazó el JWT (401). Verifique client_id, private_key_id, la llave "
                "privada, su vigencia y que el usuario delegado exista en el dominio.",
                401, data or response.text, cfg.get("auth_url"))
        if not response.ok or not isinstance(data, dict) or not data.get("access_token"):
            raise SaekoAuthError(
                "No se obtuvo access_token: %s" % ((data or {}).get("error_description")
                                                   if isinstance(data, dict) else response.text),
                response.status_code, data or response.text, cfg.get("auth_url"))
        self._set_token(data)
        return self.token

    def refresh(self):
        """Renueva con refresh_token; si fue revocado (401) re-autentica con JWT."""
        refresh_token = self.token.get("refresh_token")
        if not refresh_token:
            return self.authenticate()
        body = {"refresh_token": refresh_token, "scope": self.config.get("scope") or "admin",
                "grant_type": "refresh_token"}
        try:
            response, data = self._send(
                "POST", self.config.get("auth_url"), body=body, headers=self._base_headers(),
                operation="refresh", endpoint="oauth/token (refresh_token)",
            )
        except SaekoConnectionError:
            raise
        if response.status_code == 401 or not response.ok or not (data or {}).get("access_token"):
            # Refresh token revocado: invalidar y volver a delegar autoridad.
            self.clear_token()
            return self.authenticate()
        self._set_token(data)
        return self.token

    def ensure_token(self):
        if self.token_valid:
            return self.token
        if self.token.get("refresh_token"):
            return self.refresh()
        return self.authenticate()

    # ------------------------------------------------------------- API
    def request(self, method, path, params=None, body=None, operation=None):
        """Llamada autenticada con reintentos. Devuelve el JSON decodificado."""
        method = method.upper()
        url = self._url(path)
        self.ensure_token()
        auth_retried = False
        attempt = 0
        while True:
            headers = self._base_headers()
            headers["Authorization"] = "Bearer %s" % self.token.get("access_token")
            try:
                response, data = self._send(method, url, params=params, body=body,
                                            headers=headers, operation=operation, endpoint=path)
            except SaekoConnectionError:
                if attempt < self.max_retries:
                    self._sleep(attempt)
                    attempt += 1
                    continue
                raise

            if response.status_code == 401 and not auth_retried:
                auth_retried = True
                self.refresh()
                continue
            if response.status_code in RETRY_STATUS and attempt < self.max_retries:
                self._sleep(attempt, response.headers.get("Retry-After"))
                attempt += 1
                continue
            if not response.ok:
                desc = data.get("error_description") if isinstance(data, dict) else None
                exc_cls = SaekoAuthError if response.status_code in (401, 403) else SaekoError
                raise exc_cls(desc or response.reason or "Error HTTP", response.status_code,
                              data if data is not None else response.text, url)
            return data

    def get(self, path, params=None, operation=None):
        return self.request("GET", path, params=params, operation=operation)

    def iterate(self, path, params=None, paginate=False, page_size=100, response_key=None,
                sort_by="id:asc", max_pages=10000, operation=None):
        """Generador de páginas ``(items, page_number)``."""
        params = dict(params or {})
        if not paginate:
            data = self.get(path, params=params, operation=operation)
            yield extract_items(data, response_key), 1
            return
        if sort_by:
            params.setdefault("sort_by", sort_by)
        offset, page = 0, 1
        while page <= max_pages:
            page_params = dict(params, limit=page_size, offset=offset)
            data = self.get(path, params=page_params, operation=operation)
            items = extract_items(data, response_key)
            yield items, page
            if len(items) < page_size:
                return
            offset += page_size
            page += 1

    def _sleep(self, attempt, retry_after=None):
        delay = self.backoff * (2 ** attempt)
        if retry_after:
            try:
                delay = max(delay, float(retry_after))
            except ValueError:
                pass
        time.sleep(min(delay, 60))
