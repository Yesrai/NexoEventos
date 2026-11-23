# Entregable 3 · Plan: respaldo PostgreSQL restaurable de RDS → OCI (11-nov-2026)

> ## ⚠ ADVERTENCIA VIGENTE — reinicio automático de RDS
> RDS `nexoeventos-academy-postgres` está **detenida** desde **2026-11-11 14:38:33 UTC**. AWS la **reiniciará sola hacia el 2026-11-18 ~14:38 UTC** (7 días) y desde ese momento cobra ≈ 0,04 USD/h. Recordatorio: `docs/entregable3/recordatorio-rds-20261116.md` (16-nov). **Si en este plan se enciende RDS, la parada posterior fija una fecha nueva (parada + 7 días): actualizar el recordatorio.**

**Estado: SOLO PLANIFICACIÓN. No se encendió nada, no se creó ni transfirió nada, no se consultó ninguna nube; sin commits ni push.** Base: scripts y documentos locales (`scripts/cloud/db-backup-cms.py`, `scripts/multicloud/*`, `docs/multicloud/05–08`, `docs/evidencias/multicloud/oci/20261023-*`).

## 1. Instantánea nativa de RDS ≠ respaldo PostgreSQL restaurable
| | Instantánea nativa de RDS | Respaldo lógico PostgreSQL (`pg_dump -Fc`) |
|---|---|---|
| Qué es | Copia de bloques del volumen cifrado, formato interno de AWS | Archivo con esquema + datos que cualquier PostgreSQL ≥ 18 sabe leer |
| Dónde se restaura | Solo como una **nueva instancia RDS** en AWS (misma cuenta/región o compartida) | En cualquier PostgreSQL (Docker, VM de OCI, otra nube) con `pg_restore` |
| ¿Sale de AWS? | No. Vive en la misma cuenta de Academy; si la cuenta expira, **se pierde** | Sí: se cifra, se envía a OCI y se verifica con SHA-256 |
| Verificación | Estado `available` | Hash + catálogo + restauración real + huella de datos |
| Con RDS detenida | Existe y sirve (tenemos 5 manuales; la nueva `nexoeventos-pre-parada-20261111`) | **No se puede generar**: `pg_dump` necesita la base **encendida** |
Otras vías **no** sirven como respaldo portable: «exportar instantánea a S3» produce Parquet (analítico, no restaurable con `pg_restore`); restaurar la instantánea solo para volcarla cuesta más y también necesita una EC2 dentro de la VPC.

## 2. Hallazgo clave: ya existe un flujo probado (23-oct) — hay que adaptarlo, no inventarlo
Cadena probada: EC2 V1 por SSM (`pg_dump | openssl cms -encrypt` con certificado público de AWS, sin texto plano en disco) → S3 privado → estación local (verifica SHA-256, comprueba que descifra a `PGDMP`, huella antes/después) → `prepare-oci-transfer.sh` (descifra y **re-cifra con el certificado independiente de OCI** en tubería, genera manifiesto) → subida a `nexoeventos-recovery` (privado, versionado, usuario sin sobrescribir ni borrar) → descarga y verificación → `restore-drill.sh` (restauración aislada + huella). El 23-oct: huella idéntica 10/10, restauración 24 s.
**Defectos a corregir antes de reutilizarlo (✔ corregidos el 11-nov; ver informes 12 y 19):**
1. `db-backup-cms.py` tiene una **línea base fija** (135 reservas, 25 usuarios, Alembic 0008) y **aborta** si los datos cambiaron: hay que cambiarlo a «huella previa = huella posterior» sin valores fijos, y guardar esa huella como nueva línea base (`baselines[…]` en `docs/multicloud/baseline-restauracion.json`).
2. Los datos ya no coinciden con el 22-oct: la línea base 0008 queda obsoleta para este respaldo.
3. Corrección del informe 09: el listado vacío de S3 usó el prefijo `database-backups/`; el real del script es **`backups/database/`**. Hay que verificarlo en solo lectura al abrir la ventana (no consta aún qué copias hay allí).
4. `aws rds wait db-instance-stopped` no existe; para la parada se sondea el estado.
5. Confirmar que `/etc/nexoeventos/migration.env` en la EC2 sigue siendo válido tras el reinicio de credenciales maestras del 4-nov (se comprueba con la propia huella previa; si falla, el flujo se detiene).

## 3. Qué se prepara localmente y qué exige encender RDS
| Paso | Local, sin nube | Requiere RDS (y EC2 V1) encendidas |
|---|---|---|
| Corregir `db-backup-cms.py` y probar con CLI falsa/jmespath | ✔ | |
| Comprobar claves: correspondencia certificado↔clave de AWS y de OCI (offline, `openssl`) | ✔ | |
| Ensayo completo del flujo con el respaldo del 23-oct (descifrar → re-cifrar → `restore-drill.sh --mode docker` con `postgres:18`) | ✔ (Docker local; no toca OCI/AWS) | |
| Preparar comandos, manifiestos y plantilla de evidencias | ✔ | |
| Huella previa y `pg_dump` cifrado | | ✔ |
| Descarga, verificación SHA-256, descifrado de control, huella posterior | ✔ (tras el volcado) | |
| Re-cifrado para OCI, manifiesto, subida y verificación en OCI | ✔ (red a OCI; escritura en OCI → autorización aparte) | |
| Restauración aislada del nuevo respaldo (Docker local) | ✔ | |

## 4. Ventana corta de ejecución en AWS (propuesta)
Objetivo: tener RDS y EC2 V1 encendidas **solo** el tiempo del volcado.
| Min | Acción (todas requieren autorización de escritura) |
|---|---|
| 0 | Tú: Start Lab + credenciales. Verifico rol/cuenta/región. Solo lectura: prefijo `backups/database/`, RDS `stopped`, EC2 V1 `stopped`, ASG 0, sin ALB. |
| 2 | `start-db-instance` (5–10 min hasta `available`) y, en paralelo, `start-instances` EC2 V1 (SSM en línea ≈ 2–3 min). |
| ≈ 12 | Huella previa (solo lectura SQL) → `pg_dump -Fc` cifrado con CMS → S3 (SSE). Seconds–1 min (la base pesa ≈ 0,1 MB). |
| ≈ 15 | Descarga local, SHA-256 contra el de la EC2, descifrado de control (`PGDMP`), huella posterior; deben coincidir. |
| ≈ 17 | **Apagar de inmediato:** `stop-instances` EC2 V1 y `stop-db-instance` RDS; esperar `stopped` (RDS Multi-AZ ≈ 5–8 min, aún factura hasta entonces). |
| ≈ 25–30 | Confirmar `stopped`; **anotar la nueva hora → nueva fecha de reinicio automático (+7 días)** y actualizar el recordatorio. |
El resto (re-cifrar, OCI, restauración) ocurre **sin** AWS encendido.
Si la huella previa no coincide con otra posterior (hubo escrituras de la app V1 al arrancar), se repite el volcado (segundos) antes de apagar.

## 5. Costos, tiempo, permisos y red
- **Costo AWS estimado (tarifas públicas):** RDS Multi-AZ ≈ 0,042 USD/h + EC2 `t3.small` y su IPv4 ≈ 0,03 USD/h ≈ **0,07 USD/h × ≈ 0,5 h ≈ 0,04–0,10 USD**; S3 y SSM ≈ 0. Peor caso por olvidar apagar: ≈ 0,07 USD/h (≈ 1,7 USD/día). Crédito disponible estimado: ≈ 27 USD (a verificar en la consola).
- **Costo OCI:** objeto ≈ 0,1 MB en Object Storage Standard: dentro de lo gratuito (no verificado en el panel de OCI). Sin VM ni IP pública.
- **Tiempo total:** ventana AWS ≈ 25–35 min; local ≈ 10–15 min; **RTO de la restauración de prueba** se medirá (el del 23-oct fue 24 s de restauración; no es el RTO de producción).
- **Permisos AWS (rol de Academy; ya usados el 3 y 23-oct):** `rds:StartDBInstance/StopDBInstance/DescribeDBInstances`, `ec2:StartInstances/StopInstances/DescribeInstances`, `ssm:SendCommand/GetCommandInvocation`, y desde la EC2 (perfil de instancia) `s3:PutObject/GetObject` en el bucket privado `nexoeventos-academy-*`. **Permisos OCI:** perfil `NEXOEVENTOS_UPLOADER` (crear/leer/inspeccionar objetos; sin sobrescribir ni borrar). Claves: el CMS de AWS se descifra con la clave privada de AWS (`work/recovery-keys/`); el de OCI con `~/.nexoeventos/recovery-oci/oci-recovery-private.pem` (frase de paso solo en tu terminal; ambos pares existen localmente: verificado por nombre, sin leerlos).
- **Red:** no se abre ningún puerto ni VPN. EC2 V1 (subred pública) → RDS por el SG existente; SSM por HTTPS saliente; S3 por HTTPS; **no hay camino directo AWS→OCI**: el archivo pasa por tu estación (donde se descifra y re-cifra) y sube a OCI por HTTPS 443 (sa-saopaulo-1).

## 6. Verificación de integridad (SHA-256) y restauración aislada
SHA-256 en cada salto: (1) CMS calculado en la EC2 = CMS descargado; (2) volcado en claro (`plaintext_dump_sha256`, calculado en tubería) = el del manifiesto; (3) CMS para OCI = objeto subido = objeto **descargado de OCI** (`verify-transfer.sh`). Restauración (`restore-drill.sh --mode docker`, PostgreSQL 18 desechable, directorio 0700 destruido al salir): hash del cifrado → descifrado → hash del volcado → `pg_restore --list` → `pg_restore --exit-on-error` en una base nueva → huella (alembic, usuarios, eventos, reservas, entradas, `reserved_total`, `inventory_md5`, `reservations_md5`) **idéntica a la huella previa** del origen. **La base original no se toca** (solo `SELECT` y `pg_dump`, que son lecturas) y el simulacro corre en un contenedor sin conexión a AWS. Casos negativos (archivo alterado, clave errónea, línea base distinta) deben fallar. Opcional y aparte: repetir el simulacro en la VM de OCI (hay que crearla, E5 de pago con crédito de prueba; no necesario para esta fase).

## 7. Comandos preparados (NO ejecutados)
```bash
# Local — correspondencia certificado↔clave de OCI (pide la frase en tu terminal)
openssl x509 -in ~/.nexoeventos/recovery-oci/oci-recovery-public.crt -noout -pubkey | openssl sha256
openssl pkey -in ~/.nexoeventos/recovery-oci/oci-recovery-private.pem -pubout | openssl sha256
```
```bash
# Local — ensayo del flujo con el respaldo del 23-oct en Docker (sin nube)
scripts/multicloud/restore-drill.sh --manifest work/oci-transfer/nexoeventos-alembic0008-20261023T150946Z.manifest.json --cms work/oci-transfer/nexoeventos-alembic0008-20261023T150946Z.oci.cms --key ~/.nexoeventos/recovery-oci/oci-recovery-private.pem --baseline docs/multicloud/baseline-restauracion.json --baseline-key 0008-estado-20261022 --mode docker
```
```bash
# Ventana AWS (tras autorización) — encender
aws rds start-db-instance --db-instance-identifier nexoeventos-academy-postgres --profile nexoeventos-lab --region us-east-1
aws rds wait db-instance-available --db-instance-identifier nexoeventos-academy-postgres --profile nexoeventos-lab --region us-east-1
aws ec2 start-instances --instance-ids <i-V1> --profile nexoeventos-lab --region us-east-1 && aws ec2 wait instance-status-ok --instance-ids <i-V1> --profile nexoeventos-lab --region us-east-1
```
```bash
# Respaldo cifrado (tras corregir el script; hoy abortaría por la línea base fija)
NEXO_ALLOW_CLOUD_CHANGES=YES backend/.venv/bin/python scripts/cloud/db-backup-cms.py --cert work/recovery-keys/preupdate-20261008t0113z/recovery-public.crt --key work/recovery-keys/preupdate-20261008t0113z/recovery-private.pem --out docs/evidencias/multicloud/aws/<AAAAMMDD>-respaldo-rds
```
```bash
# Apagar inmediatamente
aws ec2 stop-instances --instance-ids <i-V1> --profile nexoeventos-lab --region us-east-1
aws rds stop-db-instance --db-instance-identifier nexoeventos-academy-postgres --profile nexoeventos-lab --region us-east-1
# esperar 'stopped' sondeando: aws rds describe-db-instances ... --query 'DBInstances[0].DBInstanceStatus'
```
```bash
# Local — re-cifrado para OCI y subida (escritura OCI: autorización aparte; nombre único: el usuario no puede sobrescribir)
scripts/multicloud/prepare-oci-transfer.sh work/backups/external/<nuevo>.cms <clave-aws.pem> ~/.nexoeventos/recovery-oci/oci-recovery-public.crt work/oci-transfer <sha256-esperado>
oci os object put --profile NEXOEVENTOS_UPLOADER -ns "$OCI_NS" --bucket-name nexoeventos-recovery --name backups/<nuevo>.oci.cms --file work/oci-transfer/<nuevo>.oci.cms
oci os object put --profile NEXOEVENTOS_UPLOADER -ns "$OCI_NS" --bucket-name nexoeventos-recovery --name backups/<nuevo>.manifest.json --file work/oci-transfer/<nuevo>.manifest.json
oci os object get --profile NEXOEVENTOS_UPLOADER -ns "$OCI_NS" --bucket-name nexoeventos-recovery --name backups/<nuevo>.oci.cms --file /tmp/verif.oci.cms && scripts/multicloud/verify-transfer.sh work/oci-transfer/<nuevo>.manifest.json /tmp/verif.oci.cms
```

## 8. Riesgos y límites (sin sobredeclarar)
- **Reinicio automático ≈ 18-nov:** si se enciende RDS para esta ventana, hay que **volver a detenerla** y registrar la nueva fecha; olvidarlo cuesta ≈ 0,04–0,07 USD/h.
- **Es un respaldo puntual**, no continuo: su RPO es el momento del volcado (datos al estado de la última parada, ya protegidos además por la instantánea del 11-nov). Los respaldos frecuentes requieren la aplicación y la BD encendidas (otra fase).
- La restauración aislada es **local (Docker)**; la prueba en OCI con VM sigue pendiente salvo que se repita y se autorice.
- `TICKET_ENCRYPTION_KEY` y `SECURITY_HASH_KEY` **no están en el volcado**: deben custodiarse aparte para que las entradas ya emitidas sigan validándose.
- Arrancar EC2 V1 enciende la app V1 (puede escribir); la huella antes/después lo detecta.
- Si RDS no inicia o el entorno de la EC2 falla, **me detengo** y consulto; plan B (más caro y lento): restaurar la instantánea del 11-nov en una instancia temporal.

## 9. Autorizaciones que se pedirán por separado (ninguna concedida)
1. **Local:** corregir `db-backup-cms.py`, comprobar claves y ensayo en Docker con el respaldo del 23-oct (sin nube).
2. **Ventana AWS:** Start Lab, encender RDS + EC2 V1, volcado cifrado, apagar ambas (con nueva fecha de reinicio).
3. **OCI:** subir el nuevo respaldo y su manifiesto al bucket y verificarlo.
4. **Restauración aislada local** del nuevo respaldo y registro de evidencias.
