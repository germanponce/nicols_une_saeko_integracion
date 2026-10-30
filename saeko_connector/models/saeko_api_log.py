# -*- coding: utf-8 -*-
from odoo import api, fields, models

OPERATIONS = [
    ("auth", "Autenticación (JWT)"),
    ("refresh", "Renovación de token"),
    ("test", "Prueba de conexión"),
    ("healthcheck", "Healthcheck"),
    ("sync", "Sincronización"),
    ("explorer", "Explorador API"),
    ("api", "API"),
]


class SaekoApiLog(models.Model):
    """Bitácora inmutable de cada intento HTTP hacia SAEKO."""
    _name = "saeko.api.log"
    _description = "SAEKO - Bitácora de API"
    _order = "id desc"
    _rec_name = "display_label"

    backend_id = fields.Many2one("saeko.backend", required=True, ondelete="cascade", index=True,
                                 readonly=True)
    company_id = fields.Many2one(related="backend_id.company_id", store=True)
    correlation_id = fields.Char(index=True, readonly=True,
                                 help="Agrupa todas las llamadas de una misma operación/ejecución.")
    job_ref = fields.Char(string="Ejecución", index=True, readonly=True)
    operation = fields.Selection(OPERATIONS, index=True, readonly=True)
    method = fields.Char(readonly=True)
    url = fields.Char(string="URL completa", readonly=True)
    endpoint = fields.Char(index=True, readonly=True)
    params = fields.Text(readonly=True)
    request_headers = fields.Text(readonly=True)
    request_body = fields.Text(readonly=True)
    status_code = fields.Integer(string="HTTP", index=True, readonly=True)
    response_headers = fields.Text(readonly=True)
    response_body = fields.Text(readonly=True)
    response_size = fields.Integer(string="Bytes", readonly=True)
    duration_ms = fields.Integer(string="Duración (ms)", readonly=True, aggregator="avg")
    success = fields.Boolean(index=True, readonly=True)
    error_message = fields.Text(readonly=True)
    user_id = fields.Many2one("res.users", readonly=True)
    display_label = fields.Char(compute="_compute_display_label")

    _create_date_idx = models.Index("(create_date DESC)")
    _backend_success_idx = models.Index("(backend_id, success, create_date DESC)")

    @api.depends("method", "endpoint", "status_code")
    def _compute_display_label(self):
        for rec in self:
            rec.display_label = "%s %s → %s" % (rec.method or "", rec.endpoint or "",
                                                 rec.status_code or "ERR")

    def write(self, vals):
        # La bitácora es inmutable (auditoría); solo el superusuario puede alterarla.
        if not self.env.su:
            from odoo.exceptions import UserError
            raise UserError(self.env._("La bitácora de SAEKO no puede modificarse."))
        return super().write(vals)

    def action_open_job(self):
        self.ensure_one()
        job = self.env["saeko.sync.job"].search([("correlation_id", "=", self.correlation_id)],
                                                limit=1)
        return job._action_open() if job else False
