# Preparación de la publicación en Git: auditoría y plan (22-nov-2026)

Auditoría **local y de solo lectura** (salvo las correcciones de §6). No se ejecutó `git add`, `commit`, `push` ni reescritura de historial; no se tocó Terraform remoto, la nube ni S14. Sin valores secretos en este informe. Lista exacta de archivos por commit: [plan-publicacion-git-archivos.txt](plan-publicacion-git-archivos.txt).

## 1. Estado de Git
- Rama `entregable2-auditoria`, **11 commits locales** sobre `origin/entregable2-auditoria` (73 archivos, +3727/−22; sobre todo `docs/evidencias` 34, `scripts/v2-ops` 11, `docs/operacion` 8, `infra/oci` 5, `backend/app` 5). `main` está igual que `origin/main`. Rama local `backup/pre-reescritura-92f4b06` (no se publica).
- Sin confirmar: **34 modificados + 101 entradas sin seguimiento = 925 archivos** (las carpetas nuevas se expanden), 0 eliminados.
- Ignorados (38 rutas): cachés, `.venv`, `node_modules`, `dist`, `.terraform`, `.env`/`backend/.env`, `ansible/monitoring-inventory.yml`, `work/` (4,2 GB). **Ningún archivo de código, Terraform, Ansible o documentación queda fuera por `.gitignore`**; solo lo que debe ser privado. Ojo: `*.crt`, `*.pem`, `*.cms` y `*.dump` están ignorados a propósito (no hay certificados de ejemplo que publicar).

## 2. Auditoría de seguridad
| Alcance | Método | Resultado |
|---|---|---|
| 925 archivos candidatos (texto) | 10 patrones: claves privadas, AWS key/secret/token, ARN con cuenta, IDs de 12 dígitos, asignaciones de contraseña/token, JWT, tokens de proveedor, IP pública, OCID, correos; y nombres (`.env`, `.tfstate`, `.tfvars`, `.pem`, `.key`, `.cms`, `.dump`, `credentials`) | **0 archivos con nombre sensible**; las coincidencias son detectores/pruebas con valores ficticios (`AKIAIOSFODNN7…`, `123456789012`, IP/correos de ejemplo) y contraseñas de **laboratorio local** (`lab-local-only…`, sin uso fuera de contenedores locales; 0 en lo ya publicado) |
| **Historial de los 11 commits** (líneas añadidas, commit a commit) | Los mismos patrones | 0 claves, 0 tokens, 0 `.env/.tfstate/.tfvars`; 6 IDs de 12 dígitos = **ficticios** (`123456789012`, `000…`, `111…`, `999…`); 1 contraseña de **fixture de prueba**; **1 hallazgo de privacidad** (§2.1) |
| Comparación contra valores reales de `work/` y `.env` | No ejecutada: el sistema bloqueó leer esos archivos (correcto) | **Límite:** no se pudo verificar por valor exacto; la ausencia se basa en patrones y contexto |
| Escáner dedicado (Trivy/gitleaks) | No instalado localmente | La CI ya ejecuta Trivy con `scanners: secret`: ver riesgo R2 |
| Binarios | 9 `.docx/.pdf/.pptx` + `outputs/` (47,8 MB) | **Privados**: el repositorio no versiona ninguno (0), no se escanean por texto |
### 2.1 Hallazgos y su estado
1. **Dirección de correo personal** (1 cuenta de Gmail, la identidad de Tailscale) en `docs/operacion/azure-acceso-tailscale.md`, **dentro del commit local `cc1193f`** (nada de ello está publicado todavía; 0 en `origin`). No es un secreto de acceso, pero es dato personal. **Remediación propuesta (requiere tu autorización):** sustituirla por `<cuenta-tailscale>` con una modificación del commit `cc1193f` (rebase interactivo/`fixup` de commits **aún no publicados**) antes del `push`. Hasta que decidas, **la publicación queda bloqueada** por este punto. Alternativa menos limpia: un commit nuevo que lo sustituya, pero el valor quedaría en el historial publicado.
2. **ID de cuenta de AWS real** codificado en `scripts/multicloud/hybrid/hybrid_b1.py` y como fixture en `tests/test_verify_clean.py` (ambos sin seguimiento; no estaba en commits ni en `origin`). **Corregido**: ahora se lee de `NEXO_EXPECTED_ACCOUNT_ID` (por defecto `000000000000`: sin la variable, la identidad no coincide y el script se detiene) y la prueba usa un ID ficticio. 40 pruebas OK.
3. **Correo personal** en `scripts/multicloud/hybrid/oci_seal_lab.py` y `tests/test_hybrid_tools.py` (sin seguimiento): **sustituido** por `admin@example.invalid`; 10 pruebas OK.
4. Contraseñas literales de laboratorio en `scripts/repl-lab/*` y `scripts/failover-lab/compose.yml` (valor marcado «lab-local-only», redes aisladas 127.0.0.1): aceptables; riesgo bajo de que un escáner las marque (R2).
5. **Incidente mío:** al comprobar el punto 2, un `grep -n` mostró una vez el ID de cuenta en la terminal (mi enmascarado falló). No se copió a ningún informe, archivo ni mensaje, y ya no está en el código.

## 3. Coherencia con el código y con Terraform
- **Terraform:** `infra/aws-v2/*.tf` no tiene cambios pendientes (ya está en los 11 commits); `fmt -check` y `validate` correctos en `infra/aws-v2` e `infra/oci` (sin `plan` ni acceso remoto). Las variables que citan las guías (`asg_enabled`, `ami_includes_livez`, `expected_account_id`, `instance_profile_name`, `certificate_arn`) existen; `asg_enabled` no tiene valor por defecto (comprobado por `check_security.py`: 17 OK, 0 fallos).
- **Rutas obsoletas corregidas** (documentación, sin cambiar su sentido): `deploy/backup/verify-transfer.sh` → `scripts/multicloud/verify-transfer.sh` (c04) y `deploy/duckdns/switch.sh` → `scripts/multicloud/dns_switch.py` (backlog E3). 71 archivos `.md` revisados; quedan 4 referencias abreviadas o marcadores de posición (`docs/multicloud/0x`, `AAAAMMDD`), sin impacto.
- **Cifras desactualizadas:** el manifiesto de recuperación decía 34 modificados / 97 sin seguimiento; hoy son 34 / 101 entradas (925 archivos); se actualiza en §6.
- **Procedimientos que podrían fallar en una reconstrucción (no probados):** (a) la AMI dorada no cruza cuentas; (b) los secretos no viajan (sin `TICKET_ENCRYPTION_KEY` original los QR no se descifran); (c) `rds-window.sh`/`review-plan.py` solo se probaron con simulaciones; (d) el certificado de ACM y los buckets hay que rehacerlos; (e) `hybrid_b1.py` ahora exige `NEXO_EXPECTED_ACCOUNT_ID` (anotado para el procedimiento de sesión).

## 4. Validaciones locales ejecutadas (sin nube ni coste)
| Validación | Resultado |
|---|---|
| Backend `pytest -q` (con el código actual, incluidos los módulos nuevos) | **322 correctas**, 0 fallos |
| Frontend `npm test` + `tsc -b` | **44 correctas**; tipos OK |
| `infra/aws-v2/tests/check_security.py` | 17 OK, 0 fallos |
| `scripts/v2-ops/tests/test-rds-window.sh` | TODAS OK |
| Pruebas de la tarea CI «respaldo-script» (`test_backup_cycle`, `test_cms_key_passin`, `test_backup_source`, `test_oci_source`, `test_lease_http`, `test_failover_e2e`) | OK |
| `test_chaos_evidence` + `test_v2_plan_review` | 14 OK |
| `terraform fmt -check` / `validate` (aws-v2, oci) | OK |
| `test_hybrid_b1`, `test_verify_clean` (tras la corrección) / `test_hybrid_tools` | 40 OK / 10 OK |
**No ejecutado:** Trivy/gitleaks (no instalados), pruebas con Docker, `terraform plan`, `test_py39_compat` (necesita `pytest` en el Python del sistema; en CI corre con 3.12).

## 5. Plan de commits (en este orden; cada uno depende de los anteriores)
| # | Mensaje propuesto | Contenido (archivos) | Depende de | Riesgo | Estado |
|---|---|---|---|---|---|
| 1 | `feat(backend): sello, testigo y fences del escritor único; panel de operaciones` | `backend/app/**` (gate, lease, store, database, main; **nuevos** db_fence, pg_fence, seal, seal_log, site_member, witness, write_paths, external_writers, enforce_readiness, `ops.py`) + `backend/tests/**` (35 archivos) + `deploy/nginx/…template` | — (`gate.py` importa pg_fence/seal/seal_log/site_member/witness; `main.py` importa `ops`: **van juntos**) | Medio: compuerta de escritura (apagada por defecto) | **Listo** (322 pruebas OK) |
| 2 | `feat(frontend): panel de operaciones` | `frontend/src/{Operations.tsx,Operations.test.tsx,Organizer.tsx,theme.css}` | 1 (usa el router `/ops`) | Bajo | **Listo** (44 OK) |
| 3 | `feat(multicloud): failover, testigo, respaldo periódico y simulacros OCI` | `scripts/multicloud/**` (198 archivos con tests), `scripts/{failover-lab,repl-lab,v2}`, `deploy/backup/`, `deploy/systemd/nexoeventos-backup.*`, `deploy/install-rds-ca-bundle.sh`, `scripts/cloud/{db-backup-cms,test_db_backup_cms}.py`, `scripts/{test-backup-role,demo_ops_panel,check-local}…` | 1 | Medio: muchos scripts; ahora sin ID de cuenta ni correos | **Listo** tras R2 |
| 4 | `feat(v2-ops): modo resume, revisión estricta de planes, ventana de RDS y respaldo cifrado` | `scripts/v2-ops/**` (rds-window, review-plan, pruebas), `scripts/ops/*` (respaldo y prueba de restauración externa), `scripts/cloud/validate-chaos-result.py`, `infra/aws-v2/{README,RUNBOOK-academy}.md`, `tests/check_security.py`, `backend/tests/test_v2_plan_review.py` ya en 1 | — | Bajo | **Listo** |
| 5 | `docs(operacion): reconstrucción, reconciliación, verificación, respaldo, custodia y copia externa` | `docs/operacion/*` nuevos (9), `docs/README.md`, `scripts/README.md` | 4 | Bajo | **Listo** |
| 6 | `docs(entregable2): matrices de caos, cierre y cobertura actualizadas` | `docs/entregable2/*.md` (4) — **sin** `.docx/.pdf/.pptx` | — | Bajo | **Listo** |
| 7 | `docs(entregable3): diagnóstico, viabilidad y herramientas` | `docs/entregable3/**` (638 archivos, ≈ 10 MB; incluye diagramas PNG y evidencias de replicación) — **sin** informe `.docx/.pdf` | — | Medio: volumen alto; revisar R3 | **Necesita revisión** (R3) |
| 8 | `docs(evidencias): B1/B2 V2 del 20-nov, copia externa, C04, respaldo RDS e índice` | `docs/evidencias/{20261120-b1-b2-v2,20261122-copia-externa-respaldo,c04-20261119,20261105-ci-correccion,multicloud/aws/20261111-respaldo-rds,INDICE-PRUEBAS-AWS.md}` (14) | 5, 6 | Bajo | **Listo** |
| 9 | `ci: pruebas del respaldo periódico y del selector de failover` | `.github/workflows/ci.yml` | **3** (los scripts que ejecuta deben existir) | Medio: puede fallar la CI en la rama | **Listo** tras R1 |
**Privado (no se versiona):** `outputs/entregable2-final/**` (47,8 MB), `docs/entregable2/Entregable2-NexoEventos.{docx,pdf}`, `docs/entregable2/presentacion/*.pptx`, `docs/entregable3/informe-final/*.{docx,pdf}` (convención: 0 binarios de este tipo en el repositorio), `work/`, `.env`, clave y respaldo.
**Los 11 commits locales:** se publican con la corrección del correo ya aplicada (§8.1).

## 6. Qué modifiqué en esta ronda (todo local, sin commit)
1. `scripts/multicloud/hybrid/hybrid_b1.py`: ID de cuenta por entorno (§2.1-2).
2. `scripts/multicloud/tests/test_verify_clean.py`: fixture ficticio.
3. `scripts/multicloud/hybrid/oci_seal_lab.py`, `tests/test_hybrid_tools.py`: correo sustituido.
4. `docs/evidencias/c04-20261119/siguiente-restauracion-rto.md`, `docs/entregable3/19-backlog-tecnico-y-auditoria-fase1.md`: dos rutas corregidas.
5. `scripts/ops/probar-restauracion-externa.sh` (ya registrado en el informe de copia externa) y este plan + su lista de archivos.
6. Manifiesto de recuperación: cifras de §2 actualizadas (ver el propio archivo).

## 7. Riesgos y correcciones pendientes
- **R1 (CI):** el trabajo nuevo de `ci.yml` y las pruebas nuevas nunca han corrido en GitHub; hacer el `push` a la **rama** y revisar la CI antes de cualquier fusión; no tocar `main`.
- **R2 (CI, Trivy `secret`):** los detectores y pruebas contienen cadenas con forma de clave (`BEGIN … PRIVATE KEY`, `AKIA…`) y contraseñas de laboratorio; el escaneo puede marcarlas aunque sean ficticias. Preparar una exclusión justificada (`trivy-secret.yaml`/`.trivyignore`) solo si ocurre.
- **R3:** `docs/entregable3/**` es el mayor lote (638 archivos): revisar a ojo antes de publicar y decidir si todo debe ser público (informes de auditoría con direcciones y cuentas ya enmascaradas).
- **R4 (resuelto el 22-nov):** correo personal en `cc1193f` corregido (§8.1).
- **R5:** al publicar, el paquete de respaldo (`…022238Z`) queda desactualizado respecto de los archivos nuevos; regenerar y volver a subir a Drive y OneDrive después del `push`.

## 8. Actualización del 22-nov-2026 (tras las decisiones de la propietaria)
### 8.1 Corrección del historial (ejecutada, sin push)
- **Condiciones comprobadas:** remoto único `origin`; `origin/entregable2-auditoria` = `7755e48` (confirmado también con `ls-remote`, solo lectura) y `origin/main` = `42dd9e0`; `cc1193f` **no está en ningún ref remoto** (solo en la rama local) ni en etiquetas; el correo no está en `origin`, en mensajes de commit ni en otros archivos del árbol; el archivo solo lo toca `cc1193f` (los 7 commits posteriores no lo modifican); commits sin firma GPG.
- **Referencia de recuperación:** rama local `backup/pre-saneo-correo-ab61a4b` → `ab61a4b` (estado exacto anterior). **No debe publicarse** (conserva el correo) y se debe excluir del `push`.
- **Acción:** se reconstruyeron los 8 commits desde `cc1193f` (con comandos de bajo nivel, sin tocar el directorio de trabajo): mismo contenido, autor, fecha y mensaje; solo cambia el archivo `docs/operacion/azure-acceso-tailscale.md` (5 apariciones → `<cuenta-tailscale>`; 4 líneas). Nuevos hashes: `cc1193f→8313be2`, … , `ab61a4b→105d103`. Los 3 commits anteriores no cambiaron.
- **Verificación:** 11 commits sobre `7755e48`; mensajes y metadatos idénticos; el diff entre el tip antiguo y el nuevo es solo ese archivo; **0 commits con el correo**; el estado del directorio de trabajo es idéntico al de antes (137 entradas, nada perdido); `git fsck` correcto; `main` y `origin/*` intactos; sin force-push ni push.
- **Pendiente de esa rama de recuperación:** una vez publicado y validado, borrarla (con tu autorización) para que el correo no quede localmente.
- **Nota:** el autor y el committer de los 11 commits usan el correo institucional de la UPeU (el mismo que ya figura en los commits publicados).
### 8.2 Entregable 3
Dictamen en [dictamen-entregable3.md](dictamen-entregable3.md): 638 archivos **versionables**; `informe-final/*.docx|pdf` **fuera**; 2 evidencias de Terraform saneadas (manifiesto 607/607).
### 8.3 Matriz definitiva (918 archivos a versionar; 10 fuera)
| # | Commit | Archivos | Dependencia | Estado |
|---|---|---|---|---|
| 1 | `feat(backend): sello, testigo y fences del escritor único; panel de operaciones` | 35 | — | Listo |
| 2 | `feat(frontend): panel de operaciones` | 4 | 1 | Listo |
| 3 | `feat(multicloud): failover, testigo, respaldo periódico y simulacros OCI` | 198 | 1 | Listo |
| 4 | `feat(v2-ops): modo resume, revisión estricta de planes, ventana de RDS y respaldo cifrado` | 12 | — | Listo |
| 5 | `docs(operacion): reconstrucción, reconciliación, verificación, respaldo, custodia, copia externa y publicación` | 12 | 4 | Listo |
| 6 | `docs(entregable2): matrices de caos, cierre y cobertura` | 4 | — | Listo |
| 7 | `docs(entregable3): diagnóstico, viabilidad, evidencias y herramientas` | 638 | — | **Listo** (dictamen favorable) |
| 8 | `docs(evidencias): B1/B2 V2, copia externa, C04, respaldo RDS e índice` | 14 | 5, 6 | Listo |
| 9 | `ci: pruebas del respaldo periódico y del selector de failover` | 1 | 3 | Listo (revisar la CI en la rama) |
Lista exacta: [plan-publicacion-git-archivos.txt](plan-publicacion-git-archivos.txt) (`[M]` = modificado).
**Fuera del repositorio (10 archivos privados):** `outputs/entregable2-final/` (5), `docs/entregable2/Entregable2-NexoEventos.{docx,pdf}`, `docs/entregable2/presentacion/NexoEventos-Entregable2.pptx`, `docs/entregable3/informe-final/*.{docx,pdf}`; además, por `.gitignore`, `work/`, `.env`, `backend/.env`, `ansible/monitoring-inventory.yml`, claves, certificados, `*.cms`, `.terraform`, cachés y la rama de recuperación.
### 8.4 Validaciones posteriores a la corrección
`git fsck` OK; árbol de trabajo idéntico; 23 pruebas (caos, plan V2, salud) OK; re-escaneo de los 11 commits: **el correo personal ya no aparece**, el resto son los mismos ficticios; 0 correos de Gmail en los archivos candidatos; 0 archivos con nombre sensible. Las suites completas (backend 322, frontend 44, Terraform, CI local) se ejecutaron antes de la corrección y no dependen del historial.

## 9. Informe de publicación (22-nov-2026)
### 9.1 Commits publicados (`origin/entregable2-auditoria`: `7755e48..f83de56`, fast-forward, sin force)
Los 11 commits previos (con el saneado del correo en `8313be2`): `65bafe4`, `037be7f`, `47f678f`, `8313be2`, `293e4c3`, `bfe1768`, `6247cd4`, `511ba0e`, `3bc97ba`, `1225c86`, `105d103`.
Los 10 nuevos: `e566108` backend (31 archivos) · `66dc808` frontend (4) · `f10d6dc` multicloud (201) · `46336af` v2-ops (13) · `2922acb` docs/operacion (12) · `9ad2b19` entregable2 (4) · `f99d023` entregable3 (638) · `77656bc` evidencias (14) · `9445e6f` ci (1) · `f83de56` test de failover (1). Total: **918 + 1 archivos**, sin `Co-Authored-By`. Quedaron fuera los 10 archivos privados, `work/`, secretos y respaldos. Remoto: solo `entregable2-auditoria` (`f83de56`) y `main` (`42dd9e0`, intacto); no se publicó ninguna rama `backup/*`. Existe el PR n.º 1 (base `main`), abierto: **no se fusionó**.
### 9.2 Décimo commit
`tests/test_failover_defaults.py` protege que ningún despliegue o configuración active la compuerta de escritura ni el failover. Era válida, pero demasiado amplia para la documentación: prohibía cualquier mención en `docs/operacion`, incluida la trazabilidad de `dns_switch.py`. Ahora: configuración y código de despliegue conservan la prohibición de **cualquier mención**; en `.md` se prohíben las **instrucciones de activación** (`WRITE_GATE_*` distinto de `off`, `NEXO_ALLOW_FAILOVER_EXECUTE`/`NEXO_ALLOW_DNS_CHANGE` asignadas, el subcomando de aplicación de `dns_switch.py` o la de ejecución del orquestador). Se añadió una prueba parametrizada con 9 casos (3 permitidos en doc, 3 bloqueados en doc, 3 bloqueados en configuración).
### 9.3 Pruebas locales sobre el HEAD `f83de56` (secuenciales)
Backend completo **331 correctas**; frontend **44** y build; tipos OK; `check_security` 17 OK/0 fallos; `test-rds-window` OK; failover y recuperación (`test_failover_defaults`, `test_write_gate`, `test_rollback_attack`, `test_chaos_evidence`) **56 OK**; las 6 pruebas de la tarea de CI «respaldo» OK; Terraform `fmt`/`validate` OK en `aws-v2` y `oci`.
**Límite local:** `test_backup_cycle.py` falla en 2 pruebas con el OpenSSL de macOS (LibreSSL crea las claves con 0644 y el código exige 0600); con OpenSSL 3/4 pasa 36/36 (así corre la CI en Linux).
### 9.4 Resultado real de GitHub Actions (ejecución 44984148507, `f83de56`, PR n.º 1)
| Job | Resultado | Causa |
|---|---|---|
| Backend (pytest + PostgreSQL 18) | **Correcto** | — |
| Frontend (pruebas + build) | **Correcto** | — |
| Trivy: dependencias y **secretos** | **Falló solo en el lockfile de producción**; el análisis de dependencias y **secretos del repositorio: 0 hallazgos** | `dnspython 2.9.0` (HIGH, CVE-2026-128089, corregida en 2.9.2). Dependencia transitiva; `backend/requirements-production.lock` **no** cambió en esta publicación: es un aviso nuevo posterior a la última CI verde |
| Imagen Docker + Trivy | **Falló** | El mismo `dnspython 2.9.0` (único hallazgo: 1 HIGH); Debian y el resto de paquetes, 0 |
| Respaldo periódico cifrado (nuevo) | **Falló** | Defecto de mi `ci.yml` (commit 9): `test_cms_key_passin.py` importa `httpx` (vía `db-backup-cms.py` → `verify-controlled-flow.py`) y el trabajo instalaba las dependencias **después** de ese paso; además el lockfile no incluye `httpx`. Los 4 pasos siguientes no llegaron a ejecutarse en la CI |
### 9.5 Correcciones de la CI (commit correctivo posterior; el resultado de la nueva ejecución está en el PR n.º 1)
1. `backend/requirements-production.lock`: `dnspython==2.9.2` (única diferencia del lock; requiere Python ≥ 3.11 y la imagen usa 3.12; sin dependencias obligatorias nuevas; `pip check` limpio; `email-validator` es el único dependiente; el entorno limpio resuelve exactamente el lock). Backend: 331 correctas con 2.9.2. No se tocó la severidad ni la configuración de Trivy.
2. `.github/workflows/ci.yml` (job de respaldo): paso inicial `pip install -r backend/requirements-production.lock httpx==0.28.1` y retirada de la instalación duplicada. **`httpx` y su dependencia `certifi` son solo de pruebas**: se instalan únicamente en ese job (el backend ya lo hace con su propio `pip install … pytest httpx`) y **no** se añaden al lock de producción ni a la imagen. Reproducido en un entorno limpio con solo esas dependencias: `test_backup_cycle` (36), `test_cms_key_passin` (20), `test_backup_source` (14), `test_oci_source` (36), `test_lease_http` (11) y `test_failover_e2e` (83) **todas OK**, incluidas las 4 etapas que antes no llegaron a ejecutarse.
### 9.6 Dependencia entre los commits 1 y 3 (implicaciones para `git bisect`)
`e566108` (backend) y `f10d6dc` (multicloud) son interdependientes: el backend declara el inventario de escritores externos (`write_paths.py`) que `test_write_gate_coverage.py::test_el_inventario_declara_los_productores_externos_y_los_limites` contrasta con scripts de `scripts/multicloud`, y los scripts importan `app.failover.*`. Probado aislado, **`e566108` tiene 1 prueba fallida** (esa) y 271 correctas. Tres pruebas del backend que importan scripts (`test_ops_panel`, `test_enforce_readiness`, `test_v2_alb_asg_local`) viajan con el commit 3, y `test_v2_plan_review` con el 4, para no romper más. Implicación: en un `bisect`, marcar `e566108` como «omitir» (`git bisect skip`); el estado consistente de cada bloque es `f10d6dc` en adelante. Solo la punta (`f83de56`) se ha validado completa.
### 9.7 Limitaciones
No hay escáner de secretos local equivalente a Trivy (se usó el escaneo propio por patrones, más el de Trivy en la CI: 0 secretos); las suites completas de intermedios no se ejecutaron salvo `e566108`; la rama `backup/pre-saneo-correo-ab61a4b` sigue local (conserva el correo) y **no** está en GitHub.
