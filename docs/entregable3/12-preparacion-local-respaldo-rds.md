# Entregable 3 · Preparación local del respaldo RDS → OCI — resultados (11-nov-2026)

> ## ⚠ ADVERTENCIA VIGENTE — reinicio automático de RDS
> RDS está **detenida** desde **2026-11-11 14:38:33 UTC** y AWS la **reiniciará sola hacia el 2026-11-18 ~14:38 UTC** (≈ 0,04 USD/h). Recordatorio del 16-nov: `recordatorio-rds-20261116.md`. Si se enciende RDS para el respaldo, la nueva parada fija una fecha nueva.

**Alcance cumplido:** solo trabajo local. No se consultó ni modificó AWS, OCI ni Azure; no se encendió nada; Docker local solo con contenedores desechables (ya destruidos); sin commits ni push. Plan de referencia: `11-plan-respaldo-restaurable-rds-a-oci.md`.

## 1. Cambios de código (locales, sin confirmar en Git)
**`scripts/cloud/db-backup-cms.py`** (copia original en `work/db-backup-cms.py.orig-20261111`; diff en `evidencias/db-backup-cms-cambios-20261111.diff`):
- Se eliminó la **línea base fija** (135 reservas/25 usuarios/Alembic 0008) que habría abortado el respaldo. Ahora usa `scripts/multicloud/fingerprint.sql` (las mismas 10 claves que `restore-drill.sh`) **antes y después** del volcado.
- Se detiene si la huella previa está vacía (la base no responde) **antes** de volcar.
- Termina con error —y dice por qué— si el SHA-256 de la EC2 no coincide con el descargado, si no descifra a `PGDMP`, si la huella cambió durante el volcado o si el volcado pesa < 1 KiB (aviso: no apagar RDS sin un respaldo válido).
- Escribe `respaldo-rds.json` y **`linea-base-restauracion.json`** (huella observada en el origen, clave `rds-<fecha>`), listo para `restore-drill.sh --baseline … --baseline-key rds-<fecha>`.
- Nombre de salida nuevo: `nexoeventos-rds-<fecha>.cms` (ya no «alembic0008»).
**Nuevo `scripts/cloud/test_db_backup_cms.py`:** prueba con una CLI `aws` falsa y claves desechables (sin nube).

## 2. Pruebas realizadas (todas locales)
| Prueba | Resultado | Evidencia |
|---|---|---|
| `test_db_backup_cms.py`: éxito; huella cambia durante el volcado; volcado no PGDMP; sin `NEXO_ALLOW_CLOUD_CHANGES`; base sin respuesta; sin huella previa no hay volcado | **9/9 correctas** | `evidencias/prueba-local-db-backup-cms-20261111.txt` |
| `test-restore-pipeline.sh` (base local → CMS «AWS» → re-cifrado «OCI» → verificación → restauración en PostgreSQL 18 desechable → huella) con 7 casos negativos | **16 correctas, 0 fallidas**; restauración 6 s | `evidencias/prueba-local-pipeline-restauracion-20261111.txt` |
| Correspondencia certificado↔clave de **AWS** (huella de la clave pública, sin leer la clave) | **Coincide**; certificado vigente hasta 8-oct-2027 | esta nota |
| Respaldo real del 23-oct: SHA-256 del CMS de AWS = manifiesto (`91c4ca41…`); descifrado con la clave de AWS → volcado `PGDMP` con SHA-256 del volcado en claro = manifiesto (`67b6876f…`); SHA-256 del `.oci.cms` = manifiesto (`ae87bb87…`) | **Todo coincide** | esta nota |
| Certificado de **OCI**: huella SHA-256 `98:1C:97:B5…` = la registrada el 23-oct; vigente hasta 22-oct-2029 | **Coincide** | esta nota |
**Nota de honestidad:** una primera comprobación del hash del volcado dio un valor distinto porque mi tubería con `tee >(head -c5)` cortó el flujo (SIGPIPE); repetida sin ese atajo coincide. No hay discrepancia real.

## 3. Lo que NO se pudo comprobar localmente
- La **clave privada de OCI** está cifrada con frase de paso; no la tengo ni debo tenerla. Por eso no verifiqué su correspondencia con el certificado ni ensayé el descifrado real del `.oci.cms` del 23-oct. **Lo debes hacer tú en tu terminal** (pide la frase):
```bash
openssl x509 -in ~/.nexoeventos/recovery-oci/oci-recovery-public.crt -noout -pubkey | openssl sha256
openssl pkey -in ~/.nexoeventos/recovery-oci/oci-recovery-private.pem -pubout | openssl sha256   # deben dar el mismo hash
```
```bash
scripts/multicloud/restore-drill.sh --manifest work/oci-transfer/nexoeventos-alembic0008-20261023T150946Z.manifest.json --cms work/oci-transfer/nexoeventos-alembic0008-20261023T150946Z.oci.cms --key ~/.nexoeventos/recovery-oci/oci-recovery-private.pem --baseline docs/multicloud/baseline-restauracion.json --baseline-key 0008-estado-20261022 --mode docker
```
- El script corregido **no se probó contra AWS real** (solo con CLI falsa): la primera ejecución real será la ventana autorizada; ante cualquier error me detengo.
- Sigue sin verificarse en la nube el prefijo S3 `backups/database/` ni el entorno de `/etc/nexoeventos/migration.env` en la EC2 tras el reinicio de credenciales del 4-nov.

## 4. Siguientes autorizaciones (ninguna concedida)
1. (Tuya, local) ejecutar los dos comandos de §3 con la frase de paso y decirme el resultado.
2. Ventana AWS: Start Lab, encender RDS + EC2 V1, volcado cifrado, apagar (plan `11` §4).
3. Subida a OCI y restauración aislada local del nuevo respaldo.
