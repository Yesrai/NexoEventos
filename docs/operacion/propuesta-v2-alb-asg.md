# Propuesta AWS V2: ALB + Auto Scaling (2 instancias en 2 zonas)

Propuesta del 19-oct-2026, **sin crear recursos ni aplicar Terraform**. Amplía [arquitectura-v2.md](../arquitectura-v2.md) con los hallazgos medidos de V1.

## Arquitectura
Internet → **ALB** (HTTPS 443, redirección 80→443; 2 subredes públicas en AZ a y b) → **Target group** HTTP :80 con health check `/healthz` → **ASG** (min 2, máx 3, deseado 2; `health_check_type = ELB`, gracia 120 s) con **launch template** (AMI AL2023 con Nginx + FastAPI 2 workers; `t3.small`; IMDSv2; EBS 20 GiB cifrado; `LabInstanceProfile`) → **RDS actual** (privada) + S3/Secrets Manager/CloudWatch existentes.
- V1 no se toca: V2 vive en una **raíz Terraform separada** (`infra/aws-v2`, estado propio) que lee la VPC, la RDS y el SG de la base con `data` y solo **añade**: subred pública b, 2 SG nuevos (ALB; web-v2 con 80 solo desde el SG del ALB), una regla de PostgreSQL desde web-v2, ALB, listeners, target group, launch template, ASG y un secreto. Evita el refresco de S3 bloqueado por Object Lock que impide un plan autenticado del estado V1.
- Instancias en subred pública con IPv4 (SSM y repositorios sin NAT; 80 solo desde el ALB, sin SSH).

## Cambios mínimos
| Tema | Cambio |
|---|---|
| Nginx | Un solo `server` en :80 (sin TLS, sin Let's Encrypt ni DuckDNS en las instancias); `/healthz` proxificado; `X-Forwarded-Proto` tomado del ALB |
| TLS | ACM no puede validar un subdominio DuckDNS (exige CNAME de validación). Propuesta: **importar en ACM el certificado Let's Encrypt vigente** con `acm import-certificate` ejecutado *en la EC2 V1* (la clave no sale de AWS); renovar a mano (vence 1-ene-2027). Alternativa: certificado propio de un dominio con CNAME |
| IP de cliente | `set_real_ip_from 10.20.0.0/16; real_ip_header X-Forwarded-For; real_ip_recursive on;` en Nginx; si no, el limitador de intentos vería la IP del ALB para todos |
| Sesiones / fila / límite de intentos | Ya viven en PostgreSQL; sin cambio. Orígenes y cookie `Secure` iguales (mismo dominio) |
| Secretos | `TICKET_ENCRYPTION_KEY` y `SECURITY_HASH_KEY` **idénticas** en todas las instancias: secreto nuevo en Secrets Manager que el arranque escribe en `/etc/nexoeventos/backend.env` (0600). Nunca en AMI ni `user_data` en claro |
| Health checks | TG `/healthz` cada 10 s, 2 sanos / 2 no sanos; ASG por ELB |
| Migraciones únicas | La API no migra al arrancar. `deploy` con migraciones solo en una instancia (`--limit`), las demás con `nexoeventos_run_migrations=false`; las instancias nuevas salen de la AMI ya en 0008 |
| Conexiones a RDS | `db.t3.micro` admite 81; hoy 2 workers × (5+10) por instancia → 60 con dos. Reducir `max_overflow` a 5 (≈ 40) y vigilar `DatabaseConnections` |
| Argon2 | Límite por proceso ya desplegado: cada instancia protege su memoria; sin coordinación |
| AMI | «Dorada» construida con los roles Ansible existentes sobre una instancia temporal (variante sin TLS/DuckDNS), sin secretos ni `letsencrypt` |

## Restricciones del laboratorio (por verificar; ninguna probada)
IAM muy limitado: solo `LabRole`/`LabInstanceProfile` (suficiente para el launch template); roles vinculados a servicio de ELB y Auto Scaling deberían poder crearse; **ELB y Auto Scaling figuran como disponibles pero sin probar**; permiso `acm:ImportCertificate` y `secretsmanager:CreateSecret` desconocidos; región única us-east-1; cuota de instancias del laboratorio; la sesión del laboratorio detiene recursos al expirar; **el estado V1 no admite plan autenticado**. Mitigación: probar con un plan solo de lectura y una creación mínima (SG) antes de la ventana.

## Riesgos
RDS sigue siendo un punto único de fallo (Multi-AZ = +USD 0,018/h); la importación manual del certificado caduca; instancias con IP pública; el ALB no tiene IP estable (la prueba se hace con mapeo de nombre en k6 y no con DuckDNS; un corte real de DNS requeriría otro proveedor o Route 53); límites de cuota/permisos del laboratorio; vigilar créditos de CPU (modo Unlimited) y la memoria de RDS (≈ 160 MB libres).

## Costos estimados (us-east-1, sin impuestos; estimación, no consumo)
| Concepto | USD/h |
|---|---:|
| 2 × EC2 `t3.small` (0,0208) | 0,0416 |
| ALB (0,0225) + 1 LCU media (0,008) | 0,0305 |
| IPv4 públicas: 2 instancias + 2 del ALB (0,005 c/u) | 0,0200 |
| **V2 adicional** | **≈ 0,092** |
| RDS actual (ya existe) | 0,018 |
| V1 EC2 + IPv4 si se deja encendida | 0,026 |

Ventana propuesta de **3 h** con V1 y V2 encendidas: ≈ USD 0,41 (V2 0,28 + V1 0,08 + RDS 0,05), más AMI/instantánea de 20 GiB (< USD 0,05), instancia temporal de construcción (≈ USD 0,03) y secreto (≈ USD 0,02). **Techo con reserva: USD 1,00.** Si V2 queda encendida: ≈ USD 2,2/día (≈ 66/30 días con RDS, según `arquitectura-v2.md`).

## Medición V1 vs V2
Mismos escenarios y criterios que V1: `scripts/cloud/run-k6-ladder.py` con el perfil mixto 1/10/20/40/50 usuarios y la disputa de asiento (mismo origen de tráfico, mismas condiciones de parada). Diferencias a añadir: `--add-host nexoeventos-demo.duckdns.org:<IP del ALB>` en el contenedor de k6 (la URL y el certificado siguen siendo los mismos), muestreo en **ambas** instancias y métricas de ALB (`RequestCount`, `TargetResponseTime`, `HTTPCode_Target_5XX`, `HealthyHostCount`, reparto por zona). Si todo es sano a 50, repetir 100 usuarios en V1 y V2 (con autorización: sube el techo actual de 50).
Tabla final: p50/p95/p99, solicitudes/s, errores, CPU y memoria por instancia, conexiones a RDS, créditos, costo/h.

## Caída de una instancia
Con 20 usuarios de carga sostenida: (1) detener solo `nexoeventos-api` en una instancia (SSM) → medir detección (`HealthyHostCount` 2→1, esperado ≈ 20–30 s), errores 5xx durante la ventana y p95 después; (2) con autorización, terminar esa instancia en el ASG → tiempo hasta 2 sanas de nuevo (AMI dorada, esperado 3–5 min) y comprobar integridad 0 y que no se pierdan reservas ni sesiones (las sesiones están en PostgreSQL).

## Pasos de implementación
1. (Local) Raíz `infra/aws-v2` y variables; `terraform validate`/`plan` sin credenciales de escritura; variante Nginx para ALB y prueba de la AMI en Docker; opción `--add-host` en el lanzador k6.
2. (Lectura AWS) Confirmar permisos: ELB/ASG, `acm:ImportCertificate`, Secrets Manager, cuotas; plan de Terraform sin `apply`.
3. (Con autorización) Secreto, AMI dorada e importación del certificado.
4. (Con autorización) `terraform apply` **solo de la raíz V2** → ALB, ASG, 2 instancias; verificación funcional (`verify-controlled-flow.py` con el mapeo del ALB).
5. Medición V1 vs V2 y prueba de caída; limpieza (destruir la raíz V2 con autorización) y comparación final.
