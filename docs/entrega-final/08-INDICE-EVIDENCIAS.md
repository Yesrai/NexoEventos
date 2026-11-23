# 08 · Índice de evidencias T1–T7

Rutas relativas a la raíz del repositorio `NexoEventos/` salvo las que empiezan por `NexoEventos-codex-t7-t8/` (worktree hermano, rama `codex/t7-t8`). **Cada ruta fue comprobada con `ls` al generar este índice** (ver `README.md`, sección «Verificación»). Los expedientes completos (`work/evidencias/<T>-<UTC>-<id>/`, con manifiesto SHA-256) no están en Git; el informe versionado cita su ruta y el hash de `resultado.json`.

## T1 — Lease y CAS en OCI (PASS 12/12, real)

| ID | Ruta | Contenido |
|---|---|---|
| EV-T1-01 | `docs/evidencias/T1-20261122-resultado.md` | ejecución 1 FAIL (`NameError`) + ejecución 2 PASS; expedientes `work/evidencias/T1-20261122T070354Z-f59a/` y `…T070851Z-9aa1/` |
| EV-T1-02 | `ops_center/criterios/T1.json` | criterios escritos antes |

## T2 — DNS A→B→A (PASS 13/13, real)

| ID | Ruta | Contenido |
|---|---|---|
| EV-T2-01 | `docs/evidencias/T2-20261122-resultado.md` | FAIL por CA + corrección TLS + PASS; carrera del testigo encontrada y corregida |
| EV-T2-02 | `docs/evidencias/T2-TARJETA-AUTORIZACION.md` | tarjeta de autorización |
| EV-T2-03 | `backend/app/failover/tlsctx.py` | contexto TLS verificado (corrección) |
| EV-T2-04 | `ops_center/criterios/T2.json` | criterios |

## T3 — Reconstrucción en OCI (FAIL, FAIL, PASS 19/19, real)

| ID | Ruta | Contenido |
|---|---|---|
| EV-T3-01 | `docs/evidencias/T3-20261122-intento1-resultado.md` | FAIL: dnf; destruido sin residuos |
| EV-T3-02 | `docs/evidencias/T3-20261122-intento2-resultado.md` | FAIL 18/19: OOM `dnf-makecache` |
| EV-T3-03 | `docs/evidencias/T3-20261122-intento3-resultado.md` | PASS 19/19 |
| EV-T3-04 | `docs/evidencias/T3-TARJETA-AUTORIZACION.md`, `docs/evidencias/T3-INTENTO3-AUTORIZACION.md` | autorizaciones |
| EV-T3-05 | `ops_center/criterios/T3.json` | criterios |

## T4 — Centro de observación en Azure (PASS 18/18, real)

| ID | Ruta | Contenido |
|---|---|---|
| EV-T4-01 | `docs/evidencias/T4-20261122-resultado.md` | sondas, alerta y correo, panel, testigo, Grafana/Zabbix, estado final |
| EV-T4-02 | `docs/evidencias/T4-TARJETA-AUTORIZACION.md` | autorización |
| EV-T4-03 | `ops_center/criterios/T4.json` | criterios |

## T5 — Alta disponibilidad AWS (FAIL, abortado, PASS 9/9, real)

| ID | Ruta | Contenido |
|---|---|---|
| EV-T5-01 | `docs/evidencias/T5-20261123-intento1-resultado.md` | FAIL 8/9 (95,21 %) con 2 EC2 |
| EV-T5-02 | `docs/evidencias/T5-ANALISIS-Y-PROPUESTA-2-INTENTO.md` | análisis y propuesta de la variante C |
| EV-T5-03 | `docs/evidencias/T5-TARJETA-AUTORIZACION.md`, `docs/evidencias/T5-TARJETA-2-INTENTO.md` | autorizaciones |
| EV-T5-04 | `docs/evidencias/T5-20261123-intento2-abortado.md` | abortado por SCP |
| EV-T5-05 | `docs/evidencias/T5-20261123-resultado.md` | PASS 9/9 (99,49 %), modos económico/alta disponibilidad |
| EV-T5-06 | `ops_center/criterios/T5.json` | criterios |

## T6 — Failover AWS→OCI (BLOCKED; capacidades LOCALES)

| ID | Ruta | Contenido | Rótulo |
|---|---|---|---|
| EV-T6-01 | `docs/evidencias/T6-BLOQUEOS-OBLIGATORIOS.md` | B-T6-1 y D1–D8 | — |
| EV-T6-02 | `docs/evidencias/T6-PREPARACION-SOLO-LECTURA.md` | barreras, G1–G9, RTO/RPO, ruta crítica | lectura |
| EV-T6-03 | `ops_center/criterios/T6.json` | 12 criterios | — |
| EV-T6-04 | `backend/app/failover/anchor.py` | anclaje anti-rollback del testigo | LOCAL |
| EV-T6-05 | `scripts/multicloud/tests/test_witness_anchor.py` | 19 pruebas (19 passed, re-ejecutadas el 23-nov) | LOCAL |
| EV-T6-06 | `scripts/multicloud/tests/test_g5_single_writer_exhaustive.py` | exploración exhaustiva G5 (9^5 = 59.049) | LOCAL |
| EV-T6-07 | `docs/evidencias/T6-local/g5-exhaustivo-len5.txt` | salida de la ejecución con longitud 5 | LOCAL |
| EV-T6-08 | `scripts/multicloud/failover/real_providers.py` | proveedores reales cableados, no ejecutados | LOCAL |
| EV-T6-09 | `scripts/multicloud/failover/real_factory.py`, `ops_center/barriers.py` | `REAL_WIRING_ENABLED=False`, `REAL_EXECUTION_WIRED=False` | LOCAL |
| EV-T6-10 | `scripts/multicloud/failover/orchestrator.py` | etapas del orquestador | LOCAL |
| EV-T6-11 | `docs/evidencias/T6-20261123-estado-local.md` | estado local consolidado (escrito por el frente T6) | LOCAL — **ver nota** |

| EV-T6-12 | `docs/evidencias/T6-local/regresion-final.txt` | regresión: `scripts/multicloud` 704 passed + 66 subtests, `backend/tests` 343 passed, exit 0 | LOCAL |
| EV-T6-13 | `scripts/multicloud/tests/test_real_providers.py`, `scripts/multicloud/failover/adapters_probes.py`, `scripts/multicloud/tests/test_tls_policy_probes.py` | G1 y G9 | LOCAL |

> **Nota EV-T6-11:** el archivo apareció mientras se generaba este paquete (escrito por el frente T6, 23-nov 04:19Z). Su contenido es coherente con este índice; ver en `README.md` las diferencias de definición de RTO/RPO detectadas.

## T7 — NexoOps (LOCAL)

| ID | Ruta | Contenido |
|---|---|---|
| EV-T7-01 | `NexoEventos-codex-t7-t8/nexoops/` | código (rama `codex/t7-t8`, commit `040f116`) |
| EV-T7-02 | `NexoEventos-codex-t7-t8/nexoops/tests/` | pruebas: 59 en `040f116`; 66 passed el 23-nov en la copia de trabajo (con cambios sin confirmar) |
| EV-T7-03 | `NexoEventos-codex-t7-t8/docs/nexoops/README.md`, `NexoEventos-codex-t7-t8/docs/nexoops/INTEGRACIONES.md` | arquitectura, seguridad, inventario honesto |
| EV-T7-04 | `NexoEventos-codex-t7-t8/docs/codex/MATRIZ-CUMPLIMIENTO.md`, `NexoEventos-codex-t7-t8/docs/codex/INFORME-TECNICO-T7-T8.md`, `NexoEventos-codex-t7-t8/docs/codex/ARQUITECTURA-T7.md`, `NexoEventos-codex-t7-t8/docs/codex/DECISIONES-T7-T8.md`, `NexoEventos-codex-t7-t8/docs/codex/T7-T8-REGISTRO.md` | documentación T7–T8 de Codex |
| EV-T7-05 | `ops_center/criterios/T7.json`, `ops_center/criterios/T8.json` | criterios T7 y T8 |
| EV-T7-06 | (sin archivo) | login real con OTP recibido por Gmail y acceso al Overview con `SUPER_ADMIN_TI`, **en local**, confirmado por la propietaria; no hay captura versionada |

## Histórico (Entregables 2 y 3)

| Ruta | Contenido |
|---|---|
| `docs/entregable2/informe-entregable2.md` | informe E2 (seguridad, redes, HA, costos) |
| `docs/entregable2/diagramas/` | V1, V2 y multicloud (SVG/PNG) |
| `docs/entregable2/presentacion/NexoEventos-Entregable2.pptx` | estilo visual reutilizado |
| `docs/entregable3/14-matriz-cumplimiento-y-plan-minimo.md`, `docs/entregable3/15-informe-consolidado-entregable3.md` | matriz e informe E3 |
| `docs/entregable3/diagramas/` | capas, flujo de respaldo, redes |
| `docs/evidencias/MATRIZ-CIERRE-CLOUD.md` | matriz de cierre cloud |
| `docs/evidencias/escalado-v2-20261022/`, `docs/evidencias/20261104-b2-autohealing-v2/`, `docs/evidencias/multicloud/aws/20261023-rds-multiaz/`, `docs/evidencias/EV07/`, `docs/evidencias/c04-20261119/`, `docs/evidencias/multicloud/oci/20261023-recuperacion-aplicacion/`, `docs/evidencias/20261122-copia-externa-respaldo/` | HA, failover RDS, PITR, restauración local, recuperación OCI del 23-oct, paquete cifrado |
| `docs/evidencias/capturas/INDICE.md` | capturas auténticas (redactadas) |
| `PROJECT_STATUS.md` | estado del proyecto y pruebas funcionales |
