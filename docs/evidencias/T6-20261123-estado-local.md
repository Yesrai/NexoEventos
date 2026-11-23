# T6 — Estado al 2026-11-23 (cierre local) · Resultado global: **BLOCKED**

El failover real AWS→OCI **no se ha ejecutado**. No hay RTO ni RPO de failover medidos, y no se suman los tiempos de operaciones sueltas para presentarlos como RTO. Este expediente recoge solo lo que se ha demostrado **en local**, con componentes reales del código (no con un simulador de alto nivel), y lo que sigue bloqueado.

Barreras de software que siguen cerradas: `REAL_EXECUTION_WIRED=False` y `REAL_WIRING_ENABLED=False` (sin cambios).

## 1. Trabajo cerrado en local

| Id | Capacidad | Implementación | Prueba | Resultado | Clase |
|---|---|---|---|---|---|
| B-T6-1 | Anclaje anti-rollback del historial del testigo | `backend/app/failover/anchor.py` (`AnchoredAppendStore`, `FileAnchorBucket`, `SimAnchorBucket`, `OciParAnchorBucket`); integrado en `scripts/multicloud/witness/witness_service.py` (`WITNESS_ANCHOR`, `WITNESS_REQUIRE_ANCHOR`) | `scripts/multicloud/tests/test_witness_anchor.py` (19 casos) | **PASS local** 19/19 | local |
| G5-modelo | Nunca dos escritores, y ninguna época nueva con el testigo caído o retrocedido | `LeaseClient` real con firmas Ed25519 + `InMemoryStore` condicional + `WitnessGuard` + testigo anclado | `scripts/multicloud/tests/test_g5_single_writer_exhaustive.py`: todas las secuencias de 5 eventos sobre 9 acciones (59 049), más un control negativo | **PASS local**: 0 violaciones; el control negativo **sí** detecta el fallo ([salida](T6-local/g5-exhaustivo-len5.txt)) | local |
| G1 | Once proveedores reales cableados | `scripts/multicloud/failover/real_providers.py` | `scripts/multicloud/tests/test_real_providers.py` | PASS local; **sin ejecutar contra las API reales** | local |
| G9 | TLS de las sondas con certificado fijado y `verify_as` | `scripts/multicloud/failover/adapters_probes.py` | `scripts/multicloud/tests/test_tls_policy_probes.py` | PASS local; **sin probar contra los servicios reales** | local |
| Regresión | Toda la suite `scripts/multicloud` | — | `pytest scripts/multicloud` | ver §4 | local |

### Garantías del anclaje (B-T6-1)
- Cada entrada del historial se replica en un objeto **propio** `anchor/<seq>`, firmado por el testigo, encadenado por hash y creado con la precondición «no existe». No es una copia del hash en un objeto que se pueda sobrescribir.
- Primero se escribe el primario y después el anclaje. Por eso el anclaje solo puede ir por delante del primario si el primario retrocedió:
  - primario **<** anclaje ⇒ `RollbackDetected`: no arranca, no atesta y no acepta informes hasta que el operador ejecuta `recover_primary` con su frase de confirmación;
  - primario **>** anclaje ⇒ fallo parcial: completa el anclaje (idempotente) **antes** de servir nada; si el anclaje no responde, devuelve 503 (falla cerrado);
  - un prefijo distinto se trata como bifurcación. Un objeto ilegible, con firma inválida, fuera de secuencia o con un hueco se trata como corrupción. Un anclaje vacío con historial se trata como `AnchorLost`, y solo se re-ancla con `bootstrap` explícito.
- Casos probados: restauración de prefijos antiguos (incluido el primario vacío), reutilización de épocas, concurrencia (4 instancias y 8 hilos, cadena íntegra), reinicios, duplicados idempotentes, bifurcación, corrupción (4 variantes), entrada intermedia borrada, error de red al leer y al escribir, respuesta perdida tras aplicar, génesis en vuelo, pérdida del anclaje y recuperación explícita.
- **Límite:** la garantía anti-rollback **real** exige un bucket con retención **bloqueada** y una credencial sin permiso de borrar ni de sobrescribir. `FileAnchorBucket` y `SimAnchorBucket` no lo son. `OciParAnchorBucket` está escrito, pero **no se ha validado contra OCI** (hace falta crear un bucket o una PAR, lo que requiere autorización).

## 2. Matriz D1–D8 (barreras contra el doble escritor en nube)

| # | Barrera | Evidencia local | Prueba real exigida | Estado |
|---|---|---|---|---|
| D1 | Compuerta y vallado en RDS/AWS real | `gate.py`, `pg_fence.py`, `test_two_db_*`, modelo G5 | 0 respuestas 201 de AWS tras perder la autoridad | **BLOCKED** (nube, autorización) |
| D2 | Sello WORM en OCI real | `seal_log.py`, `test_oci_seal_f1.py` | rechazo real de un sello retrocedido | **BLOCKED** |
| D3 | Lease entre nubes con ambos actores | T1 real (PAR, exclusividad); modelo G5 | ciclo completo con AWS y OCI | **parcial** (T1 PASS) |
| D4 | Standby de OCI con compuerta en `enforce` | `adapters_standby.py`, `pg_standby.py` | OCI no escribe sin el lease | **BLOCKED** |
| D5 | Clientes con DNS en caché | verificación por efecto diseñada | 0 respuestas 201 desde AWS tras la toma | **BLOCKED** |
| D6 | Pausas de VM y deriva de reloj reales | `test_two_db_pauses.py` (local) | medición con el lease real | **NOT_TESTED** |
| D7 | Cancelación y aborto limpios reales (T6.0 dry-run) | `test_failover_orchestrator.py` | simulacros con adaptadores reales en `dry_run` | **BLOCKED** |
| D8 | Failback manual con vallado de OCI primero | `failback.py`, `test_failback.py` | ejecución medida | **BLOCKED** |
| B-T6-1 | Anclaje del testigo | §1 (PASS local) | anclaje en bucket OCI con retención + caso real de rollback detectado | **BLOCKED** (bucket o PAR, autorización) |

## 3. Respaldo fresco (RPO ≤ 90 min): procedimiento preparado, **no ejecutado**
1. Congelar las escrituras: la compuerta de AWS en modo `enforce` sin lease (rechaza mutaciones con 503).
2. Validar las operaciones en curso: no queda ninguna transacción abierta (`pg_stat_activity`) y el contador de 201 está estable.
3. Respaldo final: `scripts/multicloud/backup_cycle.py` (cifrado CMS con dos claves independientes).
4. Verificar el cifrado y la integridad: SHA-256 del objeto y `c04_verify.py`.
5. Restaurar en OCI: la misma ruta que T3 (PASS 19/19).
6. Verificar los datos: huella `fingerprint.sql` y `compare-fingerprint.py`; las reservas confirmadas deben ser idénticas.
7. Definición oficial (`ops_center/criterios/T6.json`, la única válida): **RPO** = edad del respaldo usado (umbral 5400 s); **RTO** = desde la inyección del fallo hasta que el nuevo escritor está verificado (umbral 3600 s). Como dato complementario se registra la ventana de congelación (última escritura confirmada → congelación) en UTC.

## 4. Regresión
- Antes de los cambios de esta sesión: `pytest scripts/multicloud` → 683 pruebas aprobadas y 66 subtests, exit 0 (658 s).
- Después de los cambios: `scripts/multicloud` 704 aprobadas + 66 subtests, exit 0; `backend/tests` 343 aprobadas, exit 0 ([salida](T6-local/regresion-final.txt)).

## 5. Criterios T6 (`ops_center/criterios/T6.json`)
Los 12 criterios quedan en **NOT_TESTED / BLOCKED**: ninguno se puede evaluar sin la ejecución real. No se declara PASS.
