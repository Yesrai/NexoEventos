# Matriz de trazabilidad y evidencias

No se acepta como evidencia una pantalla de configuración sin resultado. Las capturas deben mostrar fecha/contexto, ocultar identificadores innecesarios y nunca incluir contraseñas, cookies, secretos, tokens QR completos ni datos personales. Las cifras del caso y metas se etiquetan como objetivos; solo una ejecución registrada es resultado medido.

| ID | Sección / criterio | Recurso | Prueba exigida | Evidencia prevista | Estado al 2026-10-02 |
|---|---|---|---|---|---|
| EV01 | Aplicación y control de acceso | React, FastAPI, PostgreSQL | Compilación, pruebas de roles, idempotencia y concurrencia | `EV01/README.md` + capturas locales | **Disponible local**; falta ejecución pública |
| EV02 | Red base | VPC `10.20.0.0/16` | CIDR, DNS y etiquetas en recurso real | Captura VPC + salida sanitizada | **Pendiente cloud** |
| EV03 | Segmentación | Subred pública, dos DB privadas, tablas de ruta, IGW | Ruta pública solo donde corresponde; datos sin ruta Internet | Capturas y plan/aplicación | **Pendiente cloud** |
| EV04 | Seguridad | SG web y DB | 80/443 público, SSH `/32` opcional, 5432 solo SG web | Reglas reales + prueba de puerto | **Pendiente cloud** |
| EV05 | Cómputo y aplicación | EC2, Nginx, systemd | Servicio persistente sin reload; FastAPI solo loopback | estado del servicio, `curl` y captura | **Configuración local disponible; pendiente cloud** |
| EV06 | Datos | RDS PostgreSQL privado | Conexión desde app, no desde Internet; persistencia | endpoint RDS oculto + prueba reinicio | **Restauración local disponible; pendiente RDS** |
| EV07 | Respaldo | S3 privado + RDS backup | Carga, versionado y restauración aislada | objeto sin contenido sensible + informe restore | **Restore local disponible; pendiente S3/RDS** |
| EV08 | Observabilidad | CloudWatch Logs y alarma CPU | Logs sanitizados, retención y estado de alarma | captura grupos/alarma | **Configuración Terraform; pendiente cloud** |
| EV09 | IaC | Terraform AWS | `fmt`, `validate`, plan revisado y post-apply sin cambios | resumen sanitizado; binario solo en `work/` | **fmt/validate y plan autenticado disponibles: 30/0/0; post-apply pendiente** |
| EV10 | Flujo público seguro | HTTPS + aplicación | iniciar sesión → reservar → ver QR → validar una vez | URL real y capturas sin token reutilizable | **Flujo local probado; dominio/certificado/cloud pendientes** |

## Cifras que no son mediciones

- Caso empresarial: aforo, demanda o volúmenes descritos en la documentación son supuestos del caso.
- Objetivos: 20 usuarios virtuales durante 5 minutos, p95 menor de 2 s, errores menores de 1 %, RTO máximo 60 min y RPO máximo 24 h.
- Resultados medidos actuales: pruebas funcionales/concurrentes locales y restauración aislada. No existen todavía resultados cloud de rendimiento, RTO o RPO.

Consultar cada carpeta EV antes de capturar. EV02–EV10 no deben marcarse completas hasta desplegar con aprobación posterior.
