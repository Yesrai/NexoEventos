# Fase A1 — Lifecycle de backups S3 (4-nov-2026, saneado)

**Estado: DESPLEGADA y verificada en AWS.** Alcance: SOLO la regla de lifecycle del bucket privado de V1. La subred **no** se modificó.

## Condiciones comprobadas antes del apply
| Condición | Resultado |
|---|---|
| Sesión AWS CLI | válida |
| Crédito de Academy | 40,40 USD disponibles (lectura de la usuaria del 4-nov; gasto posterior ≈ 0; el apply cuesta 0) |
| Estado Terraform | serie 46 antes del plan y del apply; plan regenerado ese mismo momento |
| Plan | `0 a crear, 1 a actualizar, 0 a destruir`; solo `aws_s3_bucket_lifecycle_configuration.private` |
| Verificador `scripts/cloud/verificar-plan-s3-subred.py --solo-s3` | CORRECTO; plan JSON inspeccionado (antes/después de la regla) |
| `-refresh=false` | La SCP de Academy impide refrescar el bucket. Se contrastó el «antes» del plan con la lectura real de AWS: prefijo `database-backups/`, 7/7 días: **coinciden**. Incertidumbre residual: otro atributo no leído que haya cambiado fuera de Terraform (no hay indicios); el apply habría fallado o mostrado diferencias al aplicar |
| Objetos afectados | 4 respaldos en `backups/database/`, 0 versiones no vigentes, 0 marcadores de borrado, edades de 12 a 31 días: **ninguno caduca** con 365 días |
| Otros objetos | `deployment-source/` (3) y 458 versiones no vigentes con 458 marcadores de borrado en la raíz (`i-…/…`, restos de transferencias de Ansible por SSM): **fuera del prefijo, ni la regla vieja ni la nueva los toca** |

## Resultado del apply
`Apply complete! Resources: 0 added, 1 changed, 0 destroyed.` (estado, serie 48). Antes del apply se guardó una copia local del estado (`terraform.tfstate.pre-lifecycle`, sin restaurarla; solo para inspección si hiciera falta).

## Verificación posterior (lecturas reales de AWS)
- Lifecycle real: regla `expire-demo-backups`, `Enabled`, prefijo **`backups/database/`**, expiración **365** días, versiones no vigentes **365** días.
- Versionado `Enabled`; cifrado `AES256`.
- Los **4 respaldos** siguen vigentes con el mismo tamaño y **los mismos ETag** que la línea base (comparación automática, idénticos): 31 419 / 92 063 / 22 762 / 78 495 bytes. 0 marcadores de borrado.
- Sin otros cambios: subred con `MapPublicIpOnLaunch = true` (intacta), EC2 `running`, RDS `stopped`, alarmas sin cambios (2 `OK`, 3 `INSUFFICIENT_DATA` por la RDS detenida).
- Un nuevo plan dirigido al mismo recurso: «No changes».
- Se eliminó el plan guardado; el plan combinado anterior (`s3-subred.tfplan`) se eliminó **sin aplicar**.

## Qué NO se demuestra
- No se ha restaurado ningún `.cms` desde S3. La restauración del respaldo del 23-oct está probada por el experimento E (copia en OCI); los otros tres no se han restaurado ni descifrado.
- El lifecycle solo caducará objetos pasados 365 días: no hay forma de probar la caducidad en este laboratorio.
- Hallazgo lateral (no corregido): 458 versiones/marcadores huérfanos de Ansible en la raíz del bucket, de tamaño pequeño; se pueden limpiar con una regla aparte si se decide.
