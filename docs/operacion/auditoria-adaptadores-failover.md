# Auditoría de `FullRecoveryAdapters` y de su configuración real — 22-nov-2026

Solo lectura del código y ejecución de pruebas locales. **Nada se conectó a AWS, OCI ni Azure.** Fuentes: `scripts/multicloud/failover/{orchestrator,adapters_standby,adapters_probes,adapters_dns,failover_config,oci_source,promotion_gate}.py`, `backend/app/failover/*`, `scripts/multicloud/hybrid/*`.

## 1. Hallazgo principal
`FullRecoveryAdapters` existe y está probado de extremo a extremo **en local** (`test_failover_e2e.py`, 83 pruebas en el entorno del proyecto), pero **no existe ningún punto de entrada que lo construya a partir de una configuración real**: la CLI del orquestador solo usa el simulador (`sim.py`), y `failover_config.validate()` solo valida un JSON, no crea adaptadores. Ese «cableado» (una fábrica `build_real_adapters(cfg)` + un ejecutor con las barreras del centro) es el único código nuevo que T6 necesita, y se mantiene sin escribir/sin habilitar (`REAL_EXECUTION_WIRED = False`) hasta que T1–T4 estén en PASS.

## 2. Contrato `Adapters` → implementación → qué necesita en real
| Método | Implementación | En real necesita | Estado |
|---|---|---|---|
| `precheck` | `FullRecoveryAdapters.precheck` | store del lease verificado; respaldo en RPO; clave+script de restauración; standby inactivo; escritores externos (opcional) | local ✔ |
| `probe_all` / `detector` | `adapters_probes.ProbeSet`, `detector_from_http` | **≥ 3 sondas HTTPS desde fuera de AWS** (`/livez`, `/ready`, control) + estado de AWS por API de solo lectura (`ec2 describe-instances`, `rds describe-db-instances`) | local ✔; sondas reales por montar (Azure/OCI) |
| `restore_latest` | `oci_source.restore_latest_from_oci` | perfil OCI de **lectura** del bucket `nexoeventos-recovery`; `signer_pub`; huella del certificado destinatario; clave privada C-04 (frase: persona presente, `interactive_person`); `restore-drill.sh` y PostgreSQL 18 en el standby | local ✔ |
| `lease_acquire/release` | `lease.LeaseClient` + `ParHttpStore` | **PAR de lectura/escritura sobre UN objeto** (URL en archivo 0600), claves Ed25519 por nodo (`lease_keys.py`), autoprueba If-Match/If-None-Match | local ✔; real = T1 |
| `enable_standby` | `StandbyService` + `fenced_db` | permiso de promoción (archivo O_EXCL), lease válido, época vigente **en la base del standby** | local ✔ |
| `standby_status`, `standby_readiness` | HTTP al standby (`/write-gate`, `/livez`, `/ready`, API) | VM de OCI con entrada **HTTPS pública** (T3) | local ✔ |
| `dns_plan/apply`, `probe_new_endpoint` | `adapters_dns.DnsSwitchAdapter` → `dns_switch.py` | token DuckDNS 0600, `allowed_domains` solo de **pruebas**, la variable de autorización de cambios de DNS (`NEXO_ALLOW_DNS_CHANGE`, con su valor de confirmación), resolvedores 1.1.1.1/8.8.8.8/9.9.9.9 | local ✔; real = T2 |
| `synthetic_write_ok` | escritura sintética en el standby | compuerta del standby abierta tras habilitar | local ✔ |
| `old_can_write`, `primary_gate_attested`, `fencing_assessment` | `/write-gate` del primario + atestación (≤ 60 s) + vallado en la base | la compuerta en modo `enforce` y el vallado de base de datos en modo «require» (variables `WRITE_GATE_MODE` y `WRITE_GATE_DB_FENCE`) **desplegados en la API de AWS** | local ✔; real pendiente |
| `seal_primary` | `seal.py` / `seal_log.py` | **objeto de sello en OCI** + `operator_pubkey_file` (privada fuera de todo nodo) | local ✔; laboratorios F0/F1 existen |
| vallado fuerte (`promotion_gate`) | `db_hard_fence` o `rds_stop_confirmed` | `pg_signal_backend`, `track_commit_timestamp` en RDS; o `rds:StopDBInstance` (si `allow_stop_rds`) | local ✔; **no validado en RDS real** (`validated_on_real_rds=false`) |
| testigo de frescura | `witness.py` + `witness_service.py` | **servicio testigo** con clave propia y almacén de solo adición, fuera de AWS/OCI; `url_file`, `pubkey_file` | local ✔; **sin desplegar** |
| `alert` / estado | `write_last_run` → `last-run.json` | `OPS_FAILOVER_DIR` legible por el centro | local ✔ |

## 3. Requisitos de configuración (los exige `failover_config.validate`, aun con `automatic=false`)
| Requisito | Artefacto real | Cómo se produce | ¿Existe hoy? |
|---|---|---|---|
| `primary/standby.*_url` HTTPS (7 URLs) | ALB de V2 y entrada de la VM de OCI | T3 + ventana AWS | no |
| `primary.aws.instance_tag` y `db_id` | etiquetas reales | lectura de AWS | sí (etiquetas del proyecto) |
| `primary.db_fence=require`, `strong_fence.require`, `gate_attested` | compuerta y vallado desplegados en la API | plan híbrido B3/B4 (`hybrid_b3.py`, `fence_admin.py`) | no |
| `primary.seal.*` | objeto de sello + clave pública del operador | `oci_seal_lab_f0/f1.py`, `lease_keys.py` | solo laboratorio |
| `primary.freshness_witness.*` | testigo desplegado + su clave pública | `witness_service.py` (opción GCP **no aprobada**; ver §5) | no |
| `lease.store=par-http`, `lease.auth=ed25519`, `par_url_file` 0600 | PAR del lease + claves Ed25519 | `oci_par_lab.py`, `lease_admin.py init`, `lease_keys.py` | no |
| `recovery.cert_sha256`, `signer_pub`, `bucket`, `object_prefix`, `oci_profile`, `key_provider=interactive_person`, `private_key_file` **fuera del repositorio** | certificado C-04, clave pública de firma, bucket de OCI, clave en ruta absoluta 0600 | existentes; **mover/copiar la clave fuera de `work/`** (la validación rechaza rutas dentro del repo) | parcial |
| `dns.allowed_domains` solo `nexoeventos-test`, `mode` | subdominio de pruebas + token | T2 | no |
| `detector.rounds ≥ 3`, `quorum ≥ 2` | — | valores por defecto | sí |

## 4. Conectividad necesaria (todo saliente salvo la entrada pública de OCI)
| Origen → destino | Puerto | Para qué | NSG/SG |
|---|---|---|---|
| Ejecutor (Mac de la propietaria) → OCI Object Storage (PAR y bucket) | 443 | lease, sello, respaldo | sin cambio |
| API de AWS y VM de OCI → OCI Object Storage (PAR) | 443 | renovar el lease (la API de AWS **debe poder salir** a OCI) | SG de salida ya abierta a 443 |
| Azure (sondas) → ALB de V2 y → VM de OCI | 443 | detección independiente | NSG de Azure: salida 80/443/53/123 ya permitida |
| Operador/centro → testigo | 443 | informes y retos | donde se aloje el testigo |
| Internet → VM de OCI | 443 | entrada pública del standby | **IGW + NSG nuevo**: solo T3 |
| Ejecutor → DuckDNS y resolvedores | 443/53 | cambio y verificación de DNS | — |
| Ejecutor → AWS (describe/stop) | 443 | estado y vallado fuerte | credenciales del laboratorio, temporales |

## 5. Permisos mínimos (resumen; detalle en `centro-operaciones-azure.md` §3)
- **OCI, perfil de lectura de respaldo:** `inspect/read objects` en `nexoeventos-recovery` (existente: `NEXOEVENTOS_UPLOADER` solo sube; la restauración usa la clave C-04 y un perfil de **lectura**: verificar cuál).
- **OCI, creación de PAR (solo T1/A1):** perfil administrativo (`DEFAULT`) usado **solo** por `oci_par_probe.py`/`oci_par_lab.py` para crear y revocar PAR; nunca se incorpora al orquestador.
- **AWS (lectura):** `ec2:DescribeInstances`, `rds:DescribeDBInstances`, `elasticloadbalancing:Describe*`, `autoscaling:Describe*`. **Escritura solo si `allow_stop_rds=true`:** `rds:StopDBInstance`. En Academy, usar el rol del laboratorio con credenciales temporales; no crear usuarios IAM.
- **Testigo:** opción GCP (Cloud Run + KMS + bucket con retención) **no está en el alcance aprobado de Google Cloud**. Alternativa propuesta para `automatic=false`: alojarlo en la VM de Azure (`WITNESS_STORE=file`, `WITNESS_SIGNER=local-ecdsa`), declarando que **no cumple** `independent_infrastructure_validated` (sin retención WORM): válido solo para la prueba controlada, no para failover automático. **Decisión D6 pendiente.**

## 6. Brechas (G) que quedan antes de T6 — ninguna se resuelve sin autorización específica
| # | Brecha | Tipo | Bloquea |
|---|---|---|---|
| G1 | Fábrica `build_real_adapters(cfg)` + ejecutor con barreras (sin escribir aún) | código | T6 |
| G2 | PAR del lease + claves Ed25519 + autoprueba real | Cloud OCI (T1) | T6 |
| G3 | Testigo desplegado (D6) y su prueba de humo | Cloud Azure | T6 |
| G4 | Sello en OCI con clave de operador | Cloud OCI | T6 |
| G5 | Compuerta `enforce` + vallado en la base en la API/RDS de AWS (B3/B4) | Cloud AWS | T6 |
| G6 | VM de OCI con entrada pública y TLS (T3) | Cloud OCI | T6 |
| G7 | Clave C-04 fuera del repositorio con 0600 | local | T6 |
| G8 | Cuota de cómputo de OCI y trial (D4) | verificación humana | T3/T6 |
| G9 | **`infra/oci` no tiene entrada pública**: sin Internet Gateway, subred pública ni IP pública (`assign_public_ip=false`, `prohibit_public_ip_on_vnic=true`). T3 necesita un módulo Terraform opcional nuevo (apagado por defecto: IGW, subred pública, NSG 443 + administración /32, IP pública) | código Terraform | T3, T6 |

## 7. Actualización del 22-nov (tarde): estado de las brechas
| # | Brecha | Estado ahora |
|---|---|---|
| G1 | Fábrica de adaptadores | **Interfaz, mapeo configuración→argumentos, rechazo de configuración insegura/proveedores ausentes y bloqueo del modo real: HECHO y probado (10 pruebas, proveedores simulados).** Faltan los proveedores REALES (contrato en `REAL_CONTRACT`), que se escriben y revisan después de T1–T4; `REAL_WIRING_ENABLED = False` |
| G2 | PAR del lease + autoprueba real | preparada: `oci_par_probe.py` endurecido (limpieza garantizada, reloj, plazo, manifiesto, `--cleanup-only`, tercera PAR con **carrera de adquisición real**) y `lease_race.py` con control negativo; falta ejecutarla (T1) |
| G3 | Testigo | **Evaluado: la VM de Azure puede alojarlo** con el perfil «archivo + ECDSA local» **solo para la conmutación controlada**. Demostrado en local: persistencia (kill -9), exclusividad (2 procesos), autenticación por token/alcance, TLS con certificado fijado, fallos (alterado, cola a medias, sin permiso de escritura). Se corrigieron dos carencias reales: el cliente no enviaba el token ni fijaba el certificado; el servicio cortaba la conexión ante errores de disco. **Límite:** un prefijo restaurado no se detecta localmente ⇒ no cumple `independent_infrastructure_validated`. Falta desplegarlo (T4) |
| G4 | Sello en OCI | pendiente (laboratorios F0/F1) |
| G5 | Compuerta `enforce` en AWS | **mayor de lo estimado:** no hay `WRITE_GATE_*` en ningún despliegue; se hará en sitio sobre V2 con el ASG congelado (`VENTANA-UNICA-AWS.md` §2) |
| G6 | VM de OCI con entrada pública y TLS | **código listo y probado en local** (módulo `public_entry`, `RECOVERY_TLS_SAN`, arranque en solo lectura); falta `apply` autorizado |
| G7 | Clave C-04 fuera del repositorio | pendiente (acción con tu autorización) |
| G8 | Cuota/trial de OCI | **leído:** E5 y E4 = 0 (probable fin del Free Trial); A1 = 2, Micro = 2 |
| G9 | Entrada pública en `infra/oci` | **HECHO en local** (apagado por defecto; fmt/validate/5 pruebas; verificador IaC actualizado) |
| G10 | **Nuevo:** arquitectura de la VM de OCI | solo hay RPM **x86_64** → E2.1.Micro (1 GB) o A1 (ARM, requiere RPM aarch64 y capacidad) |
