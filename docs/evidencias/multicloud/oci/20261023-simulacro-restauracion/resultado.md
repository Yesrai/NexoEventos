# Simulacro de recuperación en OCI (PostgreSQL 18.6, Alembic 0008) — 2026-10-23 (UTC)

Estado: **ejecutado y verificado**. Restauración del respaldo cifrado en una VM temporal de OCI, base aislada `drill`; sin tocar la producción de AWS.

## Cadena
Respaldo lógico de AWS (CMS) → recifrado con el certificado público de recuperación de OCI → objeto en `nexoeventos-recovery` (carga con el perfil de privilegio mínimo) → descarga con ese perfil, verificación SHA-256/tamaño contra el manifiesto → descifrado **en la Mac de la propietaria** (frase de paso introducida de forma interactiva; la clave privada nunca salió de la Mac) → volcado por túnel SSH (OCI Bastion) a un archivo en tmpfs de la VM → SHA-256 del volcado en claro = manifiesto → `pg_restore` solo en `drill` → huella.

## Resultado
Huella idéntica a la línea base `0008-estado-20261022` en 10 comprobaciones: alembic 0008, users 25, events 35, reservations 135, tickets 135, operator_assignments 2, access_logs 9, reserved_total 135, inventory_md5 `a42d7ed0…`, reservations_md5 `cbe0c1c2…`. PostgreSQL 18.6 (PGDG, RPM verificados por firma). Salida completa en `huella-restaurada.txt`.

## Tiempos (UTC) — no confundir
- **Fase de restauración (medida por el script):** 24 s (`tiempos-intento-exitoso.txt`): descarga 2 s, verificación 1 s, copia de RPM/scripts 13 s, comprobación remota 2 s, **descifrado local + transmisión + restauración + huella: 3 s a partir de la comprobación remota (incluye la introducción de la frase de paso)**.
- **Tiempo integral medido de este ejercicio:** del inicio del `apply` de la VM (15:59:43) a la huella verificada (18:14:47): **2 h 15 min**. No es un RTO: incluye ≈ 1 h 30 min de diagnóstico del acceso, un reinicio suave, una corrección de red y el desvío de la instalación de PostgreSQL con 498 MB de RAM.
- Componentes medidos: `apply` de VM y Bastion 79 s; instalación de PostgreSQL entre 8 y 18 min (sondeo, hora exacta de fin no registrada); sesión de Bastion y túnel ~20 s; restauración 24 s.
- RTO reproducible de un procedimiento ya corregido: **no medido de principio a fin**. Estimación (no medición): 15–25 min dominados por la instalación de PostgreSQL en la VM de 1 GB.

## Intentos y fallos documentados
1. Diagnóstico de acceso (15:59–17:31): SSH vía Bastion fallaba (`banner exchange timeout`); causa: la lista de seguridad predeterminada, vaciada, bloqueaba la salida del endpoint del Bastion. Corregido con una regla de salida TCP/22 hacia la propia subred (ver `../20261023-vm-recuperacion/`).
2. Simulacro, intento 1 (18:10:24): falló tras instalar PostgreSQL con `cd: /var/lib/pgsql: Permission denied` (el `cd` lo ejecutaba `opc` antes del `sudo`) y luego `Error decrypting CMS structure` (consecuencia probable del cierre de la tubería; no confirmado). Sin datos restaurados ni residuos en claro (`tiempos-intento-fallido.txt`).
3. Corrección: `cd` dentro del `sudo -u postgres`, comprobación remota previa a pedir la frase de paso y códigos de salida separados para fallos de OpenSSL y de restauración.
4. Intento 2 (18:14:23): correcto.

## Higiene
- VM: sin volcados ni temporales en claro (búsqueda en /dev/shm, /tmp, /var/tmp, /home, /root, /var/lib/pgsql), sin frase de paso en el historial, sin puerto 5432 por TCP. La base `drill` conserva 14 tablas restauradas (datos de producción) en el volumen de arranque hasta destruir la VM (`preserve_boot_volume=false`).
- Estación local: solo el CMS cifrado, el manifiesto y los registros; `openssl.err` vacío.
- Estas evidencias contienen únicamente conteos y hashes; sin datos personales, claves ni OCID.

## Pendiente
Destruir VM y Bastion (plan revisado, no ejecutado); costo estimado USD 0 (Always Free) mientras la VM exista; no verificado en el panel de OCI.
