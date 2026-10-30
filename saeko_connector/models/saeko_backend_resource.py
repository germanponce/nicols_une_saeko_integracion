# -*- coding: utf-8 -*-
from dateutil.relativedelta import relativedelta

from odoo import api, fields, models, _

from .saeko_resource import INTERVAL_TYPES


class SaekoBackendResource(models.Model):
    """Programación y estado de cada recurso dentro de un backend."""
    _name = "saeko.backend.resource"
    _description = "SAEKO - Recurso programado por backend"
    _order = "sequence, id"

    backend_id = fields.Many2one("saeko.backend", required=True, ondelete="cascade", index=True)
    resource_id = fields.Many2one("saeko.resource", required=True, ondelete="cascade", index=True)
    sequence = fields.Integer(related="resource_id.sequence", store=True)
    namespace = fields.Selection(related="resource_id.namespace")
    phase = fields.Selection(related="resource_id.phase")
    parent_resource_id = fields.Many2one(related="resource_id.parent_id", string="Padre")
    scheduled = fields.Boolean(default=True, string="Programado",
                               help="Si está activo, el cron lo ejecuta según su intervalo.")
    interval_number = fields.Integer(default=1, required=True)
    interval_type = fields.Selection(INTERVAL_TYPES, default="days", required=True)
    next_run = fields.Datetime(string="Próxima ejecución")
    last_run = fields.Datetime(string="Última ejecución", readonly=True)
    last_state = fields.Selection(
        [("never", "Nunca"), ("ok", "OK"), ("error", "Error")], default="never", readonly=True)
    last_message = fields.Text(readonly=True)
    last_job_id = fields.Many2one("saeko.sync.job", readonly=True, ondelete="set null")
    raw_count = fields.Integer(compute="_compute_raw_count")

    _backend_resource_uniq = models.Constraint(
        "UNIQUE(backend_id, resource_id)", "El recurso ya está configurado en el backend.")

    @api.depends("backend_id", "resource_id")
    def _compute_raw_count(self):
        data = self.env["saeko.raw.record"]._read_group(
            [("backend_id", "in", self.backend_id.ids), ("resource_id", "in", self.resource_id.ids)],
            ["backend_id", "resource_id"], ["__count"])
        counts = {(b.id, r.id): c for b, r, c in data}
        for line in self:
            line.raw_count = counts.get((line.backend_id.id, line.resource_id.id), 0)

    def _compute_next(self, from_dt):
        self.ensure_one()
        return from_dt + relativedelta(**{self.interval_type: self.interval_number or 1})

    def _mark_done(self, state, message, job):
        now = fields.Datetime.now()
        for line in self:
            line.write({"last_run": now, "last_state": state, "last_message": message,
                        "last_job_id": job.id})

    def action_sync_now(self):
        self.ensure_one()
        job = self.backend_id._run_sync(self.resource_id, trigger="manual")
        return job._action_open()

    def action_view_raw(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("%(backend)s · %(resource)s", backend=self.backend_id.name,
                      resource=self.resource_id.name),
            "res_model": "saeko.raw.record", "view_mode": "list,form",
            "domain": [("backend_id", "=", self.backend_id.id),
                       ("resource_id", "=", self.resource_id.id)],
        }
