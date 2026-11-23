# Fase B2 — Nueva AMI de V2 con `/livez` (4-nov-2026, saneado)

**Estado: AMI CREADA (`available`), constructor ELIMINADO, `/livez` validado en el constructor.** La validación de `/livez` en una instancia real del ASG sigue **PENDIENTE (Fase C/D)**.

## Preparación (sin recursos creados)
- Reutilizado `scripts/cloud/v2-prepare.sh` (`builder-launch`, `builder-image`, `builder-delete`) y `scripts/ansible-aws.sh bake` (playbook `bake-v2.yml`). Sesión válida; EC2 V1 `running`, RDS `stopped`; sin constructor, SG ni volúmenes previos; crédito 40,20 USD (lectura de la usuaria, 9,80 usados).
- Constructor: `t3.small`, 20 GiB gp3 cifrado (`DeleteOnTermination`), IMDSv2 obligatorio, SG temporal **sin reglas de entrada** y salida solo TCP 443 y TCP/UDP 53, **IP pública pedida explícitamente**. Etiquetas `Name=nexoeventos-academy-v2-bake`, `Project=NexoEventos`, `Purpose=ami-bake`.
- Hallazgo del procedimiento: `build-release.sh` se niega a empaquetar con cambios sin commit. Se construyó el artefacto del commit **c8092b6** (el aprobado por el CI) desde un **clon local limpio de `HEAD`** (sin commit ni push, sin tocar el árbol de trabajo). El artefacto no contiene `.env`, claves, `tfstate` ni `tfvars`; contiene el bloque nginx `location = /livez`.

## Construcción
- **Prueba de la subred (A2):** el constructor se lanzó en `public_a` con la subred ya en `MapPublicIpOnLaunch=false`; recibió IP pública por la petición explícita, SSM pasó a `Online` y Ansible alcanzó internet: **A2 validada con una instancia nueva real**.
- Ansible `bake-v2.yml`: `ok=24 changed=17 failed=0 unreachable=0`; la comprobación del propio playbook («sin secretos ni certificados») pasó.
- Ventana del constructor: 15:30–15:42 UTC (≈ 12 min).

## Validación de `/livez` en el constructor (runtime; API sin base de datos)
Con `nginx` y la API de la release arrancados **temporalmente** con variables ficticias no secretas (`DATABASE_URL` hacia un puerto cerrado) para probar el aislamiento de PostgreSQL:
| Escenario | `/livez` | `/healthz` | `/` |
|---|---|---|---|
| A) API detenida | **502** (nunca 200 por `index.html`) | 502 | 200 |
| B) API viva, **base de datos inalcanzable** | **200** `{"status":"ok","service":"nexoeventos-api"}` | **503** | 200 |
Es decir: `/livez` responde con la API viva aunque PostgreSQL no esté disponible y falla si la API está caída; `/healthz` (readiness) sí depende de la base de datos. `nginx -t` correcto. Tras la prueba: API y nginx detenidos, 0 procesos.
**Límite:** no es una prueba con el RDS real ni con tráfico del ALB; eso se valida en la Fase C/D.

## Ausencia de secretos en la imagen (antes de crearla)
`/etc/nexoeventos` vacío, sin `/etc/letsencrypt`, sin `backend.env`/`migration.env`/`duckdns.env`, sin credenciales o tokens de AWS en `/root`, `/home` ni `/etc`, sin `authorized_keys`, nginx sin `ssl_certificate` activo (solo las líneas de ejemplo comentadas de fábrica). Se **eliminaron las claves de host SSH** (`/etc/ssh/ssh_host_*`) para que no se compartan entre instancias (se regeneran al arrancar). Se limpiaron los registros (nginx, API, journal, SSM agent) y `cloud-init clean --logs`. Único otro hallazgo del barrido: un archivo `.py` de la librería `cryptography` que contiene el texto del patrón (falso positivo).

## AMI
| Dato | Valor |
|---|---|
| ID | `ami-0b9d9f97ca9623d3a` (nombre `nexoeventos-v2-20261104t153809z`) |
| Estado | `available`; snapshot `completed` 100 %, 20 GiB, cifrado |
| Arquitectura / virtualización | x86_64 / hvm; raíz EBS `/dev/xvda`; ENA activado; arranque `uefi-preferred` |
| Privacidad | **privada** (`Public=False`; 0 permisos de lanzamiento) |
| AMI antigua (22-oct) | **conservada**, `available` (no se deregistró ni se tocó su snapshot) |

## Limpieza verificada
Constructor `terminated`; SG temporal eliminado; **0 volúmenes huérfanos** (1 volumen, el de V1); **2 snapshots propios** (antigua + nueva). Sin recursos de cómputo temporales. Nota: el SG temporal mostró su ID (ya eliminado) en la salida de borrado.
- Restos no sensibles en el bucket privado: Ansible dejó **37 versiones no vigentes y 37 marcadores de borrado** nuevos en la raíz (`i-…/…`), como en sesiones anteriores; los 4 respaldos de `backups/database/` siguen vigentes. Limpieza opcional con una regla aparte (no creada).

## Certificados ACM (sin cambios; ninguno borrado)
Los dos certificados importados son **idénticos entre sí y al que sirve V1**: misma huella SHA-256, mismo número de serie, misma cadena (3 certificados), mismo dominio, ECDSA P-256, `ISSUED`, vencen el 1-ene-2027. Recomendación: **usar el ARN del anterior (`…/b8f2c28e-…`, importado el 21-oct)** para V2 y borrar el duplicado nuevo (`…/cb25088b-…`) como operación independiente que requiere autorización. La referencia exacta quedó guardada en `work/operacion/v2-certificate-arn` (local, ignorado por Git).

## Coste y recursos persistentes (estimación con tarifas públicas)
Constructor ≈ 12 min de `t3.small` + EBS ≈ **0,005 USD**. Persisten: la AMI y su snapshot de 20 GiB (cobro por datos usados, ≈ 2–3 GiB): ≈ **0,10–0,20 USD/mes**. Sin otros recursos persistentes. Hay dos AMI/snapshots mientras se conserve la antigua.
