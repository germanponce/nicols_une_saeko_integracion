# SAEKO Connector para Odoo 20

Integración **Odoo 20 (CE/EE) ← SAEKO** (sistema de control escolar universitario).
Odoo **consume** la API REST de SAEKO; todo lo que entra queda auditado.

> Fase 1 — Base: conexión, autenticación, bitácora, datos crudos y crons.
> Rama `20.0` (este código). La rama `19.0` conserva la versión para Odoo 19.
> Las fases siguientes mapean los datos crudos a modelos estándar de Odoo.

## Qué incluye

| Componente | Modelo | Para qué |
|---|---|---|
| Conexiones | `saeko.backend` | Service Account (OAuth2 JWT RS256), parámetros HTTP, retención, chatter con historial de cambios |
| Token | `saeko.token` | Access/refresh token aislado; solo visible para Administración |
| Catálogo de recursos | `saeko.resource` | Endpoints como **datos**: ruta, padre/contexto, paginación, detalle por ID |
| Programación | `saeko.backend.resource` | Frecuencia, próxima ejecución y último resultado por recurso y backend |
| Bitácora API | `saeko.api.log` | Cada intento HTTP: URL, params, headers y cuerpos **enmascarados**, status, duración, error. Inmutable |
| Ejecuciones | `saeko.sync.job` | Cada sincronización: contadores (nuevos, modificados, sin cambio, ausentes, errores) y resultado por recurso |
| Datos crudos | `saeko.raw.record` | JSON tal como llegó + SHA-256 + versión + estado de procesamiento |
| Historial crudo | `saeko.raw.history` | Versiones anteriores de cada JSON (qué dijo SAEKO y cuándo) |
| Explorador API | `saeko.api.explorer` | GET de solo lectura para descubrir endpoints; también queda en bitácora |
| Importar credenciales | `saeko.credentials.import` | Pega el bloque YAML/JSON `service_account` de SAEKO |

Crons:

| Cron | Frecuencia | Función |
|---|---|---|
| SAEKO: Sincronización programada | 15 min | Ejecuta los recursos cuya próxima ejecución venció |
| SAEKO: Healthcheck y renovación de token | 30 min | Mantiene el token vivo, detecta credenciales rotas, avisa 30 días antes de que venza la llave |
| SAEKO: Depuración por retención | diario | Borra bitácora/ejecuciones/historial según los días configurados (0 = nunca) |

## Inicio rápido

1. Copie `saeko_connector` a su ruta de addons e instale **SAEKO Connector**.
2. *SAEKO → Configuración → Conexiones → Nuevo*.
3. Botón **Importar Service Account**: pegue el bloque que entrega soporte SAEKO e indique el
   correo del usuario delegado (creado en el Portal Administrador de SAEKO).
4. **Probar conexión**. Verá el resultado paso a paso: configuración → llave → token → `GET /api/v1/core/schools`.
5. Pestaña *Recursos y programación*: ajuste frecuencias y pulse ▶ en un recurso, o **Sincronizar ahora**.
6. Active **Sincronización automática** cuando esté conforme.

Sin credenciales todavía, puede probar todo contra el simulador:

```bash
python3 saeko_connector/tools/mock_saeko_server.py --port 8765
# imprime un service_account listo para importar; usuario delegado: api@universidad.test
```

## Documentación

* [doc/ARQUITECTURA.md](doc/ARQUITECTURA.md): diseño, flujo de autenticación, auditoría y motor de sincronización.
* [doc/ANALISIS_API.md](doc/ANALISIS_API.md): **requerimiento por requerimiento vs. API pública de SAEKO** y preguntas para SAEKO.
* [doc/INSTALACION.md](doc/INSTALACION.md): instalación, permisos, pruebas y operación.
* [doc/ROADMAP.md](doc/ROADMAP.md): fases y mapeo propuesto a Odoo 20 EE.
* [CHANGELOG.md](CHANGELOG.md)

## Pruebas

```bash
odoo-bin -d <db> -i saeko_connector --test-tags=/saeko_connector --stop-after-init
```

15 pruebas: permisos y multicompañía (`ir.access`), inmutabilidad de la bitácora, firma JWT, conexión OK/rechazada, enmascarado de secretos, refresh ante 401,
reintentos 5xx, paginación, detección de cambios/historial/ausentes, aislamiento de fallos por
recurso, detalle por ID, cron por programación, importación de credenciales y explorador.

## Licencia

LGPL-3 · ANFEPI
