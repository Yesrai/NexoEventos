# Guía reproducible: desplegar, validar y apagar AWS V2 en una sesión de AWS Academy

Preparada el 22-nov-2026 a partir de la prueba real B1+B2 del 20-nov-2026 ([evidencias](../evidencias/20261120-b1-b2-v2/resultado.md)). **Es una guía; nada de lo que describe se ejecuta solo.** Cada paso que cambia AWS exige la autorización expresa de la propietaria en esa sesión. No contiene credenciales, ARN, IDs de cuenta ni valores de secretos.

Documentos relacionados: [respaldo local cifrado](respaldo-local-cifrado.md) · [índice de evidencias](../evidencias/INDICE-PRUEBAS-AWS.md) · [reconciliación de Terraform](aws-v2-reconciliacion-terraform.md) · [verificación de la restauración de datos y aplicación](aws-v2-verificacion-restauracion.md) · [operación de V2](../../scripts/v2-ops/README.md) · [respaldo y recuperación](respaldo-y-recuperacion.md).

## 1. Qué se probó y qué no (B1+B2, 20-nov-2026)
Probado: encendido controlado de la RDS con watchdog; plan regenerado y revisado antes de aplicar; `apply` del plan guardado; 2 destinos sanos en `us-east-1a` y `us-east-1b`; HTTPS por el ALB con `/livez` y `/api/events` = 200; limpieza ASG → ALB → RDS verificada. **No probado:** autohealing, failover de RDS con V2, carga, entrega de correos de las alarmas, restauración de datos, DNS de producción apuntando a V2.

## 2. Requisitos locales
`aws` (v2), `terraform` ≥ 1.16, `jq`, `dig`, `curl`, `python3`, `caffeinate` (macOS) y `shasum`. **Mac enchufado (AC Power), despierto y con red** durante toda la ventana: el watchdog corre en el Mac; si se apaga, nadie detiene la RDS ni el ALB. Terraform ya inicializado en `infra/aws-v2/.terraform`.

## 3. Variables y archivos locales (ninguno se sube a Git)
Archivos en `work/terraform-envs/` (ignorado por Git). Se enumeran **solo los nombres**; los valores no se documentan.
| Archivo | Variables | Notas |
|---|---|---|
| `academy-v2-common.tfvars` | `expected_account_id`, `ami_id`, `certificate_arn`, `ami_includes_livez`, `enable_alarms`, `alarm_topic_arn` | No debe definir `asg_enabled`. `ami_includes_livez = true` solo con una AMI que ya trae `/livez` (la del 4-nov la trae). Con `enable_alarms = true` las alarmas del ALB se crean con V2 |
| `academy-v2-on.tfvars` | `asg_enabled = true` | V2 encendida (mín = deseada = 2; máx = 3) |
| `academy-v2-off.tfvars` | `asg_enabled = false` | V2 apagada (mín = deseada = 0) |
Resto de variables de `infra/aws-v2/variables.tf`, con sus valores por defecto: `aws_region`, `project_slug`, `environment`, `public_b_cidr`, `instance_type` (t3.small), `root_volume_gib`, `instance_profile_name`, `cpu_credits_mode`, `app_secret_name`, `asg_min/asg_max/asg_desired`, `scale_cpu_target_pct`, `scale_requests_per_target`, `rds_ca_sha256`, `db_pool_size`, `db_max_overflow`, `alb_deletion_protection`.
Dependencias que deben existir en AWS antes de un despliegue (comprobadas en solo lectura el 22-nov): AMI dorada con `/livez` (la del 4-nov), plantilla de lanzamiento, grupo de destino, grupo de seguridad del ALB y de las EC2, subred pública B, secreto compartido de la aplicación (`app_secret_name`), certificado importado en ACM (**caduca el 1-ene-2027**; `aws acm list-certificates` oculta por defecto los certificados EC: usar `--includes keyTypes=EC_prime256v1,RSA_2048`), RDS `nexoeventos-academy-postgres`.

## 4. Renovar las credenciales de AWS Academy (sin guardar credenciales en el repositorio)
1. En AWS Academy abre el curso → **Start Lab** y espera el indicador verde. **Al iniciar el laboratorio la EC2 de V1 suele arrancar sola** (pasó el 23-oct, 29-oct, 3-nov, 20-nov y 22-nov): `chain` exige 0 EC2 en ejecución, así que hay que detenerla **con autorización expresa** antes de empezar. Su `LaunchTime` marca el inicio del laboratorio.
2. **AWS Details → Show** y copia el bloque con las tres claves de la CLI (acceso, secreto y token de sesión).
3. En tu terminal: `bash work/enter-aws-academy-credentials.sh`. Pide los valores sin mostrarlos y escribe el perfil `nexoeventos-lab` con permisos 0600 (no se muestran ni se registran; no hagas commit de esa ruta).
4. Comprueba sin imprimir la cuenta: `aws sts get-caller-identity --profile nexoeventos-lab --query Account --output text > /dev/null && echo vigente`.
5. **Caducidad:** inicio del laboratorio + ≈ 4 h (leer también el temporizador de la página de Academy). Fórmula para `--creds-until`: `caducidad − 10 min`; hace falta que `creds-until − ahora ≥ 120 min` (75 de ventana + 45 de seguridad).
6. Si cambia de día UTC usa la fecha completa (`2026-11-23T01:25Z`); `rds-window.sh` la acepta y rechaza fechas inexistentes o vencidas.

## 5. Preflight (solo lectura)
`AWS_PROFILE=nexoeventos-lab scripts/v2-ops/rds-window.sh check` debe dar 5 «OK»: cuenta y región correctas, RDS `stopped`, ASG de V2 0/0/0, **ninguna** EC2 en ejecución y **ningún** ALB, y «Watchdog: no armado». Además: Mac en AC Power (`pmset -g batt`), saldo y tiempo restante visibles en el panel de Academy (los confirma la propietaria; **no se infieren**), y revisión del escenario de Terraform (§6).

## 6. Elegir el escenario de `chain`
| Situación | `--scenario` | Qué revisa el plan |
|---|---|---|
| Nunca se desplegó V2 (o se destruyó con Terraform) | `first` (por defecto) | 8 creaciones + ASG 0→2 |
| **Reanudación tras una limpieza de emergencia verificada** (el caso de hoy: ALB y listeners borrados por la API; panel y alarmas siguen) | `resume` | 3 creaciones (ALB y 2 listeners) + ASG 0→2 + 5 actualizaciones de monitoreo limitadas a los atributos que dependen del ALB. Exige que la última limpieza conste como `PARADA_VERIFICADA` |
La revisión (`scripts/v2-ops/review-plan.py`) es **por recurso y por atributo**; bloquea cualquier destrucción o sustitución y cualquier cambio en RDS, IAM, secretos, DNS, redes, certificados, claves, S3, grupo de destino o plantilla de lanzamiento. Detalle y estrategia en [aws-v2-reconciliacion-terraform.md](aws-v2-reconciliacion-terraform.md).

## 7. Despliegue (B1+B2) — requiere autorización expresa
```bash
NEXO_ALLOW_CLOUD_CHANGES=YES scripts/v2-ops/rds-window.sh chain --scenario resume --minutes 75 \
  --confirm "ENCENDER RDS Y APLICAR V2" --not-after <HH:MMZ|AAAA-MM-DDTHH:MMZ> --creds-until <AAAA-MM-DDTHH:MMZ>
```
Qué hace, en orden: preflight → arma el watchdog y verifica que está vivo → `start-db-instance` (solo esa RDS) → espera `available` → **regenera** el plan y lo **revisa** (si difiere, aborta y apaga) → `apply` solo del plan guardado → espera 2 destinos sanos en las dos zonas → HTTPS y `/livez` por el ALB con `--resolve` (sin tocar DNS) → se detiene (B3 y pruebas de fallo requieren otra autorización). Tiempos medidos el 20-nov: RDS `available` ≈ 5 min, `apply` ≈ 2 min 16 s, destinos sanos ≈ 20 s después. Gasto del 20-nov: ≈ 0,10 USD (estimado con tarifas públicas, no verificado con la facturación).

## 8. Validación (checklist; guardar las evidencias saneadas en `docs/evidencias/<fecha>-<prueba>/`)
- [ ] RDS `available` y Multi-AZ; ASG mín/deseada/máx = 2/2/3 con 2 instancias `InService/Healthy` en **us-east-1a y us-east-1b**.
- [ ] ALB `active`, público, 2 zonas; grupo de destino con 2 `healthy` en el puerto 80 y health check `/livez`.
- [ ] HTTPS por el ALB: `/livez` = 200 y `/api/events` = 200 (con `curl --resolve`; **sin** cambiar DNS), con hora UTC.
- [ ] Alarmas de V2: estados esperados (`OK` o `INSUFFICIENT_DATA` sin tráfico); acciones definidas.
- [ ] Registro de la ventana saneado (`work/operacion/rds-window.log`: sin IDs, ARN ni IP) y lista de acciones del plan aplicado.

## 9. Apagado
- **Normal:** el watchdog detiene todo al vencer la ventana (ASG a 0 → ALB eliminado → RDS detenida y verificada).
- **Anticipado (autorizado):** `NEXO_ALLOW_CLOUD_CHANGES=YES scripts/v2-ops/rds-window.sh stop-now --also-v2`. Después: `rds-window.sh cancel`, retirar `work/operacion/rds-window.keepalive` y comprobar que no quedan procesos (`ps`).
- **Verificar siempre (solo lectura):** RDS `stopped` (no `stopping`), ASG 0/0/3 sin instancias, 0 ALB, EC2 de V2 `terminated`, EC2 de V1 `stopped`, 0 NAT y 0 IP elásticas. El apagado de la RDS Multi-AZ tarda 5–15 min.
- **Qué sigue facturando tras apagar (céntimos):** alarmas y panel de CloudWatch, AMI e instantáneas, almacenamiento de la RDS detenida, S3, secretos. **La RDS vuelve a arrancar sola a los 7 días** de estar detenida: anotar la fecha y volver a detenerla.
- La limpieza de emergencia elimina el ALB **por la API**: el estado de Terraform queda desfasado (ver reconciliación).

## 10. Qué NO restaura Terraform (se restaura por separado)
Terraform crea ALB, ASG, alarmas y reglas; **no recupera PostgreSQL ni los secretos ni las claves**. Resumen (detalle y verificación en [aws-v2-verificacion-restauracion.md](aws-v2-verificacion-restauracion.md)):
| Elemento | Dónde está hoy | Si se pierde |
|---|---|---|
| **Datos de PostgreSQL** | RDS `nexoeventos-academy-postgres` (detenida, Multi-AZ, cifrada); 17 instantáneas (6 manuales, la más reciente del 20-nov); respaldos cifrados `.cms` en S3 (`backups/database/`, 5 objetos) y copia externa en OCI | Restaurar desde instantánea o PITR (R01: ≈ 21 min) o desde un `.cms` descifrado con la **clave privada de recuperación** (solo en poder de la propietaria) |
| **Secreto compartido de la aplicación** (`app_secret_name`) | Secrets Manager; lo crea `deploy/v2/create-shared-secret-on-v1.sh` copiando el `backend.env` de V1 | Volver a crearlo desde el `backend.env` de V1 o del paquete de recuperación. **Sin la `TICKET_ENCRYPTION_KEY` original no se descifran los QR** |
| Credenciales de la aplicación en PostgreSQL y secreto maestro de la RDS | RDS (el secreto maestro lo rota AWS) | Roles `nexoeventos_owner`, `_migrator` y `_app` según `deploy/bootstrap-rds-secrets.sh` |
| Certificado HTTPS (ACM, importado) | ACM; **caduca el 1-ene-2027** | `v2-prepare.sh import-cert` (necesita la EC2 de V1) o emitir otro; actualizar `certificate_arn` |
| AMI dorada con `/livez` | AMI del 4-nov | `v2-prepare.sh builder-launch` → `scripts/ansible-aws.sh bake` → `builder-image` (≈ 45 min) |
| DNS (`nexoeventos-demo.duckdns.org`) | Apunta a V1; no se cambió | Cambio de DNS = autorización aparte |
| Terraform (estado y tfvars) | **Solo en este Mac** (`work/`); copia local cifrada creada y verificada el 22-nov ([guía](respaldo-local-cifrado.md)) | Copia **externa** pendiente (decisión de la propietaria); en otra cuenta o laboratorio no se reutiliza el estado |
| Clave privada de recuperación | Solo en poder de la propietaria | Sin ella los `.cms` no se descifran |

## 11. Autorizaciones que se necesitarán en la próxima sesión (cada una independiente)
1. Detener la EC2 de V1 si Academy la arranca (única forma de pasar el preflight).
2. **Fase de reconciliación:** `terraform apply -refresh-only` (solo estado) — ver la guía de reconciliación — y, si se prefiere, la alternativa del `destroy` dirigido.
3. `chain` (B1+B2): encender la RDS, aplicar el plan revisado y crear el ALB y las EC2, con presupuesto, horas límite y comando exactos.
4. Cualquier experimento (B3, autohealing, failover de RDS, carga) y cualquier restauración real.
5. Cambios de DNS, IAM, secretos o datos; failover AWS → OCI (`automatic=false` se mantiene).
