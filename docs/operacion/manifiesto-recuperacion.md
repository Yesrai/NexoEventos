# Manifiesto de recuperación de NexoEventos (22-nov-2026)

Lista de lo **indispensable** para reconstruir el sistema y de qué depende cada pieza. Solo rutas y categorías: **sin secretos, claves ni valores**. Estado verificado el 21/22-nov-2026 (trabajo local; sin AWS, sin commits).

## 1. Capas de custodia
| Capa | Qué contiene | Dónde está hoy | Riesgo |
|---|---|---|---|
| A. Git publicado | Historia hasta `origin/entregable2-auditoria` y `origin/main` | GitHub | — |
| B. Git local sin publicar | **11 commits locales** (HEAD `ab61a4b`, rama `entregable2-auditoria`): escritor único con lease, guarda de Terraform de V2, scripts de V2, docs y evidencias | Solo este Mac y el respaldo cifrado | Se pierden con el Mac |
| C. Cambios sin commit | 34 archivos modificados y 101 entradas sin seguimiento (= 925 archivos; plan en `plan-publicacion-git.md`) | Solo este Mac y el respaldo cifrado (**anterior** a 7 de ellos) | Idem |
| D. `work/` (ignorado por Git) | tfvars, estado de Terraform, secretos de Ansible, respaldos de BD, registros | Solo este Mac y el respaldo cifrado | Idem |
| E. Clave privada de recuperación | Descifra el paquete y los `.cms` de la BD | Solo este Mac, **sin frase de paso** | Crítico (ver `custodia-clave-y-copia-externa.md`) |

## 2. Cambios importantes aún sin versionar (verificado con `git status`)
| Grupo | Archivos clave | Estado |
|---|---|---|
| **AWS V2 y modo `resume`** | `scripts/v2-ops/rds-window.sh`, `scripts/v2-ops/review-plan.py`, `scripts/v2-ops/tests/{test-rds-window.sh,fake-aws-rds.sh,fake-terraform-chain.sh}`, `backend/tests/test_v2_plan_review.py`, `scripts/v2-ops/README.md` (M), `infra/aws-v2/RUNBOOK-academy.md`, `infra/aws-v2/README.md` (M), `infra/aws-v2/tests/check_security.py` (M) | Sin commit |
| **Terraform** (`infra/aws-v2/*.tf`) | Sin modificaciones pendientes: ya está en los commits locales (B) | Solo falta **publicar** |
| **Scripts de operación y respaldo** | `scripts/ops/respaldo-reconstruccion.sh`, `scripts/cloud/validate-chaos-result.py` (M), `scripts/cloud/db-backup-cms.py` (M), `scripts/cloud/test_db_backup_cms.py`, `scripts/multicloud/**` (OCI, failover, witness, hybrid, c04, backup_cycle…), `deploy/backup/`, `deploy/systemd/nexoeventos-backup.*` | Sin commit |
| **Guías y evidencias** | `docs/operacion/{aws-v2-reconstruccion,aws-v2-reconciliacion-terraform,aws-v2-verificacion-restauracion,respaldo-local-cifrado,manifiesto-recuperacion,custodia-clave-y-copia-externa}.md`, `docs/evidencias/INDICE-PRUEBAS-AWS.md`, `docs/evidencias/20261120-b1-b2-v2/`, `docs/evidencias/c04-20261119/`, `docs/evidencias/multicloud/aws/20261111-respaldo-rds/`, `docs/entregable3/`, `docs/entregable2/matriz-*.md` (M) | Sin commit |
| **Aplicación necesaria para reconstruir** | `backend/app/database.py`, `main.py`, `failover/{gate,lease,store}.py` (M) y nuevos `failover/{db_fence,pg_fence,seal,seal_log,site_member,witness,write_paths,external_writers,enforce_readiness}.py`, `backend/app/ops.py`; `deploy/install-rds-ca-bundle.sh`, `deploy/nginx/nexoeventos.conf.template` (M); `frontend/src/{Organizer.tsx,theme.css}` (M), `Operations.tsx` (+prueba); `.github/workflows/ci.yml` (M); ≈ 14 pruebas nuevas de backend | Sin commit |
| Otros | `outputs/entregable2-final/`, `docs/entregable2/Entregable2-NexoEventos.{docx,pdf}` y `presentacion/*.pptx` (sin seguimiento; **no generados en esta tarea**) | Revisar antes de cualquier publicación |

## 3. Indispensables para reconstruir (en orden de dependencia)
1. **Paquete cifrado** `work/respaldo-cifrado/nexoeventos-reconstruccion-<fecha>.tar.cms` + su `.sha256` → incluye B, C y D.
2. **Clave privada de recuperación** (guardada aparte) → sin ella, 1 y los `.cms` de la BD son irrecuperables.
3. Dentro del paquete: `repositorio.bundle` (todo Git), `sin-publicar.tar.gz`, `work-esencial.tar.gz` (tfvars, estado, Ansible, respaldos de BD), `MANIFIESTO.sha256`.
4. Herramientas: `terraform`, `aws` CLI, `jq`, `python3 ≥ 3.9`, `ansible`, `openssl`, `git`, `node` (`.node-version`), PostgreSQL client (`pg_restore`).
5. Credenciales **temporales** de AWS Academy (se renuevan en cada sesión; no se respaldan).
6. Por cuenta nueva (no viajan): AMI dorada, RDS/instantáneas, secretos, certificado de ACM, buckets. Ver `respaldo-local-cifrado.md` §8 y `migracion-entre-cuentas.md`.
7. Procedimiento: `aws-v2-reconstruccion.md` → `aws-v2-reconciliacion-terraform.md` → `aws-v2-verificacion-restauracion.md`.

## 4. Dependencias entre piezas
- `rds-window.sh` → `review-plan.py` (revisión de planes) → `infra/aws-v2` (+ tfvars de `work/terraform-envs`).
- `respaldo-reconstruccion.sh` → certificado público y clave privada de `work/recovery-keys/<corrida>/`.
- `validate-chaos-result.py` ← `docs/evidencias/*/resultado.json`; pruebas en `backend/tests/test_chaos_evidence.py`.
- La compuerta de escritura (`failover/gate.py`) y el lease dependen de las migraciones y del módulo `infra/oci` (creación desactivada por defecto).

## 5. Qué NO está (a propósito)
Clave privada de recuperación, claves de OCI/SSH, credenciales de Academy, planes de Terraform, `.terraform`, entornos virtuales, `node_modules`, capturas originales sin redactar y `work/ia-s14`.

## 6. Estado del respaldo (actualizado 22-nov-2026)
Paquete vigente: `nexoeventos-reconstruccion-20261122T022238Z.tar.cms` (399.524.048 B; SHA-256 `5b201c801dc5101b18416d022a63661628f125cef986b91ed5581ac3b0dbcdfb`), con Git completo (136 commits, HEAD `ab61a4b`), 922 archivos sin publicar y 228 de `work/`. El anterior (`…T021218Z`) se conserva.
**Copias externas verificadas por separado** (descarga + restauración de prueba con la clave protegida): Google Drive **pasó**; OneDrive UPeU **pasó**. Informe: `docs/evidencias/20261122-copia-externa-respaldo/resultado.md`.
**Clave:** existe una copia protegida con frase de paso (verificada: abre, coincide con el certificado, descifra el paquete); la original sin protección sigue en el Mac. Falta custodiar la clave protegida y la frase aparte.
**Límites:** (a) el paquete es anterior a los documentos y al script de prueba creados después (informe, instrucciones, corrección del script); (b) no se ha probado reconstruir en una cuenta nueva (ver pendientes en el informe).
