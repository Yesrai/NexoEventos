# Matriz de trazabilidad y evidencias

No se acepta como evidencia una pantalla de configuración sin resultado. Las capturas deben mostrar fecha/contexto, ocultar identificadores innecesarios y nunca incluir contraseñas, cookies, secretos, tokens QR completos ni datos personales. Las cifras del caso y metas se etiquetan como objetivos; solo una ejecución registrada es resultado medido.

Lectura API consolidada y sanitizada de inventario: [9 de octubre de 2026](lectura-aws-2026-10-09.md). Recepción real de logs: [10 de octubre de 2026](EV08/recepcion-real-2026-10-10.md).

| ID | Criterio oficial Entregable 2 | Recurso | Prueba exigida | Evidencia prevista | Estado al 2026-10-10 |
|---|---|---|---|---|---|
| EV01 | C5: pruebas/documentación | React, FastAPI, PostgreSQL | Compilación, roles, idempotencia y concurrencia | `EV01/README.md` + resultados sanitizados | **Disponible local y público**; suite cloud aprobada |
| EV02 | C3: seguridad de red | VPC `10.20.0.0/16` | CIDR, DNS y etiquetas en recurso real | estado Terraform + inventario sanitizado | **Lectura API 7-oct disponible**; falta captura de consola |
| EV03 | C3/C4: red y tolerancia | Subred pública, dos DB privadas, tablas de ruta, IGW | Ruta pública solo donde corresponde; datos sin ruta Internet | estado Terraform + conectividad comprobada | **Lectura API 7-oct disponible**; falta captura de consola |
| EV04 | C3: controles de seguridad | SG web y DB | 80/443 público, SSH cerrado, 5432 solo SG web | reglas reales + HTTPS/RDS desde aplicación | **Reglas API comprobadas 7-oct**; falta captura de consola |
| EV05 | Cómputo y aplicación | EC2 AL2023, Nginx, systemd | Instalación reproducible; servicio sin reload; FastAPI solo loopback | versiones, estados, health y captura | **Ansible/SSM y commit `7955e7e` comprobados**; capturas escritorio/móvil disponibles |
| EV06 | Datos | RDS PostgreSQL privado | Conexión desde app, no desde Internet; persistencia | migraciones y prueba tras reinicio | **RDS 18.3 y Alembic `0005` comprobados**; datos históricos preservados |
| EV07 | C4/C5: recuperación y pruebas | S3 privado + snapshot RDS + copia externa | línea base, punto recuperable, restauración, reservas y QR | metadatos y verificación sin secretos | **R01 ejecutada 10-oct**: RPO 3 min 32 s; datos verificados 21 min 4 s; 135 QR válidos; temporal eliminada; servicio completo pendiente |
| EV08 | Observabilidad | CloudWatch Logs y alarma CPU | Logs sanitizados, retención y estado de alarma | inventario y ausencia de QR en log API | **CUMPLE 10-oct**: agente AL2023 activo, streams API/Nginx y solicitud sanitizada recibida; retención 7 días; alarma CPU comprobada, sin notificaciones configuradas |
| EV09 | IaC | Terraform AWS | identidad, estado separado, plan y aplicación controlada | estado protegido + plan autenticado | refresh autenticado: resumen parcial 0/1/0 y SCP Object Lock; **sin plan aplicable** |
| EV10 | Flujo público seguro | DuckDNS + Let's Encrypt + aplicación | iniciar sesión → reservar → ver QR → validar una vez | URL real, suite y captura sin secretos | **`7955e7e` comprobado públicamente por HTTPS y capturado**; cámara física pendiente |
| EV11 | C4/C5: escalabilidad y pruebas | EC2 + RDS + CloudWatch | 20 usuarios virtuales × 5 min; p95 y errores inesperados; evento `[CARGA]` si hay reservas | `EV11/README.md` + resultado + métricas CPU/BD | **CUMPLE 9-oct**: 2 520 solicitudes, p95 421.2 ms, 0 % inesperados; 132 reservas/entradas sin sobreventa ni duplicados |
| EV12 | C1/C4/C5: evolución V2 | ALB + 2 EC2 (propuesta) | comparar V1/V2, health checks, retirar una instancia y repetir carga | diagrama, plan/costo y mediciones antes/después | **Diseñada, no desplegada**; ver `docs/arquitectura-v2.md` |

## Cifras que no son mediciones

- Caso empresarial: aforo, demanda o volúmenes descritos en la documentación son supuestos del caso.
- Objetivos: 20 usuarios virtuales durante 5 minutos, p95 menor de 2 s, errores menores de 1 %, RTO máximo 60 min y RPO máximo 24 h.
- Resultados medidos actuales: pruebas funcionales/concurrentes locales y públicas, persistencia RDS, respaldo cifrado, E01 cloud y R01 de datos. El RPO medido fue 3 min 32 s y la recuperación/verificación de datos 21 min 4 s; el RTO del servicio completo sigue pendiente.

Revisión criterio por criterio, sin asignar puntajes: [revision-rubrica.md](revision-rubrica.md). Procedimientos: [sesión cloud](../operacion/procedimientos-sesion-cloud.md) y [despliegue Ansible](../operacion/ansible-despliegue.md).

Consultar cada carpeta EV antes de capturar. Una infraestructura desplegada no completa por sí sola la rúbrica: siguen pendientes capturas de consola sanitizadas y recuperación completa del servicio. La recepción real de logs ya quedó medida; no debe repetirse salvo cambio del agente, rutas o permisos.
