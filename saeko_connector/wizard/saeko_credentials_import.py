# -*- coding: utf-8 -*-
"""Importa el bloque ``service_account`` que entrega soporte SAEKO.

Acepta YAML (formato de la documentación) o JSON, sin depender de PyYAML::

    service_account:
      auth_url: "https://..."
      api_url: "https://..."
      client_id: "..."
      private_key_id: "..."
      private_key: "-----BEGIN RSA PRIVATE KEY-----\\n...\\n-----END RSA PRIVATE KEY-----"
      expires_at: "2021-01-01T00:00:00Z"
"""
import json
import re
from datetime import timezone

from dateutil import parser as date_parser

from odoo import fields, models, _
from odoo.exceptions import UserError

KEYS = ("auth_url", "api_url", "client_id", "private_key_id", "private_key", "expires_at")
LINE_RE = re.compile(r"^\s*([A-Za-z_]+)\s*:\s*(.*)$")


def parse_service_account(text):
    text = (text or "").strip()
    if not text:
        return {}
    if text.startswith("{"):
        data = json.loads(text)
        data = data.get("service_account", data)
        return {k: data.get(k) for k in KEYS if data.get(k)}
    result, current_key, block = {}, None, []
    for line in text.splitlines():
        match = LINE_RE.match(line)
        if match and match.group(1) in KEYS + ("service_account",):
            if current_key and block:
                result[current_key] = "\n".join(block)
            key, value = match.group(1), match.group(2).strip()
            current_key, block = (None, []) if key == "service_account" else (key, [])
            if current_key and value not in ("|", ">", "|-", ">-"):
                value = value.strip('"').strip("'")
                result[current_key] = value
                current_key = None if not value.startswith("-----BEGIN") or \
                    "-----END" in value else current_key
                block = [value] if current_key else []
        elif current_key:
            block.append(line.strip().strip('"'))
    if current_key and block:
        result[current_key] = "\n".join(block)
    return result


class SaekoCredentialsImport(models.TransientModel):
    _name = "saeko.credentials.import"
    _description = "SAEKO - Importar Service Account"

    backend_id = fields.Many2one("saeko.backend", required=True)
    content = fields.Text(string="Bloque service_account (YAML o JSON)", required=True)
    user_email = fields.Char(string="Usuario delegado (email)")

    def action_import(self):
        self.ensure_one()
        try:
            data = parse_service_account(self.content)
        except ValueError as exc:
            raise UserError(_("No se pudo interpretar el contenido: %s", exc)) from exc
        missing = [k for k in KEYS if k not in data]
        if missing:
            raise UserError(_("Faltan claves en el bloque: %s", ", ".join(missing)))
        vals = {k: data[k] for k in ("auth_url", "api_url", "client_id", "private_key_id",
                                       "private_key")}
        try:
            expires = date_parser.isoparse(data["expires_at"])
            if expires.tzinfo:
                expires = expires.astimezone(timezone.utc).replace(tzinfo=None)
            vals["key_expires_at"] = expires
        except (ValueError, TypeError) as exc:
            raise UserError(_("expires_at inválido: %s", data["expires_at"])) from exc
        if self.user_email:
            vals["user_email"] = self.user_email
        self.backend_id.sudo().write(vals)
        self.backend_id.message_post(body=_(
            "Credenciales del Service Account importadas (client_id %(cid)s, key id %(kid)s, "
            "vigencia %(exp)s).", cid=vals["client_id"], kid=vals["private_key_id"],
            exp=vals["key_expires_at"]))
        return {"type": "ir.actions.act_window_close"}
