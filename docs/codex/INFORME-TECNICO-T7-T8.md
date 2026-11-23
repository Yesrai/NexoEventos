# Informe técnico T7–T8

## Resumen ejecutivo

NexoEventos dispone de evidencia versionada de T1–T5: 12/12, 13/13, 19/19, 18/18 y 9/9 criterios respectivamente. T7 integra esas fuentes en NexoOps, un portal con autenticación de dos factores, rol `SUPER_ADMIN_TI`, sesiones, CSRF, auditoría encadenada, consultas de monitoreo y una lista blanca de operaciones. T6 no se considera terminado y T8 sigue pendiente de cierre verificable.

## Estado de la solución

- **Identidad:** contraseña Argon2id, OTP aleatorio de seis dígitos, expiración, un solo uso y cookies HttpOnly.
- **Monitoreo:** clientes preparados para Grafana y Zabbix, con TLS verificado y permisos de solo lectura.
- **Multicloud:** el recolector T4 clasifica AWS, OCI y Azure con fuente, hora y frescura.
- **Operación:** catálogo explícito; consultas permitidas, solicitudes registradas y failover/failback bloqueados.
- **Diagnóstico:** motor determinista que separa hechos, hipótesis y recomendaciones. No se presenta como IA generativa.
- **Auditoría:** actor, rol, operación, recurso, resultado e identificadores en una cadena verificable.

## Integraciones T7

### Grafana

El cliente lista dashboards y paneles y consulta métricas mediante la API. La configuración real exige URL bajo `/grafana`, token Viewer y CA fijada cuando corresponda. La incrustación es opcional y no debe activarse sin autorización porque modifica `grafana.ini`; los enlaces directos permiten operar sin ese cambio.

### Zabbix

El cliente se limita a `host.get`, `problem.get`, `event.get` y `apiinfo.version`. Debe usar un token de usuario de solo lectura y mostrar severidad, fuente y UTC. La ausencia de configuración o una falla de API se presenta como no disponible, no como cero incidentes.

### Recolector Azure T4

NexoOps lee la instantánea e historial producidos por T4. Un estado OCI “en espera” se clasifica como advertencia, no como operativo. Los datos sin fuente o fuera de vigencia se muestran como no verificados. T4 demostró 38 ciclos reales, Grafana/Zabbix y una alerta recibida; no demuestra por sí solo el estado actual de una nube apagada.

### Operaciones y seguridad

Las operaciones admitidas son consultas de estado, salud, actividades de ASG, barreras y evidencias, más solicitudes de intervención. Los parámetros, frecuencia, rol, confirmación y contexto se validan. No hay consola arbitraria, encendido/apagado, cambio DNS ni ejecución de failover.

## Pruebas y evidencia

Las pruebas locales deben incluir clientes simulados para respuestas, errores, permisos, secretos y lista blanca. Esas pruebas validan el código, no la conectividad cloud. La prueba real pendiente consiste en ejecutar `check-integrations` contra servicios de Azure en una ventana autorizada y conservar el resultado saneado y capturas con UTC/URL.

## Resultados heredados T1–T5

La tabla completa está en `docs/codex/RESULTADOS-Y-COSTOS.md`. La métrica de disponibilidad T5 (99,49 %) proviene de una única ejecución con seis instancias y una parada controlada. El FAIL con dos instancias (95,21 %) se conserva; no se extrapola el PASS a una caída abrupta ni a tráfico de escritura.

## Limitaciones y pendientes

1. T6 no tiene ejecución real completa: no declarar RTO/RPO AWS→OCI.
2. T7 requiere integración real autorizada, capturas y expediente de los cuatro criterios.
3. T8 requiere inventario final de nubes, revocación de credenciales temporales y paquete cifrado nuevo verificado.
4. No existe costo facturado consolidado versionado; solo estimaciones de ventanas.
5. Los expedientes originales bajo `work/` necesitan custodia externa con manifiestos, sin incluir secretos en Git.

## Conclusión

La base técnica permite terminar T7 sin introducir una arquitectura nueva ni relajar controles. El criterio de éxito es verificabilidad: toda fuente real conserva UTC y procedencia, toda simulación se rotula local y toda acción no autorizada falla cerrada. T8 debe reflejar tanto los PASS como los fallos y límites medidos.

