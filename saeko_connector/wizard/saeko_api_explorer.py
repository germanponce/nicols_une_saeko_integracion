# -*- coding: utf-8 -*-
"""Explorador de API (solo lectura).

Permite lanzar GET arbitrarios contra SAEKO para descubrir estructuras y
endpoints no documentados (p. ej. pagos, cargos, CFDI). Cada llamada queda
en la bitácora.
"""
import json
import uuid

from odoo import api, fields, models, _
from odoo.exceptions import UserError

from ..services.jwt_auth import SaekoKeyError
from ..services.saeko_client import SaekoError, extract_items


class SaekoApiExplorer(models.TransientModel):
    _name = "saeko.api.explorer"
    _description = "SAEKO - Explorador de API"

    backend_id = fields.Many2one("saeko.backend", required=True)
    resource_id = fields.Many2one(
        "saeko.resource", string="Plantilla de recurso",
        help="Precarga ruta y parámetros desde el catálogo.")
    path = fields.Char(required=True, default="/api/v1/core/schools")
    parent_value = fields.Char(string="Valor de {parent_id} / {id}")
    query = fields.Char(string="Query string",
                        help="Ej.: include_fields=enrollments&limit=5&offset=0")
    status_code = fields.Integer(readonly=True)
    item_count = fields.Integer(string="Registros detectados", readonly=True)
    response = fields.Text(readonly=True)
    keys_summary = fields.Text(string="Estructura detectada", readonly=True)
    correlation_id = fields.Char(readonly=True)

    @api.onchange("resource_id")
    def _onchange_resource_id(self):
        if self.resource_id:
            self.path = self.resource_id.path
            params = self.resource_id._build_params()
            self.query = "&".join("%s=%s" % kv for kv in params.items())

    def _reopen(self):
        return {
            "type": "ir.actions.act_window", "res_model": self._name, "res_id": self.id,
            "view_mode": "form", "target": "new", "name": _("Explorador API SAEKO"),
        }

    def action_execute(self):
        self.ensure_one()
        path = (self.path or "").strip()
        if not path.startswith("/"):
            raise UserError(_("La ruta debe ser relativa al API URL y empezar con '/'."))
        if "{" in path:
            if not self.parent_value:
                raise UserError(_("La ruta contiene marcadores: indique su valor."))
            path = path.replace("{parent_id}", self.parent_value).replace("{id}", self.parent_value)
        params = {}
        for part in (self.query or "").split("&"):
            if "=" in part:
                key, val = part.split("=", 1)
                params[key.strip()] = val.strip()
        correlation = uuid.uuid4().hex
        try:
            client = self.backend_id._get_client(correlation, operation="explorer")
            data = client.get(path, params=params, operation="explorer")
            status = 200
        except (SaekoError, SaekoKeyError) as exc:
            data = getattr(exc, "response_body", None) or str(exc)
            status = getattr(exc, "status_code", 0) or 0
        items = extract_items(data) if status == 200 else []
        self.write({
            "status_code": status,
            "item_count": len(items),
            "response": json.dumps(data, ensure_ascii=False, indent=2, default=str)
            if not isinstance(data, str) else data,
            "keys_summary": self._summarize(items),
            "correlation_id": correlation,
        })
        return self._reopen()

    @staticmethod
    def _summarize(items):
        """Lista los campos encontrados con su tipo y un ejemplo."""
        if not items:
            return False
        fields_seen = {}
        for item in items[:200]:
            for key, val in item.items():
                if key not in fields_seen and val not in (None, "", [], {}):
                    sample = json.dumps(val, ensure_ascii=False, default=str)
                    fields_seen[key] = "%s = %s" % (type(val).__name__, sample[:80])
        for item in items[:1]:
            for key in item:
                fields_seen.setdefault(key, "null")
        return "\n".join("%s: %s" % (k, fields_seen[k]) for k in sorted(fields_seen))
