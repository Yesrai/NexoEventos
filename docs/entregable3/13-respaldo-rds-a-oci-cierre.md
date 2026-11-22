# Entregable 3 · Respaldo PostgreSQL de RDS en OCI — cierre (11-nov-2026)

> ## ⚠ ADVERTENCIA VIGENTE — reinicio automático de RDS
> RDS `nexoeventos-academy-postgres` está **detenida** desde **2026-11-11 16:52:03 UTC**; AWS la **reiniciará sola hacia el 2026-11-18 ~16:52 UTC** (≈ 0,04 USD/h si queda encendida). Recordatorio: `recordatorio-rds-20261116.md` (16-nov). Cualquier nueva ventana que la encienda fija una fecha nueva (parada + 7 días).

## Estado: validación local del respaldo AWS–OCI COMPLETADA
El respaldo PostgreSQL cifrado de RDS del **11-nov-2026 16:46 UTC** está **almacenado en OCI** (bucket `nexoeventos-recovery`, São Paulo, privado, versionado) y **fue restaurado en un PostgreSQL 18 desechable en Docker local, NO en una VM de OCI**.

| Paso | Estado | Evidencia |
|---|---|---|
| Respaldo `pg_dump -Fc` (pg_dump 18.6) cifrado con CMS; SHA-256 EC2 = local; formato PGDMP; huella antes = después | ✔ | `aws-ventana-respaldo-rds-20261111.txt`, `respaldo-rds-20261111.json` |
| Re-cifrado con el certificado independiente de OCI, manifiesto, subida sin sobrescritura, descarga desde OCI y SHA-256 | ✔ | `oci-subida-respaldo-rds-20261111.txt` |
| Restauración aislada en Docker local con la clave de AWS (9 s, huella 10/10) | ✔ | `restauracion-aislada-local-rds-20261111.txt` |
| **Restauración aislada en Docker local desde el objeto de OCI con la clave privada de OCI** (ejecutada **por la usuaria**: SHA-256 del cifrado OK, descifrado OK, hash del volcado OK, catálogo 119 líneas, restauración OK, huella idéntica 10/10, **8 s**, código 0) | ✔ (declarado por la usuaria; salida completa no incorporada al repositorio) | resultado comunicado por la usuaria el 11-nov |

**Objetos en OCI** (`backups/`): `nexoeventos-rds-20261111T164610Z.oci.cms` (92.908 bytes, SHA-256 `5ef0532830ed45d9…`) y `nexoeventos-rds-20261111T164610Z.manifest.json` (612 bytes, SHA-256 `cb46035a685fe495…`); hash del volcado en claro `8ea75d66987266bd…`. Los objetos del 23-oct permanecen intactos.
**Datos al momento del volcado:** Alembic 0008, 26 usuarios, 35 eventos, 136 reservas, 136 entradas.

## Qué demuestra y qué no
- **Demuestra:** existe una copia fuera de AWS, cifrada con una clave independiente, íntegra (SHA-256 en cada salto), descifrable con la clave privada de OCI y **restaurable** en PostgreSQL 18 con datos idénticos a los del origen. Restauración medida: 8–9 s en Docker local (no es el RTO de producción).
- **No demuestra:** restauración en una **VM de OCI** con este respaldo (solo la del 23-oct, con el respaldo anterior); la aplicación funcionando sobre la base restaurada; recuperación de entradas QR ya emitidas.

## Limitaciones registradas
1. **Respaldo puntual**, no continuo: RPO = momento del volcado (11-nov 16:46 UTC). Los cambios posteriores no están protegidos por este respaldo; los respaldos frecuentes requieren la aplicación y la BD encendidas (fase pendiente).
2. **Claves de aplicación custodiadas por separado:** `TICKET_ENCRYPTION_KEY` y `SECURITY_HASH_KEY` **no están en el volcado**; sin ellas no se validan las entradas QR ya emitidas. Su custodia debe mantenerse fuera del repositorio, de AWS y del bucket.
3. **Clave privada de OCI** con frase de paso en poder exclusivo de la usuaria; sin ella el respaldo de OCI no se descifra (no hay custodia alternativa documentada).
4. **Reinicio automático de RDS** previsto ≈ 18-nov 16:52 UTC (ver advertencia superior).
5. Las 5 instantáneas manuales de RDS (incluida `nexoeventos-pre-parada-20261111`) existen **solo en la cuenta de Academy** y se perderán con ella.
6. Costo de OCI estimado ≈ USD 0 (no verificado en el panel de OCI).
