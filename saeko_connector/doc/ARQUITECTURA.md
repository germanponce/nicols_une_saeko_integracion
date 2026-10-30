# Arquitectura

## Principios

1. **Odoo consume SAEKO** (solo lectura en fase 1). Nada se escribe en SAEKO.
2. **Primero aterrizar, después mapear.** Todo llega primero a una zona de datos crudos
   (`saeko.raw.record`) idéntica a lo que respondió SAEKO. El mapeo a modelos Odoo es un paso
   separado y repetible: si una regla cambia, se reprocesa sin volver a llamar a la API.
3. **Auditoría que no se pierde.** La bitácora se escribe en un cursor independiente con COMMIT
   inmediato: aunque la sincronización falle y haga ROLLBACK, la evidencia de cada llamada queda.
4. **Endpoints como datos.** Rutas, dependencias y paginación viven en `saeko.resource`. Un endpoint
   nuevo se da de alta desde la interfaz.
5. **Secretos fuera de la bitácora.** Llave privada, JWT, access/refresh token y `Authorization` se
   enmascaran (`***` + últimos 4 caracteres).

## Componentes

```
saeko_connector/
├── services/                 # Python puro, sin ORM (se prueba de forma aislada)
│   ├── jwt_auth.py           # JWT RS256 con `cryptography`, huella de llave
│   └── saeko_client.py       # HTTP: auth, refresh, reintentos, paginación, enmascarado
├── models/
│   ├── saeko_backend.py      # Conexión, prueba, motor de sync, crons, token
│   ├── saeko_resource.py     # Catálogo de endpoints
│   ├── saeko_backend_resource.py  # Programación por backend
│   ├── saeko_api_log.py      # Bitácora inmutable
│   ├── saeko_sync_job.py     # Ejecuciones
│   └── saeko_raw_record.py   # Datos crudos + historial
├── wizard/                   # Explorador API, importación de Service Account
├── data/                     # Catálogo de recursos, crons, secuencia
├── security/                 # Grupos (Auditor / Administrador), ACL, reglas multicompañía
├── tests/                    # Pruebas + SAEKO simulado
└── tools/mock_saeko_server.py
```

## Autenticación (OAuth2 JWT Bearer)

```
Odoo                                   SAEKO Auth                 SAEKO API
 │ JWT {iss=client_id, sub=email,           │                          │
 │      scope=admin, iat, jti=MD5(kid:iat)}  │                          │
 │ firmado RS256 con la llave privada ─────► POST auth_url             │
 │ ◄──── access_token (1 h) + refresh_token │                          │
 │ GET /api/v1/... Authorization: Bearer ──────────────────────────────►│
 │ ◄──── 401 (token expirado) ──────────────────────────────────────────│
 │ POST auth_url grant_type=refresh_token ─►│                          │
 │   (si el refresh también da 401: se borra el token y se vuelve a firmar un JWT)
```

* El token se renueva 2 minutos antes de expirar y ante cualquier 401 (una vez por petición).
* El healthcheck (cada 30 min) lo mantiene vivo y cambia el backend a *Error* si las credenciales
  dejan de funcionar, con aviso en el chatter.
* El token vive en `saeko.token` (solo `base.group_system`), separado del backend para que su
  escritura no bloquee la fila del backend durante una sincronización larga.

## Reintentos

| Situación | Acción |
|---|---|
| 401 | refresh → reintento (una vez) |
| 408, 425, 429, 500, 502, 503, 504 | backoff exponencial `backoff × 2^n` (máx. 60 s), respeta `Retry-After`, hasta *Reintentos* |
| Timeout, DNS, TLS | igual que 5xx |
| 400, 403, 404, 422 | error inmediato con `error_description` de SAEKO |

Cada **intento** es una línea de bitácora, así que los reintentos también se ven.

## Motor de sincronización

```
_run_sync(recursos)
  ├─ agrega padres faltantes y ordena topológicamente (school → term → student …)
  ├─ crea saeko.sync.job (correlation_id compartido con la bitácora)
  └─ por recurso, en su propio SAVEPOINT:
       ├─ contextos = registros crudos del padre (filtrados, ej. is_current=true)
       ├─ por contexto: GET paginado → (opcional) detalle por ID → upsert
       │    upsert: SHA-256 del JSON canónico
       │      nuevo       → crea (versión 1, estado pendiente)
       │      hash ≠      → guarda versión anterior en historial, versión+1, pendiente
       │      hash =      → solo actualiza "última vez visto"
       ├─ registros del contexto que ya no vinieron → "ausente en SAEKO"
       └─ COMMIT (fuera de pruebas); un error en un recurso no detiene a los demás
```

Clave única del dato crudo: `(backend, recurso, contexto, id SAEKO)`. El contexto es el ID del padre;
por ejemplo, un alumno inscrito en dos ciclos vigentes tiene un registro por ciclo, porque su
`enrollment_id` difiere.

## Seguridad

En Odoo 20 los permisos y las reglas de registro viven en un solo modelo, `ir.access`
(`security/ir.access.csv`): una fila con grupo concede una operación (`r`, `cr`, `crud`…); una fila
sin grupo y con dominio restringe a todos (así se expresa la regla multicompañía).

| Grupo | Puede |
|---|---|
| SAEKO / Auditor - Consulta | Ver bitácora, ejecuciones, datos crudos, backends y catálogo |
| SAEKO / Administrador | Lo anterior + configurar backends y recursos, probar conexión, sincronizar, explorar API |
| Ajustes (`base.group_system`) | Ver y editar la llave privada, importar Service Account, ver tokens, borrar bitácora |

* La bitácora es inmutable salvo para el superusuario (la depuración por retención la hace el cron).
* Reglas multicompañía en backend, bitácora, ejecuciones y datos crudos.
* La validación impide URLs `http://` en backends de **Producción**.

## Volumen y rendimiento

* Upsert por página: 1 búsqueda + 1 `create` masivo + escrituras solo de lo que cambió.
* Índices en bitácora `(create_date)` y `(backend_id, success, create_date)`.
* La bitácora guarda cuerpos de respuesta de hasta 2 MB. Con alto volumen conviene
  *Solo errores* o desactivar *Guardar cuerpo de respuesta* (los datos ya quedan en la zona cruda).
