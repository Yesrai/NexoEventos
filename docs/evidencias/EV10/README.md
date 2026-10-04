# EV10 — HTTPS y flujo público

El 3 de octubre de 2026 `https://nexoeventos-demo.duckdns.org` respondió con HTTPS válido. Una suite ejecutada contra la URL pública confirmó:

- registro público limitado a cliente y cookie de sesión `Secure`/`HttpOnly`;
- reserva con una entrada y repetición idempotente sin nuevo descuento;
- consulta del QR por su propietario;
- rechazo de operador para evento no asignado y de QR inexistente;
- dos validaciones simultáneas con exactamente un `200` y un `409`;
- segundo uso rechazado;
- cierre de sesión seguido por `401`;
- persistencia después de reiniciar FastAPI;
- ausencia del token QR completo en el log de API.

La cámara no se comprobó en un dispositivo físico; el flujo por código sí fue probado. La web queda fuera de servicio mientras EC2/RDS estén detenidos para ahorrar crédito.
