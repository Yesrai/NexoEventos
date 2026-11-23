# Auditoría de fallos seguros, cancelaciones y prevención de doble escritor — 22-nov-2026

Alcance: lo que las pruebas **locales/simuladas** ya demuestran y lo que **no** pueden demostrar. Nada se ejecutó en la nube. Registros: `work/pruebas/` (logs locales, no versionados).

## 1. Resultado de la ejecución de hoy (local)
| Batería | Entorno | Resultado |
|---|---|---|
| Backend completo (`scripts/ops/pruebas-backend-aislado.sh`) | PostgreSQL 18.7 desechable, socket privado, eliminado al terminar | **331 pasan, 0 fallan** (77,7 s) |
| Failover y seguridad: `scripts/multicloud/tests` + `test_lease*`, `test_db_fence`, `test_seal*`, `test_rollback_attack`, `test_enforce_readiness`, `test_external_writers` | pytest con clústeres PostgreSQL temporales propios | **589 pasan** · 30 fallan **por contaminación del entorno al mezclar suites en un solo proceso** (`test_write_gate*.py` necesita la base de la aplicación) |
| Esos 30 + `test_lease`, `test_db_fence`, `test_seal`, `test_enforce_readiness` en el entorno aislado correcto | PostgreSQL desechable | **107 pasan, 0 fallan** |
| `ops_center` | local y desde el paquete extraído | **37 pasan** |
Conclusión honesta: no hay fallos del producto, pero **la batería de failover no debe ejecutarse mezclada con las pruebas del backend en un solo proceso** (el CI ya las separa). Corregido también un defecto del script nuevo: PostgreSQL 18 en macOS exige `LC_ALL` válido.

## 2. Qué garantías están cubiertas y dónde (todas en simulación o con bases locales reales)
| Garantía | Prueba |
|---|---|
| Nunca dos escritores aunque haya cancelaciones, caídas y flapping | `test_failover_orchestrator`: 400 escenarios aleatorios (cancelación + caídas), 30 semillas de flapping |
| Cancelar en **cada** frontera deja ≤ 1 escritor; cancelar durante la espera del lease | `test_cancelar_en_cada_frontera…`, `test_cancelar_durante_la_espera_del_lease` |
| Una ejecución abortada **no se reanuda** con el mismo `run_id`; idempotencia | `test_una_ejecucion_abortada_no_se_reanuda…` |
| DNS solo tras datos verificados + lease + standby listo | invariante I2 y 400 escenarios (sin DNS prematuro) |
| Ante datos ambiguos no se promueve; primario de estado desconocido bloquea | I3, I6, `test_failover_detector_evidence` |
| Standby no listo ⇒ se libera el lease y el registro vuelve a `NONE` (aborto limpio) | I7, `test_failover_e2e` (83) |
| El escritor anterior no puede confirmar tras perder autoridad (vallado en la base) | `test_two_db_*` (pausas, hard fence, tamper, reinicio tras promoción, rollback, sello) con **dos PostgreSQL reales locales** |
| Lease no falsificable ni retrocedible | `test_lease_tampering` (19), `test_rollback_attack`, `test_witness_*` |
| DNS incierto o rechazado ⇒ ninguna ejecución automática vuelve a promover | `test_dns_switch`, `adapters_dns`, `test_failover_e2e` |
| Failback nunca automático | `test_failback` |

## 3. Supuestos que las propias pruebas declaran (controles negativos)
- `test_control_negativo_una_pausa_mayor_que_el_presupuesto_SI_produce_doble_escritura`: **si un proceso se congela más tiempo que el presupuesto de pausa, la garantía se rompe.** Es un supuesto de diseño, no un defecto oculto: en la nube real hay que medirlo (pausas de VM, reloj).
- `test_control_negativo_un_cliente_que_se_fia_del_contenido_SI_permite_doble_escritura`: un cliente que confíe en el contenido del lease sin verificar firma/ETag permite doble escritura; por eso la firma Ed25519 es obligatoria.
- El PAR permite sobrescribir **sin condición** (límite que T1 registrará): el lease se protege con su firma, no con el PAR.

## 4. Lo que NO se puede demostrar en local (y T-pruebas deben cubrir)
| # | Riesgo real | Cómo se cubre | Etapa |
|---|---|---|---|
| R1 | Latencia/atomicidad real de Object Storage bajo contención | `oci_par_probe` (20 rondas × 8; latencia p95 medida) | T1 |
| R2 | Propagación real de DNS y estados de fallo reales de DuckDNS | `dns_switch` con rollback | T2 |
| R3 | Vallado fuerte en una **RDS real** (`validated_on_real_rds=false`) | plan híbrido B3/C1–C4 (base de laboratorio dentro de la RDS) | previo a T6 |
| R4 | Sello antirretroceso (WORM) en OCI real | laboratorios F0/F1 | previo a T6 |
| R5 | Testigo independiente desplegado (D6) | despliegue y prueba de humo | previo a T6 |
| R6 | Clientes con DNS en caché que siguen escribiendo en AWS | verificación **por efecto**: 0 respuestas 201 de AWS tras la toma | T6 |
| R7 | Pausas de VM / deriva de reloj reales | medir con el lease real y registrar en T1/T6 | T1/T6 |
| R8 | Cancelación durante un cambio de DNS real (estado incierto) | ledger `UNCERTAIN_DNS` observado en T2 | T2 |
| R9 | Failback manual real | procedimiento y vallado del escritor de OCI primero | T6 (cierre) |

## 5. Cambios para que T6 **contemple** fallos seguros y cancelación (ya reflejados en `ops_center/criterios/T6.json`)
1. **T6.0 — ensayo en seco** con adaptadores reales en `dry_run=True` (solo lectura): valida sondas, precheck y lease **sin habilitar nada ni cambiar DNS**.
2. **Simulacro de cancelación real:** cancelar tras adquirir el lease y antes de `ENABLE_STANDBY`; verificar lease liberado, registro en `NONE` y AWS como único escritor.
3. **Simulacro de aborto limpio:** con el standby deliberadamente no listo, `HEALTH_GATE` debe abortar sin tocar el DNS.
4. **Botón de parada:** `ops_center kill-switch on` (B01) bloquea nuevas solicitudes; la cancelación del orquestador usa `cancel_check`.
5. Solo después, el failover real con medición de RTO/RPO y verificación por efecto.
