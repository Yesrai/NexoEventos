# Notificación CloudWatch → SNS → correo de una alarma de V2, provocada con `set-alarm-state` (4-nov-2026, saneado)

**Estado: COMPLETADA y confirmada por la usuaria.** Etiqueta correcta: **«notificación CloudWatch → SNS → correo recibida y confirmada por la usuaria, provocada manualmente con `set-alarm-state`»**. NO es una detección automática por métricas: la alarma no se activó por datos reales (V2 estaba sana) y sus umbrales no se tocaron.

Alarma probada: `nexoeventos-academy-v2-alb-destinos-no-sanos` (`UnHealthyHostCount` ≥ 1, 3 periodos). Antes: estado `OK`, acciones habilitadas, 1 acción de alarma y 1 de OK hacia el tema `nexoeventos-academy-alarmas` (1 suscripción confirmada, 0 pendientes; la misma de P1/P2). Las otras 4 alarmas de V2 no se tocaron (siguieron en `OK`).

## A. Evidencia técnica verificada en CloudWatch (hora de Perú)
| Hora | Evento |
|---|---|
| 12:01:47 | `set-alarm-state` (una vez, exit 0, motivo «prueba manual… no es una detección automática»): `OK` → `ALARM` |
| 12:01:47 | Acción: «Successfully executed action» hacia el tema SNS |
| 12:03:41 | CloudWatch devolvió la alarma de `ALARM` a `OK` por evaluación (≈ 1 min 54 s; **sin restablecimiento manual**) |
| 12:03:41 | Acción: «Successfully executed action» hacia el tema SNS (acción de OK) |

Estado final: `OK`, acciones habilitadas (1/1), umbral y periodos intactos. V2 operativa: destinos `healthy` ×2, ASG 2 `InService`, ALB `/livez`, `/healthz` y `/api/events` → 200; RDS `available`; EC2 de V1 `running`.

## B. Recepción de correo (confirmación de la usuaria)
La usuaria confirmó haber recibido en Gmail **los dos correos** de AWS Notifications de esta alarma: **ALARM el 04/11/2026 a las 12:01** y **OK a las 12:03** (hora de Perú), coincidentes con el historial (12:01:47 y 12:03:41). El historial de CloudWatch se conserva en `historial-cloudwatch.txt`.
**Captura:** el 4-nov-2026 NO existe todavía en `docs/evidencias/20261104-fase-d-notificacion-v2/correos-alarm-ok.png`; no se afirma evidencia visual hasta que la usuaria guarde el recorte (solo las dos filas ALARM 12:01 y OK 12:03, sin datos personales). La confirmación textual de la usuaria es la prueba de recepción por ahora.

## Límites
Prueba de notificación, no de detección. Las 5 alarmas de V2 siguen sin haberse activado por métricas reales (el fallo de B2/D2 duró ≈ 20 s, menos que sus periodos de evaluación). Las alarmas se destruirán con V2 en la Fase E.
