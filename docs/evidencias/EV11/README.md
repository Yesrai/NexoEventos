# EV11 — prueba de carga (E01)

**E01 cloud pendiente; no ejecutada.** Objetivo del caso: 20 usuarios virtuales durante 5 min, p95 < 2 s y errores inesperados < 1 %. Son metas, no resultados.

Smoke test local del 4 de octubre de 2026, **no equivalente a E01**: 5 usuarios durante 30 s, 5/5 registros completados, 76 solicitudes, p95 30.6 ms y 0 % de errores inesperados. Se ejecutó contra PostgreSQL de pruebas y sin reservas; sirvió para corregir/validar el script, no para demostrar rendimiento cloud.

Procedimiento: [docs/operacion/procedimientos-sesion-cloud.md § 3](../../operacion/procedimientos-sesion-cloud.md). Script: `scripts/cloud/load-test.py`.

Cuando se ejecute, adjuntar aquí:

- `resumen.md` generado y revisado (fecha/hora UTC, usuarios, mezcla, solicitudes/s, p50/p95/p99, errores por categoría y cumplimiento E01);
- captura CloudWatch de CPU EC2 (y RDS si se observa) durante la ventana de carga;
- commit de referencia y la aclaración de que la latencia se midió desde el cliente e incluye red y TLS.
