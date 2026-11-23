# C-04 — tres ciclos de respaldo AWS → OCI (runbook; NADA de esto se ejecuta sin autorización por paso)
Ventana máxima **90 min**. Parada inmediata si: sesión de Academy < 1,5 h, `pg_isready` falla, un ciclo termina con código ≠ 0 dos veces, el PAR devuelve 401/403/412, o se supera la ventana.

| # | Paso | Dónde | Escribe en | Autorización |
|---|---|---|---|---|
| 0 | Lista previa del bucket: `oci os object list --bucket-name nexoeventos-recovery --all --query 'data[].name' > antes.json` (solo lectura) | Mac | nada | no |
| 1 | Copiar `backup_cycle.py`, `backup_freshness.py`, `fingerprint.sql`, `backup-role.sql`, `provision-backup-role.sh`, `oci-recuperacion/aws-academy.example.json` (sin secretos) | SSM → EC2 `/opt/nexoeventos/…` | disco de la EC2 | **sí** |
| 2 | Paquete de CA de RDS con SHA-256 verificado (`deploy/install-rds-ca-bundle.sh`) | EC2 | `/etc/nexoeventos/rds-ca-bundle.pem` | **sí** |
| 3 | Clave de FIRMA dedicada generada **en la EC2** (`openssl genpkey … -out /etc/nexoeventos/backup-sign.pem`, 0600) y solo su parte PÚBLICA se trae a la Mac | EC2 | `/etc/nexoeventos/backup-sign.pem` | **sí** |
| 4 | Certificado PÚBLICO de cifrado en `/etc/nexoeventos/recovery-oci-public.crt` (`work/recovery-keys/…/recovery-public.crt`; nunca la `.pem` privada) | EC2 | disco | **sí** |
| 5 | `provision-backup-role.sh <rds> us-east-1`: crea `nexoeventos_backup` (solo lectura) y `backup.env` 0600 | EC2 | **RDS (rol nuevo)** y disco | **sí (escritura en la base)** |
| 6 | PAR de **solo escritura** (`AnyObjectWrite`) con **prefijo `backups/c04-20261119/`** (nombre de objeto = prefijo), caducidad ≤ 2 h, creado por la propietaria; la URL se pega **dentro de una sesión interactiva** (`aws ssm start-session`) en `/etc/nexoeventos/backup-par.url` (0600). **No** pasarla como parámetro de `send-command` (queda en el historial de SSM) | OCI + EC2 | **OCI (PAR)** | **sí (propietaria)** |
| 6b | Sonda `c04-par-probe.py` (1 objeto diminuto escrito 2 veces; esperado 200 y luego 412): **no se asume** que el PAR respete `If-None-Match` | EC2 → OCI | **OCI (1 objeto de prueba)** | **sí** |
| 7 | Tres ciclos manuales (`bash /opt/nexoeventos-c04/deploy/backup/c04-run-cycle.sh`): `systemctl start nexoeventos-backup.service` ×3, ~25–30 min entre ciclos (el **timer NO se habilita**) | EC2 | **OCI (3 objetos + 3 manifiestos + 3 firmas)** | **sí** |
| 8 | `c04_verify.py --prefix backups/c04-20261119/ --profile NEXOEVENTOS_UPLOADER --since <inicio> --before-list antes.txt --signer-pub deploy/backup/signers/c04-backup-sign.pub --expect 3` y `backup_freshness.py --report` sobre `cycles.jsonl` (RPO **observado**) | Mac / EC2 | evidencias saneadas | no (lectura) |
| 9 | **Revocar el PAR** (OCI) y comprobar que la PUT con esa URL ya falla; borrar `backup-par.url` | OCI + EC2 | OCI | **sí (propietaria)** |
| 10 | (opcional) `backup-role-revert.sql` si no se conserva el rol; detener EC2 y RDS y anotar el nuevo reinicio automático (+7 días) | AWS | AWS | **sí** |

Reversión: PAR → revocar; rol → `backup-role-revert.sql` (solo ese rol); objetos subidos → **no se borran** (versionado; son evidencia); archivos de la EC2 → `shred -u` de `backup-par.url` y `backup-sign.pem` si se descarta. Sin tocar la compuerta de escritura, DNS, SG/NSG ni el failover.
