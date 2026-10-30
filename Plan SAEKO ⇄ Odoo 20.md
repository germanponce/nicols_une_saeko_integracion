# Plan SAEKO ⇄ Odoo 20

Integración Versión Enterprise

## Resumen Ejecutivo

La integración se construye sobre Odoo 20 en seis fases y 14 semanas hábiles, unos tres meses y medio aprox.&#32;

Lo anterior arrojaria un arranque estimado (ejemplo) empleando el día 9 de noviembre de 2026, con una salida a producción estimada para el 1 de marzo de 2027.&#32;

El proyecto inicia con el análisis de la API de SAEKO y el desarrollo del conector (modulo versión 20.0), que es la base de todas las fases siguientes.

El cuello de botella no es Odoo sino SAEKO. La API pública no documenta cargos, pagos, CFDI, adeudos, asistencias, suplencias ni bonos, un estimado de 14 puntos de los 25  solicitados via correo. Las fases 4 (finanzas) y 5 (docentes y nómina) arrancan solo cuando SAEKO nos entregue estos endpoints o generen una aclaración en caso de entenderlo incorrectamente, las fases 1 a 3 avanzan sin esperar.

**Decisiones que se necesitan antes del 20 de noviembre de 2026**

1. **Quién timbra los CFDI.** Si timbra SAEKO, Odoo importa UUID, XML y PDF sin re-timbrar. Si timbra Odoo, se factura con la localización mexicana de Enterprise, incluida la factura global. Moveria el alcance de la Fase 4 aproximadamente 1 semana.
2. **H****o****sting****.** Odoo.sh o servidor propio On Premise. Odoo 20 requiere Python 3.12 a 3.14 y PostgreSQL 16 o superior.
3. **Módulos estándar.** Usar Empleados (`hr`), Asistencias (`hr_attendance`), Contabilidad y Nómina de Enterprise en lugar de modelos propios.  Pendiente el análisis y aclaración para determinar si es una versión 100% nativa sin adaptaciones o campos añadidos con Studio y no esten contemplados.
4. **Fecha compromiso de SAEKO** para los endpoints faltantes, a más tardar el 11 de enero de 2027. Sin estos endpoints, las fases 4 y 5 no tienen fecha real.

## Qué cambia en Odoo 20 y cómo afecta al proyecto (Releases Notes)

Dos cambios de Odoo 20 tocan directamente este proyecto: la seguridad se reescribió en un solo modelo y la nómina ya no usa entradas de trabajo. Los primeros cinco renglones se validaron en el código de la rama `20.0` de Odoo. Los marcados como *reportado* vienen de publicaciones de terceros y están en análisis.

| Cambio en Odoo 20 | Impacto en el proyecto | Estado |
| --- | --- | --- |
| Permisos y reglas de registro unificados en `ir.access` (`ir.access.csv`); desaparecen `ir.model.access` e `ir.rule` | El conector y los módulos nuevos definen sus permisos y su regla multicompañía en este formato, con pruebas automatizadas | Verificado · define Fase 2 |
| `hr.work.entry` se elimina; las **reglas de tiempo** (`hr.time.rule`) se evalúan sobre asistencias (`hr.attendance`) y ausencias (`hr.leave`) | El checador de profesores debe aterrizar en `hr.attendance`; horas extra, faltas y suplencias se calculan con reglas de tiempo | Verificado · define Fase 5 |
| Contrato y salario viven en versiones del empleado (`hr.version`) | La tarifa por hora del profesor se registra por versión, con historial | Verificado |
| `/xmlrpc` y `/jsonrpc` obsoletos, con retiro previsto en Odoo 22; reemplazo: `/json/2/<modelo>/<método>` con API key | El conector no se ve afectado: Odoo llama a SAEKO. Si SAEKO u otro sistema escribe en Odoo, debe usar JSON-2 | Verificado |
| Python 3.12 a 3.14 y PostgreSQL 16 o superior | Define el ambiente de servidor propio u Odoo.sh | Verificado |
| Agente de IA que ejecuta acciones con aprobación del usuario; Odoo como cliente y servidor MCP | Consultas en lenguaje natural sobre alumnos y adeudos. Mejora opcional en Fase 6 | Reportado |
| Nómina: tablero de avisos previos, simulador neto a bruto y localizaciones reajustadas | Validar que la nómina mexicana de Enterprise esté disponible en 20 durante el análisis (Fase 1) | Reportado |
| Nuevo esquema de licencia *Light User* para empleados sin acceso completo (contrato Enterprise v13) | Los profesores que solo registren asistencia podrían caer en este esquema; revisar costos con Odoo | Reportado |

Fuentes:&#32;

- Lanzamiento Odoo 20.0 en [GitHub](https://github.com/odoo/odoo/tree/20.0) (`odoo/release.py`, `ir_access.py`, `h``r_time_rule.py`, `rpc/controllers`)
- &#32;[OEC.sh: Odoo 20 released](https://oec.sh/blog/odoo-20-released-what-we-see)
- [Webkul: guía de migración a Odoo 20](https://webkul.com/blog/odoo-20-migration-guide/amp/).

## Fases de desarrollo e implementación

Cada fase cierra con una compuerta medible, no se pasa a la siguiente sin cumplirla. Las duraciones son estimaciones en semanas hábiles para un equipo de 2 desarrolladores Odoo y 1 consultor funcional, y suman 14 semanas.

| Fase | Alcance | Entregables | Compuerta de salida | Semanas | Depende de |
| --- | --- | --- | --- | --- | --- |
| **1. Análisis y diseño** | API de SAEKO, procesos de la universidad, decisiones clave, ambientes | Matriz de los 25 requerimientos contra la API de SAEKO; preguntas a SAEKO respondidas; diseño de arquitectura y modelo de datos; ambientes Odoo 20 de desarrollo, staging y producción; repositorio con rama `20.0` | Las 4 decisiones del resumen tomadas por escrito y credenciales SAEKO de sandbox entregadas | 2 | Universidad, SAEKO |
| **2. Desarrollo del conector** | Módulo `saeko_connector`: conexión, bitácora, datos crudos, sincronización programada | Autenticación OAuth2 JWT con renovación de token; bitácora de cada llamada con secretos ocultos; datos crudos con versión e historial; catálogo de endpoints configurable; crons; explorador de API; pruebas automatizadas; primera carga completa desde SAEKO | Prueba de conexión verde contra SAEKO y carga cruda de todos los recursos documentados sin errores | 2 | Fase 1 |
| **3. Maestro académico** | Alumnos, profesores, planteles, ciclos, programas, grupos, materias, becas | Módulo `saeko_academic`: modelos académicos, alumnos como contactos, profesores como empleados, ficha académica por alumno, becas por inscripción, con trazabilidad al dato crudo | Conteos de alumnos y profesores por plantel y programa cuadran al 100 % con SAEKO | 3 | Fase 2 |
| **4. Finanzas de alumnos** | Conceptos, cargos, pagos, facturas y CFDI, adeudos, condonaciones | Módulo `saeko_account`: productos por concepto; facturas de cliente; pagos con diario por método (pasarela, TPV, referenciado, transferencia) y forma de pago SAT; CFDI importado o timbrado; reporte de conciliación de adeudos | Saldo por alumno y por plantel cuadra con SAEKO en un corte de mes; contabilidad lo valida | 3 | Endpoints SAEKO de finanzas; decisión CFDI |
| **5. Docentes y nómina** | Carga horaria, horario, checador, carga dada, suplencias, incidencias, bonos | Módulo `saeko_hr`: horario como calendario de trabajo; checador en Asistencias; reglas de tiempo para faltas, retardos y suplencias; incidencias con documentos adjuntos; bonos como entradas de nómina | Una quincena de nómina en paralelo con diferencia cero contra el proceso actual | 2 | Endpoints SAEKO docentes; Nómina Enterprise |
| **6. Pruebas y salida a producción** | Pruebas integrales, reportes, capacitación, arranque | Pruebas de aceptación por área; tableros por plantel; alertas por correo cuando falla una sincronización; manuales; capacitación a contabilidad, nómina y control escolar; arranque | Un ciclo de cobranza y una quincena en producción sin incidentes críticos | 2 + 2 de soporte | Fases 3 a 5 |

Las fases 4 y 5 son la ruta crítica: si SAEKO entrega tarde los endpoints, el calendario solo se protege adelantando la Fase 5 en paralelo con un desarrollador por módulo.

## Mapeo de requerimientos a Odoo 20

Once de los 25 datos ya tienen fuente en SAEKO (7 completos, 4 parciales); los otros 14 dependen de endpoints que SAEKO no documenta. El destino en Odoo se eligió para usar módulos estándar siempre que existan.

| Requerimiento | Fuente SAEKO | Destino en Odoo 20 | Fase | API SAEKO |
| --- | --- | --- | --- | --- |
| **Profesores** |  |  |  |  |
| Contacto: nombre, CURP, RFC, grado de estudios | Employee | Empleado (`hr.employee`) + contacto; grado en datos de formación | 3 | Completo |
| Tarifas | `Employee.cost_per_hour` | Versión del empleado (`hr.version`) con tarifa por hora | 3 | Parcial: una sola tarifa |
| Carga horaria: horario, plantel, modalidad, programa | Course + Group | Curso académico ligado a empleado; horario como calendario de trabajo | 3 y 5 | Parcial: sin horario |
| Carga dada | — | Asistencias (`hr.attendance`) contra horario, vía reglas de tiempo | 5 | Sin endpoint |
| Registros de asistencia y checador | GateAccessLog | Asistencias (`hr.attendance`) | 5 | Parcial: solo alta |
| Incidencias por suplencia | — | Ausencia del titular + asistencia del suplente; regla de tiempo | 5 | Sin endpoint |
| Documentación de incidencias | — | Adjuntos en la incidencia | 5 | Sin endpoint |
| Bonos | — | Entrada de nómina (Nómina Enterprise) | 5 | Sin endpoint |
| **Alumnos** |  |  |  |  |
| Contacto | Student | Contacto (`res.partner`) con matrícula y CURP; RFC en el campo fiscal | 3 | Completo |
| Ciclo escolar | Term | Modelo académico de ciclo | 3 | Completo |
| Estatus del alumno | Student + enrollments | Ficha académica por ciclo | 3 | Parcial: modelo sin documentar |
| Plantel | School | Modelo académico + cuenta analítica por plantel | 3 | Completo |
| Nivel | `Program.level` | Programa académico | 3 | Completo |
| Programa | Program | Programa académico | 3 | Completo |
| Concepto pagado | — | Producto por concepto en la factura | 4 | Sin endpoint |
| Monto | — | Línea de factura | 4 | Sin endpoint |
| Fechas del concepto | — | Fecha y vencimiento de factura | 4 | Sin endpoint |
| Fecha de pago | — | Pago (`account.payment`) | 4 | Sin endpoint |
| Forma de pago (tarjeta, transferencia, débito, efectivo) | — | Forma de pago SAT en el pago | 4 | Sin endpoint |
| Método de pago (pasarela, TPV, referenciado, transferencia) | — | Diario de pago por método | 4 | Sin endpoint |
| Factura individual o global | — | Factura de cliente; factura global de la localización mexicana | 4 | Sin endpoint |
| CFDI de cada concepto | — | Importado (UUID, XML, PDF) o timbrado en Odoo | 4 | Sin endpoint |
| Adeudo | — | Saldo de cuentas por cobrar + reporte de conciliación | 4 | Sin endpoint |
| Becas | ScholarshipType + Scholarship | Beca por inscripción; descuento en factura | 3 y 4 | Completo |
| Condonaciones | — | Nota de crédito o descuento con referencia al dato crudo | 4 | Sin endpoint |

## Cronograma, equipo y riesgos

Con arranque el 9 de noviembre de 2026, las 14 semanas hábiles terminan el 26 de febrero de 2027 y la salida a producción cae el 1 de marzo de 2027, siempre que SAEKO entregue los endpoints de finanzas antes del 11 de enero de 2027. Cada semana de retraso de SAEKO mueve la fecha final una semana. La pausa del 21 de diciembre al 1 de enero no cuenta dentro de las 14 semanas.

&#91;embedded content: cronograma · 6 fases, 14 semanas hábiles, nov 2026 a mar 2027\]

Las fases 4 y 5 son las únicas que dependen de un tercero; el resto del calendario está en manos del equipo.

### Equipo

| Rol | Dedicación | Responsabilidad |
| --- | --- | --- |
| Líder de proyecto&#32; | 25 % | Plan, compuertas, relación con SAEKO |
| Desarrolladores Odoo (2) | 100 % | Módulos `saeko_academic`, `saeko_account`, `saeko_hr`; pruebas automatizadas |
| Consultor funcional | 50 % | Contabilidad, CFDI, nómina; pruebas de aceptación |
| Contraparte de la universidad | 20 % por área | Control escolar, contabilidad y nómina validan cada compuerta |
| Contacto técnico SAEKO | A demanda | Endpoints, credenciales, dudas de datos |

### Riesgos

| Riesgo | Impacto | Mitigación |
| --- | --- | --- |
| SAEKO no expone cargos, pagos o CFDI | Fase 4 bloqueada; sin finanzas no hay valor contable | Pedir compromiso por escrito en la Fase 1; alternativa: exportación periódica de SAEKO cargada al catálogo del conector como recurso |
| Diferencias entre adeudos de SAEKO y saldos de Odoo | Desconfianza en los números | Reporte de conciliación diario desde la Fase 4; datos crudos con historial para rastrear cada diferencia |
| Doble timbrado de CFDI | Error fiscal ante el SAT | Una sola fuente de timbrado decidida en la Fase 1; validación por UUID antes de importar |
| Volumen: el detalle de alumno requiere una llamada por registro | Sincronizaciones lentas | Medir en la Fase 2; pedir a SAEKO un listado con más campos; programar fuera de horario |
| Nómina mexicana de Enterprise sin publicar para Odoo 20 | Fase 5 sin motor de nómina | Confirmar con Odoo en la Fase 1; si no está, exportar a la nómina actual |
| Llave del Service Account vence | Integración detenida | El conector avisa 30 días antes del vencimiento |
| Calendario de 14 semanas sin holgura | Una compuerta fallida recorre todo | Revisión semanal del avance contra compuertas; alcance de Fase 6 negociable (tableros y alertas pueden salir después del arranque) |
| Licencias *Light User* para profesores | Costo no presupuestado | Cotizar con Odoo en la Fase 1 |

## Estimación de tiempos y costo

El proyecto se estima entre 160 y 200 horas. Los precios los completa el área de ventas.

| Fase | Horas (mín–máx) | Precio unitario por hora | Precio total |
| --- | --- | --- | --- |
| 1. Análisis y diseño | 16–20 |  |  |
| 2. Desarrollo del conector | 28–36 |  |  |
| 3. Maestro académico | 32–40 |  |  |
| 4. Finanzas de alumnos | 36–44 |  |  |
| 5. Docentes y nómina | 28–36 |  |  |
| 6. Pruebas y salida a producción | 20–24 |  |  |
| **Total** | **160–200** |  |  |

Incluye desarrollo y consultoría, no incluye licencias de Odoo Enterprise ni hospedaje.
