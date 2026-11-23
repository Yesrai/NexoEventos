# C-04 · Continuación técnica (PREPARADA, NO EJECUTADA): restauración aislada y medición de RTO

Estado de partida: tres respaldos reales verificados bajo `backups/c04-20261119/` (OCI), PAR revocado (0), EC2 V1 y RDS detenidas. No se ha creado infraestructura nueva.

## Qué mide y qué no
Mide el tiempo de **recuperar los datos de un respaldo cifrado** en una base aislada (descarga desde OCI + hash + descifrado + `pg_restore` + huella contra la línea base). NO es el RTO del failover AWS–OCI
(no incluye DNS, aplicación, RDS/OCI Database ni conmutación). Declararlo así.

## Piezas ya existentes
- Lectura: `failover/oci_source.py` (perfil de LECTURA, verifica manifiesto, firma y SHA-256).
- Simulacro: `scripts/multicloud/verify-transfer.sh` y `restore-drill.sh` (descifra en directorio 0700 temporal, `pg_restore` en base aislada `drill`, compara huella con `--baseline`).
- Respaldo candidato: `nexoeventos-rds-20261119T055432Z` (el más reciente) y, para repetir, `…T053032Z`.

## Bloqueos / decisiones antes de ejecutar (requieren tu autorización)
1. **Clave privada de recuperación** (descifrado): debe estar disponible solo en el equipo de restauración (frase de paso por `--passin env:`/`fd:`; nunca en argumentos). Confirmar dónde reside (S-01).
2. **Dónde restaurar**: (a) tu Mac con PostgreSQL 18 local o Docker (sin nube, coste 0, mide un RTO "de laboratorio"); (b) una VM temporal en OCI (infraestructura nueva: autorización y coste aparte).
3. **Línea base** (`--baseline` y `--baseline-key`): huella de la base en el instante del volcado; hay que identificar cuál corresponde a los manifiestos C-04 (el manifiesto C-04 guarda `fingerprint_before/after`). Si no, se compara contra la huella del manifiesto.
4. Credenciales de lectura OCI (`NEXOEVENTOS_UPLOADER`) ya existentes; ningún PAR nuevo.

## Procedimiento propuesto (opción a, sin nube)
1. Descargar con el lector OCI el CMS, el manifiesto y la firma del respaldo elegido (solo lectura) y cronometrar.
2. `verify-transfer.sh` (SHA-256 y tamaño) → `restore-drill.sh --mode docker|local` → huella idéntica.
3. Registrar t0 (inicio de la descarga) y t_fin (huella verificada) = RTO de datos medido; repetir 2–3 veces y reportar mínimo/máximo, no un promedio como garantía.
4. Evidencia saneada en `docs/evidencias/c04-20261119/restauracion.md`.
