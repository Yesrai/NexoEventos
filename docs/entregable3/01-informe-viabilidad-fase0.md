# Entregable 3 — Informe de viabilidad (Fase 0, solo lectura)

Fecha: 9-nov-2026. Solo lectura: no se creó ni modificó ningún recurso, no se reinició RDS, no se encendió nada, no hubo Terraform, DNS, commits ni push.

**Resultado global:** el diseño es viable, pero **los puntos 1 a 4 (consultas a AWS) no se pudieron ejecutar**: la sesión de AWS Academy tiene el token vencido (`ExpiredToken`, 9-nov 15:16 UTC). Todo lo que digo de AWS abajo viene de la documentación oficial y de los archivos del repositorio (con su fecha), **no de una consulta de hoy**. Los puntos 5 a 9 sí están resueltos.

Convención: **Verificado hoy** · **Documentado** (repositorio, fecha anterior) · **Doc. oficial** (consultada hoy) · **Supuesto** · **No verificado**.

---

## 1–4. AWS Academy (identidad, permisos, RDS, créditos)

| Punto | Estado | Detalle |
|---|---|---|
| 1. Identidad, región y permisos | **No ejecutado** | `aws sts get-caller-identity` falla con token vencido. La región configurada en el perfil es us-east-1 (Verificado hoy). La identidad y los permisos actuales **no se pudieron comprobar** |
| 2. ¿Puede el rol crear/modificar grupos de parámetros? | **No verificado** | Ver abajo: la única prueba definitiva es intentar crearlo, y eso es un cambio |
| 2. ¿PostgreSQL admite replicación lógica? | **Sí** (Doc. oficial) | RDS for PostgreSQL admite publicación/suscripción desde la 10.4. La RDS es la **18.3** (Documentado, `20261106-rds-max-almacenamiento/`), así que está soportada en principio; la compatibilidad exacta con 18.3 no la he verificado en una consulta |
| 3. Parámetros actuales | **Documentado** (6-nov) | Grupo `default.postgres18`, `db.t3.micro`, Multi-AZ, no pública, gp2 de 20 GiB (máximo 40) |
| 4. Créditos | **No obtenible por CLI** | El saldo de Academy solo aparece en el panel del laboratorio; no tenemos Cost Explorer (Documentado). Última cifra declarada por la usuaria: **11,2 de 50 USD usados el 5-nov**; no es el saldo de hoy |

### Qué implicaría habilitar replicación lógica (Doc. oficial; no se ejecutó nada)
- **Reinicio: sí.** `rds.logical_replication` es un parámetro **estático**; no se aplica sin reiniciar la instancia. Al activarlo, RDS ajusta además `wal_level`, `max_wal_senders`, `max_replication_slots` y `max_connections`.
- **Grupo de parámetros propio: sí.** `default.postgres18` es un grupo por defecto y no se puede editar; habría que **crear un grupo nuevo** y **asociarlo a la RDS existente** (modificar un recurso existente + reinicio). Con Multi-AZ el reinicio puede implicar una breve interrupción (el failover medido el 4-nov fue de ~39 s; **no es una cifra del reinicio**, que no se ha medido).
- **Rol de base de datos:** `rds_superuser` para activarlo y `rds_replication` para gestionar los *slots*.
- **Seguridad:** la RDS es **privada** (no pública), así que el suscriptor de otra nube no puede conectarse directamente. Haría falta un **relé dentro de la VPC** (por ejemplo una EC2 mínima con Tailscale) y una regla de Security Group desde ese relé hacia la RDS (cambio de seguridad, requiere autorización). La conexión debe seguir con `verify-full`.
- **Costos:** no hay cargo por la función en sí. Sí hay efectos: más WAL en una RDS de **20 GiB** (un *slot* inactivo llena el disco; es el riesgo principal), una EC2 relé (≈ 4 USD/mes encendida, Supuesto) y salida de datos (≈ 0,09 USD/GB, Supuesto; los volúmenes serían pequeños).
- **Limitaciones funcionales:** la replicación lógica **no copia secuencias ni cambios de esquema (DDL)**; hay que aplicar las migraciones de Alembic en ambos extremos y sincronizar las secuencias al promover.
- **Capacidad de la instancia:** `db.t3.micro` (instancia pequeña de capacidad variable) puede sentir la carga extra; **no medido**.

### Qué consultaré cuando el laboratorio esté activo (todo solo lectura)
`sts get-caller-identity`, `rds describe-db-instances` y `describe-db-parameter-groups` (estado, grupo, parámetros pendientes), `rds describe-db-parameters` del grupo actual, `ec2 describe-instances` y `elbv2 describe-target-health` (estado real de V2). Para los permisos: `iam simulate-principal-policy` casi seguro está bloqueado en Academy (ya vimos denegaciones al leer políticas del rol). **La única comprobación fiable de «¿puedo crear un grupo de parámetros?» es crearlo**, lo cual es un cambio (gratuito, pero un cambio) y queda fuera de esta fase sin tu autorización.

**Lo que necesito de ti para cerrar 1–4:** iniciar el laboratorio de Academy y actualizar las credenciales del perfil, como en las sesiones anteriores. Tu decisión: ten en cuenta que mientras el laboratorio está activo siguen corriendo los recursos que quedaron encendidos (ALB y RDS) y se gasta crédito.

---

## 5. Riesgo de un solo HAProxy en GCP y alternativa redundante

**Riesgos de una sola VM:** (1) si la VM cae, **toda** la entrada cae aunque AWS esté sano (el gateway sería peor que el problema que resuelve); (2) falla de zona o de región de GCP; (3) error de configuración o de certificado; (4) reinicios y actualizaciones; (5) la recuperación por autocuración de GCP tarda del orden de minutos, no segundos (Supuesto).

**Alternativa redundante recomendada:**
```
Usuarios → Global External ALB (IP anycast, TLS gestionado)
              └─ grupo de instancias gestionado, 2 gateways en 2 zonas
                    HAProxy: AWS (principal)  ·  app local GCP (backup)
```
Cómo conmuta el tráfico (dos niveles independientes):
1. **GCP → gateways:** el balanceador usa health checks de Google y retira un gateway que falla (intervalo por defecto 5 s; el mínimo permitido no lo he podido confirmar en la documentación, **verificar**).
2. **Gateway → sitios:** HAProxy sondea a AWS cada 1–2 s (`inter 1s fall 2 rise 3`, Supuesto). Si AWS falla, entra el servidor `backup` local sin tocar DNS.
3. **Enrutar por rol, no solo por salud.** La sonda no debe preguntar «¿responde AWS?» sino «¿AWS es el escritor?» (endpoint `/role` que devuelve 200 solo si ese sitio tiene la concesión de escritura). Así, cuando la base se promueva en GCP, AWS **no** vuelve a recibir tráfico solo porque «ya responde».
4. **Retorno:** el servidor de AWS queda deshabilitado hasta que `/role` lo declare listo tras la resincronización; el regreso es planificado, no automático.

**Alternativas más baratas, con sus límites:**
- **Cloud DNS con failover** (comprobación de endpoints externos): admite IPs externas cualesquiera por TCP/HTTP/HTTPS, pero el intervalo de la comprobación es de **30 a 300 s** y los resolutores guardan la respuesta según el TTL; la conmutación sería de **decenas de segundos a minutos** (Doc. oficial). Sirve como segundo camino, no para ≤ 10 s.
- **Hybrid NEG** con health checks de Google: existe, pero exige conectividad privada (Cloud VPN/Interconnect) hacia AWS; añadiría un túnel de pago y complejidad (Doc. oficial).

El gateway **sigue siendo una dependencia de GCP**: es un riesgo residual que se documenta, no se elimina.

---

## 6. DB-A vs DB-B

| Criterio | **DB-A: RDS + réplica lógica asíncrona** | **DB-B: PostgreSQL propio + Patroni** |
|---|---|---|
| Continuidad | Réplica caliente en otra nube; promoción con script y fencing | Failover automático con quórum entre nubes |
| RTO de escritura | ~20–60 s (Supuesto) | ~15–30 s (Supuesto) |
| RPO | **Segundos, no cero**: las confirmaciones recientes pueden perderse | ≈ 0 solo con réplica síncrona; si la réplica cae, el sistema debe elegir entre bloquear escrituras o degradar a asíncrono |
| Consistencia de reservas | Un solo escritor: la unicidad por asiento, el aforo transaccional y la idempotencia siguen válidos. Riesgo: reserva confirmada al cliente y ausente en la réplica tras el failover | Igual, con menos ventana de pérdida (síncrona) |
| Complejidad | Media: relé, parámetro estático, secuencias y DDL a mano | Alta: migrar datos fuera de RDS, operar parches, copias, etcd en 3 nubes |
| Cambios en lo existente | Modifica la RDS (parámetros + reinicio), SG nuevo | Reemplaza la RDS como primaria |
| Presupuesto | ≈ EC2 relé + VM réplica (e2-micro gratis en GCP si cabe) | + 2–3 VMs siempre encendidas durante pruebas |
| Riesgo en Academy | Permisos de grupos de parámetros **no verificados** | Menor dependencia de permisos, más tiempo de trabajo |
| Defensa académica | Fácil de explicar; el RPO se declara con honestidad | Más impresionante; mayor riesgo de no terminar |

**Veredicto:** DB-A para el MVP. DB-B queda como mejora opcional, solo si sobra tiempo y se quiere defender RPO ≈ 0.

---

## 7. Balanceador global de Google: qué admite y qué no (Doc. oficial, consultada hoy)

Mi afirmación anterior **era correcta, pero la afino**:

| Configuración | ¿Admite health check / failover? |
|---|---|
| Backend externo `INTERNET_FQDN_PORT` (global) | **No**: el servicio de backend no puede referenciar un health check, no hay detección de outliers, reintentos ni espejado; con un solo endpoint, no hay a dónde conmutar. Si el externo cae o no resuelve, el cliente recibe **502**. Valida el certificado (CA conocida, SAN con el FQDN) y envía SNI |
| Grupos de instancias y NEG compatibles (zonales) | **Sí**, health checks centralizados |
| NEG de conectividad híbrida (`NON_GCP_PRIVATE_IP_PORT`) | **Sí**, con health checks, pero **solo IPs privadas por VPN/Interconnect/router** |
| Cloud DNS con política de failover y comprobación de endpoints externos | **Sí** para IPs externas por TCP/HTTP/HTTPS, **intervalo 30–300 s** |

Conclusión: «AWS como backend externo del balanceador global» no da failover; el balanceador global sí sirve como **entrada redundante** de gateways propios dentro de GCP. Lo que **no** he podido confirmar: el intervalo mínimo de health check para backends propios y el precio exacto de la regla de reenvío; hay que verificarlos en la documentación y la calculadora de precios antes de presupuestar.

---

## 8. Los 14 criterios oficiales de la rúbrica

Archivo: `rúbrica proyecto_qod3szrctm (1).xlsx` (idéntico a la copia sin «(1)»); la usuaria lo confirmó como rúbrica del Entregable 3. Total del archivo: **20 puntos**. Niveles: Excelente · Bueno · En proceso · Deficiente.

1. Análisis del problema y requerimientos · 2. Diseño de arquitectura cloud · 3. Redes VPC/VCN · 4. Cómputo, almacenamiento y BD · 5. Seguridad cloud · 6. Alta disponibilidad y escalabilidad · 7. Monitoreo y observabilidad · 8. Infrastructure as Code · 9. Backup, RTO/RPO y recuperación · 10. Arquitectura AWS–OCI / multicloud · 11. Costos y optimización · 12. Pruebas técnicas · 13. Documentación técnica · 14. Sustentación y defensa técnica.

**Pendientes (no aparecen en ningún documento):** el reparto de puntos por criterio y la fecha de entrega. La columna «Puntaje» (J) tiene textos «1.0», «2.0», «1.5», «2.5» y «0.5» **solo** en los criterios 1, 2, 4, 5 y 11; no los uso como ponderaciones (no suman 20 y el resto está vacío; parecen anotaciones de calificación de otro uso). El criterio 10 pide integración AWS–OCI; **Google Cloud no aparece en la rúbrica.**

---

## 9. Arquitectura mínima viable recomendada

**Objetivo:** cubrir los criterios 6, 9, 10 y 12 con pruebas medidas, con el menor cambio sobre lo que ya funciona.

| Componente | MVP |
|---|---|
| AWS | V2 y RDS actuales, sin rediseñar. Único cambio previsto (con autorización): grupo de parámetros con replicación lógica + reinicio, y relé en la VPC |
| GCP | 2 gateways HAProxy en 2 zonas detrás de un balanceador global; contenedor del backend y réplica PostgreSQL en espera |
| OCI | Respaldo cifrado y programado (cierra el pendiente del respaldo diario) y recuperación por restauración como **tercer nivel, manual**. Integración AWS–OCI real y demostrable |
| Azure | Sondas externas, Zabbix/Grafana, alertas y tablero de la línea de tiempo del failover |
| Datos | **DB-A**; un solo escritor; concesión de escritura caducable |
| Failover | Lectura automática primero (meta ≤ 10 s, a medir); promoción de la base automática con condiciones de quórum en una segunda etapa; retorno **planificado** |
| Declaración honesta | RTO de lectura y de escritura medidos por separado; **RPO en segundos**, nunca «cero» |

**Hitos defendibles, de menor a mayor riesgo** (cada uno es entregable por sí solo):
1. Gateway redundante en GCP + app en espera con una base **de prueba**, y failover de tráfico medido contra un «AWS» simulado.
2. Réplica lógica RDS → GCP medida (lag y RPO), con sincronización de secuencias.
3. Promoción automática con fencing y quórum; prueba de split-brain.
4. Retorno planificado a AWS.
5. Respaldo programado a OCI y sondas/alertas de Azure.

**Plan B** si falla GCP (cuenta, cuota o crédito): gateway y sitio caliente en OCI (E5.Flex pagada con crédito de prueba o A1 si hay capacidad); se mantiene el cumplimiento del criterio 10, pero deja de ser «cuatro nubes».

---

## Riesgos y costos (estimaciones; verificar)

| Riesgo | Mitigación |
|---|---|
| Reinicio de RDS con Multi-AZ (interrupción breve) | Hacerlo con V1 y V2 apagadas y en ventana planificada; medir su duración |
| *Slot* inactivo llena los 20 GiB | Monitorizar `pg_replication_slots`, alarma de `FreeStorageSpace`, máximo ya en 40 GiB |
| Permisos de Academy insuficientes | Verificar al inicio de la fase siguiente; si no, DB-B o réplica por `pg_dump`/WAL como alternativa |
| Datos personales en otra nube | Usar datos de prueba hasta que lo autorices |
| Gateway como nuevo punto único | Redundancia de 2 zonas + riesgo declarado |
| Crédito de Academy | Sin saldo verificable por CLI; trabajar en ventanas cortas con lista de apagado |

| Concepto | Costo estimado (Supuesto) |
|---|---|
| Ventanas de prueba de V2/RDS (3 de 3 h) | ≈ 1,0–1,5 USD |
| EC2 relé t3.nano | ≈ 0,005 USD/h |
| GCP: balanceador + 2 gateways | ≈ 0,05–0,10 USD/h (**verificar**) |
| GCP: réplica e2-micro | 0 dentro de la capa gratuita (límites de disco/egreso: **verificar**) |
| OCI: réplica de apoyo (si se usa) | ≈ 0,05 USD/h en E5.Flex; Always Free ≈ 0 |
| Azure: VM de observabilidad | 0,108 USD/h solo en ventanas |
| **Total del Entregable 3 con ventanas cortas** | **≈ 3–8 USD**, sin dejar nada encendido |

## Recomendación concreta
1. Que inicies el laboratorio y actualices las credenciales para completar los puntos 1–4 en solo lectura (≈ 15 minutos).
2. Con ese resultado decidimos DB-A (lo esperado) o el plan alternativo.
3. Luego, y solo con tu autorización, empezar el hito 1 (gateway en GCP con base de prueba), que no toca AWS.

Nada de lo anterior se implementa hasta que lo autorices.
