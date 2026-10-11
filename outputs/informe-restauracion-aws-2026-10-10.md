# Informe R01 AWS — 10 de octubre de 2026

Se ejecutó una restauración PITR aislada de PostgreSQL sin desplegar aplicación, aplicar Terraform ni cambiar DNS.

## Resultado medido

- RPO demostrado: 3 min 32 s.
- RDS temporal disponible: 20 min 49 s desde T0.
- Datos restaurados y verificados: 21 min 4 s desde T0.
- Alembic `0005`, seis tablas y huella lógica coincidentes.
- Reservas sin propietarios huérfanos.
- 135/135 entradas QR descifrables y con hash correcto; ningún token fue mostrado.
- Recuperación completa del servicio: pendiente, porque no hubo conmutación de aplicación/DNS/HTTPS.

La RDS temporal `nexoeventos-academy-restore-20261010t2347` fue eliminada únicamente después de validar recibo, hash de ARN y etiquetas. No quedaron RDS temporales con el prefijo de restauración.

## Cierre de consumo

EC2 y RDS original quedaron `stopped` a las 19:23 Lima. La RDS se reiniciará automáticamente alrededor del 17 de octubre a las 19:23 Lima si no se interviene. Continúan los cargos persistentes por EBS, almacenamiento/backups RDS, snapshots, S3, secreto, grupos de logs y alarma.

El costo de la copia temporal corresponde aproximadamente a 21 minutos de `db.t3.micro` más almacenamiento proporcional, dentro de la estimación operativa de USD 0.02–0.03 por hora. No se presenta como cargo facturado porque el panel de consumo no se consultó.
