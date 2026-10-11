# Estado del proyecto NexoEventos

| Dato | Valor |
|---|---|
| Fecha de corte | 10 de octubre de 2026 (Lima) |
| Commit desplegado comprobado | `7955e7e` el 7-oct; el HEAD local se indica en `git log` |
| URL pública | `https://nexoeventos-demo.duckdns.org`, **fuera de servicio mientras EC2 y RDS estén detenidas** |
| Estado AWS comprobado | 10-oct 19:23 Lima: EC2 `stopped`, RDS original `stopped` y cero RDS temporales, confirmados por API; reinicio automático estimado: 17-oct 19:23 Lima |
| Entrega final | 26 de noviembre de 2026 |

Convención de este documento:

- **Medido:** ejecutado y observado, con la fuente indicada.
- **Objetivo:** meta del caso o del laboratorio, no medida.
- **Supuesto:** cifra del caso empresarial o hipótesis de costo.

## Terminado (con evidencia)

| Área | Resultado medido | Fuente |
|---|---|---|
| Aplicación local | React/TS + FastAPI + PostgreSQL; autenticación, autorización, reservas transaccionales/idempotentes y QR; automatización Ansible corregida y versionada | historial Git, EV01 |
| Infraestructura AWS V1 | 30 recursos Terraform en `us-east-1`: VPC `10.20.0.0/16`, una subred pública, dos privadas de datos, rutas, IGW, SG web/DB, EC2 `t3.small` AL2023, RDS PostgreSQL 18.3 privada, S3 privado y versionado, 2 log groups y una alarma CPU | `outputs/informe-despliegue-aws-2026-10-03.md`, EV09 |
| Seguridad operativa | SSH cerrado, administración por Session Manager, FastAPI en `127.0.0.1:8000` con usuario sin privilegios, secretos `root:root 0600`, roles PostgreSQL `owner`/`migrator`/`app` sin atributos elevados, IMDSv2 | informe del 3 de octubre, EV05, EV06 |
| HTTPS público | DuckDNS + Let's Encrypt, válido del 3 de octubre de 2026 al 1 de enero de 2027, timers de renovación y DNS activos | EV10, `deploy/README.md` |
| Suite pública | Tras desplegar `7955e7e`: catálogo 27 sin asientos; registro 201, reserva 201, entrada privada, acceso operador 200, primer ingreso 200, segundo ingreso 409, estado usado, logout 204 y sesión posterior 401; cookies solo en memoria y QR no impreso | EV10 |
| Persistencia RDS | Alembic `0001`–`0005`; 3 registros históricos preservados y 27 eventos ficticios añadidos; sin eventos/asientos numerados habilitados | EV06 |
| Respaldo | snapshot cifrado de 20 GiB `nexoeventos-academy-preupdate-20261008t0113z` disponible; dump PostgreSQL 18.6 CMS en S3 y copia externa `0600`, descifrado y SHA-256 coincidentes | EV07 |
| Captura | portada pública actualizada en escritorio y móvil, sin sesión, secretos ni QR | EV10 |
| Carga cloud E01 | 20 VU × 300 s, 2 520 solicitudes, p95 421.2 ms, 0 % inesperados; 132 reservas/entradas sin sobreventa ni duplicados | EV11 |
| Restauración cloud R01 | PITR: RPO 3 min 32 s; RDS disponible 20 min 49 s; datos verificados 21 min 4 s; Alembic, seis tablas y 135 QR coinciden; temporal eliminada | EV07 |

## Diferencia local frente a AWS

| Componente | Local al 7-oct | AWS verificado por última vez | Sincronizado |
|---|---|---|---|
| frontend | versión visual actual hasta `7955e7e` | `7955e7e`, HTTPS `/ = 200` verificado el 7-oct | **Sí al cierre de la prueba** |
| backend/API | migraciones `0004`/`0005`, catálogo seguro y recorrido público | `7955e7e`, Alembic `0005`, `/healthz = 200`, 27 eventos | **Sí al cierre de la prueba** |
| infraestructura | AMI fija, RDS autoscaling explícito y prefijo S3 corregidos localmente | estado protegido serial 32; configuración remota previa | **No**; falta plan autenticado, no se aplicó Terraform |
| automatización | Ansible con artefacto, migraciones, health check y rollback | probado por SSM; rollback automático también observado durante un fallo controlado | **Sí para actualización V1** |
| evidencias | matriz y capturas históricas conservadas | inventario sanitizado y EV10 actual obtenidos el 7-oct | faltan capturas de consola EV02–EV04/EV06–EV08 |

## Pendiente

| Pendiente | Motivo / bloqueo | Preparado en esta revisión |
|---|---|---|
| Capturas de consola sanitizadas EV02, EV03, EV04, EV06, EV07, EV08 | requiere arrancar recursos | script y checklist revisados localmente; ejecución AWS pendiente |
| Recepción de CloudWatch Logs | grupos/retención existen, pero el 9-oct no había streams; agente no instalado | permisos de escritura del rol comprobados; falta preparar y desplegar configuración del agente |
| Configuración operativa protegida | completada localmente | reconstruida desde el estado real `academy-current` (serial 32), ignorada por Git y modo `0600`; valores no impresos |
| Recuperación completa del servicio | R01 midió datos, pero no conmutó aplicación, DNS ni HTTPS | preparar un entorno aislado de aplicación sobre la copia restaurada |
| Arranque/apagado verificable | hoy es manual | `scripts/cloud/cloud-session.sh` |
| Plan Terraform vigente (I01/EV09) | refresh autenticado termina por SCP Object Lock | resumen parcial 0 altas/1 cambio/0 bajas; **sin plan aplicable** |
| Actualización versionada de AWS | completada el 7-oct | `7955e7e`, Alembic `0005`, frontend/API/flujo HTTPS comprobados |
| Identificador `Equipo XX` del modelo oficial | falta confirmación docente; no se inventa | autora: Yesenia; proyecto individual; pendiente no bloqueante |
| Cámara física para QR | no probada; la alternativa por código sí | — |
| Captura pública con fecha/hora (tabla 15 del Entregable) | la existente (EV05) muestra solo la página: sin barra de direcciones, candado HTTPS ni fecha/hora | checklist § 2.2 |
| Registro de timestamps reales (`LaunchTime`/`InstanceCreateTime`) y consumo observado del panel | no consolidado en `costos-v1.md` | `cloud-session.sh` registra transiciones |
| Preparar el Entregable 2 oficial | requiere evolución V1→V2 y evidencias nuevas | contraste exacto en `docs/evidencias/revision-rubrica.md` |
| Repositorio remoto (fila SaaS de GitHub) | `git remote` vacío | — |
| Azure (continuidad) y GCP (analítica) | mejoras del proyecto, no proveedores exigidos por los Word oficiales revisados | — |

## Objetivos y mediciones vigentes

- E01: **medido y cumplido el 9-oct** con 20 usuarios virtuales durante 5 min, p95 421.2 ms y 0 % de errores inesperados.
- R01: **datos medidos** en 21 min 4 s y RPO 3 min 32 s; ambos dentro del objetivo. RTO del servicio completo ≤ 60 min sigue sin medir.
- V01: sin promesa de alta disponibilidad en V1; reponer una instancia en ≤ 120 s es una meta posterior.
- I01: plan sin cambios inesperados después de aplicar.

## Supuestos

- Las cifras empresariales (12 000 usuarios registrados, 500–700 concurrentes en campaña, 380 GB) describen el caso, no el laboratorio.
- Costo: USD 36.465 por 30 días continuos y techo planificado de USD 13.719 hasta el 26 de noviembre. Son estimaciones con tarifas públicas, no consumo observado (`docs/costos-v1.md`).

## Limitaciones reales

1. **Arquitectura de instancia única.** Una EC2 y una RDS Single-AZ son puntos únicos de falla; no hay ALB, Auto Scaling, Multi-AZ ni NAT. No se declara alta disponibilidad.
2. **Servicio intermitente por costo.** La URL solo funciona en ventanas activas. Al arrancar cambia la IPv4 y DuckDNS tarda hasta unos 5 min en actualizarse.
3. **Restricciones del Learner Lab.** Se deniegan `s3:GetBucketObjectLockConfiguration` (refresh general), `iam:GetPolicy` y `pricing:GetProducts`. Las credenciales son temporales.
4. **Cambios Terraform sin plan cloud.** AMI fija, autoescalado RDS desactivado y prefijo S3 se corrigieron localmente, pero no se conoce su plan real. El bucket se conserva en estado y Object Lock puede bloquear refresh.
5. **RDS detenida se reinicia sola a los 7 días.** EBS, almacenamiento/backups RDS, S3, logs, alarma, secreto y snapshot cobran aunque todo esté detenido.
6. **Cuentas demo.** Las cuentas de organizador y operador son para la demostración, no un mecanismo de administración.
7. **Recuperación completa sin medir.** R01 acredita RPO y recuperación de datos; no acredita aplicación, DNS ni HTTPS sobre la copia.
8. **Cámara física no probada.**
9. **Demostración académica, no lista para producción.** MFA, recuperación de cuenta e interfaz de auditoría no están implementados.
10. **Refresh Terraform limitado por SCP.** `s3:GetBucketObjectLockConfiguration` tiene un deny explícito. No se retiró S3 del estado ni se usó `-refresh=false` como evidencia.
11. **Respaldo lógico histórico fuera del RPO objetivo.** El dump/snapshot manual tenía 38 h al cierre; el backup automático sí informó un punto recuperable a las 15:39 UTC. Solo una restauración y comparación con línea base demostrará el RPO.

## Siguiente paso

Preparar y revisar la configuración de `amazon-cloudwatch-agent` antes de desplegarla; los grupos existentes aún no reciben eventos. Después, diseñar la prueba de recuperación completa con una aplicación aislada conectada a una copia restaurada, sin cambiar el DNS público del origen. No repetir E01, R01 de datos ni el despliegue `7955e7e` sin un cambio o fallo concreto.
