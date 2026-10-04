# Siguiente sesión cloud: alcance, costo y riesgos

**Procedimiento aprobado para la próxima reanudación, no ejecutado por el bloqueo de credenciales.** Revisado el 4 de octubre de 2026 (Lima) sobre `7e879ad`. Academy autoarrancó la EC2 al iniciar el lab; se detuvo desde la consola y quedó `Detenida`. RDS quedó en `Detención temporal`. La carga/restauración no comenzó porque STS rechazó un bloque recién emitido con `InvalidClientTokenId`. Los procedimientos están en [procedimientos-sesion-cloud.md](procedimientos-sesion-cloud.md).

## Fecha sugerida

**Antes del reinicio automático de RDS.** AWS puede reiniciar una RDS tras un máximo de siete días detenida. Si la parada se completó el 3 de octubre, el límite aproximado cae alrededor del **10 de octubre**, pero debe comprobarse con el estado/evento real. Consultar el estado o repetir `stop-db-instance` cuando ya está detenida **no reinicia** ese periodo. Solo un arranque real seguido de una nueva parada completada inicia otro periodo continuo de detención. El trabajo local no necesita esperar a una fecha concreta.

## Alcance (máximo 3.5 h activas)

| # | Actividad | Resultado que se busca | Evidencia |
|---|---|---|---|
| 0 | Revisar el panel Academy y `cloud-session.sh status` (solo lectura) | consumo inicial y fecha límite de RDS | registro de la sesión |
| 1 | `cloud-session.sh start` + `check` | DNS = IP de la EC2, 301→HTTPS, `/healthz` 200, certificado válido | salida de `check` |
| 2 | `capture-inventory.sh` + capturas de consola sanitizadas | red, rutas, SG, RDS privado, S3 y CloudWatch | EV02, EV03, EV04, EV06, EV07, EV08 |
| 3 | Captura pública con fecha/hora; autoría individual y equipo pendiente | flujo cliente → DNS → Nginx → página del proyecto | EV10; no inventar `Equipo XX` |
| 4 | Prueba de carga de 20 usuarios × 5 min | p95, errores y solicitudes/s medidos frente a E01 | EV11 + gráfico CloudWatch |
| 5 | `restore-drill.sh run --pitr` + `cleanup` | línea base, punto recuperable y tiempo de recuperación/verificación de datos | EV07; recuperación completa del servicio queda separada |
| 6 | `check` final, respaldo actualizado si hubo escrituras y `stop` | EC2 y RDS en `stopped` | registro y consumo final |

**Fuera de alcance:** `terraform apply`/`destroy`, las correcciones de [terraform-advertencias.md](terraform-advertencias.md) (sesión dedicada), cambios de IAM, Multi-AZ, ALB, Azure/GCP y migración entre cuentas.

## Costo estimado de la sesión

Tarifas públicas `us-east-1` de [costos-v1.md](../costos-v1.md), sin impuestos ni créditos. Es una **estimación**, no un consumo observado.

| Partida | Supuesto | Importe |
|---|---|---:|
| EC2 `t3.small` | 3.5 h × USD 0.0208 | USD 0.073 |
| RDS `db.t3.micro` | 3.5 h × USD 0.018 | USD 0.063 |
| IPv4 pública | 3.5 h × USD 0.005 | USD 0.018 |
| RDS temporal de restauración | 1.5 h × USD 0.018 | USD 0.027 |
| almacenamiento gp2 temporal | 20 GiB × USD 0.115/GiB-mes × 1.5 h | USD 0.005 |
| ingestión de logs adicional por la carga | 0.05 GiB × USD 0.50 | USD 0.025 |
| transferencia saliente de la carga | ≈ 0.05 GB × USD 0.09 | USD 0.005 |
| **subtotal** | | **USD 0.215** |
| margen por desvíos (sesión más larga, reintentos) | | USD 0.535 |
| **techo de la sesión** | | **USD 0.75** |

Aparte, **los componentes persistentes siguen cobrando** aunque todo esté detenido: EBS, almacenamiento RDS, secreto, alarma, S3/logs y el snapshot manual. En el escenario conservador de `costos-v1.md` suman ≈ **USD 0.21 por día**. Si la sesión se demora, ese costo continúa.

Reglas de crédito que se mantienen: al observar USD 30, reconciliar el inventario; al observar USD 40, congelar las pruebas. No son límites automáticos.

## Riesgos y mitigaciones

| Riesgo | Probabilidad | Impacto | Mitigación |
|---|---|---|---|
| La sesión del Learner Lab expira a mitad de una tarea (credenciales temporales) | media | restauración o parada a medias | iniciar con la sesión recién renovada, dejar la restauración antes del final y repetir `status`/`stop` al renovar |
| STS rechaza un bloque recién emitido (`InvalidClientTokenId`) | observado el 4-oct | impide inventario y cualquier operación segura | detenerse, conservar todo apagado, presentar el reporte sanitizado y pedir revisión a docente/soporte; no regenerar en bucle |
| DuckDNS tarda en actualizar la IPv4 nueva | media | HTTPS falla temporalmente | `check` espera hasta 6 min; si no basta, revisar el timer por Session Manager |
| `ssm:SendCommand` denegado al usuario del laboratorio | desconocida | no se verifica la copia restaurada desde el Mac | ejecutar `verify-restore.sh` manualmente en una sesión de Session Manager y registrar las marcas de tiempo a mano |
| `restore-db-instance-to-point-in-time` o SSM se rechaza | desconocida | no hay medición completa | registrar el error; no sustituirlo por una afirmación; una restauración desde snapshot puede demostrar integridad pero solo cumple RPO si coincide con la línea base |
| La instancia temporal queda viva | baja | ≈ USD 0.51/día (cómputo + almacenamiento) | `cleanup` exige recibo local, ARN y etiquetas de la misma ejecución; inventario final confirma ausencia |
| La carga degrada la demo pública | baja | latencia alta durante 5 min | 20 usuarios con tiempo de espera de 1–3 s, límite duro de 40 y ejecución fuera de horario de revisión |
| La carga consume cupos de la demo | baja | eventos agotados | por defecto no se reserva; las reservas solo se activan con `--event-id` de un evento ficticio dedicado |
| Una captura filtra un identificador | media | exposición de la cuenta | checklist del § 2.2, rectángulos opacos y revisión a 200 % antes de cualquier commit |
| AMI `most_recent` provoca reemplazo de la EC2 | nula en esta sesión | — | no se ejecuta Terraform; la corrección queda para la sesión dedicada |
| RDS se reinicia sola antes de la sesión | media al acercarse al límite de 7 días | cómputo RDS no previsto | comprobar estado/eventos; no asumir que consultar o repetir la parada reinicia el límite |

## Bloqueos previos a resolver localmente

1. **Identificador `Equipo XX`:** pendiente de confirmación docente; no se inventa y no bloquea carga, inventario ni recuperación. La autora registrada es Yesenia y el proyecto es individual.
2. **Config operativa:** recrear o señalar el tfvars protegido de Academy; hoy falta la ruta predeterminada y los scripts fallan de forma cerrada.
3. Decidir si la sesión incluye también el dump lógico desde S3; requiere la clave privada de recuperación y la credencial maestra solo en memoria.
4. Aprobación explícita de Yesenia para `start`/`stop`, carga pública, pausa breve de escrituras, creación/eliminación de la RDS temporal y SSM.
