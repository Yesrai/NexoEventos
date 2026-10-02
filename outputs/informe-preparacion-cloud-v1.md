# Informe de preparación cloud V1 — NexoEventos

Fecha de actualización: 2 de octubre de 2026. Se inició una sesión autorizada de AWS Academy únicamente para lectura y planificación. No se creó, modificó, detuvo ni eliminó ningún recurso cloud; no se ejecutó `terraform apply` ni `destroy`.

## Resultado ejecutivo

El repositorio estaba limpio en `4971e5d`, rama `main`, sin remoto. El Learner Lab inició correctamente, se configuró un perfil CLI temporal fuera del repositorio y se comprobó una identidad de rol asumido sin registrar cuenta ni ARN en este informe. El inventario no encontró recursos de NexoEventos. Terraform produjo un plan válido de **30 altas, 0 cambios y 0 eliminaciones**; el binario queda solo en `work/`, ignorado y con modo `0600`.

La aplicación no está desplegada. La siguiente acción cloud requiere aprobar expresamente este plan, el costo y el mecanismo de secretos.

## AWS Academy comprobado

| Comprobación | Resultado | Evidencia | Limitación |
|---|---|---|---|
| Laboratorio | Learner Lab 184558; sesión de 4 h iniciada y terminada normalmente | Temporizador `04:00`, “Lab environment ready” y luego `Lab terminated` | No se verificó fecha de expiración global del curso |
| Presupuesto | `Used $0.1 of $50` | Panel de Vocareum | USD 50 es asignado; USD 0.10 es uso mostrado. Remanente aritmético USD 49.90, no saldo independiente; retraso 8–12 h |
| Regiones | `us-east-1` y `us-west-2` | Instrucciones vigentes, actualización 2025-06-24 | Listado no prueba permisos de creación |
| Identidad/CLI | Rol asumido válido; perfil `nexoeventos-lab`, archivos `0600` | `sts get-caller-identity` sanitizado | Credenciales temporales; caducan y no están en Git |
| EC2 | On-Demand; tamaños nano–large; AMI disponible en región, no Marketplace; 9 instancias y 32 vCPU máximos por región | Instrucciones | No se intentó crear una instancia ni consultar cuota de creación |
| EBS | gp2, gp3, sc1 o standard; máximo 100 GB; sin PIOPS | Instrucciones | Plan usa 20 GiB gp3, compatible documentalmente |
| Auto Scaling / ELB | Servicios listados; tamaños nano–large en Auto Scaling; pueden asumir `LabRole` | Instrucciones | No incluidos en V1 y no se probó creación |
| IAM | `LabRole` y `LabInstanceProfile` existen; el perfil contiene el rol | Lectura CLI | `iam:GetPolicy` fue denegado; no se pudo auditar permiso efectivo ni mínimo |
| RDS PostgreSQL | Documentado nano–medium, gp2 hasta 100 GB y sin enhanced monitoring | Instrucciones revisadas anteriormente y configuración actual | Plan usa `db.t3.micro`, 20 GiB gp2, monitoring 0; creación y cuota no probadas |
| S3 / CloudWatch / Secrets | Listado e inventario de lectura exitosos | CLI | Crear recursos y leer secretos no se probaron; listar no demuestra esos permisos |
| Precios API | `pricing:GetProducts` denegado | CLI | Se usaron listas públicas oficiales, no se intentó ampliar privilegios |
| Persistencia de sesión | Recursos y datos se conservan; EC2 se detiene al terminar y vuelve a iniciarse en una nueva sesión | Instrucciones | RDS, EBS, S3, logs y secretos pueden seguir cobrando |

## Inventario de solo lectura

No existe ningún recurso con etiqueta/prefijo NexoEventos en las dos regiones permitidas.

| Recurso | us-east-1 | us-west-2 | Posible consumo actual |
|---|---:|---:|---|
| EC2 | 0 | 0 | Ninguno |
| EBS volúmenes / snapshots propios | 0 / 0 | 0 / 0 | Ninguno |
| VPC / subredes | 1 / 6 | 1 / 4 | Predeterminadas; sin costo directo |
| Elastic IP / NAT Gateway | 0 / 0 | 0 / 0 | Ninguno |
| ELB clásico / ELBv2 / Auto Scaling | 0 / 0 / 0 | 0 / 0 / 0 | Ninguno |
| RDS / snapshots manuales | 0 / 0 | 0 / 0 | Ninguno |
| S3 | 0 global | — | Ninguno |
| CloudWatch Logs | 3 | 0 | 6,187 bytes; sin retención, ajenos a NexoEventos |
| Alarmas CloudWatch | 0 | 0 | Ninguno |
| Secrets Manager | 0 | 0 | Ninguno |

Los tres grupos de logs son la única fuente existente que puede seguir acumulando almacenamiento si otro servicio escribe. No se inspeccionó su contenido ni se modificó retención.

## Plan Terraform autenticado

`fmt` y `validate` pasaron. `terraform init` intentó consultar el registro y agotó el tiempo de red, pero el proveedor ya estaba bloqueado/cacheado y tanto `validate` como `plan` se completaron con ese proveedor. Resultado: **30 add, 0 change, 0 destroy**.

| Tipo | Cantidad |
|---|---:|
| VPC / Internet Gateway | 1 / 1 |
| Subredes | 3 |
| Tablas / asociaciones de ruta | 2 / 3 |
| Security groups | 2 |
| Reglas ingress / egress | 3 / 4 |
| EC2 `t3.small` | 1 |
| RDS PostgreSQL `db.t3.micro` | 1 |
| DB subnet group | 1 |
| S3 + acceso público, cifrado, versión y lifecycle | 5 recursos |
| CloudWatch log groups / alarma | 2 / 1 |

Configuración exacta: VPC `10.20.0.0/16`; pública `10.20.1.0/24`; datos `10.20.21.0/24` y `10.20.22.0/24`; EC2 Amazon Linux 2023 con 20 GiB gp3 cifrado, IMDSv2 y `LabInstanceProfile`; RDS privado Single-AZ, 20 GiB gp2 cifrado, backup 7 días, sin enhanced monitoring; S3 privado/versionado/SSE-S3; logs 7 días y alarma CPU. No hay NAT, ALB, Auto Scaling, Multi-AZ ni réplica.

Un plan exitoso confirma sintaxis, lecturas y composición; **no confirma permisos de creación, cuotas ni que Secrets Manager funcionará al aplicar**.

## Secretos y archivos sensibles

- No existe `user_data`; ninguna contraseña ni clave QR entra en la instancia desde Terraform.
- RDS administraría la contraseña maestra en Secrets Manager. El valor no se declara en variables ni código.
- El plan marca `aws_db_instance.postgres` como recurso con metadata sensible. El binario puede contener cuenta, nombres derivados, endpoint previsto y ARNs; por eso queda en `work/`, modo `0600`, sin adjuntarse como evidencia.
- El estado posterior contendrá IDs, endpoints y metadata/ARN del secreto. No debe versionarse ni compartirse.
- La aplicación no debe ejecutar con la cuenta maestra. Tras crear RDS se debe crear `nexoeventos_app` con permisos limitados y mantener separado el rol de migraciones.
- Opción preferida pendiente de verificar: secreto de aplicación separado, leído por EC2. `iam:GetPolicy` está denegado, así que no se puede afirmar acceso mínimo de `LabInstanceProfile`.
- Alternativa V1 sin poner valores en Terraform: carga interactiva sin eco a `/etc/nexoeventos/backend.env`, `root:root` y `0600`. Las claves de sesión, derivación y QR se respaldan separadas del dump.

## Costo del plan

Precios públicos oficiales de `us-east-1`: EC2 `t3.small` USD 0.0208/h; RDS `db.t3.micro` USD 0.018/h; IPv4 USD 0.005/h; EBS gp3 USD 0.08/GiB-mes; RDS gp2 USD 0.115/GiB-mes.

| Categoría | 8 h | 730 h / 30 días |
|---|---:|---:|
| Tiempo: EC2 + RDS + IPv4 | USD 0.3504 | USD 31.974 |
| Almacenamiento/servicios persistentes | USD 0.0485 prorrateado | USD 4.429 |
| Consumo supuesto: 1 GB de logs | USD 0.0055 prorrateado | USD 0.500 |
| **Total** | **USD 0.4044** | **USD 36.903** |

No incluye créditos CPU T3, solicitudes S3, transferencia facturable, exceso de backups ni impuestos. Al detener EC2 sigue EBS; al detener RDS siguen almacenamiento/backups y AWS lo reinicia tras siete días; S3, logs, alarma y secretos persisten. La propuesta de 37 horas activas y 52 días de persistencia hasta el 26 de noviembre estima **USD 10.164**, siempre que se cumpla el calendario y no haya olvidos.

## HTTPS

No hay dominio configurado: Nginx conserva `${DOMAIN}` y no existe certificado. Opciones sin comprar nada automáticamente:

1. Subdominio que ya controle la usuaria + registro DNS A + Let's Encrypt. Es la opción más estable; exige control DNS y actualizar el registro cuando cambie la IPv4.
2. Nombre dinámico gratuito gestionado por un tercero. Requiere cuenta/token externo, que sería otro secreto operativo.
3. Dominio basado en IP como `sslip.io` para demostración. No requiere compra, pero depende de un tercero y cambia al cambiar la IPv4.

Un certificado autofirmado no produce HTTPS confiable para EV10. ACM no se conecta directamente a Nginx/EC2 sin otro servicio como ALB o CloudFront, que no forma parte de esta V1. No se registró dominio ni se emitió certificado.

## Calendario y decisiones pendientes

El calendario detallado propone sesiones el 5, 8, 14, 20 y 26 de octubre; 1, 7, 13, 19, 24 y 26 de noviembre. Cada sesión empieza revisando presupuesto/inventario y termina deteniendo cómputo. El intervalo máximo de seis días evita olvidar RDS hasta su reinicio automático de siete días.

Decisiones mínimas antes de `apply`:

1. Aprobar los 30 recursos y el techo de costo.
2. Elegir dominio/subdominio y método TLS.
3. Elegir secreto de aplicación separado o aceptar temporalmente el archivo root-only; no usar la cuenta maestra.
4. Decidir si se mantiene `skip_final_snapshot = true`; no ejecutar `destroy` como estrategia de ahorro sin una evidencia de backup/restauración.
5. Aceptar que los permisos de creación y cuota solo se conocerán al desplegar; no intentar ampliar privilegios si falla.

## Evidencias

- EV09 actualizado con `fmt`, `validate` y plan autenticado 30/0/0.
- EV01 permanece local; EV02–EV08 y EV10 siguen pendientes de recursos reales y pruebas cloud.
- No se capturaron credenciales, tokens, cuenta completa ni plan binario.

NexoEventos sigue siendo una implementación académica local con infraestructura planificada; no está desplegado ni listo para producción.
