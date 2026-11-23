# Entregable 3 · Viabilidad de la integración AWS Academy ↔ OCI y recomendación de arquitectura (10-nov-2026)

**Fase de evaluación: no se modificó, inició, detuvo ni creó nada en AWS, OCI ni Azure; no se consultó ninguna nube.** Todo sale del repositorio, de los estados Terraform locales (`work/terraform-state/*`, solo lectura de los archivos) y de la documentación. Lo que dependa del estado real de las nubes está marcado **no verificado** y se resuelve con comprobaciones de solo lectura ya preparadas (§4) que esperan tu autorización. Sin commits ni push; el laboratorio Docker y las evidencias se conservan.

## 1. Recomendación en una página
1. **No trasladar la replicación síncrona a AWS–OCI.** Fue una buena herramienta para entender y medir el problema (etapa F, informe `06`), pero entre nubes cada COMMIT esperaría el viaje de ida y vuelta (OCI está en São Paulo según `docs/multicloud/08`: del orden de 100–130 ms desde us-east-1, **estimación no medida**), bloquearía las escrituras si el enlace falla y probablemente RDS no permita un suscriptor externo síncrono (no verificado). Es más compleja de lo que el proyecto necesita.
2. **Base recomendada, alcanzable con lo que ya existe: recuperación entre nubes con RPO medido en minutos y conmutación controlada** (Niveles 1 y 2 del §7). Se apoya en piezas ya probadas: respaldo lógico cifrado, transferencia a OCI, restauración con huella verificada, recuperación de la aplicación en OCI y observabilidad externa en Azure.
3. **Tres planos separados** (§6): *failover de aplicación* (sondas externas + DNS), *replicación de datos* (respaldos frecuentes enviados a OCI; replicación lógica asíncrona solo como extra opcional) y *protección contra doble escritura* (un lease en un objeto con compare-and-set + compuerta en los gateways de ambos sitios, que falla cerrada).
4. **Mantener RDS Multi-AZ** (ya probado, failover ≈ 14 s). No migrar a PostgreSQL en EC2 salvo que una comprobación demuestre que RDS bloquea lo imprescindible.
5. **Honestidad de cifras:** RTO realista entre nubes de **minutos** (arranque de la VM de OCI, restauración, DNS), no 10 s; RPO igual al intervalo de respaldo más la transferencia (p. ej. 5–15 min). Se declaran solo cifras medidas. Nada de RPO cero.
6. **Antes de crear nada nuevo** en OCI hace falta decidir y autorizar un punto de entrada público (hoy la subred es privada sin Internet Gateway ni IP pública) y una VM (A1 sin capacidad el 23-oct; E5 de pago con crédito de prueba).

## 2. Lo que existe (según repositorio y estados locales; fechas = última escritura del estado)
| Nube | Recurso | Estado según el repositorio | Fecha del dato |
|---|---|---|---|
| AWS | VPC `10.20.0.0/16`; subredes pública-a, datos-privada-a/b; IGW; SG web y base | desplegado (V1); V2 (ALB + ASG 2–3 en 2 AZ) **destruida**, reproducible (`infra/aws-v2`) | estado 4-nov; V2 destruida 6-nov |
| AWS | RDS PostgreSQL **18.3** `db.t3.micro`, **Multi-AZ**, gp2 20 GiB (máx. 20), privada, cifrada, retención 7 d, CA `rds-ca-rsa2048-g1`, grupo de parámetros **`default.postgres18`** (no editable), IAM DB auth desactivado | estado `stopped` | 4-nov |
| AWS | EC2 V1 `t3.small`, perfil `LabInstanceProfile`; S3 privado versionado; Secrets Manager; CloudWatch; SNS | detenida / conservados | 4-nov |
| AWS | Medidas conservadas | failover RDS Multi-AZ ≈ 14 s (22-oct); restauración PITR con RPO de 3 min 32 s; V1 vs V2 hasta 50 usuarios | `docs/multicloud/01`, evidencias |
| OCI | Compartment `nexoeventos`, VCN `10.30.0.0/16`, subred privada `10.30.1.0/24` (**sin IP pública**), Service Gateway, NSG, tabla de rutas privada, lista de seguridad bloqueada | creado | 23-oct |
| OCI | Bucket `nexoeventos-recovery` (Standard, **versionado**, sin acceso público); grupo/usuario/política de subida (**solo** crear/leer/inspeccionar; sin borrar ni sobrescribir) | creado | 23-oct |
| OCI | **No hay** Internet Gateway, NAT, VM ni IP pública (la VM de recuperación se destruye tras cada simulacro) | — | 23-oct |
| OCI | Región (según `08`): São Paulo, AD-1. Formas: A1.Flex Always Free **sin capacidad**; E5.Flex 1 OCPU/8 GB disponible pero **de pago con crédito de prueba** (requiere aprobación); E2.1.Micro Always Free (≈ 498 MB útiles: insuficiente) | consultado | 23-oct |
| OCI | Simulacro de restauración (huella: 135 reservas, 135 entradas, 25 usuarios, Alembic 0008) y diseño de la recuperación de la aplicación (`08`: **diseñado**, plan de Terraform revisable) | restauración probada; app en OCI: diseño | 23-oct |
| Azure | VM `Standard_D2s_v4` (Zabbix + Grafana + PostgreSQL), red, Log Analytics, Monitor, presupuesto; acceso por Tailscale | desplegado, **VM desasignada** | 28-oct / 9-nov |
| Cuentas | AWS Academy con crédito hasta el 26-nov (≈ 16 días desde hoy; USD 11,2 de 50 declarados el 5-nov); AWS personal Free plan (US$100 / 6 meses, **sin pasar a Paid**) | — | `docs/operacion/calendario-credito-aws.md`, `02` |
| App | `TICKET_ENCRYPTION_KEY` y `SECURITY_HASH_KEY` necesarias en cualquier sitio que valide QR; la app **exige `sslmode=verify-full`** para cualquier BD no local | código | — |

**Advertencia:** los estados locales pueden estar desactualizados (p. ej. el de OCI es del 23-oct); su verificación real es la parte de OCI del §4.

## 3. Compatibilidad de la estrategia síncrona con AWS RDS
| Requisito de la estrategia (informes 05/06) | Compatibilidad con RDS | Estado |
|---|---|---|
| Replicación lógica activada (`rds.logical_replication`) | Parámetro **estático** (reinicio; en Multi-AZ, un failover ≈ 14 s) y exige un grupo de parámetros **personalizado**; hoy se usa `default.postgres18` | Documentación: sí. **Permisos de Academy para crear/aplicar el grupo: no verificado** |
| Rol de replicación | `rds_replication` / `rds_superuser` disponibles en RDS | Documentación: sí. No verificado en la instancia |
| Suscriptor **externo** (en OCI) leyendo de una RDS **privada** | Requiere camino de red al RDS (VPN/peering/relé). La subred de OCI no tiene Internet Gateway ni NAT; en Academy VPN/Transit Gateway **no verificados** | **No viable hoy sin crear red nueva** |
| `synchronous_standby_names` con la suscripción como candidata síncrona | La tabla pública de parámetros de RDS es parcial: lista `synchronous_commit` (dinámico) pero **no** `synchronous_standby_names`; ninguna fuente oficial lo declara modificable o no | **No verificado** (`describe-db-parameters` → `IsModifiable`) |
| Barrera de LSN, `pg_stat_replication`, slots | Vistas estándar; los slots inactivos pueden llenar el disco (20 GiB máx.) | Documentación: sí |
| `pg_hba` cerrado y arranque cerrado (fencing local) | **No disponible**: RDS no da acceso a `pg_hba` ni al arranque | **No trasladable** |
| `ALTER SYSTEM` para el solo-lectura/síncrono | No existe: se usan grupos de parámetros | **No trasladable** |
| Fencing del escritor antiguo cuando cae AWS | Sin API de AWS no se puede aislar nada | **No trasladable**: hace falta compuerta propia (§6) |
| TLS `verify-full` entre la app y la BD | Para RDS se instala el bundle de CA (ya resuelto en V1/V2) | Probado en AWS; para OCI exige certificado con el nombre usado |
| RTT AWS↔OCI | Si OCI está en São Paulo, ~100–130 ms por COMMIT síncrono (no medido) | **No medido**; desaconseja el síncrono |
**Conclusión:** del trabajo de la etapa F se traslada el **método** (invariantes, medición, estado de protección, compuerta, tratamiento de inciertas y duplicados), no la garantía ni la mayoría de los mecanismos de Docker.

## 4. Comprobaciones de solo lectura preparadas (NO ejecutadas; esperan tu autorización)
Dos scripts ya escritos (verificada su sintaxis; nada se ejecutó):
- `scripts/multicloud/viabilidad-readonly-aws.sh [identidad|rds|parametros|permisos|red]`: exige `NEXO_READONLY_VIABILIDAD=YES`, un laboratorio de Academy iniciado y credenciales renovadas; toda la salida pasa por `scripts/cloud/mask.sh` (sin cuenta, ARN, IP ni correos). Comandos (todos `describe`/`get`/`simulate`): `sts get-caller-identity` (solo el tipo de principal); `rds describe-db-instances` (estado, versión, Multi-AZ, grupo de parámetros, acceso público, almacenamiento); `rds describe-events` (arranques automáticos a los 7 días); `rds describe-db-parameter-groups`; `rds describe-db-engine-versions`; **`rds describe-db-parameters --db-parameter-group-name default.postgres18` filtrado a `synchronous_standby_names`, `synchronous_commit`, `rds.logical_replication`, `wal_level`, `max_wal_senders`, `max_replication_slots`, `max_logical_replication_workers`, `max_slot_wal_keep_size`, `wal_sender_timeout`, `rds.force_ssl`…, mostrando `IsModifiable` y `ApplyType`**; `iam simulate-principal-policy` para `rds:CreateDBParameterGroup`, `rds:ModifyDBParameterGroup`, `rds:RebootDBInstance`, `ec2:CreateVpnGateway`, `ec2:AllocateAddress`, etc. (puede devolver AccessDenied en Academy: entonces la única prueba fiable de un permiso es intentarlo, y eso necesita otra autorización); `ec2 describe-*` de VPC, subredes, rutas, SG, VPN, IP elásticas.
- `scripts/multicloud/viabilidad-readonly-oci.sh`: exige la CLI de OCI ya instalada (no se instala sin permiso) y la configuración local `~/.oci/config`; comandos `list`/`get`: regiones, compartment, VCN, subredes (`prohibit-public-ip-on-vnic`), Internet/NAT/Service Gateway, **instancias** (¿queda algo encendido?), buckets, capacidad y límites de cómputo (A1, E5, E2.1.Micro), cuotas. Salida enmascarada (OCID, IP, correos).
Notas: las comprobaciones de AWS **requieren que inicies el laboratorio de Academy** (eso lo haces tú). RDS está `stopped` según el estado local: `describe-db-parameters` y `describe-db-parameter-groups` no lo necesitan encendido. Revisar además la fecha límite de reinicio automático de RDS (7 días detenida; riesgo de crédito).

## 5. Alternativas para los datos
| | A · RDS + respaldos frecuentes a OCI (**recomendada**) | B · RDS + replicación lógica asíncrona a OCI (opcional, solo si §4 lo permite) | C · PostgreSQL autogestionado en EC2 | D · Solo restauración manual desde el último respaldo |
|---|---|---|---|---|
| RPO esperado | intervalo (5–15 min) + transferencia; **medible** (`edad del último respaldo verificado`) | segundos, **medido** como retraso; pérdida posible | segundos (asíncrono); síncrono desaconsejado por RTT | horas/días |
| Ventajas | usa lo ya probado (respaldo CMS, restauración con huella); sin cambios en RDS; sin red entrante; barata | RPO bajo; datos casi al día en OCI | control total (parámetros, `pg_hba`, síncrono) | trivial |
| Riesgos / complejidad | pérdida de hasta un intervalo; hay que automatizar el envío (EC2 → URL de subida preautenticada de solo escritura, guardada en Secrets Manager; la OCI no tiene claves en AWS) | exige grupo de parámetros propio + reinicio, rol, **camino de red hacia una RDS privada** (relé EC2 con IP elástica o VPN) y NAT/IGW en OCI; permisos de Academy sin verificar; slots pueden llenar el disco | pierde lo gestionado (Multi-AZ, respaldos, parches); más operación y riesgo; TLS y certificados propios; hay que reconstruir lo ya medido | no cumple RTO/RPO razonables |
| Costo (tarifas del repo, a verificar) | EC2 ya existente + S3/OCI Object Storage ≈ centavos; VM de OCI solo en ventanas | + relé EC2 (t3.small ≈ USD 0,0208/h) y posible VM de OCI de pago | EC2 `t3.small` ≈ USD 0,0208/h por nodo + disco | 0 |
| Encaje con lo que exige la rúbrica | cubre RTO/RPO, multicloud, backup, pruebas con cifras medidas | mejora el RPO; más IaC y pruebas | más IaC | insuficiente |
**Recomendación:** A como base obligatoria; B solo como extra si las comprobaciones lo permiten y sobra tiempo; C solo si RDS bloquea algo imprescindible y el profesor exige replicación continua; D descartada.

## 6. Arquitectura recomendada: tres planos
```
Usuarios ─HTTPS─> DNS (TTL corto) ──> [AWS] ALB ─> ASG 2–3 EC2 ─> RDS Multi-AZ (escritor)
                       │                         └─ envío de respaldo cifrado cada N min ─(HTTPS, URL de solo escritura)─> [OCI] bucket
                       │                                                                                            │
                       └──(tras conmutar)──> [OCI] IP pública + Nginx ─> app ─> PostgreSQL restaurado (solo lectura hasta promover)
 Lease (objeto con ETag, solo lectura/escritura condicional): {escritor: aws|oci, época}  — en OCI Object Storage o Azure Blob
 Sondas independientes: Azure (Zabbix/HTTP) + OCI → controlador pequeño que propone/ejecuta la conmutación
```
**Plano 1 · failover de aplicación.** Detección: sondas externas a `/healthz` (ya existen en Azure/Zabbix) más una sonda desde OCI; la VM de OCI con la app y PostgreSQL se arranca/restaura bajo demanda (*pilot light*) o se mantiene encendida solo en ventanas de prueba (crédito). Conmutación: cambiar el DNS (TTL corto; DuckDNS ya se usa) hacia la IP pública de OCI. RTO esperado: arranque + restauración + DNS = **minutos, a medir**. Requiere un punto de entrada público en OCI (Internet Gateway + IP pública + NSG a 443 + certificado): **recurso nuevo, requiere autorización**.
**Plano 2 · datos.** Nivel A: respaldo lógico cifrado cada N min → OCI (reutiliza `db-backup-cms.py`, la transferencia y la restauración probadas) con verificación de huella; el RPO real se calcula como *instante de la caída − instante del último respaldo verificado*. Nivel B (opcional): replicación lógica asíncrona vía relé, midiendo retraso.
**Plano 3 · doble escritura.** Un **lease** en un objeto con compare-and-set por ETag (OCI Object Storage o Azure Blob, ambos fuertemente consistentes; sin servidor siempre encendido; requiere un permiso de sobrescritura en un bucket/prefijo **distinto** del de respaldos, que hoy no permite sobrescribir). Una **compuerta en cada sitio** (Nginx `auth_request` hacia un comprobador local, sin tocar el backend): las operaciones de escritura (POST/PUT/PATCH/DELETE) solo se aceptan si el lease dice que *este* sitio es el escritor; si no se puede leer el lease, **falla cerrada**. La base de OCI permanece en solo lectura y con acceso cerrado hasta promover. Límite honesto: si cae todo AWS no se puede aislar RDS por API; la compuerta de AWS protege cuando AWS vuelve (las EC2 comprueban el lease al arrancar y no aceptan escrituras mientras el lease sea de OCI), pero RDS sigue siendo accesible a otros clientes dentro de la VPC.

## 7. Plan incremental con criterios de aceptación (prioridad = rúbrica de 14 criterios; pesos y fecha de entrega **pendientes**)
| Fase | Qué | Prueba / criterio de aceptación | Criterios de la rúbrica | Autorización necesaria |
|---|---|---|---|---|
| 0 | Comprobaciones de solo lectura (§4) | informe con `IsModifiable`, permisos, red, estado real de OCI; todo enmascarado | 1, 2, 10 | scripts de solo lectura + Start Lab |
| 1 | **Respaldos frecuentes AWS→OCI automatizados** + restauración verificada en OCI (VM temporal, ya diseñada) | RPO medido = edad del último respaldo verificado; huella idéntica; RTO de restauración medido; 3 repeticiones | 4, 9, 10, 12 | crear URL de subida, temporizador en la EC2, VM de OCI en ventana |
| 2 | **Punto de entrada público en OCI** + app recuperada (diseño `08`) + secretos de la aplicación | `/healthz` 200 por HTTPS desde fuera; login y reserva de prueba en OCI con datos restaurados; sin DNS de producción tocado | 3, 5, 10, 12 | IGW/IP pública/NSG/certificado y VM (costos) |
| 3 | **Conmutación controlada AWS→OCI** (script con confirmación): lease + compuerta + DNS | RTO medido de punta a punta (3–5 repeticiones); en OCI se escribe y en AWS no (escritura real rechazada); lease inalcanzable ⇒ sin escrituras | 6, 9, 10, 12 | bucket/permiso del lease, cambio de DNS en ventana |
| 4 | **Failback manual** y rescate de huérfanas (procedimiento del informe `04`, generalizado) | antiguo sitio reconstruido sin sobrescribir datos válidos; huérfanas exportadas fuera de la nube; duplicados lógicos listados | 9, 12, 13 | ventana controlada |
| 5 | **Conmutación automática** de la capa de aplicación (detección ×N sondas, quórum con la sonda de Azure, el mismo lease) | conmutación sin intervención humana en prueba; doble escritura **no observada** en pruebas de escritura real; falla cerrada si el lease no responde | 6, 7, 12, 14 | controlador en OCI/Azure |
| 6 | (Opcional) replicación lógica asíncrona RDS→OCI | solo si §4 lo permite: retraso y RPO medidos, sin declarar cero | 6, 9 | grupo de parámetros + relé |
| 7 | Documentación, costos reales y sustentación | informe con cifras medidas, límites y diferencias Docker/nube; ensayo de defensa | 8, 11, 13, 14 | — |
IaC (criterio 8): cada recurso nuevo en Terraform con estado propio (`infra/oci`, un módulo nuevo para el punto de entrada y el lease), con `fmt`/`validate` y comprobaciones estáticas; nada se aplica sin plan revisado.
Calendario: el crédito de Academy llega al 26-nov; hay que agendar las ventanas (RDS y EC2 encendidos solo en ellas) y decidir qué se hará con la cuenta personal Free plan (sin pasar a Paid) si la entrega es posterior.

## 8. Transacciones inciertas, duplicados lógicos y la observación F4
- **Qué son aquí.** Con respaldos frecuentes (Nivel A), todo lo escrito entre el último respaldo y la caída se **pierde** (RPO = ese intervalo); no hay "inciertas" en OCI porque OCI no tiene esas filas. Las **inciertas** aparecen cuando el sitio antiguo se puede recuperar (RDS PITR/instantánea, o el RDS vuelve): contiene filas confirmadas localmente que OCI no vio.
- **Qué hacer.** (1) Exigir siempre `Idempotency-Key` (la app ya lo hace). (2) Tras conmutar, **no reutilizar automáticamente** el sitio antiguo: conservarlo en solo lectura, exportar fuera de la nube las filas que no están en el nuevo escritor (procedimiento de huérfanas ya probado) y clasificarlas: *confirmada al cliente y perdida* (RPO observado), *incierta* (sin respuesta al cliente) y *duplicado lógico* (misma clave de idempotencia con otra reserva en el nuevo escritor). (3) Regla de negocio acordada: la reserva del nuevo escritor prevalece; las huérfanas se anulan con trazabilidad y, si procede, se notifica al comprador; los pagos son simulados, no hay cobros reales. (4) Nunca fusionar automáticamente.
- **F4 sin explicación.** Se mantiene como **observación abierta**: en una corrida contó 5 confirmaciones con el seguidor caído y no se reprodujo en 6 mediciones posteriores bien definidas. No condiciona esta arquitectura (no usa sincronía entre nubes). Compromisos: (a) en cualquier prueba real se registrarán los instantes de confirmación y de caída para auditar el invariante "toda reserva confirmada existe en el destino"; (b) si algún día se adopta replicación síncrona, se exigirán repeticiones suficientes (≥ 30) en la infraestructura destino antes de afirmar nada; (c) no se usa como evidencia a favor ni en contra.

## 9. Riesgos y decisiones que necesito de ti
1. **Autorización** para ejecutar los dos scripts de solo lectura (y que inicies el laboratorio de Academy). Puedo empezar solo por OCI, que no depende de Academy.
2. **Qué exige el profesor** en RPO/RTO y replicación: ¿vale "recuperación entre nubes con RPO en minutos y RTO medido", o pide replicación continua? Pesos de la rúbrica y fecha de entrega siguen sin conocerse.
3. **Punto de entrada público en OCI** (IGW, IP pública, certificado): ¿lo autorizas como recurso nuevo y dentro del crédito de prueba?
4. **Forma de la VM de OCI:** A1 si hay capacidad; si no, E5.Flex de pago con crédito de prueba (aprobación explícita, como ya estaba previsto).
5. **Dónde corre el controlador** de conmutación (OCI o Azure) y quién provee el lease (OCI o Azure Blob).
6. **Plazos:** crédito de Academy hasta el 26-nov.
Riesgos principales: permisos de Academy (RDS/VPN/IAM) sin verificar; capacidad y costo de la VM de OCI; RDS que se reinicia solo a los 7 días detenida; secretos de la aplicación (`TICKET_ENCRYPTION_KEY`, `SECURITY_HASH_KEY`) en OCI; que el RTO real entre nubes sea de varios minutos; y que la validación de la etapa F en Docker no se traduzca en garantía alguna.

## Actualización 10-nov-2026 21:45 · Primera consulta real de solo lectura a OCI (parcial)
Ejecutada con la versión v3 del script (autorizada por su SHA-256; evidencia: `evidencias/oci-consulta-solo-lectura-v3-20261110.txt`). Pasos 1–4 completados; el paso 5 (límites de cómputo) falló por una opción de la CLI no admitida (`--output text`) y el script se detuvo solo, sin cambios.
- Región de origen: **`sa-saopaulo-1`**, READY; única suscripción.
- VCN `nexoeventos-recovery-vcn` (/16) AVAILABLE; subred `nexoeventos-recovery-private` (/24) **sin IP pública**; Service Gateway `nexoeventos-recovery-sgw` AVAILABLE. **Sin Internet Gateway y sin NAT** (listas vacías). Coincide con el estado Terraform local del 23-oct: no se observa deriva.
- **Sin instancias** (nada encendido ni facturando). Bucket `nexoeventos-recovery` existe.
- Pendiente: límites de A1/E5/micro (v4 preparada, sin ejecutar).
Consecuencia para el plan: el punto de entrada público de OCI (Internet Gateway + IP pública) **sigue por crear** y requiere autorización; la subred actual solo sirve para recuperación por Bastion.

## Actualización 10-nov-2026 21:49 · Consulta de solo lectura de OCI completada (script v4, SHA-256 `04c4b76c…287c`)
Evidencia: `evidencias/oci-consulta-solo-lectura-v4-20261110.txt` (código de salida 0). Solo consultas `list`/`get`; no se creó, modificó, inició ni detuvo nada.
- Confirmado lo de la actualización anterior: región de origen `sa-saopaulo-1`; VCN y subred privada (sin IP pública); Service Gateway; **sin Internet Gateway ni NAT**; **sin instancias**; bucket `nexoeventos-recovery`.
- **Cuotas de cómputo (usado 0 en todas):** `standard-a1-core-count` 41 núcleos por dominio (regional: 16) y 277 GB de memoria (regional: 96); `standard-e5-core-count` 13 núcleos y 208 GB; `standard-e2-micro-core-count` y `vm-standard-e2-1-micro-count`: 2. Son **cuotas**, no capacidad de hosts: el 23-oct A1 devolvió `OUT_OF_HOST_CAPACITY`, y eso solo se vuelve a saber intentando crear o con un informe de capacidad (operación de creación, fuera de alcance por ahora).
- Lectura para el plan: hay cuota para una VM A1 o E5 sin pasar de los límites; el coste de E5 sigue siendo con crédito de prueba (no consultado) y la capacidad real de A1 sigue sin confirmar. El punto de entrada público (IGW + IP pública) sigue por crear con autorización.
