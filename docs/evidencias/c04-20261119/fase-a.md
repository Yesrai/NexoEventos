# C-04 — Fase A (preparación en la EC2 de V1) — 19-nov-2026 03:50–04:00 UTC — resultado saneado
Alcance autorizado: solo la EC2 `nexoeventos-academy-app` (verificada: cuenta esperada, `us-east-1`). Sin escrituras en RDS ni en OCI; sin PAR; sin timers; sin cambios de IAM/SG/DNS/Terraform. Salidas sin credenciales, ARN ni IP.

## Instalado en la EC2 (todo nuevo; nada existente se modificó ni sobrescribió)
| Elemento | Ruta | Permisos | Verificación |
|---|---|---|---|
| Scripts y pruebas de respaldo (backup_cycle, backup_freshness, fingerprint.sql, restore-drill, verify-transfer, lib-cms-key, compare-fingerprint, SQL y script del rol, runner manual) | `/opt/nexoeventos-c04/` | root, 0755/0644 | SHA-256 de los 15 archivos comparado con el manifiesto local |
| Paquete oficial de CA de RDS (`truststore.pki.rds.amazonaws.com`, 114 certificados) | `/etc/nexoeventos/rds-ca-bundle.pem` | root 0644 | SHA-256 idéntico descargado en la Mac y en la EC2 (`90a6f1a7…2f21b`) |
| Certificado PÚBLICO de cifrado (CN `NexoEventos backup recovery`, serie `5AF7C373…5808`, válido hasta 2027-10-08) | `/etc/nexoeventos/c04/recovery-oci-public.crt` | root 0644 | sin clave privada; cifrado CMS de prueba correcto |
| Clave de FIRMA nueva (EC P-256) | `/etc/nexoeventos/c04/backup-sign.pem` | root **0600** | autoprueba firmar/verificar «Verified OK»; nunca se mostró |
| Clave pública de firma (huella SHA-256 DER `2a9fdbf1…2994fd`) | `/etc/nexoeventos/c04/backup-sign.pub` y `deploy/backup/signers/` (+ copia en `work/c04/`) | 0644 | huella idéntica en la EC2 y en la Mac |
| Perfil del ciclo (solo rutas y parámetros) | `/etc/nexoeventos/c04/backup.json` | root 0600 | — |
| Estado del ciclo | `/var/lib/nexoeventos-c04/` | root 0700 | vacío |
**No existen todavía:** `backup.env` (lo crea el aprovisionamiento de la fase B), el rol `nexoeventos_backup` en RDS, `backup-par.url` (PAR de OCI) ni ningún timer o servicio de respaldo (los 2 timers existentes son `nexoeventos-duckdns` y `nexoeventos-certbot-renew`, ajenos).

## Comprobaciones técnicas
- Herramientas: Python **3.9.25** (el que usa el servicio), OpenSSL 3.5.8, `pg_dump`/`psql`/`pg_restore` 18.6 (servidor 18.3 → compatible), `aws`, `jq`, `shred`, `install`, `curl`.
- **Python 3.9:** `py_compile` y `--help` de ambos scripts correctos; **`test_backup_cycle.py`: 28/28 pruebas en la EC2** (tras corregir en local una incompatibilidad real: anotaciones `X | None` y `shasum` solo de macOS).
- **TLS `verify-full` preparado:** apretón de manos TLS 1.3 contra RDS con el paquete de CA y comprobación del nombre del servidor → correcto; control negativo con el almacén de CA del sistema → falla (`self-signed certificate in certificate chain`). Sin credenciales ni consultas.
- RDS acepta conexiones; `/` con 16 GiB libres; reloj sincronizado; servicios `nexoeventos-api` y `nginx` siguen `active`.

## Rotación de credenciales de RDS (aclarado)
El «Reset master credentials» del 18-nov 17:29 UTC (12:29 Perú) es la **rotación automática del secreto maestro gestionado por RDS**: CloudTrail muestra intentos horarios `RotationFailed` mientras la base estaba detenida y `RotationSucceeded` a las 12:29 Perú, con la base ya encendida. No fue una acción manual. El script de la fase B lee `AWSCURRENT` dentro de la EC2 (la simulación de IAM indica que `LabRole` puede leerlo) y no imprime el valor.
