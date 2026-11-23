# Entregable 3 · Plan para proteger el crédito: eliminar el ALB de V2 y detener RDS — 10-nov-2026

**Estado: SOLO PLANIFICACIÓN. No se eliminó ni se detuvo nada, no se modificó Terraform, sin commits ni push; OCI, Azure y Docker no se tocaron.** Base: `evidencias/aws-planificacion-solo-lectura-20261110.txt` (consultas `describe-/list-`, salida enmascarada, código de salida 0) y lectura de `infra/aws-v2/*.tf`. Las cifras de costo son estimaciones con tarifas públicas (no hay Cost Explorer en Academy).

## 1. El ALB de V2 y sus dependencias
| Elemento | Hallazgo |
|---|---|
| ALB | `nexoeventos-academy-v2-alb`, application, internet-facing, `active`, 2 zonas (us-east-1a/1b), 1 SG, creado el 5-nov. **Protección contra eliminación: desactivada** (`deletion_protection.enabled=false`). Sin registros de acceso en S3. |
| Listener 443 | HTTPS, política `ELBSecurityPolicy-TLS13-1-2-2021-06`, 1 certificado, acción por defecto `forward` → TG V2. |
| Listener 80 | HTTP, acción por defecto `redirect` (a HTTPS). |
| Reglas | Solo las reglas por defecto de cada listener (sin reglas personalizadas). |
| Target group | `nexoeventos-academy-v2-tg`, HTTP/80, salud `/livez`, tipo instance, **0 destinos**. |
| Auto Scaling | `nexoeventos-academy-v2-asg`: deseada 0, mín 0, máx 3, 0 instancias; apunta al TG. |
| SG | `…-alb-sg` (2 entradas, 1 salida) y `…-web-sg` (1 entrada, 4 salidas). |
| Fuera de Terraform | Certificado en ACM (se importó; `acm list-certificates` devolvió vacío — **ver riesgo R1**), 2 AMI + 2 instantáneas, 2 secretos, grupos de logs. |

## 2. Terraform: qué se eliminaría y qué se conserva (sin ejecutar nada)
La raíz `infra/aws-v2` gestiona **27 recursos**; los recursos de V1 solo entran como `data` (lectura): VPC, subred pública A, tabla de rutas, SG de base de datos, perfil de instancia, cuenta, zonas.

**Opción A — `terraform destroy` de toda la raíz V2 (27 recursos):** ALB, 2 listeners, TG, ASG, 2 políticas de escalado, notificación del ASG, plantilla de lanzamiento, 2 SG V2 y sus 9 reglas (incluida `postgres_from_web_v2`, regla añadida al SG compartido de la BD), subred `public_b` + su asociación a la tabla de rutas, 6 alarmas, 1 panel de CloudWatch. Es lo más limpio pero obliga a recrear más cosas al volver.

**Opción B — destrucción dirigida (`-target=aws_lb.main`):** elimina el ALB y, por dependencia, los listeners y las alarmas/panel que usan su `arn_suffix`; conserva ASG (a 0), TG, SG, subred, plantilla. Terraform advierte que `-target` es excepcional. **El conjunto exacto lo debe confirmar un `terraform plan -destroy -target=…` guardado y revisado antes de aplicar** (el plan no modifica AWS, pero necesita credenciales y bloquea el estado; lo pediré aparte).

**Recomendación: B**, porque el único recurso con costo es el ALB; los demás cuestan ≈ 0 con el ASG en 0. Ninguna opción usa `v2-terraform.sh` (ese script **bloquea** cualquier plan con creación o destrucción).

**Se conserva siempre (no está en la raíz V2 o es `data`):** RDS y su SG de BD (solo pierde la regla V2 en la opción A), EC2 V1, VPC, subred A, tabla de rutas, IGW, AMI, instantáneas, certificado ACM, secretos, evidencias del repositorio.

## 3. ¿Afecta eliminar el ALB a RDS, EC2 V1, bases de datos, redes compartidas o evidencias?
- **RDS / datos:** no. El ALB no tiene relación de recurso con la instancia ni con el almacenamiento.
- **EC2 V1:** no. V1 se publica por su propia IP/instancia, no usa este ALB (el TG tiene 0 destinos y la EC2 V1 está `stopped`).
- **Red compartida:** no se elimina VPC, subred A ni tabla de rutas (son `data`). Solo en la opción A se quitan la subred `public_b` y la regla de ingreso V2 del SG de BD; V1 usa su propia regla.
- **Evidencias:** están en el repositorio local; no dependen de AWS. Las instantáneas y AMI no se tocan.
- **Efecto real:** V2 queda sin punto de entrada público; está sin destinos, así que no hay pérdida de servicio actual.

## 4. Reconstrucción cuando se reanuden las pruebas de V2
1. Iniciar el laboratorio y confirmar RDS `available` (`docs/operacion/reencendido-v2.md`).
2. Confirmar que el certificado de ACM existe (`acm describe-certificate`) y que `certificate_arn` del tfvars local sigue siendo válido.
3. `terraform apply` **normal y revisado** de la raíz V2 (opción A o B recrea ALB y listeners). `v2-terraform.sh on` **no sirve para este paso** porque rechaza creaciones; se usa después, para pasar a `asg_enabled=true`.
4. Encender V2: `v2-terraform.sh on` (o `v2-up.sh`) y esperar 2 destinos `healthy` en 2 zonas.
5. **DNS:** el ALB nuevo tendrá **nombre DNS distinto y otras IP**. Si algún registro apunta al ALB viejo hay que actualizarlo: un CNAME al nombre nuevo (TTL 60 s); **DuckDNS solo admite A con una IP**, así que habría que reescribirla y puede cambiar de nuevo. Si solo se prueba con los scripts de `hosts` (`v2-hosts-on.sh`) no hay cambio de DNS: resuelven la IP actual. No pude verificar si hoy hay un registro público apuntando al ALB.
6. Tiempo estimado: ALB ≈ 3–5 min; V2 completa ≈ 10–15 min.

## 5. Las dos «IP elásticas»
**Corrección:** no son EIP reservadas. `describe-addresses` devuelve 2 direcciones asociadas **a interfaces de red** (no a instancias) y `describe-network-interfaces` muestra 2 ENI `ELB …` (us-east-1a y 1b) con IP pública: son las **IP públicas gestionadas del ALB**. Al eliminar el ALB, AWS libera las interfaces y las IP: **dejan de cobrarse** (≈ 0,005 USD/h cada una). La EC2 V1 no tiene IP pública (está detenida). Tras eliminar el ALB no quedaría ningún cargo de IPv4 pública propio de V2.

## 6. RDS: copias y seguridad de la parada
- Instancia: `available`, Multi-AZ, `db.t3.micro`, 20 GiB (máx. 40), cifrada, retención 7 días, sin modificaciones ni mantenimientos pendientes, sin réplicas, protección contra eliminación desactivada.
- **15 instantáneas disponibles:** 4 manuales (4, 8, 19 y 23-oct) y 11 automáticas (la última, 10-nov 07:56). Ventana de restauración puntual: 4-nov → 11-nov 03:24 UTC.
- **Detener no borra datos.** El almacenamiento y las copias persisten; solo dejan de facturarse las horas de instancia. Los eventos de RDS muestran que ya se detuvo y arrancó antes en esta cuenta (28-oct, 4-nov), con parada Multi-AZ aceptada por Academy; no se ve ninguna restricción de permisos para ello.
- **Límites (no exagerar):** las copias están en la misma cuenta/región de Academy, no en OCI. El prefijo `database-backups/` de S3 devolvió **vacío**, así que **no hay respaldo lógico externo verificado**. La ventana de restauración puntual y las copias automáticas envejecen sin renovarse mientras está detenida; las manuales permanecen. Si Academy se cierra al terminar el curso, todo se pierde.
- **Recomendación previa a parar:** una instantánea manual nueva (escritura, se pide aparte; costo ≈ 0, incremental) para tener un punto reciente que no caduque.

## 7. Procedimiento para detener RDS y vigilar el reinicio de 7 días (NO ejecutado)
1. Autorización separada: instantánea manual previa y `rds stop-db-instance` (identificador `nexoeventos-academy-postgres`, perfil `nexoeventos-lab`, `us-east-1`).
2. Comprobar antes: V2 sin destinos, EC2 V1 detenida, nadie conectado (no hay réplicas, no hay V2 activa).
3. Orden: `create-db-snapshot` → esperar `available` → `stop-db-instance` → esperar `stopped` (en Multi-AZ puede tardar varios minutos).
4. **Anotar la hora de parada T** (evento `DB instance stopped`). **Fecha límite = T + 7 días**: AWS la reiniciará por sí misma (por ejemplo, parada el 10-nov → arranque automático ≈ 17-nov).
5. Vigilancia: `describe-db-instances` (estado) y `describe-events` (`DB instance started`) en cada sesión de laboratorio; recordatorio humano en el calendario 2 días antes (17-nov → avisar el 15-nov). Consultar no reinicia el contador. Si no se va a usar antes de T+7, volver a detenerla manualmente (reinicia el contador) o aceptar el costo de volver a encender.
6. Para reanudar: `rds start-db-instance`, esperar `available` (≈ 5–8 min) y luego V2.
7. No existe garantía documentada de qué hace Academy con RDS al terminar la sesión: **verificar el estado al empezar cada sesión**.

## 8. Costo residual estimado y riesgos
| Escenario | Costo aprox. | Hasta el 26-nov (≈ 384 h) | Crédito disponible 28,30 |
|---|---|---|---|
| Hoy (ALB + RDS Multi-AZ activos; EC2 V1 detenida) | ≈ 0,09 USD/h (≈ 2,2 USD/día) | ≈ 34 USD | **No alcanza** (≈ 13 días, hasta ≈ 23-nov) |
| Solo se elimina el ALB | ≈ 0,05 USD/h | ≈ 19 USD | Alcanza |
| ALB eliminado + RDS detenida | ≈ 0,015–0,025 USD/h | ≈ 6–10 USD | Alcanza con holgura |
Lo que **sigue cobrando** con ambas acciones: almacenamiento RDS Multi-AZ (≈ 0,006 USD/h), copias/instantáneas por encima del almacenamiento gratuito (≤ ≈ 0,01 USD/h, cota alta), volumen EBS de V1 y 2 instantáneas de AMI (≈ 0,005 USD/h), 2 secretos, ≈ 12 alarmas, logs (cifras pequeñas). **Dejan de cobrar:** horas del ALB, 2 IPv4 del ALB, horas de instancia RDS (×2 por Multi-AZ).

**Riesgos**
- **R1 — Certificado:** `acm list-certificates` devolvió vacío aunque el listener 443 tiene un certificado. Puede ser filtro de tipo de clave o un certificado que no aparece en la lista. Si se perdiera, no se podría recrear el listener 443 sin importar otro. Verificar con `describe-certificate` antes de eliminar (ni la eliminación del ALB ni la parada de RDS borran el certificado).
- **R2 — Reinicio automático a los 7 días** de RDS (vigilar fecha T+7).
- **R3 — Sin respaldo externo verificado** (S3 vacío; nada en OCI aún): las instantáneas son la única copia.
- **R4 — Opción B con `-target`:** el conjunto exacto de recursos debe confirmarse con un plan guardado antes de aplicar.
- **R5 — Rebuild:** `v2-terraform.sh on` no recrea el ALB; hace falta un apply revisado previo.
- **R6 — DNS/DuckDNS:** si hay un registro A hacia el ALB viejo, queda obsoleto tras la reconstrucción.
- **R7 — Estado del lab:** el crédito se consume mientras ALB y RDS sigan activos (≈ 0,09 USD/h); el laboratorio Docker local (`nexo-repl-lab`) no cuesta en AWS.

## 9. Autorizaciones que se pedirán por separado (ninguna concedida)
1. Plan guardado `terraform plan -destroy` (opción A o B) — sin aplicar.
2. Eliminación del ALB (aplicar el plan revisado).
3. Instantánea manual de RDS.
4. Parada de RDS.
