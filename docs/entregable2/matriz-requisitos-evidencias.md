# Matriz: requisito del profesor → informe → evidencia → estado

Fuentes oficiales leídas completas: plantilla `entregable2_cloud_computing_upeu_*.docx` (secciones 02–20) y rúbrica `rubrica_entregable2_cloud_computing_upeu_*.docx` (5 criterios × 4 puntos = 20). Esta matriz **no asigna puntajes**: indica qué hay, qué falta y dónde está la prueba. Estados: **Completo** (con evidencia medida) · **Parcial** (hay evidencia pero falta un elemento del descriptor superior) · **Falta**. El verificador `scripts/docs/verificar-entregable2.py` comprueba que todos los enlaces de esta matriz existen.

## A. Por criterio de la rúbrica
| Criterio (secciones) | Descriptor «Excelente» | Evidencia existente | Estado | Qué falta para el descriptor superior |
|---|---|---|---|---|
| **1. Evolución V1 → V2** (2–6) | Corrige problemas y demuestra mejoras técnicas significativas | [Medición V1 vs V2](../evidencias/medicion-v2-20261022/resultado.md) · [validación V2](../evidencias/validacion-v2-20261022/resultado.md) · [escalado](../evidencias/escalado-v2-20261022/resultado.md) · [failover RDS](../evidencias/multicloud/aws/20261023-rds-multiaz/failover/resultado.md) · [diagramas](diagramas/) | **Completo en mediciones; parcial en forma** | Retroalimentación docente literal (sección 04); capturas de consola antes/después; V2 está destruida (P4) |
| **2. Amenazas y vulnerabilidades** (8, 19) | Identificación y tratamiento técnicamente completos | [Informe §08 (18 amenazas)](informe-entregable2.md#08--análisis-de-amenazas-y-vulnerabilidades) · [§19 (15 riesgos)](informe-entregable2.md#19--riesgos-residuales) · pruebas locales (44 backend, 33 frontend) | **Completo en análisis; parcial en prueba** | Repetir en AWS la ráfaga de logins y el límite de intentos (P3); verificar CloudTrail (P8) |
| **3. Controles de seguridad** (7, 9, 10, 14) | IAM, red, cifrado, monitoreo y controles correctamente implementados | [Identidad Azure](../evidencias/multicloud/azure/20261028-vm/identidad-administrada.txt) · [NSG](../evidencias/multicloud/azure/20261028-vm/nsg-reglas.txt) · [puertos/TLS](../evidencias/multicloud/azure/20261028-vm/acceso-https-y-puertos.txt) · [OCI IAM](../evidencias/multicloud/oci/20261023-iam-carga/resultado.md) · [lectura API AWS](../evidencias/lectura-aws-2026-10-09.md) · [EV08](../evidencias/EV08/recepcion-real-2026-10-10.md) | **Parcial** | Capturas de consola IAM/red/cifrado/monitoreo (P2); IAM propio de mínimo privilegio en AWS (limitado por Academy); MFA; entrega real de correo de alertas (P5) |
| **4. Escalabilidad, disponibilidad y tolerancia a fallos** (11–13, 15) | Solución coherente, redundante y justificada | [Escalado 2→3→2](../evidencias/escalado-v2-20261022/resultado.md) · [fallos V2](../evidencias/tolerancia-fallos-v2-20261022/resultado.md) · [autohealing](../evidencias/tolerancia-fallos-v2-20261022-b/resultado.md) · [Multi-AZ](../evidencias/multicloud/aws/20261023-rds-multiaz/resultado.md) · [R01](../evidencias/EV07/resultado-restauracion-2026-10-10.md) · [recuperación OCI](../evidencias/multicloud/oci/20261023-recuperacion-aplicacion/resultado.md) | **Parcial** | 100/500/1 000 usuarios no medidos (generador ≤ 50); fallo de zona completa; disponibilidad de la API durante la caída; recuperación completa en AWS (P4, P6); respaldo programado (P7) |
| **5. Evidencias, pruebas y documentación** (16–18, 20) | Evidencias verificables, pruebas completas y documentación profesional | [Informe](informe-entregable2.md) · [ventana Azure](../evidencias/multicloud/azure/20261028-vm/resultado.md) · [EV11](../evidencias/EV11/resultado-2026-10-09.md) · [validación pública](../evidencias/validacion-publica-20261019-e88f179-b/resultado.md) | **Parcial** | Capturas antes/después (sección 17); costos observados (P9); datos de portada; series de CloudWatch ([prioridad](cloudwatch-evidencia-prioritaria.md)) |

## B. Por sección de la plantilla oficial
| Sec. | Requisito | Dónde está | Evidencia principal | Estado |
|---|---|---|---|---|
| 01 | Introducción | [§01](informe-entregable2.md#01--introducción-y-alcance) | — | Completa |
| 02 | Resumen del E1 (≤ 1 página) | [§02](informe-entregable2.md#02--resumen-del-entregable-1) | `work/docx-review/NexoEventos_Entregable1_Documentacion.pdf`, [arquitectura V1](../arquitectura-inicial.md) | Completa |
| 03 | Diagrama V1 | [§03](informe-entregable2.md#03--arquitectura-v1) | [`v1-arquitectura.svg`](diagramas/v1-arquitectura.svg) | Completa |
| 04 | Retroalimentación recibida | [§04](informe-entregable2.md#04--retroalimentación-recibida) | Autoauditoría documentada | **Parcial: falta la retroalimentación docente literal** |
| 05 | Comparación V1 vs V2 | [§05](informe-entregable2.md#05--comparación-v1-versus-v2) | [Medición](../evidencias/medicion-v2-20261022/resultado.md) | Completa |
| 06 | Diagrama V2 | [§06](informe-entregable2.md#06--arquitectura-cloud-v2) | [`v2-arquitectura.svg`](diagramas/v2-arquitectura.svg), [`v2-multicloud.svg`](diagramas/v2-multicloud.svg) | Completa |
| 07 | Seguridad (9 dimensiones) | [§07](informe-entregable2.md#07--seguridad) | Tabla con evidencia por fila | Completa (con 2 `[NO VERIFICADO]`/`[NO IMPLEMENTADO]`) |
| 08 | Amenazas y vulnerabilidades | [§08](informe-entregable2.md#08--análisis-de-amenazas-y-vulnerabilidades) | Matriz de 18 filas | Completa |
| 09 | IAM | [§09](informe-entregable2.md#09--iam) | [OCI IAM](../evidencias/multicloud/oci/20261023-iam-carga/resultado.md), [Azure](../evidencias/multicloud/azure/20261028-vm/identidad-administrada.txt) | **Parcial: IAM de AWS limitado por Academy** |
| 10 | Seguridad de red | [§10](informe-entregable2.md#10--seguridad-de-red) | `infra/aws*/network.tf`, [NSG](../evidencias/multicloud/azure/20261028-vm/nsg-reglas.txt) | Completa; capturas de consola pendientes (P2) |
| 11 | Escalabilidad | [§11](informe-entregable2.md#11--escalabilidad) | [Medición](../evidencias/medicion-v2-20261022/resultado.md), [escalado](../evidencias/escalado-v2-20261022/resultado.md) | **Parcial: 100–5 000 son proyección** |
| 12 | Alta disponibilidad | [§12](informe-entregable2.md#12--alta-disponibilidad-y-tolerancia-a-fallos) | [Fallos](../evidencias/tolerancia-fallos-v2-20261022/resultado.md), [failover](../evidencias/multicloud/aws/20261023-rds-multiaz/failover/resultado.md) | Completa con limitaciones declaradas |
| 13 | Eliminación de SPOF | [§13](informe-entregable2.md#13--eliminación-de-spof) | Mismas | Completa |
| 14 | Monitoreo | [§14](informe-entregable2.md#14--monitoreo) | [Alerta Azure](../evidencias/multicloud/azure/20261028-vm/azure-alerta-cpu-disparada.json), [Zabbix](../evidencias/multicloud/azure/20261028-vm/zabbix-umbrales-triggers.txt) | Completa; entrega de correo no comprobada |
| 15 | Backup y recuperación | [§15](informe-entregable2.md#15--backup-y-recuperación) | [R01](../evidencias/EV07/resultado-restauracion-2026-10-10.md), [OCI](../evidencias/multicloud/oci/20261023-recuperacion-aplicacion/resultado.md) | **Parcial: respaldo no programado; recuperación AWS completa no acreditada** |
| 16 | Pruebas (5 categorías mínimas) | [§16](informe-entregable2.md#16--pruebas-realizadas) | Ver tabla de la sección | Completa en las 5 categorías, con límites |
| 17 | Evidencias antes/después | [§17](informe-entregable2.md#17--evidencias-antes--después) | 5 mejoras con archivos medidos | **Parcial: faltan capturas de consola** |
| 18 | Costos | [§18](informe-entregable2.md#18--costos-preliminares) | [costos V1](../costos-v1.md), [multicloud/03](../multicloud/03-costos-y-riesgos.md) | Completa como estimación; sin facturación observada |
| 19 | Riesgos residuales | [§19](informe-entregable2.md#19--riesgos-residuales) | — | Completa |
| 20 | Conclusiones | [§20](informe-entregable2.md#20--conclusiones-técnicas) | — | Completa |
| Portada | Nombre, integrantes, equipo, docente, fecha | Cabecera del informe | — | **Falta: apellidos y código, `Equipo XX`, docente, fecha** |

## C. Evidencias existentes por nube
| Nube | Carpeta | Contenido |
|---|---|---|
| AWS V1 | [`EV01`–`EV11`](../evidencias/), [validación pública](../evidencias/validacion-publica-20261019-e88f179-b/resultado.md) | Funcional, red, SG, EC2, RDS, respaldo, logs, carga E01 |
| AWS V2 | [`validacion-v2`](../evidencias/validacion-v2-20261022/resultado.md), [`medicion-v2`](../evidencias/medicion-v2-20261022/resultado.md), [`escalado-v2`](../evidencias/escalado-v2-20261022/resultado.md), [`tolerancia-fallos-v2`](../evidencias/tolerancia-fallos-v2-20261022/resultado.md) | Validación, escalera, escalado, fallos |
| AWS Multi-AZ | [`multicloud/aws`](../evidencias/multicloud/aws/20261023-rds-multiaz/resultado.md) | Conversión, failover, respaldo 0008 |
| OCI | [`multicloud/oci`](../evidencias/multicloud/oci/20261023-recuperacion-aplicacion/resultado.md) | IAM, red, transferencia, simulacro, recuperación de la aplicación, cierres |
| Azure | [`multicloud/azure/20261028-base`](../evidencias/multicloud/azure/20261028-base/resultado.md), [`…-vm`](../evidencias/multicloud/azure/20261028-vm/resultado.md) | Base, VM, SSH, servicios, alertas, identidad, métricas |

## D. Verificación de AWS del 28-oct-2026 (sin sesión)
| Elemento | Estado | Evidencia |
|---|---|---|
| Sesión de AWS Academy | **Caducada** (`ExpiredToken`); no se consultó RDS, CloudWatch, IAM, CloudTrail ni costos | [resultado](../evidencias/multicloud/aws/20261028-estado-sin-sesion/resultado.md) |
| Riesgo de reinicio de la RDS | Estimado con registros locales: ≈ 30-oct 15:18Z (**no verificado contra AWS**) | mismo archivo |
| Herramientas de solo lectura | Listas y probadas en local: auditoría con guarda, exportación de series originales y gráficos sin interpolación | `scripts/cloud/readonly-audit.py`, `scripts/observability/export-cloudwatch.py`, `plot-cloudwatch.py` |
| IAM, red, cifrado, CloudTrail y costos nuevos | **Sin evidencia nueva**: requieren sesión activa (P0) | [procedimientos](procedimientos-pendientes-autorizacion.md) |


### E. Recuperación de CloudWatch (28-oct, AWS solo lectura)
| Requisito | Estado | Evidencia |
|---|---|---|
| Series originales 1 min de V1, V2 y 23-oct (RDS, ALB, ASG) y 5 min (EC2) | **Recuperadas** (40 series; EC2 solo a 300 s, sin memoria) | `docs/evidencias/multicloud/aws/20261028-cloudwatch/` (`series-originales.json`, `graficos/`, `resultado.md`) |
| EC2 de V1 detenida tras reinicio del laboratorio | **Verificada** `stopped` el 2026-10-28 21:02:56Z (orden autorizada, solo esa instancia) | `work/operacion/sesiones-cloud.log` (local) |
| RDS Multi-AZ | **Leída** `stopped` (sin cambios); reinicio automático previsto ≈ 30-oct 15:18Z → **mitigado el 28-oct** (ciclo start-stop; nuevo plazo ≈ 4-nov 21:51Z, ver 20261028-rds-ciclo-start-stop) | — |

### F. Cierre del 28-oct (auditoría de solo lectura e informe final)
| Requisito | Estado | Evidencia |
|---|---|---|
| IAM, red, cifrado y CloudTrail de AWS | **Verificados por API** (solo lectura). Hallazgos negativos: 0 trails de CloudTrail, alarma sin acciones, RDS sin protección contra borrado, `LabRole` con 7 políticas | `docs/evidencias/multicloud/aws/20261028-auditoria-solo-lectura/` |
| Series de CloudWatch en el informe | Integradas en §11.1, §12, §14 y §17 (6 gráficos) | `docs/entregable2/graficos/`, informe |
| Medido vs proyectado | Separados en §11 y §16.1 (medido ≤ 50 usuarios; 100+ proyección) | informe |
| Informe Word/PDF | Generados con `scripts/docs/informe-a-html.py` y `html-a-docx.py` (Chrome para el PDF) | `docs/entregable2/Entregable2-NexoEventos.{docx,pdf}` |
| Sin comprobar | Permisos efectivos de `LabRole`, clave KMS, costo facturado real, retroalimentación docente, entrega real de correo de alerta, capturas de consola, datos de portada | informe §04, §16.1, §17 |

### G. Capturas auténticas de consola
| Captura | Qué respalda | Archivo | Estado |
|---|---|---|---|
| A5-1 Consola RDS: configuración (28-oct) | Multi-AZ, cifrado, sin IAM de BD, umbral de almacenamiento 20 GiB (criterios 3 y 4) | `docs/evidencias/capturas/aws/01-rds-config.png` | **Incorporada** (copia con cuenta, usuario, ARN e IDs ocultos; original intacto en Descargas) |
| A5-2 AWS CLI: acceso público, cifrado, estado, Multi-AZ, protección de borrado | Controles de RDS y ausencia de protección contra borrado (criterios 3 y 4) | `docs/evidencias/capturas/aws/02-rds-seguridad.png` | **Incorporada** (usuario/equipo ocultos) |
| A2, A1, A10, A11, A8, B3 y resto de la guía | Red, IMDSv2, escalado, 5xx, CloudTrail, alerta de Azure | `docs/entregable2/guia-capturas-consola.md` | **Pendientes** |
| A2-1 Consola EC2: reglas de **entrada** del SG web (28-oct) | 80/443 desde `0.0.0.0/0`, sin regla 22 (criterio 3) | `docs/evidencias/capturas/aws/05-web-sg-entrada.png` | **Incorporada** (cuenta, usuario, IDs ocultos) |
| A2-2 Consola EC2: reglas de **salida** del SG web | DNS 53 a la VPC, HTTPS 443, PostgreSQL 5432 hacia un SG (criterio 3). El destino del 5432 está oculto; su identidad como SG de la base se apoya en la API | `docs/evidencias/capturas/aws/04-web-sg-salida.png` | **Incorporada** |
| A10 Consola CloudWatch: `GroupInServiceInstances` (Media, 1 min, 22-oct 14:00–18:00 UTC) | Secuencia observada 0→2→3→2→0 instancias; escalabilidad horizontal (criterio 4). No se asocia a un número de usuarios (no medido) | `docs/evidencias/capturas/aws/06-asg-escalabilidad.png` | **Incorporada** (cuenta y usuario ocultos); coincide con `20261028-cloudwatch/series-originales.json` |
| A11 Consola CloudWatch: `HTTPCode_Target_5XX_Count` (Suma, 1 min, 22-oct 16:00–17:00 UTC) | 5xx del destino solo ≈16:03 (25) y ≈16:38 (40), coincidentes con las dos pruebas de fallo (criterio 4). La gráfica **no** prueba por sí sola la recuperación: esta se acredita con `tolerancia-fallos-v2-20261022*/resultado.md` | `docs/evidencias/capturas/aws/07-alb-errores-5xx.png` | **Incorporada** (cuenta y usuario ocultos) |
