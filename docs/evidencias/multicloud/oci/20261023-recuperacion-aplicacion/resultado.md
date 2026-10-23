# Recuperación de la aplicación NexoEventos en OCI — 2026-10-23 (UTC)

Estado: **ejecutada y verificada** en una VM temporal (`VM.Standard.E5.Flex`, 1 OCPU / 8 GB, Oracle Linux 9.8, sin IP pública; créditos del Free Trial). PostgreSQL 18.6, FastAPI (Python 3.12, ruedas instaladas sin Internet), Nginx 1.20 con TLS (certificado y clave efímeros de la VM) y frontend React/Vite. Acceso solo por OCI Bastion (túnel HTTPS en `https://localhost:8443`). Sin cambios en AWS (EC2/RDS detenidas), Azure ni DNS.

## Resultados funcionales (14/14 correctas, `smoke.json`)
healthz (API+BD) 200 · frontend con cabeceras de seguridad (HSTS, CSP, nosniff…) · login de cliente · cookie con Secure+HttpOnly · sesión · catálogo (32 eventos publicados) · detalle de evento · reservas del cliente · **QR descifrado con la `TICKET_ENCRYPTION_KEY` original** · un cliente no puede validar (403) · login de operador · el operador ve el evento del ticket · **validación de un ticket ya usado → 409 «Entrada ya utilizada» (`already_used`), que verifica el token con la `SECURITY_HASH_KEY` original**.
Datos: huella 10/10 idéntica a la línea base tras la restauración; tras las pruebas solo cambia `access_logs` 9 → 10 (la fila de la validación). Sin ventas ni cambios en reservas, tickets ni inventario.

## Credenciales de prueba (solo en la copia)
Autorizado por la propietaria: se restablecieron únicamente los `password_hash` de `operador.demo@example.com` y `smoke-1791073267-26124@example.com` en la base desechable de OCI. Contraseñas aleatorias solo en memoria del script (no impresas, guardadas ni registradas), hashes Argon2 (pwdlib, igual que el backend). Evidencia: 2 filas actualizadas; las otras 23 cuentas intactas (hash de los hashes idéntico antes/después). Límite: el login prueba la aplicación y el flujo, no las contraseñas originales de producción.

## Tiempos (UTC; el T0 del orquestador no se reinició)
- Aprovisionamiento (`terraform apply`): 59 s (19:23:20–19:24:19); SSH por Bastion disponible 19:26:55 (primera vez) — 19:30 tras corregir un error propio de consulta del Bastion.
- **T_datos** (datos restaurados y huella verificada): 19:46:47 → 23 min 27 s desde el `apply`; 12 min 46 s desde el T0 del orquestador (19:34:01).
- **T_servicio** (aplicación sirviendo, healthz correcto): 19:48:13 → 24 min 53 s desde el `apply`; 14 min 12 s desde el T0 del orquestador.
- **T_funcional** (pruebas completas): 19:56:02 → **32 min 42 s desde el `apply`**; 22 min 1 s desde el T0 del orquestador.
- Estos tiempos incluyen los fallos (no se descontaron) y sus correcciones: ~11 min por el orden de instalación (usuario `postgres`), ~1–2 min por `http2 on` incompatible con Nginx 1.20, y ~8 min para decidir el manejo de credenciales de prueba. Ninguna fase fue repetida desde cero.

## Fallos encontrados y corregidos (sin repetir el despliegue)
1. Consulta de Bastion con dos Bastions (uno `DELETED`) → sesiones no creadas; corregido con filtro por `ACTIVE`. Túnel 443 rechazado una vez; reintento correcto. Entrada obsoleta de `known_hosts` por la VM nueva.
2. `install: invalid user 'postgres'`: las herramientas se instalaban antes de que el RPM creara el usuario → reordenado, con verificación y reanudación por etapas (`START_AT`, `OUT_DIR`).
3. `nginx: unknown directive "http2"` (Nginx 1.20): se usa `listen 443 ssl http2;`; TLS y cabeceras de seguridad conservados; `nginx -t` correcto.
4. `GET /` → 403 (frontend construido con umask 077): `chmod` de lectura; servidor Nginx por defecto en el puerto 80 retirado.
Correcciones guardadas en `scripts/multicloud/oci-drill/` para el próximo despliegue.

## Seguridad / higiene
PostgreSQL solo por socket Unix (sin 5432), API en 127.0.0.1:8000, Nginx solo 443; sin IP pública; SELinux en modo Enforcing sin denegaciones; las dos claves de aplicación solo en tmpfs (0600), 0 archivos persistentes con la clave asignada; 0 errores en el registro de la API. Pendiente: destruir la VM y el Bastion con un plan revisado (los datos de producción y las claves desaparecen con el volumen y el tmpfs).

## Costo
≈ 0,049 USD/h (precios de lista; no verificado con la facturación de OCI): VM ≈ 1 h acumulada hasta ahora ≈ 0,05 USD. Bastion y Service Gateway sin cargo.
