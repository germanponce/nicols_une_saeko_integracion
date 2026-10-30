# Análisis: requerimientos vs. API pública de SAEKO

Fuente: https://apidoc.saeko.io (consultada el 29-oct-2026).

## Resumen

La documentación pública cubre el **núcleo académico** (planteles, ciclos, programas, grupos,
cursos, alumnos, empleados), **becas** y calificaciones. **No documenta endpoints de cobranza ni
de facturación** (cargos, pagos, CFDI, adeudos, condonaciones), ni la consulta de asistencias,
horarios, suplencias o bonos de profesores.

De 25 datos solicitados: **7 cubiertos**, **4 parciales** y **14 sin endpoint documentado**.
Todo el bloque financiero de alumnos depende de que SAEKO habilite o documente endpoints adicionales.

Leyenda: ✅ cubierto · 🟡 parcial · ❌ sin endpoint documentado

## Profesores

| Requerimiento | Estado | Fuente en SAEKO | Notas |
|---|---|---|---|
| Contacto (nombre, CURP, RFC, grado de estudios) | ✅ | `GET /api/v1/core/schools/{id}/employees`, `GET /api/v1/core/employees/{id}` | `name`, `first_surname`, `second_surname`, `curp`, `rfc`, `professor_details.grade_level / master_degree / doctors_degree` |
| Tarifas | 🟡 | `Employee.cost_per_hour` | Una sola tarifa por hora. Tarifas por programa, nivel o modalidad: no documentado |
| Carga horaria (horario, plantel, modalidad, programa) | 🟡 | `GET /api/v1/core/terms/{id}/courses` (paginado, máx. 100) + `Group` | Curso → `professor_id`, `subject_id`; grupo → `program_id`, `shift` (modalidad/turno); plantel vía ciclo. **Horario (días y horas): no documentado** |
| Carga dada | ❌ | — | Requiere sesiones impartidas o pase de lista |
| Registros de asistencia y checador | 🟡 | `POST /api/v1/scheduling/gate_access_logs` | Solo **crear** registros. Falta un `GET` para consultarlos |
| Incidencias por suplencia | ❌ | — | |
| Documentación de incidencias | ❌ | — | |
| Bonos | ❌ | — | |

## Alumnos

| Requerimiento | Estado | Fuente en SAEKO | Notas |
|---|---|---|---|
| Contacto | ✅ | `GET /api/v1/core/terms/{id}/students`, `GET /api/v1/core/students/{id}` | Detalle con `include_fields`: teléfonos, domicilios, CURP, RFC, `custom_fields`. `invoice_receiver` es **solo escritura** (no se puede leer el receptor fiscal) |
| Ciclo escolar | ✅ | `GET /api/v1/core/schools/{id}/terms` | `is_current` permite filtrar el vigente |
| Estatus del alumno | 🟡 | Listado por ciclo (solo **activos**) + `enrollments` (extra) | El modelo `Enrollment` no está documentado. El conector marca como **ausente** a quien deja de aparecer |
| Plantel | ✅ | `School` vía ciclo | |
| Nivel | ✅ | `Program.level` | Maestría, Licenciatura, Bachillerato, Doctorado, Diplomado, etc. |
| Programa | ✅ | `Program` + `enrollment.program_id` | |
| Concepto pagado | ❌ | — | |
| Monto | ❌ | — | |
| Fechas del concepto | ❌ | — | |
| Fecha de pago | ❌ | — | |
| Forma de pago (TC, transferencia, débito, efectivo) | ❌ | — | |
| Método de pago (pasarela, TPV, depósito referenciado, transferencia) | ❌ | — | |
| Factura individual o global | ❌ | — | |
| CFDI de cada concepto | ❌ | — | |
| Adeudo | ❌ | — | |
| Becas | ✅ | `GET /api/v1/accounting/scholarship_types`, `GET /api/v1/accounting/enrollments/{id}/scholarship` | Por inscripción: monto, `amount_type` (porcentaje/fijo), parcialidades a las que aplica. Fase 2: requiere los `enrollment_id` del detalle del alumno |
| Condonaciones | ❌ | — | Podrían existir como descuentos; no documentado |

## Observaciones técnicas

* **Autenticación**: OAuth2 JWT Bearer con llave RSA (RS256) por *Service Account*, delegando en un
  usuario del dominio. Los permisos de ese usuario limitan lo que ve la API. Implementado y probado.
* **Sin consultas incrementales documentadas**: no hay filtros `updated_since`/`updated_at`. Por eso
  el conector compara el hash SHA-256 de cada registro: solo marca como modificado lo que cambió.
* **Paginación**: `limit`/`offset` + `sort_by`. Obligatoria en cursos (máx. 100).
* **Alumnos**: el listado solo trae activos y pocos campos; el detalle completo exige una llamada por
  alumno (opción *Descargar detalle por ID*). Con miles de alumnos conviene acordar con SAEKO un
  listado con `include_fields` ampliado.
* **Discrepancias en la documentación**: `GET /api/v1/core/terns/{id}/groups` (dice *terns*) y
  `/location/countries` (sin `/api/v1`). El conector usa las rutas corregidas; si fallan se ajustan
  en el catálogo sin tocar código.
* **Sin webhooks documentados**: la integración es por *polling* programado.

## Preguntas para SAEKO

1. ¿Existen endpoints (aunque no estén en la documentación pública) para **cargos/conceptos por
   alumno**, **pagos**, **adeudos/saldos**, **condonaciones/descuentos** y **facturas/CFDI**
   (UUID, XML, PDF, tipo individual o global)?
2. Para pagos: ¿cómo se expresan **forma de pago** (claves SAT 01/03/04/28) y **método** (pasarela,
   TPV, referenciado, transferencia)? ¿Se puede identificar la pasarela y la referencia?
3. ¿Quién **timbra los CFDI** hoy: SAEKO o un tercero? Esto define si Odoo importa CFDI ya timbrados
   o si Odoo factura.
4. Estructura del modelo **Enrollment** (estatus: activo, baja temporal, baja definitiva, egresado…).
5. ¿Hay `GET` para **GateAccessLog** (checador), **horarios** de cursos, **asistencias** de
   profesores, **suplencias**, **incidencias** y **bonos**? Si no, ¿qué sistema es la fuente?
6. ¿Filtros por fecha de modificación para descargas incrementales? ¿Webhooks?
7. Límites de uso (*rate limits*) y ventanas recomendadas para procesos masivos.
8. ¿Hay un **dominio sandbox** con datos de prueba? ¿Vigencia y proceso de renovación de la llave
   del Service Account?
9. ¿Qué permisos mínimos debe tener el **usuario delegado** para lectura total sin poder modificar?

Los endpoints faltantes ya existen en el catálogo como recursos **[PENDIENTE]** (archivados, fase 3).
En cuanto SAEKO entregue una ruta, se captura, se prueba en el Explorador API y se activa, sin
tocar código.
