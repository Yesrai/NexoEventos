# Matriz de trazabilidad y evidencias

No se acepta como evidencia una pantalla de configuración sin resultado. Las capturas deben mostrar fecha/contexto, ocultar identificadores innecesarios y nunca incluir contraseñas, cookies, secretos, tokens QR completos ni datos personales. Las cifras del caso y metas se etiquetan como objetivos; solo una ejecución registrada es resultado medido.

| ID | Sección / criterio | Recurso | Prueba exigida | Evidencia prevista | Estado al 2026-10-03 |
|---|---|---|---|---|---|
| EV01 | Aplicación y control de acceso | React, FastAPI, PostgreSQL | Compilación, pruebas de roles, idempotencia y concurrencia | `EV01/README.md` + resultados sanitizados | **Disponible local y público**; suite cloud aprobada |
| EV02 | Red base | VPC `10.20.0.0/16` | CIDR, DNS y etiquetas en recurso real | estado Terraform + inventario sanitizado | **Desplegada**; falta captura de consola |
| EV03 | Segmentación | Subred pública, dos DB privadas, tablas de ruta, IGW | Ruta pública solo donde corresponde; datos sin ruta Internet | estado Terraform + conectividad comprobada | **Desplegada y usada**; falta captura de consola |
| EV04 | Seguridad | SG web y DB | 80/443 público, SSH cerrado, 5432 solo SG web | reglas reales + HTTPS/RDS desde aplicación | **Comprobada funcionalmente**; falta captura de reglas |
| EV05 | Cómputo y aplicación | EC2 AL2023, Nginx, systemd | Instalación reproducible; servicio sin reload; FastAPI solo loopback | versiones, estados, health y captura | **Comprobada en AWS**; captura disponible |
| EV06 | Datos | RDS PostgreSQL privado | Conexión desde app, no desde Internet; persistencia | migraciones y prueba tras reinicio | **Comprobada en RDS 18.3** |
| EV07 | Respaldo | S3 privado + snapshot RDS + copia externa | Carga, cifrado, copia y lectura del paquete | metadatos y verificación sin secretos | **Dump/copia externa y snapshot disponibles**; restore cloud pendiente |
| EV08 | Observabilidad | CloudWatch Logs y alarma CPU | Logs sanitizados, retención y estado de alarma | inventario y ausencia de QR en log API | **Recursos desplegados; sanitización API comprobada**; falta captura CloudWatch |
| EV09 | IaC | Terraform AWS | identidad, estado separado, plan y aplicación controlada | estado protegido + resumen 30 altas | **30 recursos administrados presentes**; refresh general limitado por SCP S3 y deriva de AMI |
| EV10 | Flujo público seguro | DuckDNS + Let's Encrypt + aplicación | iniciar sesión → reservar → ver QR → validar una vez | URL real, suite y captura sin secretos | **Comprobado públicamente por HTTPS**; cámara física pendiente |

## Cifras que no son mediciones

- Caso empresarial: aforo, demanda o volúmenes descritos en la documentación son supuestos del caso.
- Objetivos: 20 usuarios virtuales durante 5 minutos, p95 menor de 2 s, errores menores de 1 %, RTO máximo 60 min y RPO máximo 24 h.
- Resultados medidos actuales: pruebas funcionales/concurrentes locales y públicas, persistencia RDS y respaldo cifrado. No existen todavía resultados cloud de carga, RTO o RPO.

Consultar cada carpeta EV antes de capturar. Una infraestructura desplegada no completa por sí sola la rúbrica: siguen pendientes capturas de consola sanitizadas, carga y recuperación cloud cronometrada.
