# R01 — restauración cloud aislada preparada

Estado al 9 de octubre de 2026: **preparada, no ejecutada**.

- Origen: PITR de la RDS original `nexoeventos-academy-postgres`, usando el `LatestRestorableTime` que haya alcanzado la línea base tomada con escrituras pausadas. El snapshot manual cifrado previo permanece como alternativa, pero no sustituye la comparación con una línea base reciente.
- Destino temporal: una sola RDS privada `nexoeventos-academy-restore-<AAAAMMDDtHHMM>`, `db.t3.micro`, Single-AZ, mismo DB subnet group y SG de datos. El identificador, ARN cifrado y `RunId` se guardan en un recibo local `0600` antes de poder limpiarla.
- Costo operativo previsto: USD 0.02–0.03 por hora mientras exista la instancia temporal, más almacenamiento/backup proporcional. Es una estimación, no un límite automático; se confirmará con el precio vigente antes de ejecutar.
- Criterios de éxito de datos: RDS `available` y privada; revisión Alembic, conteos y huella lógica idénticos; reservas sin propietarios huérfanos; todas las entradas QR descifrables y con hash coincidente, sin revelar tokens.
- Medidas separadas: punto recuperable frente a T0, tiempo T0→RDS disponible y tiempo T0→datos verificados. Recuperación completa del servicio seguirá pendiente porque esta prueba no conmuta aplicación, DNS ni HTTPS.
- Limpieza: `restore-drill.sh cleanup` solo acepta el identificador exacto, el recibo `0600`, el hash del ARN y las etiquetas `Project=NexoEventos`, `Purpose=restore-drill`, `ManagedBy=manual-drill` y el `RunId` de esa ejecución. No puede alcanzar la RDS original.

El ejecutable preparado es `scripts/cloud/restore-drill.sh`; no se lanzó en esta sesión.
