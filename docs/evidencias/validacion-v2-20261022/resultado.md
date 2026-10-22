# Prueba funcional breve de AWS V2 (ALB + 2 instancias en 2 zonas) · 22-oct-2026

Contra el ALB con el dominio autorizado resuelto a la IP del ALB (una conexión nueva por solicitud) y datos ficticios ocultos (eventos 90101/90102, cuentas `ensayo-*`); la preparación y la limpieza usaron la identidad migradora de la EC2 de V1 (encendida temporalmente); no se copiaron credenciales privilegiadas a V2. Release `d3e52e8`. **15/15 comprobaciones OK**: registro y login de cliente y operadora; sesión válida en 40 lecturas repartidas entre las dos instancias; reserva de 2 asientos (201) con repetición idempotente (200); Mis entradas con QR; validación por operadora (200 y 409 en la repetición; 403 en evento no asignado y para un cliente); fila virtual (2 admitidas y 3 en espera, sin turno 403); disputa del mismo asiento (1 ganador).

Reparto entre instancias (log de Nginx de cada una, misma ventana): ver `reparto-instancias.json` — 39 y 37 solicitudes /api (51 % / 49 %), 20 lecturas de sesión en cada una, 0 errores 5xx.

Limpieza: eventos y cuentas de ensayo eliminados; huella previa y posterior idénticas. Estado final: Alembic 0008, 135 reservas (mismo hash), 135 entradas, 25 usuarios, 9 accesos, inventario original con el mismo hash. V1 detenida.
