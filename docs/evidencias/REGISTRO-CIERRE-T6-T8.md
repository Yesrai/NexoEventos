# Registro único de cierre T6–T8

Estados posibles: PASS · FAIL · BLOCKED · NOT_TESTED. Un PASS «local» no equivale a uno real. Los intentos fallidos se conservan en sus expedientes originales (T1, T3 y T5) y no se reescriben aquí.

| Fecha UTC | Etapa | Objetivo | Cambios y archivos | Pruebas | Resultado | Evidencia | Riesgos y pendientes | Commit |
|---|---|---|---|---|---|---|---|---|
| 2026-11-23T03:50Z | Inventario | Localizar los 3 worktrees y sus cambios | ninguno (solo lectura). Ramas `entregable2-auditoria` (b4682c3 + T6 sin commitear), rama de trabajo de T7–T8 (5e6e79e + 14 archivos sin commitear), `nexoops` (0218fa2 + arreglo OTP sin commitear). Hay un proceso `nexoops serve --port 8088` activo de la usuaria: no se tocó | — | PASS | `git worktree list` | Los cambios OTP de `nexoops` están contenidos en rama de trabajo de T7–T8 (idénticos en `auth.py` y `app.py`) y se portaron sus pruebas de `test_auth.py` | — |
| 2026-11-23T03:55Z | T6 | Regresión previa | — | `pytest scripts/multicloud` | **PASS local**: 683 + 66 subtests, exit 0 (658 s) | salida de la sesión | La cifra «884» del reporte anterior incluía otras suites; aquí se registra la medida en esta sesión | — |
| 2026-11-23T03:58Z | T7 | Recuperar el trabajo de la rama T7–T8 | `nexoops/*` (acciones, asistente, integraciones, auth), `docs/t7-t8/*`, 4 pruebas nuevas + pruebas OTP de `nexoops` | `pytest nexoops` | **PASS local** 59/59 | rama de trabajo de T7–T8 | Grafana y Zabbix reales sin probar (VM apagada) | `040f116` (rama de trabajo de T7–T8) |
| 2026-11-23T04:05Z | T6 B-T6-1 | Anclaje anti-rollback del testigo | `backend/app/failover/anchor.py`, `scripts/multicloud/witness/witness_service.py`, `scripts/multicloud/tests/test_witness_anchor.py` | 19 casos + suites del testigo (73) | **PASS local** | `T6-20261123-estado-local.md` §1 | Real: requiere el bucket de OCI con retención (A2) → **BLOCKED** | ver fila de commit |
| 2026-11-23T04:20Z | T6 G5 | Ningún doble escritor; ninguna época nueva con el testigo retrocedido | `scripts/multicloud/tests/test_g5_single_writer_exhaustive.py` | 59 049 secuencias (longitud 5) + control negativo | **PASS local** | `T6-local/g5-exhaustivo-len5.txt` | D1, D2, D4, D5, D7 y D8 reales → **BLOCKED** | ver fila de commit |
| 2026-11-23T04:35Z | T7 | Subruta tras Nginx + artefactos de despliegue en Azure | `nexoops/{config,app}.py`, `static/app.js`, `tests/test_base_path.py`, `deploy/nexoops/*` | `pytest nexoops` 66/66; `bash -n` del instalador | **PASS local** | rama de trabajo de T7–T8 | Despliegue real → A1 | `c1c41d5` (rama de trabajo de T7–T8) |
| 2026-11-23T04:40Z | T6/T7 | Autorizaciones mínimas | `docs/evidencias/AUTORIZACIONES-T6-T7.md` | — | BLOCKED (a la espera de la usuaria) | tarjetas A1, A2 y A3 | A3 no se recomienda antes del plazo | — |
| 2026-11-23 | T8 | Entregables académicos | `docs/entrega-final/` | verificación de rutas | en curso | — | — | — |

## Estado por etapa
| Etapa | Estado | Nota |
|---|---|---|
| T1–T5 | **PASS** (real) | Sin cambios; evidencias intactas |
| T6 | **BLOCKED** | Barreras locales en PASS; failover real no ejecutado; RTO y RPO de failover no medidos |
| T7 | **PASS local / BLOCKED real** | Login real con OTP confirmado por la usuaria (local); el despliegue en Azure espera a A1 |
| T8 | en curso | La limpieza cloud final se verifica en la última ventana |
