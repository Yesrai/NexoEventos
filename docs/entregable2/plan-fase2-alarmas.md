# Fase 2 — plan final para desplegar y probar las alarmas de V1 (PROPUESTA: **no aplicada**) — 3-nov-2026

Estado de partida (verificado): EC2 `nexoeventos-academy-app` **encendida a propósito**; RDS **detenida** (reinicio automático previsto el 4-nov 21:51 UTC); V2 destruida. El plan de este documento se generó **contra el estado real** (no una copia), con bloqueo de estado, sin `apply`; el estado no cambió (serie 36 antes y después).

## 1. Cambio de diseño: el correo ya NO está en Terraform
Un `aws_sns_topic_subscription` de correo guardaría la dirección **en texto claro en el estado y en cualquier plan guardado** (marcarla «sensible» solo la oculta en pantalla). Por eso se quitó la variable `alarm_email` y la suscripción de Terraform. **Diferencia con el plan anterior: 7 creaciones en vez de 8** (desaparece solo la suscripción).
La suscripción la crea [`scripts/cloud/suscribir-correo-alarmas.sh`](../../scripts/cloud/suscribir-correo-alarmas.sh), que **tú ejecutas en tu terminal**: pide la dirección con **entrada oculta** y te la hace repetir; la envía a la CLI de AWS por la entrada estándar (no aparece en `ps`, ni en el historial, ni en logs, ni en archivos); rechaza formatos erróneos y el marcador `.invalid`; no hace nada si el tema ya tiene suscripciones. **No se usa ningún correo marcador en el despliegue.** Probado en modo `--dry-run` (sin AWS) con pruebas automáticas.
Exposición residual del correo (no evitable): SNS la guarda (necesariamente) y es visible en tu consola; el «Historial de eventos» de CloudTrail puede registrar parámetros de la llamada `Subscribe` (no verificado si SNS enmascara el correo).

## 2. Protección de estado y plan
Backend **local** (no hay estado remoto). `work/` está en `.gitignore`; directorios `0700`, `terraform.tfstate`, su `.backup`, la copia previa y el plan guardado con permisos `0600`. El estado contiene datos de la cuenta (IDs, nombres), **no** el correo ni secretos de la aplicación. Copia previa al despliegue: `terraform.tfstate.pre-alarmas`. El plan guardado se borra tras aplicarlo (`rm work/terraform-plans/alarmas-v1.tfplan*`). Riesgo restante: copias de seguridad del Mac (Time Machine) de `work/`; se recomienda excluirlo o cifrar el soporte.

## 3. Correspondencia plan–estado
El plan se creó con el mismo perfil, el mismo archivo de estado real (`academy-current`, serie 36) y las mismas variables que usará el `apply`. Un plan guardado **registra el linaje y la serie del estado**: si el estado cambia después, Terraform **rechaza** aplicarlo («saved plan is stale»). El plan anterior contra una copia del estado **se descartó** y no se aplicará. Antes de aplicar se **vuelve a generar** y se pasa por `scripts/cloud/verificar-plan-alarmas.py` (condición de parada).

## 4. Por qué el plan es dirigido (`-target`) y qué riesgos quedan
**Motivo:** Academy tiene una política de control de servicio que **deniega `s3:GetBucketObjectLockConfiguration`**; el refresh del bucket del estado falla y un `plan` completo **no termina**. Un plan dirigido a las alarmas no toca el bucket, así que sí puede refrescar lo que usa (la EC2 y la RDS entran solo como dependencias de lectura).
**Riesgos:** (1) Terraform **no observa el bucket**: si alguien cambia en la consola su lifecycle, versionado o cifrado, ningún plan lo detecta (se mitiga con lecturas de la CLI, como en la Fase 0, que confirmó el lifecycle esperado); (2) `-target` omite el resto del grafo: la deriva de otros recursos no se revisa en este plan (el plan completo sin refresh solo propone, ajenos a las alarmas, el lifecycle de S3 y la subred); (3) todo plan o `apply` futuro que incluya el bucket seguirá necesitando `-target` o `-refresh=false`; (4) la EC2 muestra una deriva informativa (su IP pública cambió al reiniciarse el laboratorio): el `apply` solo la registra en el estado, sin tocar AWS.

## 5. Plan final verificado
`Plan: 7 to add, 1 to change, 0 to destroy` (verificado con `terraform show -json` y el verificador: **CORRECTO**).
| Acción | Recurso |
|---|---|
| crear | `aws_sns_topic.alarms[0]` (tema propio `nexoeventos-academy-alarmas`) |
| crear | `aws_sns_topic_policy.alarms[0]` (solo RDS y CloudWatch pueden publicar, limitado a la cuenta) |
| crear | `aws_db_event_subscription.rds[0]` (failover, fallos, espacio bajo, notificación, disponibilidad) |
| crear | `aws_cloudwatch_metric_alarm.ec2_status_check_failed[0]` |
| crear | `…rds_cpu_high[0]` · `…rds_free_storage_low[0]` (< 2 GiB; medido ≈ 17,1 GiB libres) · `…rds_freeable_memory_low[0]` (< 100 MiB; mínimo histórico 166 MiB) |
| actualizar | `aws_cloudwatch_metric_alarm.ec2_cpu_high`: **solo** `alarm_actions` y `ok_actions` |
**No se modifican (comprobado en el JSON del plan: ninguna acción sobre ellos):** subred (se pasa `public_subnet_auto_public_ip=true` para mantener el valor desplegado), lifecycle y respaldos de S3, RDS, EC2, red ni seguridad. El plan no contiene ninguna dirección de correo.

## 6. Costes incrementales (estimación con tarifas públicas, no verificada)
4 alarmas nuevas ≤ **0,40 USD/mes** (la de CPU ya existe; entran en la capa gratuita de 10 si la cuenta la tiene); SNS, suscripción de correo y eventos de RDS gratuitos; prueba de CPU ≈ **0,03 USD**; la EC2 encendida (ya decidido) ≈ 0,7 USD/día. El crédito de Academy no está confirmado.

## 7. Secuencia exacta (cada paso tras tu autorización)
1. **Regenerar y verificar el plan** (yo): `terraform plan … -out=work/terraform-plans/alarmas-v1.tfplan`, luego `terraform show -json … | python3 scripts/cloud/verificar-plan-alarmas.py`. Si no dice **CORRECTO**, no se aplica.
2. **Despliegue** (necesita tu «sí»): `terraform -chdir=infra/aws apply work/terraform-plans/alarmas-v1.tfplan`. Después, lectura de comprobación (alarmas creadas, tema y suscripción a eventos).
3. **Suscripción SNS** (tú, en tu terminal): `scripts/cloud/suscribir-correo-alarmas.sh`; escribes el correo dos veces (no se muestra).
4. **Confirmación** (tú): abres el correo de AWS y confirmas; yo compruebo en solo lectura que no queda ninguna suscripción pendiente (solo cuentas, sin mostrar la dirección).
5. **P1 prueba de notificación** (autorización aparte): `set-alarm-state ALARM` sobre `ec2_status_check_failed`; debe llegar el correo y la alarma volver a `OK`; se registra como **estado forzado**.
6. **P2 prueba de CPU** (autorización aparte): carga de CPU por SSM de ≈ 15 min; `ec2_cpu_high` → `ALARM` → correo → vuelve a `OK` → correo. Evidencia: historial de la alarma y gráfico.
7. **P4 opcional** (Fase 1): ciclo start/stop de la RDS para un evento real por correo.

## 8. Rollback
Mismo `plan` con `-var enable_alarms=false` (mismos `-target`): propone **7 destrucciones y 1 cambio** (la alarma de CPU vuelve a no tener acciones); se revisa y se aplica. Eliminar el tema borra su suscripción. Si fallara a medias: restaurar `terraform.tfstate.pre-alarmas` y comprobar con lectura de la CLI. Si Academy deniega algún permiso (SNS, eventos de RDS), se detiene y se informa.

## 9. Autorizaciones que necesito (independientes)
**A.** «Sí» al plan regenerado y verificado (apply dirigido de 7 + 1). **B.** Que ejecutes tú el script de suscripción y confirmes el correo. **C.** P1 (`set-alarm-state` forzado). **D.** P2 (carga de CPU por SSM, ≈ 15 min). **E.** (Opcional) Fase 1 con la RDS para P4. Aparte y más adelante: lifecycle de S3, subred y V2.
