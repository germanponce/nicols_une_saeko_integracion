# -*- coding: utf-8 -*-
"""Catálogo de recursos (endpoints) de SAEKO.

Cada registro describe CÓMO extraer un recurso: ruta, dependencia de un
recurso padre (contexto), paginación, campos extra y detalle por ID.
Al ser datos (no código), cuando SAEKO habilite endpoints nuevos (pagos,
cargos, CFDI, asistencias…) basta con dar de alta un registro aquí.
"""
import re

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError

PLACEHOLDER_RE = re.compile(r"\{(\w+)\}")

NAMESPACES = [
    ("core", "Core"),
    ("location", "Location"),
    ("accounting", "Accounting"),
    ("admissions", "Admissions"),
    ("grading", "Grading"),
    ("scheduling", "Scheduling"),
    ("provisioning", "Provisioning"),
    ("custom", "Personalizado / No documentado"),
]

INTERVAL_TYPES = [
    ("minutes", "Minutos"),
    ("hours", "Horas"),
    ("days", "Días"),
    ("weeks", "Semanas"),
]


class SaekoResource(models.Model):
    _name = "saeko.resource"
    _description = "SAEKO - Recurso / Endpoint"
    _order = "sequence, id"

    name = fields.Char(required=True, translate=True)
    code = fields.Char(
        required=True, index=True,
        help="Identificador técnico único, p. ej. 'student', 'term'.")
    sequence = fields.Integer(default=10, help="Orden de ejecución; los padres deben ir antes.")
    active = fields.Boolean(default=True)
    namespace = fields.Selection(NAMESPACES, default="core", required=True)
    description = fields.Text(translate=True)

    # ---- Extracción
    path = fields.Char(
        required=True,
        help="Ruta relativa al API URL. Use {parent_id} para el ID del registro padre. "
             "Ej.: /api/v1/core/terms/{parent_id}/students")
    parent_id = fields.Many2one(
        "saeko.resource", string="Recurso padre (contexto)", ondelete="restrict",
        help="Los IDs del padre se toman de los datos crudos ya descargados.")
    parent_filter = fields.Char(
        string="Filtro sobre padre",
        help="Filtra qué registros padre se recorren, evaluado sobre el JSON crudo. "
             "Formato: campo=valor;campo2=valor2 (ej. is_current=true).")
    paginate = fields.Boolean(string="Paginado (limit/offset)")
    page_size = fields.Integer(default=0, help="0 = usar el del backend.")
    sort_by = fields.Char(default="id:asc")
    response_key = fields.Char(
        help="Clave del arreglo en la respuesta si viene envuelta (ej. 'students'). "
             "Vacío = autodetección.")
    include_fields = fields.Char(help="Valor para ?include_fields= en el listado.")
    extra_params = fields.Char(
        help="Parámetros adicionales del listado, formato querystring: filters=active&x=1")
    id_field = fields.Char(default="id", required=True,
                           help="Campo del JSON que identifica al registro en SAEKO.")
    name_fields = fields.Char(
        default="name,surnames",
        help="Campos (separados por coma) para construir el nombre visible del dato crudo.")

    # ---- Detalle por ID
    fetch_detail = fields.Boolean(
        string="Descargar detalle por ID",
        help="Tras el listado, consulta cada registro individualmente (más datos, más llamadas).")
    detail_path = fields.Char(help="Ej.: /api/v1/core/students/{id}")
    detail_include_fields = fields.Char()

    track_missing = fields.Boolean(
        string="Detectar ausentes", default=True,
        help="Marca como 'ausente en SAEKO' los registros que ya no aparecen en el listado.")

    # ---- Programación por defecto
    default_interval_number = fields.Integer(default=1)
    default_interval_type = fields.Selection(INTERVAL_TYPES, default="days")

    # ---- Planeación funcional
    phase = fields.Selection(
        [("1", "Fase 1 - Aterrizaje crudo"),
         ("2", "Fase 2 - Mapeo a Odoo"),
         ("3", "Fase 3 - Pendiente endpoint SAEKO")],
        default="1")
    target_model = fields.Char(
        string="Modelo Odoo destino (plan)",
        help="Modelo donde se mapeará en fases posteriores (ej. res.partner).")
    requirement_ids = fields.Char(
        string="Requerimientos cubiertos",
        help="Requerimientos del cliente que alimenta este recurso.")

    child_ids = fields.One2many("saeko.resource", "parent_id", string="Recursos hijos")
    raw_count = fields.Integer(compute="_compute_raw_count")

    _code_uniq = models.Constraint("UNIQUE(code)", "El código del recurso debe ser único.")

    @api.depends("code")
    def _compute_raw_count(self):
        data = self.env["saeko.raw.record"]._read_group(
            [("resource_id", "in", self.ids)], ["resource_id"], ["__count"])
        counts = {res.id: count for res, count in data}
        for rec in self:
            rec.raw_count = counts.get(rec.id, 0)

    @api.constrains("path", "parent_id")
    def _check_path(self):
        for rec in self:
            placeholders = set(PLACEHOLDER_RE.findall(rec.path or ""))
            if rec.parent_id and "parent_id" not in placeholders:
                raise ValidationError(_(
                    "El recurso '%s' tiene padre: su ruta debe contener {parent_id}.", rec.name))
            if not rec.parent_id and "parent_id" in placeholders:
                raise ValidationError(_(
                    "El recurso '%s' usa {parent_id} pero no tiene recurso padre.", rec.name))

    @api.constrains("parent_id")
    def _check_parent_recursion(self):
        if self._has_cycle():
            raise ValidationError(_("No puede crear dependencias circulares entre recursos."))

    # ------------------------------------------------------------------ utils
    def _parse_parent_filter(self):
        """'is_current=true;status=1,2' -> [('is_current', ['true']), ('status', ['1','2'])]"""
        self.ensure_one()
        rules = []
        for chunk in (self.parent_filter or "").split(";"):
            chunk = chunk.strip()
            if not chunk:
                continue
            if "=" in chunk:
                key, val = chunk.split("=", 1)
                rules.append((key.strip(), [v.strip().lower() for v in val.split(",")]))
            else:
                rules.append((chunk, ["true"]))
        return rules

    def _payload_matches_filter(self, payload):
        for key, values in self._parse_parent_filter():
            val = payload.get(key)
            norm = str(val).lower() if not isinstance(val, bool) else ("true" if val else "false")
            if norm not in values:
                return False
        return True

    def _build_params(self, page_size=None):
        self.ensure_one()
        params = {}
        if self.extra_params:
            for part in self.extra_params.split("&"):
                if "=" in part:
                    key, val = part.split("=", 1)
                    params[key.strip()] = val.strip()
        if self.include_fields:
            params["include_fields"] = self.include_fields
        return params

    def _display_name_from_payload(self, payload):
        self.ensure_one()
        parts = []
        for fname in (self.name_fields or "").split(","):
            fname = fname.strip()
            val = payload.get(fname) if fname else None
            if isinstance(val, list):
                val = " ".join(str(v) for v in val if v)
            if val not in (None, "", False):
                parts.append(str(val))
        return " ".join(parts)[:250] or False

    def _ordered_with_parents(self):
        """Devuelve los recursos (incluyendo padres faltantes) en orden topológico."""
        result = self.env["saeko.resource"]
        visiting = set()

        def visit(res):
            nonlocal result
            if res in result or res.id in visiting:
                return
            visiting.add(res.id)
            if res.parent_id:
                visit(res.parent_id)
            result |= res

        for res in self.sorted(lambda r: (r.sequence, r.id)):
            visit(res)
        return result

    def action_view_raw(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Datos crudos: %s", self.name),
            "res_model": "saeko.raw.record",
            "view_mode": "list,form",
            "domain": [("resource_id", "=", self.id)],
            "context": {"search_default_group_backend": 0},
        }
