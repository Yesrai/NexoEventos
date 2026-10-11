# Lectura AWS sanitizada — 9 de octubre de 2026

Fuente: consultas API de solo lectura ejecutadas en `us-east-1` durante la ventana E01. Se ocultaron cuenta, ARN, endpoints, IPv4 e identificadores completos. La captura describe configuración efectiva; los estados de cómputo corresponden a la toma previa a la parada final.

| Evidencia | Resultado comprobado |
|---|---|
| EV02 VPC | `10.20.0.0/16`, estado `available`, DNS hostnames habilitado, etiquetas NexoEventos/academy/Terraform |
| EV03 subredes | pública `10.20.1.0/24` en `us-east-1a`; datos privadas `10.20.21.0/24` y `10.20.22.0/24` en dos AZ |
| EV03 rutas | tabla pública con `0.0.0.0/0` al IGW; tabla de datos solo con ruta local `10.20.0.0/16` |
| EV04 web SG | entrada TCP 80/443 pública; sin puerto 22; salida 5432 solo al SG de datos, DNS VPC y HTTPS |
| EV04 DB SG | entrada TCP 5432 exclusivamente desde el SG web; sin reglas de salida explícitas |
| EV05 EC2 | `t3.small`, Amazon Linux fijado, `us-east-1a`, IMDSv2 `required`; activa durante E01 y confirmada `stopped` al cierre |
| EV06 RDS | PostgreSQL 18.3, `db.t3.micro`, privada, Single-AZ, cifrada, 20 GiB, máximo 20 GiB, backup 7 días; confirmada `stopped` al cierre |
| EV07 S3 | bloqueo público completo, versionado habilitado y cifrado AES-256; SSE-C bloqueado |
| EV07 snapshots | manuales y automáticos disponibles, cifrados, 20 GiB; `LatestRestorableTime` 2026-10-09 15:39 UTC al cierre |
| EV08 alarma | CPU EC2 `OK`, umbral 80 %, dos periodos de 300 s |
| EV08 logs | dos grupos con retención 7 días, pero 0 bytes y 0 streams; recepción no demostrada |

El inventario fue capturado antes y después de E01. Los resúmenes de rendimiento y BD están en [EV11](EV11/resultado-2026-10-09.md). Las capturas gráficas de consola siguen pendientes; esta lectura API no se presenta como sustituto visual.
