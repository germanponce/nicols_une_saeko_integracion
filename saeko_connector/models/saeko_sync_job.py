# -*- coding: utf-8 -*-
from odoo import api, fields, models, _

COUNTERS = {
    "fetched": "fetched_count", "created": "created_count", "updated": "updated_count",
    "unchanged": "unchanged_count", "missing": "missing_count", "errors": "error_count",
    "pages": "page_count", "contexts": "context_count",
}


class SaekoSyncJob(models.Model):
    """Una ejecución de sincronización (manual o programada)."""
    _name = "saeko.sync.job"
    _description = "SAEKO - Ejecución de sincronización"
    _order = "id desc"

    name = fields.Char(readonly=True, copy=False, default="/")
    backend_id = fields.Many2one("saeko.backend", required=True, ondelete="cascade", index=True)
    company_id = fields.Many2one(related="backend_id.company_id", store=True)
    trigger = fields.Selection(
        [("manual", "Manual"), ("cron", "Programada"), ("test", "Prueba")],
        default="manual", required=True)
    state = fields.Selection(
        [("running", "En proceso"), ("done", "Completada"),
         ("partial", "Con errores"), ("failed", "Fallida")],
        default="running", required=True, index=True)
    correlation_id = fields.Char(index=True, readonly=True)
    resource_ids = fields.Many2many("saeko.resource", string="Recursos")
    user_id = fields.Many2one("res.users", readonly=True)
    started_at = fields.Datetime(readonly=True)
    finished_at = fields.Datetime(readonly=True)
    duration_s = fields.Float(string="Duración (s)", compute="_compute_duration", store=True)

    fetched_count = fields.Integer("Recibidos")
    created_count = fields.Integer("Nuevos")
    updated_count = fields.Integer("Modificados")
    unchanged_count = fields.Integer("Sin cambio")
    missing_count = fields.Integer("Ausentes")
    error_count = fields.Integer("Errores")
    page_count = fields.Integer("Páginas")
    context_count = fields.Integer("Contextos")
    message = fields.Text(readonly=True)

    log_count = fields.Integer(compute="_compute_log_count")

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", "/") == "/":
                vals["name"] = self.env["ir.sequence"].next_by_code("saeko.sync.job") or "/"
        return super().create(vals_list)

    @api.depends("started_at", "finished_at")
    def _compute_duration(self):
        for job in self:
            if job.started_at and job.finished_at:
                job.duration_s = (job.finished_at - job.started_at).total_seconds()
            else:
                job.duration_s = 0

    def _compute_log_count(self):
        data = self.env["saeko.api.log"]._read_group(
            [("correlation_id", "in", [c for c in self.mapped("correlation_id") if c])],
            ["correlation_id"], ["__count"])
        counts = dict(data)
        for job in self:
            job.log_count = counts.get(job.correlation_id, 0)

    def _add_stats(self, stats):
        self.ensure_one()
        vals = {}
        for key, val in stats.items():
            fname = COUNTERS.get(key)
            if fname and val:
                vals[fname] = self[fname] + val
        if vals:
            self.write(vals)

    def _finish(self, state, message=None):
        self.write({"state": state, "finished_at": fields.Datetime.now(),
                    "message": message or self.message})

    def _action_open(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window", "name": self.name, "res_model": self._name,
            "res_id": self.id, "view_mode": "form", "target": "current",
        }

    def action_view_logs(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window", "name": _("Bitácora de %s", self.name),
            "res_model": "saeko.api.log", "view_mode": "list,form",
            "domain": [("correlation_id", "=", self.correlation_id)],
        }

    def action_view_raw(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window", "name": _("Datos tocados por %s", self.name),
            "res_model": "saeko.raw.record", "view_mode": "list,form",
            "domain": [("last_job_id", "=", self.id)],
        }

    def action_rerun(self):
        self.ensure_one()
        job = self.backend_id._run_sync(self.resource_ids, trigger="manual")
        return job._action_open()
