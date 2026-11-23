# Verificación local del 22-nov-2026 — resultados, incluidos los fallos (sin operaciones Cloud)

Todo se ejecutó en el Mac, con PostgreSQL 18.7 **desechable** (clúster nuevo en `/tmp`, socket privado, eliminado al terminar) y servidores solo en `127.0.0.1`. Los registros crudos están en `work/pruebas/` (no versionados); aquí se anotan sus SHA-256.

## 1. Cronología honesta (nada se oculta)
| # | Ejecución | Resultado | Diagnóstico y acción |
|---|---|---|---|
| 1 | `scripts/ops/pruebas-backend-aislado.sh` (primer intento) | **FALLÓ al arrancar PostgreSQL** (`pg_ctl: no se pudo iniciar el servidor`); el log se borró con la limpieza del propio script y el rerun lo sobrescribió | Reproducido a mano: `FATAL: postmaster became multithreaded during startup — HINT: Set LC_ALL`. Mismo defecto de PostgreSQL 18 en macOS visto en C-04. **Corregido:** el script fija `LC_ALL/LANG` |
| 2 | Backend completo (rerun) | **331 aprobadas, 0 fallos** (77,7 s) | `work/pruebas/backend-suite-20261122.log` · sha256 `38d657d9…` |
| 3 | Batería «failover y seguridad» **ejecutada conjunta** (`scripts/multicloud/tests` + 6 archivos del backend en un solo proceso, sin la base aislada) | **589 aprobadas, 30 FALLARON**, 622,8 s | Lista exacta en `fallos-ejecucion-conjunta-30.txt` (9 en `test_write_gate.py`, 21 en `test_write_gate_coverage.py`). `work/pruebas/failover-seguridad-20261122.log` · sha256 `a491af64…` (329 626 B) |
| 4 | Esos mismos archivos en el entorno aislado correcto | **107 aprobadas, 0 fallos** (con `test_lease`, `test_db_fence`, `test_seal`, `test_enforce_readiness`) | Demuestra que no eran defectos del producto |
| 5 | Causa raíz de los 30 | Error: `connection to server on socket "/tmp/pgs<pid>/.s.PGSQL.<puerto>" failed` | El fixture de `scripts/multicloud/tests/test_pg_standby.py` hacía `os.environ["DATABASE_URL"] = <su clúster temporal>` (y borraba `WRITE_GATE_*`) y **nunca lo restauraba**; tras destruirse ese clúster, las pruebas del backend posteriores del mismo proceso apuntaban a un socket inexistente |
| 6 | Corrección | `test_pg_standby.py` guarda y restaura `DATABASE_URL`, `WRITE_GATE_MODE`, `WRITE_GATE_DB_FENCE` al terminar el fixture | Verificado: `test_pg_standby` + `test_write_gate` + `test_write_gate_coverage` en un solo proceso → **72 aprobadas, 0 fallos** |
| 7 | Batería conjunta completa repetida tras la corrección | ver §3 | — |

## 2. Resto de pruebas nuevas de hoy (todas locales)
| Qué | Resultado |
|---|---|
| `ops_center` (flujo, barreras, auditoría, evidencias, T1 automático) | **43 aprobadas** |
| Carrera de **adquisición del lease** (`lease_race.py`): 10 rondas × 8, servidor HTTP local con If-Match efectivo | **exclusividad demostrada**: 1 ganador por ronda, ≤ 1 lease válido, épocas 2…11 (+1) |
| **Control negativo** (servidor que ignora If-Match) | la prueba **detecta** varios ganadores/válidos simultáneos (no es una prueba que siempre pase) |
| Almacén caído / plazo global en la carrera | resultado INCONCLUSO o detenido, nunca éxito |
| Limpieza del probe de PAR con cliente OCI falso (`test_par_probe_cleanup.py`) | 10 aprobadas: limpieza completa → 0; revocación que falla → continúa y devuelve 3; red caída → no se declara limpio; PAR huérfano revocado por nombre; objeto ajeno no se borra; detenido-pero-limpio → 1 |
| Testigo (existentes 20 + perfil Azure nuevo 8) | **28 aprobadas** (persistencia tras `kill -9`, exclusividad con 2 procesos, autenticación por token y alcance, TLS con certificado fijado, almacén alterado y cola a medias → no arranca, disco sin permiso → 503 y la marca no avanza, **limitación** del prefijo restaurado documentada como prueba) |
| Fábrica de adaptadores (`real_factory.py`, proveedores simulados) | **10 aprobadas**; modo real **bloqueado** |
| Terraform `infra/oci/modules/public_entry` con proveedor simulado | **5 aprobadas** (apagado = nada; con orígenes explícitos: solo 443 + SSH desde Bastion + salida 443; rechaza 0.0.0.0/0, lista vacía y CIDR inválido) |
| `terraform fmt` / `validate` (oci, azure, aws-v2) y `check-iac-security.py` | correctos; el verificador se actualizó para el módulo opcional (53 comprobaciones OK) |

## 3. Batería conjunta tras la corrección
Ver el final de este archivo (se completa cuando termina la ejecución).

### Resultado de la repetición conjunta (tras corregir el fixture)
`scripts/ops/pruebas-backend-aislado.sh ../scripts/multicloud/tests tests/test_lease.py tests/test_lease_tampering.py tests/test_write_gate.py tests/test_write_gate_coverage.py tests/test_db_fence.py tests/test_seal.py tests/test_seal_log.py tests/test_rollback_attack.py tests/test_enforce_readiness.py tests/test_external_writers.py`
→ **696 aprobadas, 1 omitida, 0 fallos** (611 s, PostgreSQL 18.7 desechable eliminado al terminar). Incluye las baterías nuevas de hoy (carrera del lease, limpieza del probe, perfil Azure del testigo, fábrica). Registro: `work/pruebas/failover-seguridad-conjunta-corregida-20261122.log` · sha256 `87c2d9ef314dea8b…`.
Los 30 fallos del §1 quedan registrados como **causados por contaminación del entorno entre suites (corregida)**, no como defectos del producto; el registro original (`failover-seguridad-20261122.log`) se conserva sin cambios.


## 4. Ampliación del 22-nov (preparación de T1) — todo local o lectura OCI
**Prueba omitida (1):** `scripts/multicloud/tests/test_witness_hardening.py::test_contenedor_real_arranque_http_firmas_reinicio_recuperacion_y_acceso` (`SKIPPED … Docker no disponible`, identificada con `-rs`, `work/pruebas/failover-seguridad-conjunta-rs-20261122.log`). Se omite si `docker info` no responde en 15 s; **ejecutada sola con Docker 28.0.4 disponible: PASA** (26 s). Justificación: condición de entorno, no un fallo; no se eliminó ni se debilitó.
**Defectos encontrados y corregidos:** (a) `oci_par_probe.py` no creaba `--workdir` con padres (habría fallado T1 en su primer comando); (b) el verificador `check-iac-security.py` aceptaba «todos los buckets privados» si **uno** lo era (lo detectó la prueba de mutación): ahora exige que **cada** bucket sea privado y el de respaldos versionado.
**Pruebas nuevas:** `--plan-only` del probe (16 pruebas del archivo, todas OK); `ejecutar-t1.sh` con probe simulado (6); **mutaciones del IaC** (`test_iac_security_guard.py`): el árbol sin tocar pasa y **11 debilitamientos** (IGW fuera del módulo opcional, regla abierta al mundo, precondición eliminada, puerto 5432, entrada encendida por defecto, IP pública fija en la VM, subred privada con IP pública, IGW no condicional, IAM con borrado, NAT por defecto, bucket público) **son detectados** ⇒ la excepción de la entrada pública opcional **no relajó** los demás módulos.
**Lecturas OCI de solo lectura:** costo de 30 días = 0,0 en todos los servicios; límites con valor > 0: A1 (2 OCPU/12 GB), A2 (8/96, **no usar**: forma de pago), E2.1.Micro ×2, bloque 200 GB, IGW 1, IP reservada 1, VCN 2, Object Storage 20 GiB; **E5/E4 = 0** y E5.Flex ya no se ofrece en el dominio de disponibilidad. Veredicto: perfil coherente con Always Free; **no prueba** el fin del trial.
