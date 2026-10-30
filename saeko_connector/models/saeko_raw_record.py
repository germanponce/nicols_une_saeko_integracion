# -*- coding: utf-8 -*-
"""Zona de aterrizaje (landing zone) de datos crudos de SAEKO.

Cada registro guarda el JSON tal como llegó, su hash SHA-256 y una versión.
Si el contenido cambia, la versión anterior se conserva en el historial,
lo que permite auditar qué dijo SAEKO y cuándo. Las fases siguientes
procesan estos registros (state = pending) para mapearlos a modelos Odoo.
"""
import json

from odoo import api, fields, models, _

from .saeko_backend import payload_hash


class SaekoRawRecord(models.Model):
    _name = "saeko.raw.record"
    _description = "SAEKO - Dato crudo"
    _order = "resource_id, id desc"
    _rec_names_search = ["name", "saeko_id"]

    name = fields.Char(string="Descripción", index="trigram")
    backend_id = fields.Many2one("saeko.backend", required=True, ondelete="cascade", index=True)
    company_id = fields.Many2one(related="backend_id.company_id", store=True)
    resource_id = fields.Many2one("saeko.resource", required=True, ondelete="restrict", index=True)
    resource_code = fields.Char(related="resource_id.code", store=True, index=True)
    saeko_id = fields.Char(string="ID SAEKO", required=True, index=True)
    context_key = fields.Char(
        string="Contexto", default="", index=True,
        help="ID del registro padre con el que se obtuvo (p. ej. term_id para alumnos).")
    parent_raw_id = fields.Many2one("saeko.raw.record", string="Registro padre",
                                    ondelete="set null", index=True)
    payload = fields.Text(string="JSON")
    payload_hash = fields.Char(string="SHA-256", index=True)
    version = fields.Integer(default=1)
    first_seen = fields.Datetime(string="Primera vez visto")
    last_seen = fields.Datetime(string="Última vez visto")
    last_changed = fields.Datetime(string="Último cambio")
    change_type = fields.Selection(
        [("new", "Nuevo"), ("updated", "Modificado"), ("unchanged", "Sin cambio")],
        string="Último resultado")
    missing = fields.Boolean(string="Ausente en SAEKO", index=True)
    missing_since = fields.Datetime()
    state = fields.Selection(
        [("pending", "Pendiente de procesar"), ("processed", "Procesado"),
         ("error", "Error"), ("ignored", "Ignorado")],
        default="pending", required=True, index=True,
        help="Estado para el mapeo a modelos Odoo (fases 2+).")
    process_message = fields.Text()
    odoo_model = fields.Char(string="Modelo Odoo")
    odoo_res_id = fields.Integer(string="ID Odoo")
    last_job_id = fields.Many2one("saeko.sync.job", string="Última ejecución",
                                  ondelete="set null", index=True)
    history_ids = fields.One2many("saeko.raw.history", "raw_id", string="Historial")
    history_count = fields.Integer(compute="_compute_history_count")

    _raw_uniq = models.Constraint(
        "UNIQUE(backend_id, resource_id, context_key, saeko_id)",
        "Registro crudo duplicado para el mismo backend/recurso/contexto.")

    def _compute_history_count(self):
        data = self.env["saeko.raw.history"]._read_group(
            [("raw_id", "in", self.ids)], ["raw_id"], ["__count"])
        counts = {r.id: c for r, c in data}
        for rec in self:
            rec.history_count = counts.get(rec.id, 0)

    def _get_payload(self):
        self.ensure_one()
        try:
            return json.loads(self.payload or "{}")
        except ValueError:
            return {}

    # ------------------------------------------------------------------ upsert
    @api.model
    def _upsert_batch(self, backend, resource, items, context_key, parent_raw, job):
        """Inserta/actualiza una página de registros. Devuelve (contadores, ids_vistos)."""
        counts = {"fetched": len(items), "created": 0, "updated": 0, "unchanged": 0, "errors": 0}
        id_field = resource.id_field or "id"
        now = fields.Datetime.now()
        by_id = {}
        for item in items:
            rid = item.get(id_field)
            if rid in (None, "", False):
                counts["errors"] += 1
                continue
            by_id[str(rid)] = item
        if not by_id:
            return counts, set()

        existing = self.search([
            ("backend_id", "=", backend.id), ("resource_id", "=", resource.id),
            ("context_key", "=", context_key or ""), ("saeko_id", "in", list(by_id))])
        existing_map = {r.saeko_id: r for r in existing}

        to_create, history_vals, unchanged = [], [], self.browse()
        for sid, item in by_id.items():
            digest = payload_hash(item)
            pretty = json.dumps(item, ensure_ascii=False, indent=2, sort_keys=True, default=str)
            rec = existing_map.get(sid)
            if not rec:
                to_create.append({
                    "backend_id": backend.id, "resource_id": resource.id, "saeko_id": sid,
                    "context_key": context_key or "",
                    "parent_raw_id": parent_raw.id if parent_raw else False,
                    "name": resource._display_name_from_payload(item),
                    "payload": pretty, "payload_hash": digest, "version": 1,
                    "first_seen": now, "last_seen": now, "last_changed": now,
                    "change_type": "new", "state": "pending", "last_job_id": job.id,
                })
            elif rec.payload_hash != digest:
                history_vals.append({
                    "raw_id": rec.id, "version": rec.version, "payload": rec.payload,
                    "payload_hash": rec.payload_hash, "captured_at": rec.last_changed or now,
                    "replaced_at": now, "job_id": job.id,
                })
                rec.write({
                    "name": resource._display_name_from_payload(item),
                    "payload": pretty, "payload_hash": digest, "version": rec.version + 1,
                    "last_seen": now, "last_changed": now, "change_type": "updated",
                    "state": "pending", "missing": False, "missing_since": False,
                    "last_job_id": job.id,
                })
                counts["updated"] += 1
            else:
                unchanged |= rec
        if to_create:
            self.create(to_create)
            counts["created"] += len(to_create)
        if history_vals:
            self.env["saeko.raw.history"].create(history_vals)
        if unchanged:
            unchanged.write({"last_seen": now, "change_type": "unchanged", "missing": False,
                             "missing_since": False, "last_job_id": job.id})
            counts["unchanged"] += len(unchanged)
        return counts, set(by_id)

    @api.model
    def _mark_missing(self, backend, resource, context_key, seen_ids):
        stale = self.search([
            ("backend_id", "=", backend.id), ("resource_id", "=", resource.id),
            ("context_key", "=", context_key or ""), ("missing", "=", False),
            ("saeko_id", "not in", list(seen_ids) or [""])])
        if stale:
            stale.write({"missing": True, "missing_since": fields.Datetime.now()})
        return len(stale)

    # ------------------------------------------------------------------ actions
    def action_reset_pending(self):
        self.write({"state": "pending", "process_message": False})

    def action_ignore(self):
        self.write({"state": "ignored"})

    def action_view_history(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window", "name": _("Historial de %s", self.display_name),
            "res_model": "saeko.raw.history", "view_mode": "list,form",
            "domain": [("raw_id", "=", self.id)],
        }


class SaekoRawHistory(models.Model):
    """Versiones anteriores del JSON de un dato crudo."""
    _name = "saeko.raw.history"
    _description = "SAEKO - Historial de dato crudo"
    _order = "raw_id, version desc"

    raw_id = fields.Many2one("saeko.raw.record", required=True, ondelete="cascade", index=True)
    backend_id = fields.Many2one(related="raw_id.backend_id", store=True)
    resource_id = fields.Many2one(related="raw_id.resource_id", store=True)
    saeko_id = fields.Char(related="raw_id.saeko_id")
    version = fields.Integer(required=True)
    payload = fields.Text(string="JSON")
    payload_hash = fields.Char(string="SHA-256")
    captured_at = fields.Datetime(string="Vigente desde")
    replaced_at = fields.Datetime(string="Reemplazado el")
    job_id = fields.Many2one("saeko.sync.job", string="Ejecución que lo reemplazó",
                             ondelete="set null")
