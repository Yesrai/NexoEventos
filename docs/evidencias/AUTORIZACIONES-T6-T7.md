# Autorizaciones imprescindibles (T6 y T7): ninguna concedida todavía

Solo se piden las mínimas para convertir en **real** lo ya probado en local. Cada tarjeta se ejecuta por separado, de una en una (nunca dos cambios cloud a la vez), con una frase de autorización literal.

---
## A1 · T7: desplegar NexoOps en la VM de Azure existente
| Campo | Detalle |
|---|---|
| Acción | Encender la VM de Azure (hoy desasignada), instalar NexoOps detrás del Nginx HTTPS existente en `/nexoops/` (`deploy/nexoops/` de la rama de trabajo de T7–T8), comprobar las integraciones reales de Grafana y Zabbix (tokens Viewer o de solo lectura creados por la usuaria en la VM), sacar capturas con URL y fecha, y volver a desasignar la VM |
| Recursos afectados | La VM de T4 (arranque y parada), Nginx (un `location` nuevo) y systemd (`nexoops.service`). Sin puertos nuevos ni cambios de NSG, IAM o DNS |
| Costo máximo | ≤ USD 0,50 (ventana ≤ 90 min; T4 costó ≈ USD 0,21 en 55 min) |
| Riesgos | `nginx -t` falla (mitigación: no se recarga Nginx); la VM queda encendida (mitigación: apagado programado igual que en T4); exposición de tokens (mitigación: archivo 0640 en la VM, nunca por chat) |
| Reversión | `systemctl disable --now nexoops`; restaurar `/etc/nginx` desde `/var/backups/nexoops-<UTC>`; recargar Nginx; desasignar la VM |
| Criterios de aceptación | `/nexoops/healthz` 200 por HTTPS con certificado válido; login real con OTP por Gmail y rol `SUPER_ADMIN_TI`; Grafana muestra dashboards y paneles reales; Zabbix muestra hosts y problemas reales (o «No verificado» si el servicio está parado); `verify-audit` íntegro; el centro no ejecuta ninguna acción (criterios de T7) |
| Evidencia esperada | Capturas con barra de direcciones y UTC, salida de `check-integrations`, `verify-audit`, el diff de Nginx y el estado final de la VM |
| Limpieza | VM desasignada y verificada por API; servicio y configuración conservados para la demo, o retirados si la usuaria lo pide |
| Frase | `AUTORIZO A1 DESPLIEGUE NEXOOPS AZURE` |

---
## A2 · B-T6-1: anclaje del testigo en OCI (prueba real de rollback detectado)
| Campo | Detalle |
|---|---|
| Acción | Crear un bucket privado de OCI `nexo-witness-anchor` con una regla de retención de 1 día y una PAR de lectura y escritura de objetos limitada al prefijo `anchor/`, que caduca en 24 h. Ejecutar el testigo **en local** con `WITNESS_ANCHOR=oci-par:<archivo 0600>`, hacer informes, restaurar un prefijo antiguo del almacén primario y demostrar `RollbackDetected`. Intentar sobrescribir y borrar un `anchor/<seq>` (debe fallar por la retención) |
| Recursos afectados | 1 bucket y 1 PAR de OCI (Always Free) |
| Costo máximo | USD 0 (unos pocos KB en Object Storage) |
| Riesgos | La regla de retención **no se bloquea** (lock): un administrador podría quitarla. Por eso esta prueba demuestra la detección y la inmutabilidad durante la ventana, no un WORM permanente. Bloquearla sería irreversible y no se propone |
| Reversión | Borrar la PAR al terminar. El bucket se borra cuando vence la retención (1 día) |
| Criterios de aceptación | Rollback detectado y atestación rechazada (503) con un anclaje real; sobrescritura y borrado denegados por OCI; ningún objeto con la URL de la PAR en logs ni en el repositorio |
| Evidencia esperada | Salida de la prueba con UTC, respuestas HTTP de OCI (409/412/403), listado del bucket y borrado de la PAR verificado |
| Limpieza | PAR eliminada (verificada); bucket eliminado en ≥ 24 h (queda anotado como pendiente con su fecha) |
| Frase | `AUTORIZO A2 ANCLAJE OCI` |

---
## A3 · T6 completo (failover y failback reales AWS→OCI): **no se recomienda pedirla ahora**
T6 exige cerrar antes D1, D2, D4, D5, D7 y D8 con pruebas **reales**. Eso supone encender RDS y EC2 en AWS, levantar una VM standby en OCI, cambiar el DNS de pruebas y desplegar las compuertas en modo `enforce`. Es decir, varias ventanas cloud encadenadas con riesgo real de doble escritor si una barrera falla. Con el plazo vigente y las sesiones de 4 h de Academy, la regla de parada documentada (`T6-PREPARACION-SOLO-LECTURA.md`) aplica: **T6 queda BLOCKED con su causa** y se presenta lo demostrado (local + T1 a T5 reales). Si aun así se quisiera intentar, primero iría T6.0 (ensayo en seco de solo lectura), con su propia tarjeta.
