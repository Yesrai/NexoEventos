# Plan de despliegue por fases (PROPUESTA: nada de esto se ha ejecutado) — 4-nov-2026

Sustituye al reparto del `plan-ejecucion-cloud.md` (3-nov) con lo ya hecho (alarmas V1, P1, P2) y lo aprendido. Una fase por autorización. **Crédito: último dato 40,40 USD (declarado); reconfirmar antes de cada fase.** Costes: tarifas públicas, estimaciones. Sesión de Academy: ≈ 3 h restantes a las 10:00 (Perú); la RDS se reactiva sola ≈ **16:51 (Perú) de hoy** (ver fase 0).

## Orden recomendado
| Prioridad | Fase | Qué | Coste | Riesgo | Duración |
|---|---|---|---|---|---|
| 1 | **A** | Lifecycle S3 + subred V1 (plan 0/2/0 verificado) | 0 | bajo | 5 min |
| 2 | **B** | Certificado ACM + AMI nueva con `/livez` | ≈ 0,03 + 0,5–1 USD/mes la AMI | bajo | 75–90 min |
| 3 | **C** | Desplegar V2 + RDS encendida (21 recursos; 26 con alarmas) | ≈ 0,13 USD/h | medio | 30 min |
| 4 | **D** | Aceptación en V2 + TLS `verify-full` real + B2/D2 | ≈ 0,13 USD/h | medio | 90 min |
| 5 | **E** | Desmontaje de V2 y parada de RDS | ahorra | bajo | 30 min |
| 6 | **F** | Azure N2 (correo, Grafana, `alerta-vm-up`) | ≈ 0,11 USD/h × 1 h | bajo | 60 min |
| — | **G** | OCI | 0 | — | nada que desplegar (decisión aceptada) |
Totales C+D+E con RDS: ≈ 1,2 USD (techo 3 USD). B y C–E no caben en las 3 h de esta sesión: **A hoy; B en una sesión; C–E en otra, con RDS encendida**.

## Fase 0 — Decisión sobre la RDS (antes de las 16:51 Perú)
Opciones: (i) dejar que se reactive y detenerla en la siguiente sesión (≈ 0,036 USD/h × horas encendida ≈ 0,9 USD/día si se olvida); (ii) arrancarla y detenerla a mano ahora para reiniciar el plazo de 7 días (≈ centavos, pero necesita su autorización y ≈ 10–15 min). Recomiendo (i) **si C–E se hacen en menos de 24 h** (el uso previsto cubre el coste); si no, (ii). Evidencia: eventos de RDS.

## Fase A1 — HECHA el 4-nov: lifecycle de S3 (ver `docs/evidencias/20261104-fase-a1-lifecycle-s3/`)

## Fase A2 — HECHA el 4-nov: subred de V1 (ver `docs/evidencias/20261104-fase-a2-subred/`)
**Impacto analizado:** `map_public_ip_on_launch` true → false solo afecta a instancias NUEVAS lanzadas en `public_a` sin pedir IP. V1: la EC2 existente la conserva y su definición pide `associate_public_ip_address = true` (`infra/aws/compute.tf`). V2: la plantilla de lanzamiento la pide (`network_interfaces.associate_public_ip_address = true`) y `public_b` ya nace en false. Constructor de AMI: `v2-prepare.sh` usa `--associate-public-ip-address`. **No hay NAT ni endpoints VPC**: las instancias salen a internet, a SSM, a Secrets Manager y a ACM por su IP pública, así que cualquier instancia lanzada a mano en `public_a` sin IP pública quedaría incomunicada (riesgo: lanzamientos manuales desde la consola). SSM de la EC2 actual no cambia. Plan: cambio in situ de 1 recurso, coste 0; rollback `-var public_subnet_auto_public_ip=true`. Se aplicaría con plan dirigido a `aws_subnet.public_a` y verificador propio; recomiendo hacerlo antes de la fase B.

## Fase A (original, referencia) — Lifecycle de S3 y subred de V1
- **Recursos:** modifica `aws_s3_bucket_lifecycle_configuration.private` (prefijo → `backups/database/`; 7 → 365 días; versiones no vigentes 7 → 365) y `aws_subnet.public_a` (`map_public_ip_on_launch` true → false). Crea 0. Destruye 0. No toca EC2, RDS, bucket, versionado, cifrado ni alarmas.
- **Decisión técnica (retención 365 y no 90):** los 4 respaldos pesan 225 KB; el coste de conservarlos es ≈ 0 y son la única copia no-RDS. Con 365 días el más antiguo caduca el 4-oct-2027. Con el bucket versionado, una expiración crea marca de borrado y la versión queda recuperable otros 365 días.
- **Prerrequisitos:** sesión válida; estado en la serie 46; plan `work/terraform-plans/s3-subred.tfplan` vigente.
- **Comandos:** `terraform -chdir=infra/aws show -json $PWD/work/terraform-plans/s3-subred.tfplan | python3 scripts/cloud/verificar-plan-s3-subred.py` (debe decir CORRECTO) y, solo entonces, `terraform -chdir=infra/aws apply $PWD/work/terraform-plans/s3-subred.tfplan` con `TF_DATA_DIR=$PWD/work/terraform/academy-multiaz` y `AWS_PROFILE=nexoeventos-lab`.
- **Riesgos:** datos: ninguno si el prefijo y los días son los verificados; servicio: la subred cambia in situ y solo afecta a instancias nuevas; presupuesto: 0. Plan con `-refresh=false`: la SCP bloquea refrescar el bucket (contrastado a mano con la lectura real).
- **Rollback:** reaplicar con `-var s3_backup_retention_days=7` (no recomendado) y `-var public_subnet_auto_public_ip=true`; los objetos siguen versionados.
- **Evidencia para dar la fase por completada:** `get-bucket-lifecycle-configuration` (prefijo y 365), `describe-subnets` (`MapPublicIpOnLaunch=false`), los 4 objetos con los mismos ETag y tamaño (`docs/evidencias/20261104-fase-a-prechequeo/`), EC2 `running` con su IP pública, serie de estado +1.

## Fase B1 — HECHA el 4-nov: certificado validado e importado en ACM (ver `docs/evidencias/20261104-fase-b1-acm/`; **hay 2 certificados idénticos, decidir cuál conservar**)

## Fase B2 — HECHA el 4-nov: AMI `ami-0b9d9f97ca9623d3a` con `/livez` (ver `docs/evidencias/20261104-fase-b2-ami/`)
**Referencia exacta para Terraform V2:** `-var ami_id=ami-0b9d9f97ca9623d3a` y `-var certificate_arn=<ARN de `…/b8f2c28e-…` (anterior; en `work/operacion/v2-certificate-arn`)>`. Mantener `ami_includes_livez = false` en el primer `apply` y validar `/livez` en cada instancia del ASG antes de pasarlo a `true`. Sigue pendiente: validar `/livez` en una instancia real del ASG y con la RDS encendida (Fase C/D).

## Fase B (original, referencia) — Certificado y AMI con `/livez`
- **Recursos:** certificado importado en ACM (gratis) con `deploy/v2/import-acm-certificate-on-v1.sh` (lee el certificado de V1 por SSM; no se imprime); instancia temporal t3.small (≈ 0,02 USD/h, SG sin entradas, 20 GiB cifrado), AMI + instantánea (≈ 0,5–1 USD/mes; hay una AMI anterior de 22-oct sin `/livez`, se sustituye). El secreto `nexoeventos/academy/backend-env` ya existe.
- **Prerrequisitos:** EC2 de V1 `running` (lo está), paquete de la aplicación actual.
- **Riesgos:** constructor olvidado (se verifica `builder-delete`); ningún dato ni servicio.
- **Rollback:** `builder-delete`, anular registro de la AMI y borrar su instantánea; borrar el certificado importado.
- **Evidencia:** ARN del certificado enmascarado, `nginx -T` con `location = /livez`, hash del paquete, AMI `available`.

## BLOQUEO previo a la Fase C — RESUELTO EN LOCAL el 4-nov con la opción A (ver `docs/evidencias/20261104-fase-c-prechequeo/`; plan V2 regenerado: 27/0/0, verificado; falta validar en AWS) (texto original del bloqueo)
**La AMI `ami-0b9d9f97ca9623d3a` contiene todo el código de aplicación necesario** (el artefacto es el del commit c8092b6 y es idéntico al árbol de trabajo en `backend/app`, `backend/alembic`, `deploy`, el lock de producción y `ansible`; los cambios locales posteriores son solo pruebas, scripts, documentación e infraestructura de V1/V2 que no viajan en la imagen). **Pero le falta algo imprescindible para arrancar la API contra RDS:** desde el commit 1331a74 (29-oct) la API exige, para toda base remota, `sslmode=verify-full` **y** un `sslrootcert` que apunte a un archivo existente (`enforce_tls_policy`, ejecutada en `build_engine` al arrancar). Hoy:
1. **La AMI no trae el paquete de CA de RDS** (`/etc/nexoeventos/rds-ca-bundle.pem`; ninguna tarea de Ansible lo instala y `bootstrap-instance.sh.tftpl` tampoco lo descarga).
2. **El secreto compartido (`nexoeventos/academy/backend-env`) se creó el 21-oct**, antes de esa exigencia; es muy probable (no leí su valor) que su `DATABASE_URL` no tenga `verify-full`. Aunque lo tuviera, el archivo de CA no existiría.
Efecto: con esta AMI y este secreto, la API de cada instancia V2 **no arranca** (`RuntimeError`), `/livez` da 502, el ASG las marca no sanas y las reemplaza en bucle. El plan de Terraform (27 a crear, 0/0) **no lo detecta**. En el constructor no se vio porque se probó con una base local, exenta de la regla.
**Opciones (no ejecutadas):** (A, recomendada) corregir solo el `user_data` de Terraform (`deploy/v2/bootstrap-instance.sh.tftpl`): descargar `global-bundle.pem` de AWS por HTTPS 443 (ya permitido) con comprobación de huella, instalarlo en `/etc/nexoeventos/rds-ca-bundle.pem` y fijar `sslmode=verify-full&sslrootcert=…` en el `DATABASE_URL` del archivo generado, **sin reconstruir la AMI ni editar el secreto**; (B) reconstruir la AMI con el bundle y actualizar el secreto (más pasos y una operación sobre Secrets Manager). Pendiente de decisión de la propietaria. Plan guardado `work/terraform-plans/v2-c.tfplan` (27/0/0): **no aplicar** hasta resolver esto.

## Fase C y D — HECHAS el 4-nov (ver `docs/evidencias/20261104-fase-c-d-v2/`); V2 y RDS siguen encendidas a la espera de la Fase E (requiere confirmación)

## Fase C — Desplegar V2 (texto original)
- **Recursos (plan verificado hoy con un certificado ficticio): 21 a crear, 0 a modificar, 0 a destruir** (26 con `enable_alarms`): ALB, listener HTTPS, grupo de destino, ASG, plantilla de lanzamiento, política de escalado, subred B, asociación de rutas, 2 grupos de seguridad, 9 reglas y un panel (las 5 alarmas son las que suman 26). Usa `ami_includes_livez = false` primero (salud acoplada) y `true` después de validar `/livez` por instancia.
- **Prerrequisitos:** fase B; RDS en `available` (arrancarla ≈ 10–15 min); `alarm_topic_arn` del tema existente si se activan alarmas.
- **Coste:** ≈ 0,13 USD/h (ALB + 2 t3.small + RDS Multi-AZ). **Riesgo:** presupuesto si se olvida; datos: ninguno (V2 reutiliza la misma RDS). **Rollback:** `terraform destroy` solo de `infra/aws-v2` con plan guardado revisado.
- **Evidencia:** `Plan: 21/0/0` guardado y verificado, 2 destinos `healthy`, captura del TG.

## Fase D — Aceptación en V2 (misma ventana de RDS)
1. `/livez` correcto en cada instancia; luego `ami_includes_livez = true` (cambio in situ del health check).
2. **TLS `verify-full` real contra RDS** (observación 14).
3. **B2** autohealing con `v2-failover-test.py --allow-replacement` y **D2** failover de RDS con `/livez` (los destinos deben seguir sanos).
4. Alarmas de V2 con entrega al tema SNS ya confirmado (sin forzar estados salvo que se decida).
- **Coste:** incluido en C. **Riesgos:** ALB sin sanos > 90 s ⇒ abortar (criterio del plan). **Evidencia:** `resultado.json` completo, actividades del ASG, métricas del ALB.

## Fase E — HECHA el 4-nov 16:34–16:47 (ver `docs/evidencias/20261104-fase-e-desmontaje/`): V2 destruida (27) y RDS detenida
(texto original) Desmontaje
`terraform destroy` de `infra/aws-v2` (plan guardado: solo V2), borrar la AMI antigua, **detener RDS** (reinicia el plazo de 7 días) y verificar por lectura. Conservar respaldos.

## Fase F — Azure N2
VM un máximo de 1 h (≈ 0,11 USD/h): disparar la alerta con carga controlada, comprobar la **recepción real del correo** (obs. 3), capturar Grafana (obs. 5) y observar `alerta-vm-up` (obs. 6); luego desasignar y verificar. Requiere que la propietaria inicie sesión en Azure.

## Fase G — OCI
Sin despliegues: la recuperación (E) está demostrada con 14/14 pruebas y huella; el monitoreo nativo se descarta por decisión documentada.

## No se prevé (sin autorización específica)
CloudTrail (permiso `CreateTrail` no verificado; ≈ centavos), AWS FIS, zona completa, carga alta.
