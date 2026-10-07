# Estado del proyecto NexoEventos

| Dato | Valor |
|---|---|
| Fecha de corte | 7 de octubre de 2026 (Lima) |
| Commit de referencia | `1d21b7a` al iniciar esta revisión; los cambios cloud/Ansible quedan en el commit indicado por `git log` |
| URL pública | `https://nexoeventos-demo.duckdns.org`, **fuera de servicio mientras EC2 y RDS estén detenidas** |
| Estado AWS comprobado | último estado observado el 4 de octubre: EC2 `Detenida`, RDS en `Detención temporal`, sin RDS temporal. El 7 de octubre STS volvió a rechazar las credenciales antiguas; no se presume el estado actual |
| Entrega final | 26 de noviembre de 2026 |

Convención de este documento:

- **Medido:** ejecutado y observado, con la fuente indicada.
- **Objetivo:** meta del caso o del laboratorio, no medida.
- **Supuesto:** cifra del caso empresarial o hipótesis de costo.

## Terminado (con evidencia)

| Área | Resultado medido | Fuente |
|---|---|---|
| Aplicación local | React/TS + FastAPI + PostgreSQL; autenticación, autorización, reservas transaccionales/idempotentes y QR. Desde el despliegue se añadieron múltiples revisiones de interfaz hasta `1d21b7a` | historial Git, EV01 |
| Infraestructura AWS V1 | 30 recursos Terraform en `us-east-1`: VPC `10.20.0.0/16`, una subred pública, dos privadas de datos, rutas, IGW, SG web/DB, EC2 `t3.small` AL2023, RDS PostgreSQL 18.3 privada, S3 privado y versionado, 2 log groups y una alarma CPU | `outputs/informe-despliegue-aws-2026-10-03.md`, EV09 |
| Seguridad operativa | SSH cerrado, administración por Session Manager, FastAPI en `127.0.0.1:8000` con usuario sin privilegios, secretos `root:root 0600`, roles PostgreSQL `owner`/`migrator`/`app` sin atributos elevados, IMDSv2 | informe del 3 de octubre, EV05, EV06 |
| HTTPS público | DuckDNS + Let's Encrypt, válido del 3 de octubre de 2026 al 1 de enero de 2027, timers de renovación y DNS activos | EV10, `deploy/README.md` |
| Suite pública | 14 comprobaciones aprobadas por HTTPS: 401 sin sesión, 422 al escalar rol, registro con cookie `Secure`/`HttpOnly`, reserva idempotente, 403 de operador ajeno, 404 de QR inexistente, validación concurrente 200/409, segundo uso 409, logout 204→401, persistencia tras reinicio y QR ausente del log | EV10 |
| Persistencia RDS | Alembic `0001`–`0003` aplicadas; reserva y entrada persisten tras reiniciar la API | EV06 |
| Respaldo | dump `pg_dump` 18.6 en paquete CMS cifrado → S3 privado, cifrado y versionado; copia externa `0600` con hash coincidente; claves QR/hash cifradas fuera de AWS y del repositorio; snapshot manual RDS cifrado de 20 GiB `available` | EV07 |
| Captura | página pública sin sesión (`EV05/public-home-2026-10-03.png`) | EV05 |

## Diferencia local frente a AWS

| Componente | Local al 7-oct | AWS verificado por última vez | Sincronizado |
|---|---|---|---|
| frontend | rediseño y accesibilidad hasta `1d21b7a` | versión desplegada y probada el 3-oct | **No**; falta despliegue versionado y prueba pública |
| backend/API | controles funcionales ya probados; no se identificó una migración nueva en esta revisión | flujo completo y migraciones `0001`–`0003` probados el 3-oct | no se vuelve a afirmar hasta comparar commits |
| infraestructura | AMI fija, RDS autoscaling explícito y prefijo S3 corregidos localmente | estado protegido serial 32; configuración remota previa | **No**; falta plan autenticado, no se aplicó Terraform |
| automatización | Ansible con artefacto, health check y rollback preparado | instalación inicial ejecutada con scripts shell | **No probado en AWS** |
| evidencias | matriz actualizada; capturas históricas conservadas | no hubo acceso API el 7-oct | faltan EV02–EV04, EV06–EV08 y nueva EV10 |

## Pendiente

| Pendiente | Motivo / bloqueo | Preparado en esta revisión |
|---|---|---|
| Capturas de consola sanitizadas EV02, EV03, EV04, EV06, EV07, EV08 | requiere arrancar recursos | script y checklist revisados localmente; ejecución AWS pendiente |
| Prueba de carga E01 (20 usuarios × 5 min) | no ejecutada; **no hay resultados de rendimiento** | `scripts/cloud/load-test.py`, EV11 |
| Scripts operativos contra AWS | revisados y comprobados sintácticamente, pero no ejecutados contra AWS | la próxima sesión debe confirmar permisos, estados y fallos parciales reales |
| Configuración operativa protegida | completada localmente | reconstruida desde el estado real `academy-current` (serial 32), ignorada por Git y modo `0600`; valores no impresos |
| Restauración cloud aislada y cronometrada (R01) | no ejecutada; **punto recuperable, recuperación de datos y servicio completo no medidos** | línea base exacta, QR y limpieza por recibo preparados; ejecución AWS pendiente |
| Arranque/apagado verificable | hoy es manual | `scripts/cloud/cloud-session.sh` |
| Plan Terraform vigente (I01/EV09) | STS inválido; además Object Lock puede bloquear refresh | configuración corregida y validada localmente; falta plan autenticado antes de aplicar |
| Actualización versionada de AWS | credenciales temporales antiguas inválidas y Session Manager Plugin ausente en el Mac | playbooks y rollback validados sintácticamente; `docs/operacion/ansible-despliegue.md` |
| Identificador `Equipo XX` del modelo oficial | falta confirmación docente; no se inventa | autora: Yesenia; proyecto individual; pendiente no bloqueante |
| Cámara física para QR | no probada; la alternativa por código sí | — |
| Captura pública con fecha/hora (tabla 15 del Entregable) | la existente (EV05) muestra solo la página: sin barra de direcciones, candado HTTPS ni fecha/hora | checklist § 2.2 |
| Registro de timestamps reales (`LaunchTime`/`InstanceCreateTime`) y consumo observado del panel | no consolidado en `costos-v1.md` | `cloud-session.sh` registra transiciones |
| Preparar el Entregable 2 oficial | requiere evolución V1→V2 y evidencias nuevas | contraste exacto en `docs/evidencias/revision-rubrica.md` |
| Repositorio remoto (fila SaaS de GitHub) | `git remote` vacío | — |
| Azure (continuidad) y GCP (analítica) | mejoras del proyecto, no proveedores exigidos por los Word oficiales revisados | — |

## Objetivos vigentes (no medidos)

- E01: 20 usuarios virtuales durante 5 min, p95 < 2 s y errores inesperados < 1 %.
- R01: RTO ≤ 60 min y RPO ≤ 24 h.
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
7. **Rendimiento y recuperación sin medir en cloud.** La restauración local no acredita RTO/RPO cloud.
8. **Cámara física no probada.**
9. **Demostración académica, no lista para producción.** MFA, recuperación de cuenta e interfaz de auditoría no están implementados.
10. **Credenciales Academy no vigentes.** El 7 de octubre el perfil protegido seguía usando el bloque temporal del 2 de octubre y STS devolvió `InvalidClientTokenId`. No había variables AWS sustituyendo el perfil y la hora era correcta. No se reintentó en bucle ni se consultó/modificó AWS.

## Siguiente paso

Con el laboratorio listo, ejecutar personalmente `./work/enter-aws-academy-credentials.sh` y después una sola comprobación STS. Si funciona: inventario/consumo, plan Terraform nuevo y preflight Ansible. Si vuelve a fallar con un bloque recién emitido, actualizar el reporte a soporte y continuar sin cambios cloud. No aplicar Terraform hasta revisar un plan con refresh. El identificador `Equipo XX` sigue pendiente, sin bloquear el trabajo técnico.
