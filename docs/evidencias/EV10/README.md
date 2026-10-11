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

## Actualización verificada el 7 de octubre de 2026

Se desplegó el commit `7955e7e` mediante Ansible/SSM. Se observó `HTTP 301 → HTTPS`, `/ = 200`, `/healthz = 200`, 27 eventos públicos y cero eventos con modalidad de asientos. Una ejecución nueva y sin reutilizar sesiones confirmó: registro `201`, reserva `201`, una entrada privada, acceso del operador `200`, primera validación `200`, segundo ingreso `409`, estado usado, logout `204` y acceso posterior `401`. El QR no se imprimió y las cookies permanecieron en memoria.

- [Escritorio](EV10-sitio-actualizado-2026-10-07-desktop.png), 1440 × 1200.
- [Móvil](EV10-sitio-actualizado-2026-10-07-mobile.png), 390 × 844.

Las capturas muestran únicamente la portada pública. No demuestran por sí solas el candado/certificado ni el flujo privado; esos resultados proceden de las comprobaciones HTTPS registradas. El 9-oct la usuaria informó que apagó AWS por falta de tokens; no se revalidaron los estados finales por API.
