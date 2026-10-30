# Roadmap por fases

## Fase 1: Base (este entregable) ✅

Conexión OAuth2 JWT, prueba de conexión, bitácora inmutable, datos crudos con hash, versión,
historial y ausentes; catálogo de endpoints; programación por recurso; crons de sincronización,
healthcheck y depuración; explorador API; importación de credenciales; seguridad; simulador y pruebas.

Recursos que ya aterrizan: planteles, ciclos, programas, grupos y cursos del ciclo vigente,
materias, alumnos activos, empleados/profesores, tipos de beca, campañas de admisión y países.

## Fase 2: Mapeo académico a Odoo 19 (con lo que hoy expone SAEKO)

Procesar `saeko.raw.record` en estado *pendiente* → modelos Odoo, guardando `odoo_model` y
`odoo_res_id` en el crudo (trazabilidad en ambos sentidos).

| SAEKO | Odoo 19 propuesto | Notas |
|---|---|---|
| School | `saeko.school` (catálogo) + cuenta analítica por plantel | Permite reportar ingresos y costos por plantel |
| Term | `saeko.term` | Fechas, tipo, vigente |
| Program | `saeko.program` | Nivel, RVOE |
| Group / Course / Subject | `saeko.group`, `saeko.course`, `saeko.subject` | Base de la carga horaria |
| Student | `res.partner` (alumno) + `saeko.enrollment` | Matrícula, CURP; RFC en `vat`; plantel, programa, nivel, ciclo, estatus |
| Employee (profesor) | `hr.employee` + `res.partner` | CURP, RFC, grado, `cost_per_hour` como tarifa base |
| ScholarshipType / Scholarship | `saeko.scholarship` | Porcentaje o fijo; parcialidades a las que aplica |

Decisión pendiente: ¿módulos `hr` y `contacts` como dependencia (recomendado), o solo modelos propios?

## Fase 3: Finanzas de alumnos (depende de SAEKO)

Requiere los endpoints de cargos, pagos, adeudos, condonaciones y CFDI (ver *ANALISIS_API.md*).

| Dato | Odoo 19 EE propuesto |
|---|---|
| Concepto, monto, fechas | Productos por concepto (colegiatura, inscripción, reinscripción…) y líneas de factura de cliente (`account.move`) |
| Pagos | `account.payment` con diario por método (pasarela, TPV, depósito referenciado, transferencia) |
| Forma de pago (SAT) | Catálogo de formas de pago de la localización mexicana (`l10n_mx_edi`, Enterprise) |
| Factura individual/global, CFDI | Si **SAEKO timbra**: importar UUID, XML y PDF como adjuntos sin re-timbrar. Si **Odoo timbra**: facturar desde Odoo con `l10n_mx_edi`, incluida la factura global |
| Adeudo | Saldo de cuentas por cobrar del alumno, conciliado contra SAEKO |
| Becas y condonaciones | Descuentos en línea o notas de crédito, con referencia al crudo |

Esta fase incluye una **conciliación**: reporte de diferencias entre adeudos de SAEKO y saldos de Odoo.

## Fase 4: Nómina docente (depende de SAEKO)

Carga horaria × tarifa, carga dada (asistencias/checador), suplencias, incidencias con
documentación y bonos → entradas de trabajo y nómina (Odoo Payroll EE), con evidencia en crudo.

## Transversal

* Tablero de salud de la integración (errores por día, latencia, volumen por recurso).
* Alertas por correo o actividad al fallar una ejecución programada.
* Si SAEKO ofrece webhooks o filtros por fecha de modificación: sincronización incremental.
