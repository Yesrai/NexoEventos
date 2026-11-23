# Registro de decisiones T7–T8

| ID | Decisión | Razón | Consecuencia |
|---|---|---|---|
| D-T7-01 | Reutilizar NexoOps y `ops_center`; no crear V3. | Ya existen autenticación, auditoría, adaptadores y UI. | Menor riesgo y trazabilidad con T1–T5. |
| D-T7-02 | Integraciones Grafana/Zabbix exclusivamente de solo lectura. | T7 no autoriza modificar monitoreo ni nube. | Tokens Viewer/Usuario; llamadas limitadas; errores explícitos. |
| D-T7-03 | No habilitar failover/failback desde NexoOps. | T6 está pendiente y las barreras deben fallar cerrado. | `REAL_EXECUTION_WIRED=False`; acciones bloqueadas y auditadas. |
| D-T7-04 | Mantener “NexoOps AI” como motor determinista. | No hay modelo generativo conectado. | La interfaz debe declarar reglas, hechos, hipótesis y recomendaciones; no llamarlo IA generativa. |
| D-T7-05 | Toda métrica muestra fuente, hora UTC y frescura. | Evita convertir datos obsoletos o simulados en hechos actuales. | Estados `no_verificado`, `unavailable` y `stale` visibles. |
| D-T8-01 | Conservar todos los intentos fallidos. | Son parte de la evidencia de corrección y aprendizaje. | El informe cita FAIL→corrección→PASS, no solo el resultado final. |
| D-T8-02 | Separar costo facturado de estimación. | Los expedientes no contienen facturas consolidadas. | USD 0,50 se rotula suma estimada de ventanas, no gasto real. |
| D-T8-03 | T6 permanece pendiente. | No existe expediente real aprobado de failover AWS→OCI. | No se declaran RTO/RPO ni pérdida cero de failover completo. |
| D-T8-04 | T8 requiere verificación final independiente. | Estados de cierre T1–T5 no sustituyen limpieza y revocación finales. | T8 queda pendiente hasta ejecutar sus 5 criterios. |

