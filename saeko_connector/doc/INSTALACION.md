# Instalación y operación

## Requisitos

* Odoo 20.0 (Community o Enterprise). Depende solo de `base` y `mail`.
* Python 3.12 a 3.14 y PostgreSQL 16 o superior (requisitos de Odoo 20).
* La rama `19.0` del repositorio conserva la versión para Odoo 19.
* Python: `cryptography` y `requests` (ya vienen con Odoo).
* Salida HTTPS del servidor Odoo hacia el `auth_url` y el `api_url` de SAEKO.

## Instalación

```bash
cp -r saeko_connector /ruta/a/addons_custom/
odoo-bin -c odoo.conf -d <db> -i saeko_connector --stop-after-init
```

En Odoo.sh: agregue la carpeta al repositorio; se instala desde *Aplicaciones* (busque *SAEKO*).

## Permisos

*Ajustes → Usuarios*, sección **SAEKO Connector**:

* **Auditor / Consulta**: control interno, contraloría.
* **Administrador**: responsable de la integración.

Capturar o ver la **llave privada** requiere además *Ajustes / Administración*.

## Configuración de una conexión

1. Solicite a soporte SAEKO el bloque `service_account` (`auth_url`, `api_url`, `client_id`,
   `private_key_id`, `private_key`, `expires_at`).
2. Cree en el Portal Administrador de SAEKO un **usuario para la API**, con los permisos mínimos
   de lectura. Sus permisos son los que aplica la API.
3. En Odoo: *SAEKO → Configuración → Conexiones → Nuevo* → **Importar Service Account**.
4. Elija *Pruebas/Sandbox* o *Producción* (Producción exige HTTPS).
5. **Probar conexión**. El resultado queda en la pestaña *Última prueba*, en el chatter y en la
   bitácora (operaciones *Autenticación* y *Prueba de conexión*).

## Primera sincronización recomendada

1. En *Recursos y programación*, ejecute ▶ **Planteles** y revise *Datos crudos*.
2. Ejecute ▶ **Ciclos escolares** y **Programas**.
3. Ejecute ▶ **Alumnos** sin *Descargar detalle por ID* para medir el volumen.
4. Revise en la ejecución el tiempo y el número de páginas; ajuste frecuencias.
5. Active **Sincronización automática**.

Frecuencias sugeridas: catálogos (planteles, programas, materias, tipos de beca) semanal; ciclos
y empleados diario; alumnos, grupos y cursos cada 4 a 12 h según el volumen.

## Operación diaria

| Pregunta | Dónde |
|---|---|
| ¿Funcionó la sincronización de anoche? | *SAEKO → Operación → Ejecuciones* (filtro *Con errores*) |
| ¿Qué respondió SAEKO exactamente? | Ejecución → *Llamadas API* → pestaña *Respuesta* |
| ¿Qué alumnos cambiaron hoy? | *Datos crudos* → filtro *Modificados* → *Versiones previas* |
| ¿Quién dejó de aparecer en SAEKO? | *Datos crudos* → filtro *Ausentes en SAEKO* |
| ¿El endpoint X existe? | Backend → **Explorador API** |
| ¿Está vigente la llave? | Backend → *Vigencia de la llave* (aviso automático 30 días antes) |

## Agregar un endpoint nuevo (sin programar)

1. Pruébelo en el **Explorador API** y revise *Estructura detectada*.
2. *Configuración → Catálogo de recursos*: cree o reactive el recurso (los **[PENDIENTE]** están
   archivados), con su ruta, padre y paginación.
3. En el backend: **Agregar recursos nuevos del catálogo**, y luego ▶.

## Pruebas automatizadas

```bash
odoo-bin -c odoo.conf -d <db_prueba> -i saeko_connector \
         --test-tags=/saeko_connector --stop-after-init
```

## Simulador local

```bash
python3 saeko_connector/tools/mock_saeko_server.py --port 8765 --students 500
```

Implementa OAuth2 (JWT + refresh) y planteles, ciclos, programas, alumnos (paginados) y empleados.
Imprime un `service_account` para importar; el usuario delegado es `api@universidad.test`.
Use el backend en modo *Pruebas/Sandbox*, que acepta `http://`.

## Respaldo y retención

* La bitácora y el historial crudo pueden crecer rápido. Ajuste la retención por backend
  (0 = conservar siempre) y considere *Solo errores* en producción una vez estabilizada.
* Los datos crudos vigentes no se depuran: son la fuente para las fases de mapeo.
