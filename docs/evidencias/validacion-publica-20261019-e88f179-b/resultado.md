# Validación pública controlada · e88f179 · 19-oct-2026 (segunda ejecución: TODO OK, 37/37)

Eventos ficticios ocultos 90101 (asignado) y 90102 (sin asignar); cuentas `ensayo-*`. La UI corrió antes de activar la fila virtual.

- UI real (Chrome, escritorio y móvil): enlace directo (evento fuera del catálogo, parámetro retirado) → recinto 3D → clic en butaca → registro con sesión iniciada → reserva y confirmación → Mis entradas con QR → QR a tamaño completo; sin excepciones de página.
- API: registro/sesiones (40/40, 2 workers), reserva idempotente, Mis entradas con QR, validación de la operadora (200 y 409 en repetición), 403 en evento no asignado y para clientes, fila virtual (2 admitidas, 3 en espera; sin turno 403), disputa del mismo asiento (1 ganador).
- Limpieza: eventos, zonas, asientos, reservas, entradas, fila y cuentas de ensayo eliminados por id/prefijo; huella previa y posterior idénticas. Estado final: Alembic 0008, 135 reservas (mismo hash), 135 entradas, 25 usuarios, 9 accesos, inventario de los 31 eventos originales con el mismo hash, eventos 1028-1031 sin reservas.

Se conservan solo las capturas de selección 3D; las de QR no se guardan.
