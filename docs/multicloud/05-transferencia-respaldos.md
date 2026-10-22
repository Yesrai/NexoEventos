# 5. Transferencia cifrada de respaldos AWS → estación local → OCI

Objetivo: tener en OCI una copia del respaldo lógico **cifrada con una clave independiente de la de AWS**, con SHA-256 verificado en cada salto y restauración comprobable. Estado: scripts y pruebas locales **PROBADOS con claves desechables**; ejecución real **PENDIENTE** (sin cuenta OCI, sin credenciales y sin generar la clave real).

## Claves (decisión de custodia)
- AWS (ya existe): par de recuperación usado para los CMS en S3; privada solo en la estación de la usuaria.
- **OCI (nuevo, independiente):** `scripts/multicloud/oci-recovery-keygen.sh` la genera **fuera del repositorio** (`~/.nexoeventos/recovery-oci/`, RSA 3072 con frase de paso); el script rechaza cualquier ruta dentro del repo. La clave privada y su frase se guardan fuera de línea; en OCI solo viaja el certificado público para cifrar y la copia cifrada. Comprometer una clave no compromete la otra.

## Procedimiento (cada paso con su autorización)
1. **Respaldo fresco en AWS** con el procedimiento existente (volcado + CMS con la clave de AWS + recibo con SHA-256). Requiere el laboratorio activo (etapa 0).
2. **Descargar** el CMS y su hash de S3 a `work/` en la estación y comprobar el SHA-256 contra el recibo.
3. **Preparar la copia para OCI:** `scripts/multicloud/prepare-oci-transfer.sh <cms> <clave-aws.pem> <certificado-oci.crt> work/transferencias/AAAAMMDD <sha256-esperado>` — descifra y re-cifra en una tubería (el texto plano nunca toca el disco), y escribe `*.manifest.json` con SHA-256 del origen, de la copia OCI y del volcado en claro.
4. **Subir** a OCI (HTTPS, usuario API con política de solo crear/leer objetos de ese bucket): `oci os object put --bucket-name nexoeventos-recovery --file <x.oci.cms> --name backups/<x.oci.cms> --if-none-match "*" --metadata '{"sha256":"<hash>"}'` (no sobrescribe).
5. **Verificar en destino:** `oci os object get` a un archivo temporal y `scripts/multicloud/verify-transfer.sh <manifiesto> <archivo>`; guardar la comparación como evidencia (`docs/evidencias/multicloud/oci/AAAAMMDD-transferencia/`).
6. **Limpieza:** borrar de `work/` los archivos temporales según se vayan verificando; no se guarda ninguna clave ni credencial en Git, logs ni capturas.

## Protecciones comprobadas en la prueba local (`scripts/multicloud/test-restore-pipeline.sh`)
Archivo alterado (hash y simulacro fallan), clave equivocada, línea base distinta, SHA-256 de origen distinto, claves o salidas dentro del repositorio rechazadas, y claves de AWS y OCI distintas.
