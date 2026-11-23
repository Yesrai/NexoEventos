# Entregable 2 — índice, estado y siguiente paso

Preparado el **28-oct-2026** solo con trabajo local (sin encender, crear ni destruir nada en AWS, OCI o Azure; sin `apply`/`destroy`; VM de Azure desasignada).

| Archivo | Qué es |
|---|---|
| [`informe-entregable2.md`](informe-entregable2.md) | Informe con las **20 secciones** de la plantilla oficial; cada cifra enlaza su evidencia; `[PENDIENTE]` marca lo que no existe |
| [`diagramas/`](diagramas/) | `v1-arquitectura`, `v2-arquitectura`, `v2-multicloud` en `.svg` (editable) y `.png` (2400 px, para el Word) ( fieles a `infra/aws`, `infra/aws-v2` y a las evidencias) |
| [`matriz-requisitos-evidencias.md`](matriz-requisitos-evidencias.md) | Requisito del profesor → sección del informe → archivos → estado |
| [`procedimientos-pendientes-autorizacion.md`](procedimientos-pendientes-autorizacion.md) | Pruebas que necesitan AWS o Azure (P1–P9), **listas y sin ejecutar** |
| [`cloudwatch-evidencia-prioritaria.md`](cloudwatch-evidencia-prioritaria.md) | Qué copia local de CloudWatch existe, qué se pierde y cuándo |
| `scripts/docs/verificar-entregable2.py` | Verificador sin red: secciones 01–20, enlaces y anclas, datos sensibles, cifras ↔ evidencias |

Fuentes oficiales: plantilla y rúbrica del Entregable 2 (Word, descargadas por la propietaria). **No hay puntajes asignados**: la rúbrica la aplica el docente.

## Estado por sección
| Sección | Estado | Observación |
|---|---|---|
| 01 Introducción, 03 V1, 05 Comparación, 06 V2, 07 Seguridad, 08 Amenazas, 10 Red, 12 HA, 13 SPOF, 14 Monitoreo, 16 Pruebas, 18 Costos, 19 Riesgos, 20 Conclusiones | **Completas** con evidencia y límites declarados | Costos: estimaciones, sin facturación observada |
| 02 Resumen del E1 | **Completa** | Basada en el PDF del Entregable 1 |
| 04 Retroalimentación | **Parcial** | No existe retroalimentación docente escrita en el repositorio; se muestra la autoauditoría rotulada como tal |
| 09 IAM | **Parcial** | IAM de AWS lo impone Academy; mínimo privilegio propio solo como diseño |
| 11 Escalabilidad | **Parcial** | 100–5 000 usuarios son proyección (no medidos) |
| 15 Backup y recuperación | **Parcial** | Respaldo manual; recuperación completa en AWS no acreditada |
| 17 Evidencias antes/después | **Parcial** | Faltan capturas de consola (marcadas, no inventadas) |
| Portada | **Falta** | Apellidos y código, `Equipo XX`, docente, fecha |

## Qué evidencias faltan (resumen)
Capturas de consola (AWS/OCI/Azure) y de los paneles de Grafana/Zabbix · retroalimentación docente · series de 1 min de CloudWatch · 100/500/1 000 usuarios · fallo de zona y disponibilidad de la API durante un fallo · recuperación completa en AWS · respaldo programado · entrega real de un correo de alerta · CloudTrail verificado · costos observados · datos de portada.

## Qué pruebas necesitan autorización
Todas están en [`procedimientos-pendientes-autorizacion.md`](procedimientos-pendientes-autorizacion.md): **P1** exportar CloudWatch, **P2** capturas de consola, **P3** seguridad en AWS, **P4** ventana de V2, **P5** segunda ventana de Azure, **P6** recuperación completa en AWS, **P7** respaldo programado (diseño), **P8** CloudTrail/IAM de solo lectura, **P9** costos observados.

## Urgencias con fecha
1. **≈ 30-oct 15:18Z** — la RDS (detenida el 23-oct ≈ 15:18Z según los registros locales) se reiniciaría sola tras 7 días: quedaban ≈ 43 h a las 19:5xZ del 28-oct; costo ≈ 0,86 USD/día. **La sesión de AWS está caducada**: ver P0 en los procedimientos.
2. **≈ 3-nov** — vencen las series de 1 min de CloudWatch del 19-oct (línea base V1); 6-nov las del 22-oct; 7-nov las del 23-oct.
3. **1-ene-2027** — vence el certificado importado en ACM para V2.

## Siguiente paso recomendado por criterio (para acercarse a «Excelente»)
| Criterio | Siguiente paso |
|---|---|
| 1. Evolución V1 → V2 | Añadir la retroalimentación docente literal (sección 04) y las capturas de consola antes/después (P2, P4) |
| 2. Amenazas | Repetir en AWS la ráfaga de logins y el límite de intentos (P3) y verificar CloudTrail (P8) |
| 3. Controles | Capturas de IAM/red/cifrado/monitoreo (P2); comprobar la entrega real de correo de una alerta (P5); decidir si implementar MFA |
| 4. Escalabilidad/HA | Medir disponibilidad de la API en un fallo y la pérdida de una zona (P4); programar el respaldo diario (P7); recuperación completa en AWS (P6) |
| 5. Evidencias/documentación | Capturas antes/después, costos observados (P9), exportar CloudWatch (P1) y completar la portada |

Sugerencia de orden: **AWS-1** (P1+P2+P8+P9a, solo lectura, antes del 30-oct), luego **Azure-2** (P5), luego **AWS-3** (P3+P4).

## Entregables finales (28-oct)
Guía de capturas pendientes: [guia-capturas-consola.md](guia-capturas-consola.md).

`Entregable2-NexoEventos.docx` y `Entregable2-NexoEventos.pdf` (generados desde `informe-entregable2.md`; regenerar con `scripts/docs/informe-a-html.py` y `html-a-docx.py`). Pendientes que requieren a la autora: datos de portada, retroalimentación docente literal, capturas de consola.

Cobertura completa de los 18 puntos de la rúbrica e inventario definitivo de faltantes: [matriz-cobertura-rubrica.md](matriz-cobertura-rubrica.md).
