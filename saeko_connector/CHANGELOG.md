# Changelog

## 20.0.1.0.0 — 2026-10-29

Migración a Odoo 20.

* Seguridad migrada a `ir.access` (`security/ir.access.csv`): Odoo 20 unifica `ir.model.access`
  e `ir.rule`. Las reglas multicompañía son ahora restricciones sin grupo.
* Script `migrations/20.0.1.0.0/pre-migrate.py`: libera los XML-ID de seguridad heredados.
* 4 pruebas nuevas: permisos de Auditor y Administrador, acceso a secretos, multicompañía e
  inmutabilidad de la bitácora (15 en total).
* Documentación actualizada a Odoo 20: requisitos (Python 3.12–3.14, PostgreSQL 16+), reglas de
  tiempo para la nómina docente, versiones de empleado.

## 19.0.1.0.0 — 2026-10-29

Fase 1 — Base.

* Backends SAEKO con Service Account OAuth2 JWT (RS256), importación del bloque YAML/JSON y huella
  de la llave.
* Cliente HTTP: renovación anticipada y ante 401, reintentos con backoff, paginación, enmascarado
  de secretos.
* Prueba de conexión paso a paso, con resultado en chatter y bitácora.
* Bitácora inmutable en cursor independiente (sobrevive a rollbacks), con correlación por ejecución.
* Zona de datos crudos con SHA-256, versión, historial, detección de ausentes y estado de procesamiento.
* Catálogo de 11 recursos documentados + 7 recursos [PENDIENTE] de endpoint SAEKO.
* Programación por recurso y backend; crons de sincronización, healthcheck y depuración.
* Explorador API (GET) con detección de estructura.
* Grupos Auditor/Administrador y reglas multicompañía.
* 11 pruebas automatizadas y servidor SAEKO simulado.
