# Fase A — prechequeo de solo lectura (4-nov-2026, 10:06 Perú)

Bucket privado de V1: versionado `Enabled`, cifrado `AES256`, sin marcadores de borrado en `backups/database/`.

**Lifecycle desplegado hoy:** regla `expire-demo-backups`, prefijo **`database-backups/`** (vacío: 0 objetos), expiración **7 días**, versiones no vigentes **7 días**. Es decir: la regla actual **no toca los respaldos reales** (que están en `backups/database/`), pero tampoco es la política deseada.

**Respaldos reales (4 objetos, `backups/database/`)** — línea base «antes»:
| Objeto | Bytes | ETag | Modificado (UTC) |
|---|---|---|---|
| nexoeventos-20261004T002702Z.cms | 31 419 | e314db2d…ff | 2026-10-04 |
| nexoeventos-preupdate-20261008t0113z.cms | 22 762 | aeaaafac…59ca | 2026-10-08 |
| nexoeventos-preupdate-20261019t0628z.cms | 78 495 | d54dc396…7ee7 | 2026-10-19 |
| nexoeventos-alembic0008-20261023T150946Z.cms | 92 063 | f12c636f…ad0 | 2026-10-23 |

Tamaño total ≈ 225 KB: guardarlos 365 días cuesta ≈ 0 USD, así que caducarlos pronto solo añade riesgo.

**Plan guardado (no aplicado):** `work/terraform-plans/s3-subred.tfplan`, con `-refresh=false` y `-target` (el refresco del bucket lo bloquea la SCP de Academy; se contrastó a mano con la lectura real de arriba). Resultado: **0 a crear, 2 a actualizar, 0 a destruir**; `scripts/cloud/verificar-plan-s3-subred.py` = CORRECTO:
- `aws_s3_bucket_lifecycle_configuration.private`: prefijo `database-backups/` → `backups/database/`; expiración 7 → 365; versiones no vigentes 7 → 365.
- `aws_subnet.public_a`: `map_public_ip_on_launch` true → false (in situ; la EC2 pide su IP pública explícitamente, `associate_public_ip_address = true`).

**Qué NO está demostrado:** que los `.cms` se puedan restaurar (descifrar y cargar). Lo que sí está probado es la restauración del respaldo del 23-oct desde la copia de OCI (experimento E, 14/14 pruebas y huella) y la restauración PITR de RDS (R01). Los otros tres `.cms` no se han restaurado.
