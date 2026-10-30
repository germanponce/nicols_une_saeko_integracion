# -*- coding: utf-8 -*-
import hashlib
import json
import logging
import time
import traceback
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

from odoo import SUPERUSER_ID, api, fields, models, _
from odoo.exceptions import UserError, ValidationError
from odoo.modules import module as odoo_module

from ..services.jwt_auth import SaekoKeyError, key_fingerprint
from ..services.saeko_client import (
    SaekoAuthError, SaekoClient, SaekoConnectionError, SaekoError, to_text,
)

_logger = logging.getLogger(__name__)

TEST_ENDPOINT = "/api/v1/core/schools"


def _epoch_to_dt(epoch):
    if not epoch:
        return False
    return datetime.fromtimestamp(int(epoch), timezone.utc).replace(tzinfo=None)


def _in_test_mode():
    return bool(getattr(odoo_module, "current_test", False))


class SaekoBackend(models.Model):
    _name = "saeko.backend"
    _description = "SAEKO - Backend / Conexión"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "sequence, id"

    # ------------------------------------------------------------------ general
    name = fields.Char(required=True, tracking=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True, tracking=True)
    company_id = fields.Many2one(
        "res.company", required=True, default=lambda self: self.env.company, tracking=True)
    environment = fields.Selection(
        [("sandbox", "Pruebas / Sandbox"), ("production", "Producción")],
        default="sandbox", required=True, tracking=True)
    state = fields.Selection(
        [("draft", "Sin probar"), ("connected", "Conectado"), ("error", "Error")],
        default="draft", required=True, tracking=True, copy=False)
    notes = fields.Html()

    # ------------------------------------------------------------------ service account
    auth_url = fields.Char(
        string="Auth URL", tracking=True,
        help="Endpoint OAuth2 de SAEKO (service_account.auth_url), p. ej. https://…/oauth/token")
    api_url = fields.Char(
        string="API URL", tracking=True,
        help="Servidor API del dominio (service_account.api_url), p. ej. https://…saeko.io")
    client_id = fields.Char(string="Client ID", tracking=True)
    private_key_id = fields.Char(string="Private Key ID", tracking=True)
    private_key = fields.Text(
        string="Private Key (PEM)", groups="base.group_system", copy=False,
        help="Llave RSA privada del Service Account. Nunca se registra en bitácora.")
    key_expires_at = fields.Datetime(
        string="Vigencia de la llave", tracking=True,
        help="service_account.expires_at. Se alerta 30 días antes.")
    key_fingerprint = fields.Char(string="Huella de la llave", readonly=True, copy=False,
                                  tracking=True)
    key_expiry_warned = fields.Boolean(copy=False)
    user_email = fields.Char(
        string="Usuario delegado (email)", tracking=True,
        help="Cuenta creada en el Portal Administrador de SAEKO. Sus permisos aplican a la API.")
    scope = fields.Char(default="admin", required=True)

    # ------------------------------------------------------------------ comportamiento HTTP
    timeout = fields.Integer(string="Timeout (s)", default=60)
    max_retries = fields.Integer(string="Reintentos", default=3)
    backoff = fields.Float(string="Backoff base (s)", default=2.0)
    verify_ssl = fields.Boolean(string="Verificar SSL", default=True)
    page_size = fields.Integer(string="Tamaño de página", default=100,
                               help="SAEKO limita algunos listados a 100 registros por página.")

    # ------------------------------------------------------------------ auditoría
    log_level = fields.Selection(
        [("all", "Todas las llamadas"), ("errors", "Solo errores"), ("none", "No registrar")],
        default="all", required=True, tracking=True)
    log_response_body = fields.Boolean(string="Guardar cuerpo de respuesta", default=True)
    log_retention_days = fields.Integer(
        string="Retención bitácora (días)", default=365, help="0 = conservar siempre.")
    history_retention_days = fields.Integer(
        string="Retención historial crudo (días)", default=0, help="0 = conservar siempre.")
    job_retention_days = fields.Integer(
        string="Retención ejecuciones (días)", default=365, help="0 = conservar siempre.")

    # ------------------------------------------------------------------ sincronización
    sync_enabled = fields.Boolean(
        string="Sincronización automática", default=False, tracking=True,
        help="Si está activo, el cron ejecuta los recursos programados de este backend.")
    resource_line_ids = fields.One2many("saeko.backend.resource", "backend_id",
                                        string="Recursos")
    last_connection_date = fields.Datetime(readonly=True, copy=False)
    last_error = fields.Text(readonly=True, copy=False)
    last_test_result = fields.Text(readonly=True, copy=False)

    # ------------------------------------------------------------------ token (solo lectura)
    token_expires_at = fields.Datetime(compute="_compute_token_info", string="Token expira")
    token_status = fields.Selection(
        [("none", "Sin token"), ("valid", "Vigente"), ("expired", "Expirado")],
        compute="_compute_token_info")

    # ------------------------------------------------------------------ contadores
    log_count = fields.Integer(compute="_compute_counts")
    error_log_count = fields.Integer(compute="_compute_counts")
    raw_count = fields.Integer(compute="_compute_counts")
    job_count = fields.Integer(compute="_compute_counts")

    _name_company_uniq = models.Constraint(
        "UNIQUE(name, company_id)", "Ya existe un backend con ese nombre en la compañía.")

    # ================================================================== computes
    def _compute_token_info(self):
        tokens = self.env["saeko.token"].sudo().search([("backend_id", "in", self.ids)])
        by_backend = {t.backend_id.id: t for t in tokens}
        now = fields.Datetime.now()
        for rec in self:
            tok = by_backend.get(rec.id)
            if not tok or not tok.access_token:
                rec.token_expires_at = False
                rec.token_status = "none"
            else:
                rec.token_expires_at = tok.expires_at
                rec.token_status = "valid" if tok.expires_at and tok.expires_at > now else "expired"

    def _compute_counts(self):
        def count_by(model, domain):
            data = self.env[model]._read_group(
                domain + [("backend_id", "in", self.ids)], ["backend_id"], ["__count"])
            return {b.id: c for b, c in data}

        logs = count_by("saeko.api.log", [])
        errors = count_by("saeko.api.log", [("success", "=", False)])
        raws = count_by("saeko.raw.record", [])
        jobs = count_by("saeko.sync.job", [])
        for rec in self:
            rec.log_count = logs.get(rec.id, 0)
            rec.error_log_count = errors.get(rec.id, 0)
            rec.raw_count = raws.get(rec.id, 0)
            rec.job_count = jobs.get(rec.id, 0)

    # ================================================================== CRUD
    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._update_key_fingerprint()
        records._ensure_resource_lines()
        return records

    def write(self, vals):
        res = super().write(vals)
        if "private_key" in vals:
            self._update_key_fingerprint()
            self.sudo().write({"key_expiry_warned": False})
        if {"auth_url", "api_url", "client_id", "private_key_id", "private_key",
                "user_email", "scope"} & set(vals):
            # Credenciales cambiaron: invalidar token y marcar como no probado.
            self.env["saeko.token"].sudo().search([("backend_id", "in", self.ids)]).unlink()
            if "state" not in vals:
                super().write({"state": "draft"})
        return res

    def _update_key_fingerprint(self):
        for rec in self.sudo():
            fingerprint = False
            if rec.private_key:
                try:
                    fingerprint = key_fingerprint(rec.private_key)
                except SaekoKeyError as exc:
                    raise ValidationError(str(exc)) from exc
            if rec.key_fingerprint != fingerprint:
                super(SaekoBackend, rec).write({"key_fingerprint": fingerprint})

    @api.constrains("auth_url", "api_url")
    def _check_urls(self):
        for rec in self:
            for url in (rec.auth_url, rec.api_url):
                if url and not url.startswith(("https://", "http://")):
                    raise ValidationError(_("Las URLs deben iniciar con https://"))
                if url and url.startswith("http://") and rec.environment == "production":
                    raise ValidationError(_("En producción las URLs deben usar HTTPS."))

    def _ensure_resource_lines(self):
        resources = self.env["saeko.resource"].search([])
        Line = self.env["saeko.backend.resource"]
        for rec in self:
            existing = rec.resource_line_ids.resource_id
            Line.create([{
                "backend_id": rec.id,
                "resource_id": res.id,
                "interval_number": res.default_interval_number or 1,
                "interval_type": res.default_interval_type or "days",
                "scheduled": res.phase != "3",
            } for res in resources - existing])

    # ================================================================== audit infra
    @contextmanager
    def _audit_env(self):
        """Entorno sobre un cursor independiente que hace COMMIT inmediato.

        Garantiza que la bitácora sobreviva aunque la transacción principal
        haga ROLLBACK (requisito de auditoría). En pruebas usa el mismo cursor.
        """
        if _in_test_mode() or self.env.context.get("saeko_same_cursor"):
            yield self.env(su=True)
            return
        with self.env.registry.cursor() as cr:
            cr.execute("SET LOCAL lock_timeout = '5s'")
            yield api.Environment(cr, SUPERUSER_ID, dict(self.env.context))

    def _write_api_log(self, entry, job_ref=None):
        self.ensure_one()
        if self.log_level == "none":
            return
        if self.log_level == "errors" and entry.get("success"):
            return
        vals = {
            "backend_id": self.id,
            "correlation_id": entry.get("correlation_id"),
            "job_ref": job_ref,
            "operation": entry.get("operation") or "api",
            "method": entry.get("method"),
            "url": entry.get("url"),
            "endpoint": (entry.get("endpoint") or "")[:500],
            "params": to_text(entry.get("params")) if entry.get("params") else False,
            "request_headers": to_text(entry.get("request_headers")),
            "request_body": to_text(entry.get("request_body")),
            "status_code": entry.get("status_code") or 0,
            "response_headers": to_text(entry.get("response_headers")),
            "response_body": to_text(entry.get("response_body"))
            if (self.log_response_body or not entry.get("success")) else False,
            "response_size": entry.get("response_size") or 0,
            "duration_ms": entry.get("duration_ms") or 0,
            "success": bool(entry.get("success")),
            "error_message": entry.get("error_message") and str(entry.get("error_message"))[:4000],
            "user_id": self.env.uid,
        }
        try:
            with self._audit_env() as env:
                env["saeko.api.log"].create(vals)
        except Exception:  # noqa: BLE001
            _logger.warning("SAEKO: bitácora en cursor independiente falló; se usa el principal",
                            exc_info=True)
            self.env["saeko.api.log"].sudo().create(vals)

    def _store_token(self, token):
        self.ensure_one()
        vals = {
            "access_token": token.get("access_token") or False,
            "refresh_token": token.get("refresh_token") or False,
            "expires_at": _epoch_to_dt(token.get("expires_at")),
            "token_type": token.get("token_type") or False,
            "obtained_at": fields.Datetime.now() if token.get("access_token") else False,
        }

        def _do(env):
            Token = env["saeko.token"]
            tok = Token.search([("backend_id", "=", self.id)], limit=1)
            if tok:
                tok.write(vals)
            else:
                Token.create(dict(vals, backend_id=self.id))

        try:
            with self._audit_env() as env:
                _do(env)
        except Exception:  # noqa: BLE001
            _logger.warning("SAEKO: no se pudo guardar el token en cursor independiente",
                            exc_info=True)
            _do(self.env(su=True))
        self.env["saeko.token"].invalidate_model()

    def _get_token_state(self):
        tok = self.env["saeko.token"].sudo().search([("backend_id", "=", self.id)], limit=1)
        if not tok or not tok.access_token:
            return {}
        epoch = int(tok.expires_at.replace(tzinfo=timezone.utc).timestamp()) \
            if tok.expires_at else 0
        return {"access_token": tok.access_token, "refresh_token": tok.refresh_token,
                "expires_at": epoch}

    # ================================================================== client
    def _check_configuration(self):
        self.ensure_one()
        rec = self.sudo()
        missing = [label for label, val in [
            ("Auth URL", rec.auth_url), ("API URL", rec.api_url), ("Client ID", rec.client_id),
            ("Private Key ID", rec.private_key_id), ("Private Key", rec.private_key),
            ("Usuario delegado", rec.user_email)] if not val]
        if missing:
            raise UserError(_("Faltan datos de configuración: %s", ", ".join(missing)))
        if rec.key_expires_at and rec.key_expires_at < fields.Datetime.now():
            raise UserError(_(
                "La llave del Service Account expiró el %s. Solicite una nueva a soporte SAEKO.",
                rec.key_expires_at))

    def _get_client(self, correlation_id=None, operation="api", job_ref=None):
        self.ensure_one()
        self._check_configuration()
        rec = self.sudo()
        config = {
            "auth_url": rec.auth_url, "api_url": rec.api_url, "client_id": rec.client_id,
            "private_key_id": rec.private_key_id, "private_key": rec.private_key,
            "user_email": rec.user_email, "scope": rec.scope, "timeout": rec.timeout,
            "max_retries": rec.max_retries, "backoff": rec.backoff,
            "verify_ssl": rec.verify_ssl,
        }
        client = SaekoClient(
            config,
            token_state=self._get_token_state(),
            on_token=self._store_token,
            on_log=lambda entry: self._write_api_log(entry, job_ref=job_ref),
            correlation_id=correlation_id,
        )
        client.operation = operation
        return client

    # ================================================================== actions
    def _notify(self, title, message, ntype="success", sticky=False, reload=True):
        action = {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {"title": title, "message": message, "type": ntype, "sticky": sticky},
        }
        if reload:
            action["params"]["next"] = {"type": "ir.actions.client", "tag": "soft_reload"}
        return action

    def action_test_connection(self):
        """Prueba de conexión completa: llave → JWT → token → GET schools."""
        self.ensure_one()
        correlation = uuid.uuid4().hex
        steps = []
        start = time.monotonic()
        try:
            self._check_configuration()
            steps.append("✔ Configuración completa")
            steps.append("✔ Llave RSA válida (huella %s)" % (self.sudo().key_fingerprint or "-"))
            client = self._get_client(correlation, operation="test")
            client.authenticate()
            steps.append("✔ Token obtenido (expira en %s min)" % int(
                (client.token["expires_at"] - time.time()) / 60))
            data = client.get(TEST_ENDPOINT, operation="test")
            from ..services.saeko_client import extract_items
            schools = extract_items(data)
            names = ", ".join(str(s.get("name")) for s in schools[:10])
            steps.append("✔ GET %s → %s plantel(es): %s" % (TEST_ENDPOINT, len(schools), names))
        except (SaekoError, SaekoKeyError, UserError) as exc:
            msg = getattr(exc, "args", [str(exc)])[0] if isinstance(exc, UserError) else str(exc)
            steps.append("✘ %s" % msg)
            result = "\n".join(steps)
            self.write({"state": "error", "last_error": result, "last_test_result": result})
            self.message_post(body=_("Prueba de conexión FALLIDA (correlación %s):\n%s",
                                     correlation, result))
            return self._notify(_("Conexión SAEKO fallida"), result, "danger", sticky=True)
        elapsed = int((time.monotonic() - start) * 1000)
        steps.append("Tiempo total: %s ms · correlación %s" % (elapsed, correlation))
        result = "\n".join(steps)
        self.write({"state": "connected", "last_connection_date": fields.Datetime.now(),
                    "last_error": False, "last_test_result": result})
        self.message_post(body=_("Prueba de conexión exitosa:\n%s", result))
        return self._notify(_("Conexión SAEKO exitosa"), result, "success", sticky=True)

    def action_refresh_token(self):
        self.ensure_one()
        try:
            client = self._get_client(operation="refresh")
            client.refresh()
        except (SaekoError, SaekoKeyError) as exc:
            self.write({"state": "error", "last_error": str(exc)})
            return self._notify(_("No se pudo renovar el token"), str(exc), "danger", True)
        return self._notify(_("Token renovado"), _("Token vigente hasta %s",
                                                   self.token_expires_at), "success")

    def action_revoke_token(self):
        self.env["saeko.token"].sudo().search([("backend_id", "in", self.ids)]).unlink()
        return self._notify(_("Token eliminado"), _("Se solicitará uno nuevo en la próxima llamada."),
                            "info")

    def action_sync_all(self):
        self.ensure_one()
        lines = self.resource_line_ids.filtered("scheduled")
        if not lines:
            raise UserError(_("No hay recursos activos para este backend."))
        job = self._run_sync(lines.resource_id, trigger="manual")
        return job._action_open()

    def action_reload_resources(self):
        self._ensure_resource_lines()
        return True

    def _open_related(self, model, name, domain=None, context=None):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window", "name": name, "res_model": model,
            "view_mode": "list,form",
            "domain": [("backend_id", "=", self.id)] + (domain or []),
            "context": dict(context or {}, default_backend_id=self.id),
        }

    def action_view_logs(self):
        return self._open_related("saeko.api.log", _("Bitácora API"))

    def action_view_error_logs(self):
        return self._open_related("saeko.api.log", _("Errores API"), [("success", "=", False)])

    def action_view_raw(self):
        return self._open_related("saeko.raw.record", _("Datos crudos"),
                                  context={"search_default_group_resource": 1})

    def action_view_jobs(self):
        return self._open_related("saeko.sync.job", _("Ejecuciones"))

    def action_open_explorer(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window", "name": _("Explorador API SAEKO"),
            "res_model": "saeko.api.explorer", "view_mode": "form", "target": "new",
            "context": {"default_backend_id": self.id},
        }

    def action_import_credentials(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window", "name": _("Importar Service Account"),
            "res_model": "saeko.credentials.import", "view_mode": "form", "target": "new",
            "context": {"default_backend_id": self.id},
        }

    # ================================================================== sync engine
    def _commit(self):
        if not _in_test_mode() and not self.env.context.get("saeko_no_commit"):
            self.env.cr.commit()

    def _run_sync(self, resources, trigger="manual"):
        """Sincroniza ``resources`` (y sus padres) hacia la zona de datos crudos.

        Cada recurso corre en su propio savepoint: un fallo no detiene a los
        demás. La bitácora HTTP se escribe en un cursor independiente.
        """
        self.ensure_one()
        ordered = resources._ordered_with_parents()
        correlation = uuid.uuid4().hex
        Job = self.env["saeko.sync.job"].sudo()
        job = Job.create({
            "backend_id": self.id,
            "trigger": trigger,
            "correlation_id": correlation,
            "resource_ids": [(6, 0, ordered.ids)],
            "state": "running",
            "started_at": fields.Datetime.now(),
            "user_id": self.env.uid,
        })
        self._commit()
        messages = []
        try:
            client = self._get_client(correlation, operation="sync", job_ref=job.name)
        except (SaekoError, SaekoKeyError, UserError) as exc:
            job._finish("failed", "No se pudo crear el cliente: %s" % exc)
            self._commit()
            return job

        lines = {l.resource_id.id: l for l in self.resource_line_ids}
        for resource in ordered:
            line = lines.get(resource.id)
            t0 = time.monotonic()
            try:
                with self.env.cr.savepoint():
                    stats = self._sync_resource(client, resource, job)
                job._add_stats(stats)
                msg = "✔ %s: %s" % (resource.name, ", ".join(
                    "%s=%s" % (k, v) for k, v in stats.items() if v))
                if line:
                    line._mark_done("ok", msg, job)
            except Exception as exc:  # noqa: BLE001 - se registra y continúa
                if isinstance(exc, (SaekoError, UserError)):
                    _logger.warning("SAEKO: %s falló: %s", resource.code, exc)
                else:
                    _logger.exception("SAEKO: error inesperado sincronizando %s", resource.code)
                detail = str(exc) if isinstance(exc, (SaekoError, UserError)) else \
                    "%s\n%s" % (exc, traceback.format_exc(limit=5))
                msg = "✘ %s: %s" % (resource.name, detail)
                job._add_stats({"errors": 1})
                if line:
                    line._mark_done("error", msg, job)
                if isinstance(exc, SaekoAuthError):
                    self.write({"state": "error", "last_error": str(exc)})
            messages.append("%s (%.1fs)" % (msg, time.monotonic() - t0))
            self._commit()

        state = "done" if not job.error_count else ("partial" if job.created_count
                                                      or job.updated_count
                                                      or job.unchanged_count else "failed")
        job._finish(state, "\n".join(messages))
        if state != "failed" and self.state != "connected":
            self.write({"state": "connected", "last_error": False})
        self.write({"last_connection_date": fields.Datetime.now()})
        self._commit()
        return job

    def _parent_contexts(self, resource):
        """Lista de (raw_padre, context_key) a recorrer para ``resource``."""
        if not resource.parent_id:
            return [(self.env["saeko.raw.record"], "")]
        parents = self.env["saeko.raw.record"].search([
            ("backend_id", "=", self.id),
            ("resource_id", "=", resource.parent_id.id),
            ("missing", "=", False),
        ])
        result, seen = [], set()
        for parent in parents:
            if parent.saeko_id in seen:
                continue
            if resource.parent_filter and not resource._payload_matches_filter(parent._get_payload()):
                continue
            seen.add(parent.saeko_id)
            result.append((parent, parent.saeko_id))
        return result

    def _sync_resource(self, client, resource, job):
        stats = {"fetched": 0, "created": 0, "updated": 0, "unchanged": 0, "missing": 0,
                 "errors": 0, "pages": 0, "contexts": 0}
        contexts = self._parent_contexts(resource)
        page_size = resource.page_size or self.page_size or 100
        for parent_raw, ctx in contexts:
            stats["contexts"] += 1
            path = resource.path.replace("{parent_id}", str(ctx))
            seen_ids = set()
            for items, _page in client.iterate(
                    path, params=resource._build_params(), paginate=resource.paginate,
                    page_size=page_size, response_key=resource.response_key,
                    sort_by=resource.sort_by, operation="sync"):
                stats["pages"] += 1
                if resource.fetch_detail and resource.detail_path:
                    items = self._fetch_details(client, resource, items, stats)
                counts, ids = self.env["saeko.raw.record"]._upsert_batch(
                    self, resource, items, ctx, parent_raw, job)
                seen_ids |= ids
                for key, val in counts.items():
                    stats[key] += val
            if resource.track_missing:
                stats["missing"] += self.env["saeko.raw.record"]._mark_missing(
                    self, resource, ctx, seen_ids)
        return stats

    def _fetch_details(self, client, resource, items, stats):
        detailed = []
        params = {"include_fields": resource.detail_include_fields} \
            if resource.detail_include_fields else None
        for item in items:
            rid = item.get(resource.id_field or "id")
            if rid in (None, ""):
                detailed.append(item)
                continue
            try:
                data = client.get(resource.detail_path.replace("{id}", str(rid)),
                                  params=params, operation="sync")
                if isinstance(data, dict):
                    # Algunos endpoints envuelven el objeto: {"student": {...}}
                    if len(data) == 1 and isinstance(next(iter(data.values())), dict):
                        data = next(iter(data.values()))
                    merged = dict(item)
                    merged.update(data)
                    detailed.append(merged)
                else:
                    detailed.append(item)
            except SaekoError as exc:
                stats["errors"] += 1
                item = dict(item, _detail_error=str(exc))
                detailed.append(item)
        return detailed

    # ================================================================== crons
    @api.model
    def _cron_sync(self):
        """Ejecuta los recursos cuya próxima ejecución ya venció."""
        now = fields.Datetime.now()
        backends = self.search([("sync_enabled", "=", True), ("state", "!=", "draft")])
        for backend in backends:
            due = backend.resource_line_ids.filtered(
                lambda l: l.scheduled and (not l.next_run or l.next_run <= now))
            if not due:
                continue
            backend._run_sync(due.resource_id, trigger="cron")
            for line in due:
                line.next_run = line._compute_next(now)
            backend._commit()

    @api.model
    def _cron_healthcheck(self):
        """Mantiene el token vigente y alerta de llaves por vencer o credenciales rotas."""
        soon = fields.Datetime.now() + timedelta(days=30)
        for backend in self.search([("state", "!=", "draft")]):
            if (backend.key_expires_at and backend.key_expires_at <= soon
                    and not backend.key_expiry_warned):
                backend.message_post(body=_(
                    "⚠ La llave del Service Account vence el %s. Solicite renovación a SAEKO.",
                    backend.key_expires_at))
                backend.key_expiry_warned = True
            try:
                client = backend._get_client(operation="healthcheck")
                remaining = int(client.token.get("expires_at") or 0) - time.time()
                if not client.token_valid or remaining < 900:
                    if client.token.get("refresh_token"):
                        client.refresh()
                    else:
                        client.authenticate()
                if backend.state == "error":
                    backend.write({"state": "connected", "last_error": False})
            except (SaekoError, SaekoKeyError, UserError) as exc:
                if backend.state != "error":
                    backend.message_post(body=_("✘ Healthcheck falló: %s", exc))
                backend.write({"state": "error", "last_error": str(exc)})
            backend._commit()

    @api.model
    def _cron_cleanup(self):
        """Depura bitácora, historial y ejecuciones según la retención de cada backend."""
        now = fields.Datetime.now()
        for backend in self.with_context(active_test=False).search([]):
            for model, days in (("saeko.api.log", backend.log_retention_days),
                                ("saeko.sync.job", backend.job_retention_days)):
                if days > 0:
                    self.env[model].sudo().search([
                        ("backend_id", "=", backend.id),
                        ("create_date", "<", now - timedelta(days=days))]).unlink()
            if backend.history_retention_days > 0:
                self.env["saeko.raw.history"].sudo().search([
                    ("raw_id.backend_id", "=", backend.id),
                    ("captured_at", "<", now - timedelta(days=backend.history_retention_days)),
                ]).unlink()
            backend._commit()


class SaekoToken(models.Model):
    """Token OAuth2 aislado del backend: se escribe en cursor independiente
    sin bloquear la fila del backend y solo es visible para administradores."""
    _name = "saeko.token"
    _description = "SAEKO - Token OAuth2"

    backend_id = fields.Many2one("saeko.backend", required=True, ondelete="cascade", index=True)
    access_token = fields.Char()
    refresh_token = fields.Char()
    token_type = fields.Char()
    expires_at = fields.Datetime()
    obtained_at = fields.Datetime()

    _backend_uniq = models.Constraint("UNIQUE(backend_id)", "Un token por backend.")


def payload_hash(payload):
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"),
                           default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
