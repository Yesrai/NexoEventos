# Contenido de presentación editable

## Diapositiva 1 — NexoEventos Multicloud: operación verificable

- AWS: operación y alta disponibilidad
- OCI: lease y recuperación
- Azure: observabilidad y centro de operaciones
- T1–T5 cerradas; T6 pendiente; T7/T8 en cierre

Visual: diagrama de `ARQUITECTURA-T7.md`.

## Diapositiva 2 — Método de evidencia

- Criterios medibles por etapa
- Expediente + manifiesto SHA-256 + UTC
- Fallos conservados y corregidos
- Local/simulado ≠ cloud/real

## Diapositiva 3 — T1–T3: control y recuperación

| T1 | T2 | T3 |
|---|---|---|
| PASS 12/12 | PASS 13/13 | PASS 19/19 |
| Lease exclusivo | DNS prueba A→B→A | Recuperación OCI |
| p95 0,414 s | 62,1 s / 62,0 s | Humo 11/11 + 23/23 |

## Diapositiva 4 — T4: observabilidad desde Azure

- PASS 18/18
- 38 ciclos, hueco máximo 67 s
- Grafana + Zabbix + recolector
- Alerta real y correo confirmado
- Cierre: VM desasignada, tokens temporales destruidos

## Diapositiva 5 — T5: resultado y límite

- 6 instancias: 99,49 %, detección 9,6 s, recuperación 125 s
- Sustitución real por ASG, dos zonas, limpieza completa
- Comparación honesta: dos instancias = 95,21 % FAIL
- Una sola ejecución; parada controlada; tráfico de solo lectura

Visual: tabla comparativa económico/alta disponibilidad.

## Diapositiva 6 — NexoOps: seguridad de acceso

- `SUPER_ADMIN_TI`
- Argon2id + OTP Gmail + sesión HttpOnly
- SameSite/CSRF/Origin/auditoría
- Sin secretos en navegador ni registros

## Diapositiva 7 — Integración operativa T7

- Grafana API (Viewer)
- Zabbix API (solo lectura)
- AWS describe/list
- Recolector T4: fuente + UTC + frescura
- Errores y datos no disponibles visibles

## Diapositiva 8 — Acciones y diagnóstico

- Lista blanca y límites de frecuencia
- Solicitudes de intervención auditadas
- Failover/failback bloqueados
- Diagnóstico determinista: hechos, hipótesis, recomendaciones

## Diapositiva 9 — Costos

- Estimación ventanas T1–T5 citadas: ≈ USD 0,50
- V2 económica: ≈ USD 0,13/h
- V2 alta disponibilidad: ≈ USD 0,26/h
- Sin factura consolidada: no presentar estimación como gasto real

## Diapositiva 10 — Estado y próximos hitos

- T1–T5: PASS con límites documentados
- T6: pendiente, sin RTO/RPO declarado
- T7: código/pruebas locales → integración Azure autorizada → expediente
- T8: limpieza, revocación, copia cifrada y paquete final

## Notas de diseño

- Formato 16:9, fondo claro, verde oscuro como color principal y ámbar para pendientes.
- Una cifra principal por diapositiva; notas al pie con la ruta de evidencia.
- Nunca mostrar tokens, OTP, IP sensibles o URLs PAR.
- Mantener las tablas editables; no rasterizar texto.

