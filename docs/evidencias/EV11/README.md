# EV11 — prueba de carga (E01)

**E01 cloud ejecutada y válida el 9 de octubre de 2026.** Se probaron 20 usuarios virtuales durante 300 segundos contra la versión AWS `7955e7e`, con un evento aislado `[CARGA]`. Resultado: 2 520 solicitudes, 8.4 solicitudes/s, p95 421.2 ms y 0 % de errores inesperados. Los objetivos p95 < 2 s y errores inesperados < 1 % se cumplieron en esta escala; no equivalen a una garantía de producción.

La prueba incluyó 132 reservas de un cupo. La comprobación posterior directa en PostgreSQL encontró 132 reservas, 132 claves de idempotencia distintas, `reserved_count=132`, suma de cantidades 132 y 132 entradas. No hubo sobreventa ni duplicados. No hubo `409`: en esta ejecución el evento de 1 000 cupos no se agotó, por lo que no se observaron conflictos de negocio esperados.

Evidencia revisada: [resultado cloud](resultado-2026-10-09.md). La latencia se midió desde el Mac e incluye red y TLS.

Smoke test local del 4 de octubre de 2026, **no equivalente a E01**: 5 usuarios durante 30 s, 5/5 registros completados, 76 solicitudes, p95 30.6 ms y 0 % de errores inesperados. Se ejecutó contra PostgreSQL de pruebas y sin reservas; sirvió para corregir/validar el script, no para demostrar rendimiento cloud.

Procedimiento: [docs/operacion/procedimientos-sesion-cloud.md § 3](../../operacion/procedimientos-sesion-cloud.md). Script: `scripts/cloud/load-test.py`.

Para una escala posterior, adjuntar además:

- captura CloudWatch de CPU EC2 (y RDS si se observa) durante la ventana de carga;
- commit de referencia y la aclaración de que la latencia se midió desde el cliente e incluye red y TLS.
