# Matriz de trazabilidad y evidencias

No se acepta como evidencia una pantalla de configuración sin resultado. Las capturas deben mostrar fecha/contexto, ocultar identificadores innecesarios y nunca incluir contraseñas, cookies, secretos, tokens QR completos ni datos personales. Las cifras del caso y metas se etiquetan como objetivos; solo una ejecución registrada es resultado medido.

| ID | Criterio oficial Entregable 2 | Recurso | Prueba exigida | Evidencia prevista | Estado al 2026-10-07 |
|---|---|---|---|---|---|
| EV01 | C5: pruebas/documentación | React, FastAPI, PostgreSQL | Compilación, roles, idempotencia y concurrencia | `EV01/README.md` + resultados sanitizados | **Disponible local y público**; suite cloud aprobada |
| EV02 | C3: seguridad de red | VPC `10.20.0.0/16` | CIDR, DNS y etiquetas en recurso real | estado Terraform + inventario sanitizado | **Desplegada**; falta captura de consola |
| EV03 | C3/C4: red y tolerancia | Subred pública, dos DB privadas, tablas de ruta, IGW | Ruta pública solo donde corresponde; datos sin ruta Internet | estado Terraform + conectividad comprobada | **Desplegada y usada**; falta captura de consola |
| EV04 | C3: controles de seguridad | SG web y DB | 80/443 público, SSH cerrado, 5432 solo SG web | reglas reales + HTTPS/RDS desde aplicación | **Comprobada funcionalmente**; falta captura de reglas |
| EV05 | Cómputo y aplicación | EC2 AL2023, Nginx, systemd | Instalación reproducible; servicio sin reload; FastAPI solo loopback | versiones, estados, health y captura | **Comprobada en AWS**; captura disponible |
| EV06 | Datos | RDS PostgreSQL privado | Conexión desde app, no desde Internet; persistencia | migraciones y prueba tras reinicio | **Comprobada en RDS 18.3** |
| EV07 | C4/C5: recuperación y pruebas | S3 privado + snapshot RDS + copia externa | línea base, punto recuperable, restauración, reservas y QR | metadatos y verificación sin secretos | **Dump/copia externa y snapshot disponibles**; ensayo cloud no ejecutado |
| EV08 | Observabilidad | CloudWatch Logs y alarma CPU | Logs sanitizados, retención y estado de alarma | inventario y ausencia de QR en log API | **Recursos desplegados; sanitización API comprobada**; falta captura CloudWatch |
| EV09 | IaC | Terraform AWS | identidad, estado separado, plan y aplicación controlada | estado protegido + plan autenticado | **30 recursos administrados en estado serial 32**; AMI/RDS/prefijo corregidos localmente y validados, pero falta plan; Object Lock puede limitar refresh |
| EV10 | Flujo público seguro | DuckDNS + Let's Encrypt + aplicación | iniciar sesión → reservar → ver QR → validar una vez | URL real, suite y captura sin secretos | **Comprobado públicamente por HTTPS**; cámara física pendiente |
| EV11 | C4/C5: escalabilidad y pruebas | EC2 + RDS + CloudWatch | 20 usuarios virtuales × 5 min; p95 y errores inesperados; evento `[CARGA]` si hay reservas | `EV11/README.md` + `resumen.md` + gráfico CPU | **No ejecutada**; intento del 4 de octubre detenido antes del arranque por `InvalidClientTokenId` con credenciales recién emitidas |
| EV12 | C1/C4/C5: evolución V2 | ALB + 2 EC2 (propuesta) | comparar V1/V2, health checks, retirar una instancia y repetir carga | diagrama, plan/costo y mediciones antes/después | **Diseñada, no desplegada**; ver `docs/arquitectura-v2.md` |

## Cifras que no son mediciones

- Caso empresarial: aforo, demanda o volúmenes descritos en la documentación son supuestos del caso.
- Objetivos: 20 usuarios virtuales durante 5 minutos, p95 menor de 2 s, errores menores de 1 %, RTO máximo 60 min y RPO máximo 24 h.
- Resultados medidos actuales: pruebas funcionales/concurrentes locales y públicas, persistencia RDS y respaldo cifrado. No existen todavía resultados cloud de carga, RTO o RPO.

Revisión criterio por criterio, sin asignar puntajes: [revision-rubrica.md](revision-rubrica.md). Procedimientos: [sesión cloud](../operacion/procedimientos-sesion-cloud.md) y [despliegue Ansible](../operacion/ansible-despliegue.md).

Consultar cada carpeta EV antes de capturar. Una infraestructura desplegada no completa por sí sola la rúbrica: siguen pendientes capturas de consola sanitizadas, carga y recuperación cloud cronometrada.
