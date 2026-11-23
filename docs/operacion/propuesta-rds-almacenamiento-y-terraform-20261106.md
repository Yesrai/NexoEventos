# Propuesta: almacenamiento de la RDS y seguridad operativa de Terraform (6-nov-2026; SOLO diagnóstico y propuesta)

## 1. Almacenamiento de la RDS `nexoeventos-academy-postgres` (lecturas del 6-nov 14:2x, hora de Perú)
- Asignado 20 GiB (gp2, Multi-AZ, cifrado); **máximo de autoescalado (MaxAllocatedStorage) = 20 GiB**; sin modificaciones pendientes.
- Libre: **17,05 GiB (85 %)**; estable desde el 28-oct (17,12 → 17,05 GiB). Se usan unos 3 GiB. Alarma `nexoeventos-academy-rds-espacio-libre-bajo` (< 2 GiB durante 2×5 min, con acción SNS) en `OK`.
- Aviso de AWS cada 2 horas: «Storage size 20 GiB is approaching the maximum storage threshold 20 GiB». Causa: el máximo configurado es igual al almacenamiento asignado, así que el autoescalado no tiene margen y RDS lo avisa aunque haya espacio libre. Es un aviso de **configuración**, no de falta de espacio.
- Riesgo real de quedarse sin espacio: **bajo** (uso estable 15 %). Urgencia: **baja**.
- Respaldos: retención 7 días; ventana de restauración 30-oct 19:19 UTC → 6-nov 19:19 UTC (hasta hoy); último automático 6-nov 07:45 (hora local); 16 instantáneas, 2 manuales (19-oct y 23-oct).

### Solución propuesta
Subir `MaxAllocatedStorage` de 20 a **40 GiB**. El almacenamiento asignado no cambia (sigue en 20 GiB) y solo crece si el espacio libre baja del 10 %.
- Efecto: cambio de metadatos en línea, sin reinicio, sin failover, sin tiempo de inactividad; V1 y V2 no se afectan.
- Costo: 0 USD hoy. Peor caso (si llegara a crecer a 40 GiB): ≈ +4,6 USD/mes (gp2 0,115 USD/GiB-mes × 20 GiB × 2 por Multi-AZ). Atención: el almacenamiento, una vez ampliado, no se puede reducir.
- Alternativa descartada: poner el máximo en 0 (apaga el aviso pero elimina la red de seguridad); no hacer nada (el aviso seguirá cada 2 h).
- Cómo aplicarlo: `aws rds modify-db-instance --db-instance-identifier nexoeventos-academy-postgres --max-allocated-storage 40 --apply-immediately` (CLI, verificable con `describe-db-instances`) y **alinear después** `db_max_allocated_storage_gib = 40` en `work/terraform-envs/academy-multiaz.tfvars` para que el próximo `plan` de V1 no lo revierta a 20. Antes de cualquier `apply` de V1 hay que inicializar su raíz (hoy no está inicializada en este equipo) y revisar un plan de solo lectura. **Aviso:** `academy.tfvars` declara `db_max_allocated_storage_gib = 0` y no declara `db_multi_az`; usar ese archivo por error propondría quitar Multi-AZ y el autoescalado. Debe retirarse o renombrarse.
- Antes de aplicar: confirmar respaldo reciente (ya cumple: restaurable hasta hoy).

## 2. Seguridad operativa de Terraform (`infra/aws-v2`)
Riesgos detectados:
1. `asg_enabled` tiene por defecto `true`: un plan/apply con solo `academy-v2-c.tfvars` (sin el archivo de estado) **encendería V2**.
2. `expected_account_id`, `ami_id` y `certificate_arn` no tienen valor por defecto; sin `-var-file` Terraform los pediría de forma interactiva (no es un fallo silencioso, pero un humano apresurado podría escribir valores incorrectos).
3. Hay varios `.tfvars` locales con nombres parecidos (p. ej. `academy.tfvars` frente a `academy-multiaz.tfvars`).

Propuesta (no implementada):
- Quitar el valor por defecto de `asg_enabled` (variable obligatoria): olvidar el estado produce un error, no un cambio.
- Separar los archivos locales (ignorados por Git): `academy-v2-common.tfvars` (cuenta, AMI, certificado, alarmas), `academy-v2-on.tfvars` (`asg_enabled = true`) y `academy-v2-off.tfvars` (`asg_enabled = false`); retirar `academy-v2-estado.tfvars`.
- Un envoltorio `scripts/v2-ops/v2-terraform.sh {on|off}`: exige el argumento; comprueba cuenta y región; ejecuta `plan -lock=true -out`; muestra el resumen (acciones por recurso); **se detiene si el plan incluye algo distinto de 1 modificación del ASG, o cualquier creación/destrucción/reemplazo**; para `on` exige RDS `available`; pide escribir `APLICAR ON` o `APLICAR OFF`; aplica solo el plan guardado; después ejecuta `v2-status.sh`. No incluye `destroy`.
- Marcador local `work/operacion/v2-estado-declarado` (`on|off`) y aviso en `v2-status.sh` si difiere del ASG real.
- Procedimiento: apagar = `./v2-terraform.sh off`; encender = iniciar RDS si está detenida → `./v2-terraform.sh on` → `./v2-status.sh` → prueba funcional. Los scripts `v2-up`/`v2-down` quedan como vía de emergencia; después de usarlos se ejecuta el envoltorio para realinear.

## 3. Versionado y documentación (sin commit; solo comprobación)
- Modificados en Git: `infra/aws-v2/compute.tf` y `infra/aws-v2/variables.tf` (variable `asg_enabled`).
- Nuevos sin versionar: `scripts/v2-ops/` (scripts, README y pruebas), `docs/operacion/` (guía de reencendido y propuestas) y carpetas de evidencia del 5 y 6-nov (JSON y registros sin cuenta ni secretos).
- Ignorados por `.gitignore` y fuera de Git: `*.tfvars`, `*.tfstate*`, `*.tfplan`, `.terraform/`, todo `work/`. Búsqueda de claves, llaves privadas y cadenas de conexión en los archivos nuevos: 0 coincidencias; el número de cuenta no aparece en ellos.
- Pendiente de decisión (no se hizo commit): si se versiona el Word/PDF/pptx de `docs/entregable2/` y `outputs/`, y revisar las 3 modificaciones previas de `docs/entregable2/*.md`.
