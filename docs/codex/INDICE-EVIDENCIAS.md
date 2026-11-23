# Índice de evidencias T1–T8

## Expedientes principales versionados

| ID | Etapa | Archivo | Resultado verificable |
|---|---|---|---|
| EV-T1-01 | T1 | `docs/evidencias/T1-20261122-resultado.md` | Primera ejecución FAIL y segunda PASS 12/12; limpieza e inventario intacto. |
| EV-T2-01 | T2 | `docs/evidencias/T2-20261122-resultado.md` | FAIL TLS conservado, corrección y PASS 13/13; A→B→A en dominio de prueba. |
| EV-T3-01 | T3 | `docs/evidencias/T3-20261122-intento1-resultado.md` | Intento fallido conservado. |
| EV-T3-02 | T3 | `docs/evidencias/T3-20261122-intento2-resultado.md` | 18/19; fallo OOM conservado. |
| EV-T3-03 | T3 | `docs/evidencias/T3-20261122-intento3-resultado.md` | PASS 19/19; recuperación OCI, funcionalidad y destrucción. |
| EV-T4-01 | T4 | `docs/evidencias/T4-20261122-resultado.md` | PASS 18/18; sondas, Grafana/Zabbix, alerta/correo y cierre Azure. |
| EV-T5-01 | T5 | `docs/evidencias/T5-20261123-intento1-resultado.md` | FAIL de disponibilidad con dos instancias. |
| EV-T5-02 | T5 | `docs/evidencias/T5-20261123-intento2-abortado.md` | Intento abortado por SCP. |
| EV-T5-03 | T5 | `docs/evidencias/T5-20261123-resultado.md` | PASS 9/9 con seis instancias y límites explícitos. |

## Diseño, seguridad y operación

| Tema | Fuente versionada |
|---|---|
| Criterios ejecutables | `ops_center/criterios/T1.json` … `T8.json` |
| Plan de pruebas cloud y barreras | `docs/evidencias/PLAN-PRUEBAS-OBLIGATORIAS-CLOUD.md` |
| Matriz histórica de cierre | `docs/evidencias/MATRIZ-CIERRE-CLOUD.md` |
| Arquitectura y costos multicloud | `docs/multicloud/README.md`, `docs/multicloud/03-costos-y-riesgos.md` |
| Informe académico previo | `docs/entregable2/informe-entregable2.md` |
| NexoOps e integraciones | `docs/nexoops/README.md`, `docs/nexoops/INTEGRACIONES.md` |
| Código NexoOps | `nexoops/` |
| Pruebas NexoOps | `nexoops/tests/` |

## Evidencias pendientes de T7/T8

1. Resultado de la suite final de NexoOps en la rama Codex, distinguiendo clientes simulados de servicios reales.
2. `check-integrations` contra Grafana/Zabbix de Azure con credenciales de solo lectura, en una ventana autorizada.
3. Capturas de T7 con fecha UTC y barra de URL.
4. Expediente de flujo de solicitud/aprobación/registro y `verify-audit` íntegro.
5. Verificación T8 de AWS/OCI/Azure, revocación de tokens temporales y nueva copia cifrada reverificada.

No se incluyen contraseñas, OTP, tokens, IP privadas ni URL PAR. Los expedientes no versionados de `work/evidencias/` deben custodiarse con su manifiesto SHA-256, no copiarse sin saneamiento.

