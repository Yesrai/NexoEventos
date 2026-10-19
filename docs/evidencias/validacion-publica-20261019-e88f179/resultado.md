# Validación pública controlada · e88f179 · 19-oct-2026 (resultado: PARCIAL, limpieza completa)

API (13/13 OK): evento oculto fuera del catálogo y accesible por id; registro y sesiones (40/40 con 2 workers); reserva idempotente; Mis entradas con QR; validación de la operadora (200 y 409 en la repetición); 403 en evento no asignado (90102) y para un cliente; fila virtual (2 admitidas, 3 en espera); disputa del mismo asiento (1 ganador). UI hasta el retorno con la selección en escritorio y móvil (enlace directo, 3D, clic en butaca): OK.

**Fallo de la prueba (no del producto):** los pasos UI «confirmación → Mis entradas → QR» fallaron porque el script activó la fila virtual en el evento ANTES de la UI; con fila activa un invitado ve el botón deshabilitado «Compra no disponible todavía» (en `EventPage` la condición `gateBlocked` precede a «Inicia sesión para comprar») y el recorrido nunca inició sesión. Además el script daba por buena la UI sin comprobar la sesión ni el código de salida (corregido: ahora comprueba «Mis entradas» tras el registro, sale con error si algo falla y la UI corre antes de activar la fila).

Limpieza: completa. Huella previa y posterior idénticas (reservas, entradas, usuarios, inventario, asientos, accesos, fila, Alembic 0008); no quedan eventos 90101/90102 ni cuentas `ensayo-*`.

Observación de producto: con fila virtual activa un invitado no puede usar el botón principal para iniciar sesión (debe usar «Ingresar» del encabezado).
