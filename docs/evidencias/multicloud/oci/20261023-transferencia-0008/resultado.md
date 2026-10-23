# Transferencia AWS → OCI del respaldo Alembic 0008 — 2026-10-23 (UTC)

Estado: **subido y verificado por API**. Restauración en OCI aún no probada. Sin AWS encendido, sin VM, sin Terraform apply/destroy.

- Cadena: CMS de AWS (SHA-256 verificado contra la evidencia) → descifrado y recifrado en tubería con el certificado público de recuperación de OCI (RSA 3072, huella SHA-256 `98:1C:97:B5:…:E6:AC`; clave privada con frase de paso, custodiada por la operadora; correspondencia certificado↔clave confirmada por ella) → carga con el perfil independiente `NEXOEVENTOS_UPLOADER` (sin credenciales de administrador).
- Objetos creados en `nexoeventos-recovery` (sa-saopaulo-1, privado, versionado):
  - `backups/nexoeventos-alembic0008-20261023T150946Z.oci.cms` — 92.060 bytes — SHA-256 `ae87bb8708b75b683c4f70783cb1fc38b77cdfca2f16e663ab9943ac0171e2e9`
  - `backups/nexoeventos-alembic0008-20261023T150946Z.manifest.json` — 628 bytes — SHA-256 `8c737fae17d278c1912f6913236a4a99fe3de96dbda8db4df2c028d45ee77e47`
- Verificación: ambos objetos se descargaron en streaming desde OCI y su SHA-256 y tamaño coinciden con los locales. SHA-256 del volcado en claro (para la restauración): `67b6876f2c4381b12039e8408b7efad6866f0c11ca93a2d41e68fd6f0665669a`.
- Bucket: `NoPublicAccess`, versionado `Enabled`. Un intento de sobrescritura con el usuario técnico fue denegado (no tiene OBJECT_OVERWRITE/DELETE).
- Incidencia menor: el primer intento usó un flag inexistente (`--if-none-match`) y no subió nada; se repitió sin él.
- Costo: ~92 KB en Object Storage Standard; estimado USD 0 (dentro del almacenamiento gratuito; no verificado en el panel de OCI).
