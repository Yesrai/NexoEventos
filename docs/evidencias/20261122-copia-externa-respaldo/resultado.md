# Copia externa del respaldo de reconstrucción: verificación independiente (21/22-nov-2026)

Informe técnico sin secretos. Se descargaron las copias desde cada proveedor a carpetas distintas y se probó la restauración **solo con las copias descargadas**. Ni AWS, ni OCI, ni Azure, ni Terraform intervinieron.

## 1. Objeto
Archivo `nexoeventos-reconstruccion-20261122T022238Z.tar.cms` (CMS, AES-256-CBC, clave pública de recuperación): 399.524.048 bytes; SHA-256 `5b201c801dc5101b18416d022a63661628f125cef986b91ed5581ac3b0dbcdfb`; acompañado de su `.sha256` (118 bytes). Clave usada: la **copia protegida con frase de paso** (la frase se pidió en el terminal; no se vio ni se registró).

## 2. Resultados por proveedor (independientes)
| Comprobación | Google Drive (principal) | OneDrive UPeU (segunda) |
|---|---|---|
| Carpeta con exactamente 2 archivos | Sí | Sí |
| Tamaño del `.tar.cms` = 399.524.048 B | Sí | Sí |
| SHA-256 = valor esperado; `shasum -c` | Sí / OK | Sí / OK |
| Igual byte a byte al original local | Sí | Sí |
| Descifrado con la clave protegida | OK | OK |
| Partes del paquete íntegras (`PARTES.sha256`) | OK | OK |
| `git bundle verify` | OK | OK |
| Clonado: 136 commits, HEAD `ab61a4b` | OK | OK |
| Archivos sin publicar vs. manifiesto | OK | OK |
| Archivos de `work/` vs. manifiesto | OK | OK |
| **Veredicto** | **PASÓ** | **PASÓ** |
Las dos copias son idénticas entre sí y al original. Cada proveedor aprobó por separado.

## 3. Incidente de limpieza (no afecta al resultado)
- **Síntoma:** tras «PRUEBA COMPLETA», el `rm -r` del temporal quedó detenido en Drive (se terminó con SIGTERM) y se repitió en OneDrive.
- **Causa (verificada):** `git clone` deja los 3 packs de `.git/objects/pack` en modo 0444. En un terminal interactivo `rm -r` **pregunta** «override…?» por cada archivo de solo lectura; el script redirigía `stderr` a `/dev/null`, así que la pregunta era invisible y `rm` esperaba la respuesta en el terminal (estado `S+`, entrada = el terminal, salida de errores = `/dev/null`). No fue un fallo del disco ni de las copias.
- **Corrección:** `scripts/ops/probar-restauracion-externa.sh` hace `chmod -R u+w` antes de `rm -r </dev/null` y avisa si no puede borrar. Probado con un directorio desechable. Aún no se ha repetido la prueba real.
- **Limpieza ejecutada el 22-nov-2026 (autorizada por la propietaria, solo para estos dos temporales):**
  1. Se reverificaron procesos y rutas: el `rm -r` detenido de OneDrive (hijo del script de prueba) seguía activo; los dos temporales eran directorios reales de la prueba (contenían las partes del paquete y el clon), dentro de `$TMPDIR`, del usuario, con permisos 0700, **sin enlaces simbólicos** dentro ni en la ruta.
  2. Se envió SIGTERM únicamente a ese `rm` (tras comprobar que su línea de comandos coincidía); el proceso del script terminó y no quedó ningún proceso de prueba ni `rm` activo.
  3. Con rutas literales se aplicó `chmod -R u+w` y `rm -r` a esos dos directorios, y a nada más (un primer intento con variables fue bloqueado por la protección de Claude Code y no se ejecutó).
  4. Resultado real: **ambos directorios desaparecieron**; 0 temporales de prueba restantes.
  5. Intactos tras la limpieza: `~/Downloads/verif-drive` y `verif-onedrive` (2 archivos, 399.524.048 B, `shasum -c` OK), el respaldo local (`shasum -c` OK), las dos claves y el certificado en `work/recovery-keys/`, y el HEAD del repositorio (`ab61a4b`).

## 4. Lo demostrado y lo no demostrado
**Demostrado (con evidencia):** el respaldo existe en tres sitios independientes (Mac, Drive, OneDrive); se descifra con la clave protegida; contiene todo Git (136 commits), 922 archivos sin publicar y 228 de `work/`, íntegros según el manifiesto; el `.tar.cms` es la misma pieza en los tres. Además, de pruebas anteriores: restauración de datos PITR (R01, 10-oct), aplicación recuperada en OCI de forma manual (23-oct, 14/14 pruebas), V2 desplegada con 15/15 pruebas funcionales (6-nov), sustitución por autohealing y `/livez` sin caídas en el failover (parciales; ver matriz de caos).
**No demostrado:** que el sistema se reconstruya **en una cuenta AWS nueva** con este paquete; restauración de PostgreSQL y de la aplicación completa en AWS; reconstrucción de la AMI en una cuenta nueva; failover AWS→OCI; zona completa; FIS. El paquete prueba que **tenemos** lo necesario, no que el procedimiento completo funcione de extremo a extremo.

## 5. Pendientes priorizados
**P0 (hoy, local, sin coste)**
1. ~~Borrar los 2 temporales con el paquete descifrado~~ **Hecho el 22-nov** (ver §3).
2. Guardar la **clave protegida** (USB B + gestor) y la **frase** (gestor) según `custodia-clave-y-copia-externa.md`; hasta entonces, Drive/OneDrive solo valen con la clave original que está en el mismo Mac.
3. Decidir qué hacer con la clave original **sin** frase de paso (conservarla hasta completar 2; luego retirarla).
**P1 (versionado y respaldos)**
4. Publicar (commit/push, con autorización): 11 commits locales + ≈ 131 cambios sin versionar (V2/resume, scripts, guías, evidencias, `failover/*`). Hoy solo existen en el Mac y en el paquete.
5. Un paquete nuevo incluirá estos documentos (el actual es anterior a este informe, al script de prueba y a sus guías) y habría que subirlo de nuevo.
6. Respaldar fuera del paquete lo que no incluye: claves de OCI y SSH, capturas originales.
**P2 (pruebas que cuestan o requieren AWS; cada una con autorización y presupuesto)**
7. Restauración de PostgreSQL desde un `.cms` o instantánea en un destino aislado y verificación de datos/QR (`aws-v2-verificacion-restauracion.md`; una RDS temporal ≈ 0,018 USD/h).
8. Reconstrucción en cuenta/laboratorio nuevo: AMI dorada (≈ 45 min), secretos, certificado, buckets y tfvars nuevos (`aws-v2-reconstruccion.md`, `migracion-entre-cuentas.md`). Incluye reconciliar el estado de Terraform (`apply -refresh-only` o `destroy` dirigido), hoy solo probados con simulaciones (90 pruebas).
9. Repetir el failover de RDS con V2 con ventana mayor (hoy «no concluyente») y el autohealing con restauración corregida.
**P3 (diseño y mejora)**
10. Failover AWS→OCI con `automatic=false`, zona completa, FIS, entrega de correo de Azure, B3, lifecycle de S3 (copiar los `.cms` antes de aplicarlo).

## 6. Verificación de integridad del paquete actualizado (22-nov-2026)
Paquete: `nexoeventos-reconstruccion-20261122T044516Z.tar.cms` (reemplaza al de §2, que correspondía a HEAD `ab61a4b`; el actual corresponde a HEAD `a711929`, 147 commits). Restauración local completa del paquete actual ya demostrada en la sesión anterior (SHA-256, descifrado, bundle con 9 refs, 147 commits, manifiesto de 239 archivos). Esta sección **no repite el descifrado**: solo comprueba que las copias descargadas de los proveedores son idénticas.

Método (solo lectura, sin descifrar, sin acceso a cuentas Cloud): `stat`, `shasum -a 256`, `cmp` byte a byte contra el original local.

| Fecha | Origen | Carpeta en `~/Downloads` | Archivo | Tamaño (B) | SHA-256 | `cmp` vs. local | Veredicto |
|---|---|---|---|---|---|---|---|
| 22-nov-2026 | Mac (original) | `work/respaldo-cifrado/` | `…T044516Z.tar.cms` | 399426672 | `45b9faccdc2d3569f8a37942f0b594d2eb893c25a60898ff9f32d30da4d36e66` | — | Referencia |
| 22-nov-2026 | Google Drive | `Verify-Drive` | `…T044516Z.tar.cms` | 399426672 | `45b9faccdc2d3569f8a37942f0b594d2eb893c25a60898ff9f32d30da4d36e66` | Idéntico | **ÍNTEGRO** |
| 22-nov-2026 | OneDrive UPeU | `Verify-Ondrive` | `…T044516Z.tar.cms` | 399426672 | `45b9faccdc2d3569f8a37942f0b594d2eb893c25a60898ff9f32d30da4d36e66` | Idéntico | **ÍNTEGRO** |

Observaciones:
- Cada carpeta contiene exactamente 2 archivos (sin duplicados ni descargas parciales): el `.tar.cms` y `…T044516Z.paquete.sha256`. **No se descargó `…tar.cms.sha256`.** El `.paquete.sha256` (127 B, idéntico al local) contiene el hash del `paquete.tar` **en claro** (`383848e8…ee416`), por lo que no puede validarse sin descifrar; `shasum -c` sobre él falla únicamente porque `paquete.tar` no existe en la carpeta (comportamiento esperado, no un fallo de integridad). La integridad del cifrado queda probada por el SHA-256 del `.tar.cms` y el `cmp` con el original, y el hash coincide con el contenido del `.tar.cms.sha256` local.
- Los originales de Descargas no se modificaron, movieron ni borraron.

**Veredicto:** verificación de integridad de los respaldos externos actualizados **CERRADA** (Drive y OneDrive, cada uno de forma independiente). No se probó el descifrado desde cada origen; no es necesario, porque los bytes son idénticos a un paquete ya restaurado.
