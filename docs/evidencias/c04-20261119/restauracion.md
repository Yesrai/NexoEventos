# C-04 · Restauración aislada en Mac del respaldo `nexoeventos-rds-20261119T055432Z` (19-nov-2026, evidencia saneada)

**Tiempo observado de recuperación aislada en Mac. NO es el RTO del failover AWS–OCI** (no incluye VM/BD en OCI, aplicación, DNS ni conmutación).

- Entorno: PostgreSQL 18.7 desechable (Homebrew, sin Docker), socket Unix privado en directorio 0700 y puerto aleatorio; `pg_restore` 18.7. Nada escrito en AWS/OCI; lectura con el perfil independiente.
- Clave/cert: el CMS está dirigido a `CN=NexoEventos backup recovery` (serie `5AF7…5808`), NO al certificado de OCI. Se verificó que el certificado es el destinatario del CMS y que la clave privada corresponde a su clave pública. La clave no tiene frase, está en `work/` (ignorada por Git, nunca versionada, 0600); no se copió, imprimió ni modificó.
- Verificación previa al descifrado: firma del manifiesto válida (clave pública fijada), tamaño y SHA-256 del cifrado = manifiesto. Descifrado correcto, cabecera PGDMP, tamaño y SHA-256 del volcado = manifiesto.
- `pg_restore`: correcto (14 tablas en `public`).
- Huella = manifiesto (10 claves): alembic 0008, users 26, events 35, reservations 136, tickets 136, operator_assignments 2, access_logs 9, reserved_total 136, inventory_md5 y reservations_md5 idénticos.

| Etapa | Segundos |
|---|---|
| Descarga (3 objetos, OCI sa-saopaulo-1) | 4,6 |
| Verificación (firma, tamaño, SHA-256, correspondencia clave–cert) | 0,20 |
| Descifrado | 0,04 |
| Restauración (initdb+arranque aparte; `pg_restore`) | 0,34 |
| Comprobación final | 0,11 |
| **Total del procedimiento** | **6,7** |

Limitaciones: el volcado en claro existió brevemente en un directorio 0700 de `/tmp` (sobrescrito y borrado al salir) para poder medir descifrado y restauración por separado; tamaño 92 KB; red doméstica; un solo respaldo.
Defectos corregidos en `c04-restore-local.sh`: `read` recortaba espacios de la frase (`IFS=`); `exec 4<&- 2>/dev/null` dejaba stderr mudo; PostgreSQL 18 en macOS exige `LC_ALL` válido para arrancar.
