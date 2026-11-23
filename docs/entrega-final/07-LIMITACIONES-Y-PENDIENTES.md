# 07 · Limitaciones y pendientes

**Clasificación:** **PASS** cumplido con expediente real · **FAIL** ejecutado y no cumplido (se conserva) · **BLOCKED** no se puede ejecutar sin autorización/nube o con barreras abiertas · **NOT_TESTED** no ejecutado · **LOCAL** probado solo en el equipo.

## 1. Estado por prueba e intento

| Prueba / intento | Estado | Causa o alcance | Fuente |
|---|---|---|---|
| T1 ejecución 1 | FAIL | `NameError` (import faltante); limpieza automática correcta | `docs/evidencias/T1-20261122-resultado.md` |
| T1 ejecución 2 | PASS 12/12 | lease real; no es failover | idem |
| T2 ejecución 1 | FAIL | Python sin almacén de CA; ningún DNS cambiado | `docs/evidencias/T2-20261122-resultado.md` |
| T2 ejecución 2 | PASS 13/13 | dominio de pruebas; no es failover | idem |
| T3 intento 1 | FAIL | `dnf` saturó la VM Micro; destruido sin residuos | `docs/evidencias/T3-20261122-intento1-resultado.md` |
| T3 intento 2 | FAIL 18/19 | OOM de `dnf-makecache` | `docs/evidencias/T3-20261122-intento2-resultado.md` |
| T3 intento 3 | PASS 19/19 | reconstrucción, no RTO de failover | `docs/evidencias/T3-20261122-intento3-resultado.md` |
| T4 | PASS 18/18 | testigo sin independencia validada | `docs/evidencias/T4-20261122-resultado.md` |
| T5 intento 1 (2 EC2) | FAIL 8/9 | disponibilidad 95,21 % < 99 % (límite del mecanismo) | `docs/evidencias/T5-20261123-intento1-resultado.md` |
| T5 intento 2 | BLOCKED (abortado) | SCP de Academy denegó máx 7 | `docs/evidencias/T5-20261123-intento2-abortado.md` |
| T5 intento 3 (6 EC2) | PASS 9/9 | una ejecución; parada controlada; solo lectura | `docs/evidencias/T5-20261123-resultado.md` |
| T6 failover AWS→OCI | **BLOCKED** | requiere autorización y nube; D1–D8 y B-T6-1 abiertos | `docs/evidencias/T6-BLOQUEOS-OBLIGATORIOS.md` |
| T6 — 12 criterios | NOT_TESTED | — | `ops_center/criterios/T6.json` |
| Anclaje anti-rollback, G5, proveedores, TLS G9 | LOCAL | no prueban nada en la nube | `docs/evidencias/T6-20261123-estado-local.md` |
| T7 NexoOps | LOCAL | login con OTP real por Gmail en local; despliegue A1 en Azure PARCIAL/INCOMPLETO (servicio deshabilitado; login OTP en Azure no demostrado; ver `docs/evidencias/A1-20261123-cierre.md`) | `docs/nexoops/README.md` |
| T7 — 4 criterios (flujo en Azure, nada ejecutado, capturas con URL y fecha, verify-audit) | NOT_TESTED | sin ventana autorizada en Azure | `ops_center/criterios/T7.json` |
| T8 — 5 criterios de cierre | NOT_TESTED | sesión final de verificación pendiente | `ops_center/criterios/T8.json` |
| Integraciones NexoOps con Grafana/Zabbix/AWS reales | NOT_TESTED | solo clientes simulados | `docs/t7-t8/MATRIZ-CUMPLIMIENTO.md` |
| Caída abrupta de instancia / escritura durante sustitución / fallo de zona | NOT_TESTED | fuera del alcance de T5 | T5 resultado |
| Carga ≥ 100 usuarios | NOT_TESTED (proyección) | máximo medido: 50 usuarios | `docs/entregable2/informe-entregable2.md` §11 |

## 2. Limitaciones técnicas declaradas

1. **Sin failover real AWS→OCI** ni RTO/RPO de failover.
2. **HA con una sola ejecución**: no hay estadística de repetición; no se declara SLA.
3. **Sin red privada entre nubes**: HTTPS 443 sobre Internet.
4. **IAM de AWS impuesto** (`LabRole`); el mínimo privilegio propio en AWS es diseño.
5. **Testigo con almacén en archivo local** en la VM de Azure (B-T6-1): el anclaje externo solo existe en local; el testigo está sin inicializar y sin dueño.
6. **Respaldo puntual**, no continuo; el ciclo periódico solo está probado en local.
7. **Costos estimados**, sin facturación.
8. **Expedientes completos** en `work/evidencias/` fuera de Git; se citan por su informe versionado y su hash.
9. **Latencia del lease** medida desde el Mac de la operadora (red doméstica), no desde AWS/OCI.
10. **Token de DuckDNS** con alcance de cuenta.
11. Estado de Terraform de `aws-v2` desfasado tras eliminar el ALB por API (documentado).
12. Plazo de AWS Academy (≈ 26-nov-2026): al expirar se pierden S3, instantáneas, AMI y secretos de AWS.

## 3. Pendientes priorizados

| # | Pendiente | Requiere nube | Impacto en rúbrica |
|---|---|---|---|
| 1 | T6 completo (o declararlo pendiente con causa en la defensa) | sí, con autorización | criterios 9 y 10 |
| 2 | Cierre T8: inventario final, revocación de tokens, paquete cifrado nuevo | sí (lectura) | 5, 13 |
| 3 | Desplegar NexoOps en Azure y capturas con URL y UTC (T7) | sí | 7 |
| 4 | Capturas de saldo/costo | sí (consola) | 11 |
| 5 | Regenerar token de DuckDNS | sí | 5 |
| 6 | Ensayo de la exposición y demo local | no | 14 |
