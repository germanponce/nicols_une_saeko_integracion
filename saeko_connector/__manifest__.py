# -*- coding: utf-8 -*-
{
    "name": "SAEKO Connector",
    "summary": "Integración Odoo ↔ SAEKO (control escolar): conexión OAuth2/JWT, "
               "bitácora de API, datos crudos auditables y sincronización programada",
    "description": """
SAEKO Connector — Fase 1 (Base) · Odoo 20
=========================================
* Configuración de backends SAEKO (Service Account OAuth2 JWT RS256).
* Prueba de conexión y renovación automática de token.
* Bitácora completa de cada llamada HTTP (request/response, tiempos, errores).
* Zona de aterrizaje (landing) de datos crudos con hash, versión e historial.
* Catálogo configurable de recursos/endpoints con dependencias padre→hijo.
* Ejecuciones de sincronización (jobs) con contadores y trazabilidad.
* Crons: sincronización, renovación de token y depuración por retención.
* Explorador de API (solo GET) para descubrir endpoints.
""",
    "version": "20.0.1.0.0",
    "category": "Education",
    "author": "ANFEPI",
    "website": "https://www.anfepi.com",
    "license": "LGPL-3",
    "depends": ["base", "mail"],
    "external_dependencies": {"python": ["cryptography", "requests"]},
    "data": [
        "security/saeko_security.xml",
        "security/ir.access.csv",
        "data/saeko_resource_data.xml",
        "data/ir_cron_data.xml",
        "views/saeko_backend_views.xml",
        "views/saeko_resource_views.xml",
        "views/saeko_api_log_views.xml",
        "views/saeko_raw_record_views.xml",
        "views/saeko_sync_job_views.xml",
        "wizard/saeko_api_explorer_views.xml",
        "wizard/saeko_credentials_import_views.xml",
        "views/saeko_menus.xml",
    ],
    "images": ["static/description/banner.png"],
    "application": True,
    "installable": True,
}
