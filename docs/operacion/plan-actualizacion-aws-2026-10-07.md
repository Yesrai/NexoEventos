# Plan previo a Terraform y actualización de la aplicación

Lecturas realizadas el **7 de octubre de 2026, 14:49–15:00 (America/Lima)** con el perfil temporal protegido, cuenta esperada y `us-east-1`. No contiene IDs, endpoints ni secretos.

## Estado real

- STS: correcto contra la cuenta esperada.
- EC2 `t3.small`: `running`, iniciada por Academy a las 14:41 Lima; IMDSv2 requerido.
- RDS PostgreSQL 18.3 `db.t3.micro`: `stopped`, privada, cifrada, Single-AZ, 20 GiB; reinicio automático aproximado el 10-oct a las 19:39 Lima.
- Cost Explorer, 1–7 de octubre: **USD 0.8180416576** de costo no combinado. No es el saldo Academy. Budgets no devolvió un presupuesto consultable por API.
- HTTPS `/`: 200 y certificado vigente hasta 1-ene-2027. Con RDS detenida, `/healthz` y `/api/events` no responden. HTTP devolvió 403 en lugar del 301 documentado; debe corregirse/comprobarse en la actualización.
- Código remoto: disposición legacy; migraciones `0004` y `0005` no están presentes. `backend.env` y `migration.env` siguen `0600`; certificado presente; servicio API activo.

## Terraform autenticado

El refresh autenticado leyó el resto de la infraestructura, detectó la nueva IPv4 pública y mostró **0 altas, 1 cambio in-place y 0 eliminaciones**, pero terminó con `403` por la SCP en `s3:GetBucketObjectLockConfiguration`. Por ello **no existe un plan aplicable vigente** y no se afirma que el resumen sea completo.

Hallazgos contrastados mediante lecturas directas:

1. RDS remoto conserva `MaxAllocatedStorage=20`, igual a los 20 GiB asignados. La configuración local propone `20 → 0`, actualización in-place para expresar que el autoescalado está desactivado.
2. El lifecycle remoto usa `database-backups/`; la configuración local propone `backups/database/`, donde está el respaldo real.
3. La AMI fija local coincide con la EC2 observada. El plan parcial no indicó reemplazo de EC2.
4. El bucket permanece en estado; no se usó `removed`, `-refresh=false` ni `ignore_changes`.

El plan histórico del 2 de octubre fue movido a `work/terraform-plans/archive/` y no puede aplicarse como vigente. No se recomienda aplicar Terraform mientras el refresh completo termine en error. Las dos correcciones remotas pueden evaluarse en una cuenta con lectura suficiente o tras una aclaración del laboratorio; no son requisito para actualizar la aplicación.

## Actualización de aplicación propuesta

1. Detener temporalmente la API antes de arrancar RDS para impedir escrituras.
2. Arrancar RDS y comprobar estado/backup automático.
3. Crear snapshot manual preactualización y dump lógico cifrado; verificar copia externa y crear un recibo remoto `0600`.
4. Crear artefacto del commit aprobado con Node 24 y checksum; desplegarlo como una nueva release sin tocar `/etc/nexoeventos`, claves QR ni `/etc/letsencrypt`.
5. Con la identidad migradora, ejecutar Alembic `0003 → 0004 → 0005`; después insertar los 27 eventos ficticios. Si un ID ya existe, la siembra no modifica cupos, reservas, propietario, precio, fecha, modalidad ni zonas. En esta ventana el catálogo solo habilita entradas generales o por zonas: asientos numerados y 3D quedan fuera del despliegue.
6. Exigir `alembic current = 0005`, cambiar el enlace `current`, reiniciar systemd, validar Nginx y `/ready`.
7. Comprobar HTTPS y el flujo registro → acceso → reserva simulada → entrada → validación única, sin capturar QR utilizables.
8. Si falla el código, restaurar `previous`. Si falla o debe revertirse la migración/datos, restaurar la RDS preactualización en forma aislada; el rollback de código no deshace esquema.
9. Limpiar todas las versiones/marcadores S3 creados por Ansible bajo el prefijo exclusivo de la EC2 y confirmar que `backups/database/` permanezca intacto.
10. Recoger EV10 y detener EC2/RDS al finalizar.

Ansible por SSM quedó probado sin SSH: plugin oficial ARM64 1.2.835.0, instancia `Online`, módulo `ping` correcto. El inventario dinámico falló localmente; el wrapper ahora genera un inventario estático `0600` después de validar cuenta, región, etiqueta y unicidad. El ensayo de transferencia creó 18 versiones/marcadores temporales; se eliminaron todos y el respaldo de base permaneció.

## Costo incremental antes de ejecutar

Supuesto: ventana de dos horas, tarifas públicas ya documentadas.

| Partida | Estimación |
|---|---:|
| EC2 + RDS + IPv4 durante 2 h | USD 0.0876 |
| logs, solicitudes y transferencia pequeña | margen USD 0.02 |
| snapshot preactualización de 20 GiB | incremental real desconocido; techo conservador USD 1.90/mes si todo fuese facturable |
| **ventana sin snapshot completo** | **≈ USD 0.11** |
| **techo conservador incluyendo 20 GiB completos de snapshot** | **≈ USD 2.01** |

Mientras se espera, la EC2 activa suma aproximadamente **USD 0.0258/h** por instancia e IPv4. Persisten aparte EBS, almacenamiento RDS, secreto, S3, CloudWatch/alarma y snapshots: base aproximada **USD 0.148/día**, más snapshot, ingestión, solicitudes y transferencia; el escenario conservador anterior es ≈ USD 0.21/día.

## Cambios no incluidos

- V2, ALB, segunda EC2, EKS, IAM, SSH o nuevos privilegios.
- `terraform apply` mientras no exista un plan completo revisable.
- carga 20 VU × 5 min y restauración cloud cronometrada; permanecen como sesiones posteriores separadas.
