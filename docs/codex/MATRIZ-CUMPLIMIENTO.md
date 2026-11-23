# Matriz de cumplimiento T1–T8

Fecha de corte: 2026-11-23 UTC. Esta matriz cita exclusivamente resultados versionados; no sustituye los manifiestos de los expedientes originales.

| Etapa | Criterios | Estado | Evidencia principal | Alcance y límite |
|---|---:|---|---|---|
| T1 | 12/12 | **PASS** | `docs/evidencias/T1-20261122-resultado.md` | CAS y lease OCI reales, 0 residuos. No demuestra failover. |
| T2 | 13/13 | **PASS** | `docs/evidencias/T2-20261122-resultado.md` | Cambio y reversión en `nexoeventos-test`; no se tocó producción. No demuestra failover. |
| T3 | 19/19 | **PASS** | `docs/evidencias/T3-20261122-intento3-resultado.md` | Recuperación OCI y humo funcional. Los tiempos son reconstrucción, no RTO AWS→OCI. |
| T4 | 18/18 | **PASS** | `docs/evidencias/T4-20261122-resultado.md` | Observabilidad real desde Azure; VM terminó desasignada. La independencia externa del testigo no quedó validada. |
| T5 | 9/9 | **PASS** | `docs/evidencias/T5-20261123-resultado.md` | Una ejecución con seis instancias: 99,49 %, detección 9,6 s, recuperación 125 s. No prueba caída abrupta ni escritura durante sustitución. |
| T6 | 0/12 verificados en ejecución real | **PENDIENTE / BLOCKED** | `ops_center/criterios/T6.json`; `docs/evidencias/PLAN-PRUEBAS-OBLIGATORIAS-CLOUD.md` | No hay failover AWS→OCI autorizado y ejecutado. No se declaran RTO/RPO ni pérdida cero. |
| T7 | 0/4 con expediente cloud final | **EN IMPLEMENTACIÓN LOCAL** | `ops_center/criterios/T7.json`; `nexoops/`; `docs/nexoops/README.md` | NexoOps implementa flujo, auditoría y bloqueo de ejecución; faltan integración operativa autorizada en Azure y capturas fechadas. |
| T8 | 0/5 verificados en una sesión final | **PENDIENTE** | `ops_center/criterios/T8.json` | Hay estados finales parciales en T1–T5, pero la revocación final de tokens y el paquete cifrado nuevo deben verificarse en cierre. |

## Cobertura de T7

| Criterio T7 | Estado actual | Evidencia/acción requerida |
|---|---|---|
| Solicitar → validar → aprobar → registrar | **PARCIAL** | El centro T4 probó roles y denegaciones; NexoOps registra solicitudes bloqueadas. Falta expediente único del flujo completo sin autoaprobación. |
| Nada ejecutado por el centro | **IMPLEMENTADO, pendiente de evidencia final** | `REAL_EXECUTION_WIRED=False`; endpoints de failover/failback bloqueados. Añadir test de lista blanca y captura de auditoría. |
| Capturas con fecha y URL | **NOT_TESTED** | Capturar en navegador durante ventana autorizada, con URL y UTC visibles; no fabricar capturas. |
| Auditoría íntegra | **IMPLEMENTADO / PROBADO LOCALMENTE** | Pruebas y cadena `ops_center.audit`; repetir `verify-audit` en el expediente T7 real. |

## Criterio de cierre

T7 solo pasa cuando sus cuatro criterios figuren en un expediente reproducible. T8 solo pasa después de verificar limpieza, revocaciones y copia cifrada nueva. Un test con clientes simulados se rotula **local**, no **real**.

