# P1 — Notificación validada mediante estado forzado manualmente (4-nov-2026, saneado)

**Estado: P1 COMPLETADA.** Etiqueta correcta: **«notificación validada mediante estado forzado manualmente»**. NO es detección de CPU alta real: la CPU real era ≈ 0,8 %, bajo el umbral de 80 %, y la alarma de V1 no se ha disparado por carga.

Precondiciones: sesión válida; alarma `nexoeventos-academy-ec2-cpu-high` en `OK`, acciones habilitadas (1 de alarma y 1 de OK hacia el tema SNS); suscripción email confirmada (1 confirmada, 0 pendientes).

## A. Evidencia técnica verificada en CloudWatch (por el agente, lectura del historial)
| Hora (Perú, UTC−5) | Evento |
|---|---|
| 00:46:15 | `set-alarm-state` (ejecutado una vez, exit 0, motivo «transición forzada manualmente; no es carga real de CPU»): `OK` a `ALARM` |
| 00:46:15 | Acción: «Successfully executed action» hacia el tema SNS |
| 00:47:43 | CloudWatch devolvió la alarma de `ALARM` a `OK` por evaluación: **recuperación automática en ≈ 88 s**, sin recuperación manual |
| 00:47:43 | Acción: «Successfully executed action» hacia el tema SNS (acción de OK) |

Estado final: alarma `OK`, acciones habilitadas (1/1); EC2 `running`; RDS `stopped`. No se publicó directamente en SNS, no hubo carga de CPU ni Terraform.

## B. Recepción de correos confirmada por la usuaria (declaración en el chat, 4-nov-2026)
La propietaria confirmó explícitamente haber recibido **los dos correos de AWS Notifications**: el de **ALARM** (RECIBIDO) y el de **OK** (RECIBIDO). Esta confirmación es una declaración de la usuaria; **no hay capturas ni copias de los correos guardadas** en el repositorio. No se declara evidencia visual.

## Conclusión y límites
- Cadena CloudWatch → SNS → correo **validada de extremo a extremo con estado forzado**: A (CloudWatch ejecutó la acción SNS sin errores, 2 veces) + B (los dos correos llegaron).
- **No demuestra** la detección de una sobrecarga real de CPU (P2, no ejecutada) ni la entrega de las demás alarmas (RDS, comprobaciones de estado), que usan el mismo tema pero no se forzaron.
- Pendiente opcional: guardar capturas de los correos, saneadas (sin dirección, ID de cuenta ni enlace de baja), si se quiere evidencia visual.
