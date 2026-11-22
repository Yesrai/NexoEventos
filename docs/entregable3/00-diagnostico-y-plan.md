# Entregable 3 — Diagnóstico, arquitectura propuesta y plan (solo planificación)

Fecha: 9-nov-2026. **Nada de esto está implementado.** No se creó ningún recurso, no se ejecutó Terraform, no se cambió DNS, seguridad ni credenciales, y no hay commits de este trabajo. Todo lo que dice «propuesto» o «meta» es una hipótesis hasta que se mida.

Convención: **Verificado** = visto en archivos o en la nube con fecha · **Documentado** = lo dice el repositorio, no se volvió a consultar · **Supuesto** = mi estimación · **Meta** = objetivo sin medir.

---

## 1. Qué exige el profesor (y qué no sabemos)

**Actualización:** la usuaria confirmó que `rúbrica proyecto_qod3szrctm (1).xlsx` es la rúbrica que se usa para el Entregable 3. Es idéntica byte a byte a la otra copia sin «(1)» de Descargas y no nombra «Entregable 3» dentro del archivo; se toma como la rúbrica oficial del E3 por indicación de la usuaria. Sus 14 criterios (20 puntos) son los requisitos obligatorios conocidos. La columna «Puntaje» trae valores solo en algunas filas (1, 2, 4, 5 y 11: 1,0 · 2,0 · 1,5 · 2,5 · 0,5); no los trato como pesos oficiales porque no suman 20 y las demás filas están vacías. **Pendiente de confirmar:** el reparto real de puntos y la fecha de entrega.

Aparte de esa rúbrica no hay enunciado específico del E3 (busqué en Descargas, Documentos, el repositorio y los textos de ChatGPT guardados). Lo que hay:

| Documento | Qué es | Sirve para E3 |
|---|---|---|
| `rúbrica proyecto_qod3szrctm (1).xlsx` (y copia idéntica; creada 20-ago-2026) | 14 criterios, 20 puntos; **confirmada por la usuaria como la rúbrica del E3** | Sí, es la rúbrica de evaluación |
| `rubrica_entregable1_…docx`, `rubrica_entregable2_…docx` | Rúbricas de E1 y E2 | Solo como antecedente |
| Plantilla `entregable2_cloud_computing_upeu_…docx` | Estructura de 20 secciones de E2 | Probablemente se reutiliza la estructura |

Consecuencia: los requisitos obligatorios son los 14 criterios de la rúbrica; no invento otros. Lo que pediste (RTO ≤ 10 s, RPO ≈ 0, cuatro nubes) son **metas del equipo**, no exigencias conocidas del profesor. De la rúbrica general, el criterio 10 pide «integración real, segura y demostrable» entre **AWS y OCI**; **Google Cloud no es requisito**: lo añadimos por decisión propia y solo vale la pena si cumple una función real (ver §4 y plan B).

**Necesito de ti:** la fecha de entrega y, si existe, el enunciado del E3 y el reparto de puntos. Sin la fecha, el cronograma de §10 usa semanas relativas.

---

## 2. Auditoría del estado actual

### Qué tenemos y qué funciona realmente

| Nube | Componente | Estado | Evidencia |
|---|---|---|---|
| AWS | V1 (1 EC2 + RDS Multi-AZ), Terraform `infra/aws` | Verificado en E2; V1 con 37/37 de validación pública (19-oct) | `docs/evidencias/` |
| AWS | V2: ALB + ASG 2–3 EC2 en 2 zonas + RDS, 27 recursos, `infra/aws-v2` | Recreada 5-nov, validación funcional 15/15 (5 y 6-nov), **apagada 6-nov (ASG 0)**; última verificación AWS 6-nov 16:56 | `20261105-despliegue-v2/`, `validacion-v2-2026110{5,6}/` |
| AWS | Autohealing (~110 s, 52×502) y failover RDS Multi-AZ (~39 s, 6/2 412 timeouts) | **Medidos solo el 4-nov** | `20261104-b2-…`, `20261104-d2-…` |
| AWS | RDS: máximo de almacenamiento 20→40 GiB (6-nov) | Hecho; sin interrupción observada | `20261106-rds-max-almacenamiento/` |
| Azure | VM con Grafana 13.2.4 + Zabbix 7.0.32, alertas CPU reales, acceso privado por Tailscale (solo TCP 443) | Verificado 9-nov 00:14 desde el Mac; VM **desasignada**; prueba desde otra red **pendiente** | `20261109-azure-tailscale/` |
| OCI | Bucket cifrado y versionado, respaldo CMS, simulacro de restauración (14/14, 32 min 42 s) y diseño de recuperación de la aplicación | Datos: verificado. **App completa en OCI: diseñada/ensayada, no es continuidad automática** | `docs/multicloud/07`, `08`; `evidencias/multicloud/oci/` |
| GCP | `infra/gcp/README.md` (marcador) | **No existe cuenta ni proyecto verificado**; el marcador habla de BigQuery, no de failover | `infra/gcp/` |
| Código | Backend FastAPI, frontend React | **Todo el estado vive en PostgreSQL** (usuarios, sesiones `auth_sessions`, límites `auth_rate_limits`, reservas, tickets, cola `queue_entries`, idempotencia) | `backend/app/models.py` |

**Dato clave de diseño:** como no hay Redis ni estado en memoria, la aplicación es *stateless*: cualquier nube puede servirla si tiene una base consistente. **El problema difícil es solo la base de datos.**

### Respaldo no es continuidad (lo que hoy NO tenemos)
Hoy el DR a OCI es **manual**: restaurar un respaldo cifrado y levantar una VM (≈ 32 min medidos para datos, aplicación completa solo diseñada). Eso es **RTO de decenas de minutos y RPO de horas** (el respaldo no tiene programación diaria). No existe conmutación automática entre nubes, ni balanceo global, ni réplica continua de datos.

### Pendientes heredados de E2 que afectan a E3
Captura de consola de V2 (5 y 6-nov) · prueba manual en navegador del 6-nov · prueba de Azure desde otra red · captura del crédito/costos · respaldo diario programado · recuperación completa en AWS con DNS/HTTPS · carga >50 usuarios y fallo de zona/región · código de estudiante en la portada · 7 commits locales sin publicar ni validar por CI · fase 2 de E2 (PPT, guion, PDF) sin aprobar.

### Qué se reutiliza
`infra/aws-v2` y los scripts `v2-terraform.sh` / `asg_enabled`; imagen Docker del backend (`backend/Dockerfile`); `verify-v2-flow.py` (15 comprobaciones funcionales) como prueba de continuidad; Tailscale (WireGuard, ya con ACL) para el canal entre nubes; Zabbix/Grafana como observador independiente; red, IAM y bucket de OCI; scripts de chaos de E2 para medir tiempos.

---

## 3. Qué es realista: RTO ≤ 10 s y RPO ≈ 0

Dos hallazgos condicionan todo el diseño:

1. **El balanceador global de Google no puede hacer failover hacia AWS.** Lo comprobé en la documentación oficial de Google ([Internet NEG](https://docs.cloud.google.com/load-balancing/docs/negs/internet-neg-concepts)): los backends externos (`INTERNET_FQDN_PORT`) **no admiten health checks, ni detección de outliers, ni failover**; si AWS cae, el balanceador devuelve 502. Por tanto «poner AWS como backend externo de Google» **no** da conmutación automática.
2. **El failover seguro de escrituras no cabe en 10 s.** Para evitar *split-brain* hay que garantizar que el primario viejo no siga escribiendo (fencing, concesión de escritura con caducidad) antes de promover otra base. Con una concesión de 10 s, la escritura no puede reanudarse antes de ~10 s + el tiempo de promoción.

**Lo que propongo declarar (solo si se mide):**

| Capa | Meta honesta | Cómo se podría cumplir |
|---|---|---|
| Web/lectura (catálogo, ver entradas) | **≤ 10 s** de conmutación | Gateway con health check activo de 1–2 s + réplica de solo lectura local |
| Escrituras (reservas, validación de QR) | **20–40 s (Supuesto)**; ≤ 10 s solo si la medición lo demuestra | Concesión de escritura corta + promoción automática |
| RPO | **Segundos** con réplica asíncrona; **≈ 0 solo con replicación síncrona** | Ver §5; RPO ≈ 0 exige abandonar RDS como primario |

Si en las pruebas se mide, por ejemplo, 28 s de escritura y 6 s de lectura, **ese** es el RTO que se declara.

---

## 4. Arquitectura propuesta de cuatro nubes

```
                    Usuarios (HTTPS, nexoeventos-demo… / dominio estable)
                                      │
                  ┌───────────────────▼────────────────────┐
   GCP  (puerta   │ Global External ALB (IP anycast, cert) │
   de entrada)    │   └─ MIG de gateways HAProxy (2 zonas) │
                  │       health check activo 1–2 s        │
                  └───────┬──────────────────────┬─────────┘
                 principal│                      │backup (automático)
              ┌───────────▼─────────┐   ┌────────▼────────────────────┐
   AWS        │ ALB + ASG (V2)      │   │ GCP: app en contenedor +     │
   PRIMARIA   │ PostgreSQL primario │──▶│ réplica PostgreSQL (lectura) │
              └──────────┬──────────┘   └────────▲────────────────────┘
                         │ replicación (WireGuard/Tailscale)          │
              ┌──────────▼──────────┐   ┌────────┴────────────────────┐
   OCI        │ Réplica / testigo   │   │ Azure: Zabbix + Grafana +    │
   DR 2.º     │ + WAL/respaldos     │   │ sondas externas + alertas    │
              └─────────────────────┘   └──────────────────────────────┘
```

| Nube | Función | Por qué esta función y no otra |
|---|---|---|
| **AWS** | Producción primaria (V2) y base primaria | Ya está construido y probado; único sitio con ALB/ASG/Multi-AZ |
| **GCP** | **Puerta de entrada global** (HA propia, IP anycast, certificado gestionado) + **sitio caliente de contenedores** y réplica | El gateway tiene que vivir *fuera* de AWS para sobrevivir a AWS. La capa gratuita (e2-micro) y el crédito de prueba permiten probarlo barato |
| **OCI** | **Segundo sitio de DR** + archivo de WAL/respaldos cifrados + testigo de quórum | Ya existe red/bucket/IAM/proceso de restauración; añade un tercer voto para evitar split-brain |
| **Azure** | **Observador independiente**: sondas sintéticas desde fuera de AWS, Zabbix/Grafana, alertas y el tablero de RTO | Ya existe; medir la disponibilidad desde la misma nube que falla no vale como evidencia |

**Riesgo residual que hay que declarar:** el gateway pasa a ser una dependencia de GCP. Si GCP falla, la entrada falla aunque AWS esté sano. Mitigaciones posibles: gateway en dos zonas/regiones, y un segundo camino DNS con TTL bajo (requiere dominio propio; ver §9). No se promete «sin punto único de falla» sin una prueba.

**Plan B (si GCP no entra a tiempo o no hay crédito):** el gateway y el sitio caliente pasan a OCI (E5.Flex pagada con crédito de prueba o A1 Always Free si hay capacidad). Se pierde la IP anycast, y con ello «cuatro nubes». La rúbrica solo exige AWS–OCI, así que sigue cumpliendo.

---

## 5. Failover automático: activo-activo vs activo-pasivo caliente

| Criterio | Activo-activo | **Activo-pasivo caliente (recomendado)** |
|---|---|---|
| Web (stateless) | Fácil: se reparte tráfico | Fácil: el pasivo ya está encendido |
| Base de datos | Exige multi-maestro (CockroachDB/YugabyteDB/BDR): reescribir migraciones y la lógica de aforo; riesgo de **reservas duplicadas** si hay conflictos | **Un solo escritor** a la vez: la restricción de unicidad por asiento y el `SELECT … FOR UPDATE` actuales siguen válidos |
| Complejidad y costo | Alta; tres motores a operar | Media; reutiliza lo construido |
| Riesgo de defensa | Difícil de explicar y de probar en semanas | Defendible y medible |
| Coste en créditos | Dos sitios al 100 % siempre | El pasivo puede ir con capacidad mínima |

**Recomendación:** activo-pasivo caliente para escrituras, con **lectura local en el sitio pasivo** (catálogo y entradas siguen respondiendo mientras se promueve la base). Activo-activo de datos queda descartado por riesgo de duplicados, y lo dejo como línea futura.

### Mecanismo propuesto de conmutación
1. **Detección:** HAProxy en GCP con `option httpchk GET /healthz`, `inter 1s fall 2 rise 3` hacia el ALB de AWS → detección ≈ 2–3 s (Meta). Azure sondea además desde fuera, de forma independiente, y alerta.
2. **Cambio de tráfico:** el servidor `backup` del gateway (la app de GCP) entra solo cuando falla el principal. No hay DNS ni TTL en el camino rápido.
3. **Escrituras:** una **concesión de escritura** (lease) corta, guardada fuera de AWS. Sin concesión vigente, la app de AWS pasa a solo lectura. Con la concesión caducada y la mayoría del quórum (GCP + OCI + sonda de Azure) de acuerdo en que AWS no responde, se promueve la réplica. La app devuelve `503 + Retry-After` en escritura durante la ventana.
4. **Retorno seguro (failback):** nunca automático. AWS vuelve como **réplica**, se reconstruye (`pg_rewind` o copia base), se espera lag ≈ 0, se hace un *switchover* planificado fuera de hora pico, y el tráfico vuelve de forma gradual. Se mide el RTO del retorno.
5. **Anti-flapping:** `rise 3` y una espera mínima antes de aceptar el retorno.

---

## 6. El problema de los datos

| Riesgo | Tratamiento propuesto |
|---|---|
| **Split-brain** | Un escritor a la vez, concesión caducable, fencing al promover y quórum de tres sitios. Verificación: `pg_is_in_recovery()` debe ser `false` en un solo nodo en todo momento |
| **Reservas duplicadas** | Se mantienen las garantías de un solo escritor: restricción única por asiento, aforo transaccional e idempotencia (todo ya está en la base y se replica). Prueba: carga continua con claves de idempotencia únicas y conciliación al final |
| **Operaciones en curso** | Un cliente que recibió `201` justo antes de la caída puede **no existir en la réplica** (si es asíncrona). Se mide y se declara; se mitiga con replicación síncrona y con reintentos idempotentes del cliente |
| **Pérdida de datos (RPO)** | Se mide el *lag* en bytes/segundos y se compara el último latido escrito con el último latido en la réplica tras la promoción |
| **Secuencias y DDL** | La réplica lógica **no** copia secuencias ni migraciones: hay que sincronizar secuencias al promover y aplicar Alembic en ambos extremos |
| **Claves de aplicación** (`TICKET_ENCRYPTION_KEY`, `SECURITY_HASH_KEY`) | Sin ellas los QR no se validan en otra nube. Hay que distribuirlas por un canal seguro (nunca en Git ni en este chat) |

### Dos caminos para la base (decisión pendiente, con una comprobación previa de solo lectura)

| | **DB-A: RDS primaria + réplica lógica asíncrona** | **DB-B: PostgreSQL propio en EC2 + Patroni síncrono** |
|---|---|---|
| RPO | Segundos (**no es cero**) | ≈ 0 para transacciones confirmadas, con réplica síncrona |
| Cambio sobre lo actual | Pequeño: se mantiene RDS; **requiere** parámetro `rds.logical_replication` (reinicio de RDS) y un relé en la VPC, porque la RDS es privada | Grande: migrar los datos de RDS a EC2 y operar la base; RDS queda como respaldo |
| Failover | Promoción con script y fencing | Automático con Patroni y etcd en 3 nubes |
| RTO de escritura | ~20–60 s (Supuesto) | ~15–30 s (Supuesto) |
| Riesgo en Academy | Hay que comprobar si el rol permite grupos de parámetros | Menor dependencia de permisos, mayor trabajo |

**Propuesta:** construir **DB-A primero** como base segura y defendible, y evaluar **DB-B** solo si sobra tiempo y se quiere defender RPO ≈ 0. **No se declara RPO ≈ 0 con DB-A.** El paso previo es verificar en solo lectura qué permite el rol de Academy (grupos de parámetros de RDS y opciones de reinicio).

---

## 7. Google Cloud: plan (sin crear nada todavía)

| Servicio | Uso | Capa gratuita / costo (**verificar** en cloud.google.com/free y en la calculadora) |
|---|---|---|
| Global External Application LB | IP anycast + TLS gestionado hacia los gateways | **Sin capa gratuita** (Supuesto ≈ 0,025 USD/h la regla de reenvío + datos) |
| Compute Engine e2-micro | Réplica de lectura y/o testigo de quórum | 1 VM gratis/mes en us-west1, us-central1 o us-east1 y 30 GB de disco estándar; salida limitada a 1 GB/mes ([fuentes de terceros](https://bestusavps.pages.dev/deals/google-cloud-free), verificar) |
| Compute Engine e2-small ×2 (MIG) | Gateways HAProxy en dos zonas | De pago (≈ 0,02 USD/h cada una, Supuesto) |
| Cloud Run | Contenedor de la app en espera | Cupo gratuito mensual de solicitudes y CPU (verificar); alternativa: VM |
| Cloud DNS | Solo si se adopta dominio propio | Pequeño costo por zona |
| Crédito de bienvenida | Prueba de 300 USD (la duración, 90 días, **hay que confirmarla** en la oficial) | Requiere tarjeta; **la cuenta la debes crear tú** |

Cuotas a revisar antes de crear nada: regiones (se sugiere us-east1/us-east4 por cercanía a AWS us-east-1), IPs externas, reglas de reenvío, CPU por región, y que el proyecto de facturación no tenga límites. Integración con NexoEventos: se reutiliza la imagen del backend (variables `DATABASE_URL`, `FRONTEND_ORIGINS`, claves por secreto) y `/healthz` como sonda. `FRONTEND_ORIGINS` debe incluir el origen público de la puerta de entrada.

---

## 8. Pruebas del Entregable 3 (todas **pendientes**; ninguna ejecutada)

| # | Prueba | Cómo se mide | Criterio de éxito (Meta, no resultado) |
|---|---|---|---|
| T1 | Caída del web de AWS (ASG a 0 con el script existente; cambio autorizado) | Sonda externa cada 1 s: primer fallo → primer éxito | Lectura ≤ 10 s |
| T2 | Continuidad de reservas y QR tras la conmutación | `verify-v2-flow.py` contra la puerta de entrada | 15/15 sin duplicados |
| T3 | Caída de la base primaria | Tiempo hasta primera escritura correcta | Medir; declarar lo observado |
| T4 | RPO | Latido numerado cada 1 s; último en réplica tras promoción | Segundos (A) o ≈ 0 (B) **solo si se mide** |
| T5 | Cero reservas duplicadas | Carga con claves únicas + conciliación | 0 duplicados, 0 sobreventa |
| T6 | Split-brain | Aislar AWS de la red; comprobar un solo escritor | Nunca dos |
| T7 | Monitoreo y alertas | Azure detecta caída y notifica; Grafana muestra la línea de tiempo | Alerta recibida con hora |
| T8 | Retorno a AWS | Reconstrucción, switchover planificado, RTO de retorno | Sin pérdida ni duplicados |
| T9 | Fallo parcial (AWS lento, no caído) | Latencia alta sin corte | Sin oscilación del gateway |
| T10 | Sin disponibilidad del 100 % | Informe con errores observados | Se declaran los 5xx medidos |

Principios: primero en un entorno de ensayo (GCP vs un «AWS» simulado) sin tocar producción; cualquier prueba que cambie recursos reales de AWS se pide aparte. Cada resultado se archiva con fecha y comando, como en E2.

---

## 9. Costos (estimación con supuestos; hay que verificar con calculadoras y facturación)

Base verificada en el repositorio: V2 encendida ≈ 0,11–0,17 USD/h; persistente con todo apagado ≈ 0,21 USD/día; ASG a 0 ≈ 0,056 USD/h (por ALB y RDS).

| Nube | Concepto | Si corre 24×7 (mes) | En 3 ventanas de prueba de 3 h | Apagado seguro |
|---|---|---|---|---|
| AWS | V2 + RDS Multi-AZ (existente) | ≈ 80–125 (no se hará) | ≈ 1,0–1,5 | Script `v2-terraform.sh off` (ASG 0) y detener RDS con autorización |
| AWS | Relé EC2 pequeño para la réplica (t3.nano) | ≈ 4 | ≈ 0,1 | Detener la instancia |
| GCP | LB global + 2 gateways + app en espera | ≈ 45–70 (Supuesto) | ≈ 0,5–1 | **`terraform destroy` solo de GCP, recursos propios nuevos** |
| GCP | e2-micro réplica/testigo | 0 dentro de la capa gratuita | 0 | Apagar la VM |
| OCI | Réplica en E5.Flex 1 OCPU/8 GB (si A1 no hay capacidad) | ≈ 30–35 (Supuesto) | ≈ 0,5 | Detener/destruir la VM; el bucket queda en Always Free |
| Azure | VM D2s_v4 de observabilidad | 0,108 USD/h → ≈ 78 | ≈ 1,0 | Desasignar (ya lo hacemos) |
| — | Dominio propio (opcional) | ≈ 1–12 USD/año | — | — |

**Estimación para el Entregable 3 con ventanas cortas (Supuesto): ≈ 3–6 USD en total.** El mayor riesgo no es el consumo sino dejar algo encendido: por eso cada ventana lleva lista de apagado y verificación posterior. No se gasta crédito de AWS Academy sin que confirmes el saldo (lo último que consta es 11,2 de 50 USD usados el 5-nov). Cada recurso nuevo se propone con costo por hora antes de crearse.

---

## 10. Matriz de cumplimiento

**A. Rúbrica del Entregable 3 (`rúbrica proyecto_…xlsx`; 14 criterios, 20 puntos)** — estado respecto a lo que se podría exigir en el cierre.

| # | Criterio | Estado actual | Evidencia | Pendiente | Prioridad | Nubes | Prueba necesaria |
|---|---|---|---|---|---|---|---|
| 1 | Análisis del problema y requisitos | Cubierto en E1/E2 | Informe E2 | Añadir requisitos de continuidad (RTO/RPO) | Media | — | Revisión |
| 2 | Diseño de arquitectura cloud | V2 cubierto; multicloud activo no | Fig. 4, `arquitectura-v2.md` | Diagrama de cuatro nubes y justificación | **Alta** | Todas | Revisión |
| 3 | Redes VPC/VCN | AWS/OCI/Azure verificados; GCP y canal entre nubes no | `infra/*` | VPC de GCP, canal WireGuard/Tailscale, reglas | **Alta** | Todas | Conectividad y puertos cerrados |
| 4 | Cómputo, almacenamiento y BD | AWS sólido; sitio pasivo no existe | V2 | Réplica, contenedor en GCP/OCI | **Alta** | AWS, GCP, OCI | Réplica activa, `pg_is_in_recovery` |
| 5 | Seguridad cloud | Fuerte en AWS/Azure | E2 §7–10 | Mínimo privilegio en GCP, secretos entre nubes, SG/NSG nuevos | **Alta** | Todas | Escaneo de puertos, revisión IAM |
| 6 | Alta disponibilidad y escalabilidad | HA dentro de AWS; **sin HA entre nubes** | Autohealing 4-nov | Failover automático y su prueba | **Crítica** | AWS, GCP | T1, T3, T9 |
| 7 | Monitoreo y observabilidad | Zabbix/Grafana Azure; falta capturas y prueba otra red | `20261109-…` | Sondas externas, alertas de failover | Alta | Azure | T7 |
| 8 | Infrastructure as Code | AWS-V2 Terraform; GCP vacío | `infra/aws-v2` | Terraform de GCP y del sitio pasivo | Alta | GCP, OCI | `plan` limpio, destroy solo de lo propio |
| 9 | Backup, RTO/RPO y recuperación | Recuperación OCI manual probada; RPO/RTO automáticos no | `docs/multicloud/07` | Medir RTO/RPO del failover; respaldo programado | **Crítica** | OCI, AWS | T3, T4, T8 |
| 10 | Arquitectura AWS–OCI / multicloud | Respaldos a OCI reales; integración automática no | E2 §15 | Integración viva (réplica/testigo) | **Crítica** | AWS, OCI (+GCP) | T6, replicación |
| 11 | Costos y optimización | Estimados con tarifas públicas, sin crédito real | Tabla 27 E2 | Captura del crédito; costos reales del E3 | Media | Todas | Captura de facturación |
| 12 | Pruebas técnicas | Funcionales y HA parciales | E2 §16 | T1–T10 | **Crítica** | Todas | T1–T10 |
| 13 | Documentación técnica | E2 completo en Word | Word v2 | Informe E3 + diagramas + evidencias | Alta | — | Revisión |
| 14 | Sustentación y defensa | Guion E2 desactualizado | Guion E2 | Guion E3 y ensayo | Alta | — | Ensayo |

**B. Metas del equipo (no confirmadas por el profesor)**

| Meta | Estado | Pendiente | Prioridad | Nubes | Prueba |
|---|---|---|---|---|---|
| Failover automático si cae AWS | No existe | Gateway + sitio caliente | Crítica | GCP, AWS | T1 |
| RTO ≤ 10 s | **No verificado**; solo lectura plausible | Medición real | Alta | GCP | T1, T3 |
| RPO ≈ 0 | **No verificado**; exige DB-B | Decidir A o B; medir | Media | AWS, GCP, OCI | T4 |
| Cuatro nubes con función real | Tres existen; GCP sin cuenta | Cuenta, Terraform, función | Alta | GCP | Revisión |
| Retorno seguro a AWS | No existe | Procedimiento y prueba | Alta | Todas | T8 |
| Sin reservas duplicadas | Garantizado en AWS; no entre nubes | Prueba entre nubes | Crítica | Todas | T5 |
| Costos controlados | Proceso de apagado existente | Lista por ventana | Alta | Todas | Verificación de apagado |

---

## 11. Plan de trabajo por fases

Cada fase termina con evidencia archivada y se detiene a esperar tu autorización.

| Fase | Contenido | Prioridad | Cambios en la nube |
|---|---|---|---|
| **0 — Decisiones (sin costo)** | Confirmar rúbrica/fecha E3; decidir DB-A o DB-B; decidir GCP o plan B; consultar **solo lectura** los permisos de RDS/Academy, cuotas de OCI y el saldo del crédito | Indispensable | Ninguno |
| **1 — Cuenta y esqueleto GCP** | Tú creas la cuenta y el proyecto; yo preparo `infra/gcp` con `validate` y `plan` (sin `apply`) y presupuesto con alertas | Indispensable | Solo la cuenta nueva, con tu permiso |
| **2 — Sitio pasivo** | Contenedor del backend y réplica en GCP (y/o OCI) con base de **prueba**, nunca con datos reales sin tu OK | Indispensable | Recursos nuevos en GCP, autorizados uno a uno |
| **3 — Gateway y failover de web** | HAProxy + LB global, health checks, ensayo con un «AWS» simulado | Indispensable | GCP |
| **4 — Réplica de datos y promoción** | Replicación, secuencias, concesión de escritura, fencing, quórum | Indispensable | AWS (parámetro de RDS) **solo con autorización explícita** |
| **5 — Medición** | Scripts de RTO/RPO, T1–T10, evidencias con fecha | Indispensable | Ventanas cortas de AWS |
| **6 — Retorno a AWS** | Failback y su medición | Indispensable | AWS |
| **7 — Documentación y defensa** | Informe E3, diagramas, capturas reales, presentación, guion y ensayo | Indispensable | Ninguno |
| Opcional | DB-B con RPO ≈ 0; dominio propio con DNS de respaldo; segundo gateway regional; activo-activo de lectura | Mejora | Según caso |

**Cronograma orientativo (3 semanas desde la autorización; ajustar a la fecha real del E3):** semana 1 = fases 0–2; semana 2 = fases 3–5; semana 3 = fase 6–7 y ensayos. Las ventanas de AWS se agendan con el crédito disponible.

---

## 12. Riesgos principales

- Declarar RTO/RPO sin medir (por eso están como **meta**).
- Que el gateway en GCP se convierta en el nuevo punto único de falla.
- Permisos de Academy insuficientes para la réplica lógica (comprobación previa en la fase 0).
- Dejar recursos encendidos y gastar crédito.
- Replicar datos personales a otra nube sin tu aprobación (usar datos de prueba hasta decidir).
- Cambios de DNS o de dominio: no se tocan sin autorización.

---

## 13. Primer paso recomendado

**Fase 0, solo lectura y sin costo:** (1) confirmar la fecha de entrega y el reparto de puntos de la rúbrica, y (2) con tu permiso, hacer una consulta de solo lectura en AWS para comprobar si tu rol de Academy permite crear un grupo de parámetros de RDS con replicación lógica (esto decide entre DB-A y DB-B), junto con revisar el saldo del crédito. Con eso se fija la arquitectura final antes de abrir la cuenta de Google.

## Actualización 9-nov-2026 · Prueba local de failover (verificado)
Se ejecutó un laboratorio local (Docker, sin nubes): HAProxy + 2 instancias del backend + PostgreSQL única. 16 de 16 comprobaciones OK. Interrupción medida de 2–3,3 s con ≈ 2 % de solicitudes fallidas en la caída de la app principal; sin sobreventa ni reservas duplicadas con reintentos idempotentes; sesiones y QR válidos entre instancias. **No hay replicación de BD: RPO no medido, no se declara RPO cero.** Con la BD caída HAProxy no conmuta (app ≠ BD). Detalle, límites y componentes pendientes: `03-prueba-local-failover.md`; evidencia en `evidencias/local-20261109/`.

## Actualización 10-nov-2026 · Replicación y failover de BD en Docker (verificado)
Laboratorio local `nexo-repl-lab` (PostgreSQL 18 ×2 con replicación lógica asíncrona, witness con lease y época, HAProxy HTTP y de BD, fencing en capas con arranque cerrado). Corridas finales: A+E 8/8, B 13/13, C 10/10, D 5/5. Medido: RTO de escritura 3,1–4,4 s y de lectura 3,2–4,4 s ante la caída del escritor con carga (todos los errores fueron 503); 0 reservas confirmadas perdidas en 3 corridas naturales (observación, **no RPO cero**) y 328 perdidas con retraso inducido de 3 s; sin sobreventa ni duplicados con reintentos idempotentes; con caída tras confirmar y antes de responder, la misma clave devuelve la misma reserva si había replicado y crea otra (duplicado lógico detectado en el rescate) si no. Sin doble escritura **observada** (muestreo; no es una prueba de ausencia de split-brain). El aislamiento de Docker es solo una simulación: no es trasladable a RDS sin un diseño específico AWS–OCI. Detalle, fallos intermedios y límites: `04-prueba-replicacion-failover-bd.md`. El HTTP 500 de `/api/events` del informe anterior era un artefacto de una imagen antigua (el código actual devuelve 503).

## Actualización 10-nov-2026 · Protección de reservas confirmadas con replicación síncrona (verificado en Docker)
Estrategia síncrona con estado de protección coordinado en el witness (CAS por secuencia y época), compuerta de promoción con lectura fresca y verificación reciente, política de esperar por defecto y fencing en capas. Etapa F: **33/33** (F0–F9, F4b, F5c, F5x) y F4R **5/5**. Observado: 0 reservas confirmadas perdidas en 5 caídas con carga en modo `protected` (≈ 7 500 confirmadas), frente a 328 en asíncrono con 3 s de retraso; RTO de escritura 3,3–3,8 s con errores 503; en modo `degraded` la promoción automática se bloquea y, si se ordena la insegura, se pierde lo confirmado sin protección (511 en F5). **No se declara RPO cero ni disponibilidad continua.** Compatibilidad con AWS RDS y OCI sin verificar (¿permite RDS `synchronous_standby_names`?). Detalle: `06-informe-estrategia-sincrona.md`.

## Actualización 10-nov-2026 · Viabilidad de la integración AWS Academy ↔ OCI (solo documentación; nada consultado en la nube)
Recomendación: no trasladar la replicación síncrona entre nubes; recuperación entre nubes con respaldos frecuentes a OCI (RPO medido en minutos), conmutación controlada con lease + compuerta que falla cerrada, y RDS Multi-AZ intacto. Comprobaciones de solo lectura preparadas y **sin ejecutar** (`scripts/multicloud/viabilidad-readonly-aws.sh`, `viabilidad-readonly-oci.sh`). Informe, alternativas, plan por fases con criterios de aceptación y decisiones pendientes: `07-viabilidad-integracion-aws-oci.md`.
