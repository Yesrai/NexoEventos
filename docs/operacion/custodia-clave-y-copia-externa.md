# Custodia de la clave de recuperación y copia externa del respaldo (propuesta; NADA ejecutado)

22-nov-2026. No se ha movido, modificado ni sustituido ninguna clave, ni subido ningún respaldo. Sin secretos en este documento.

## 1. Situación
La clave privada de recuperación es un PKCS#8 **sin cifrar** (comprobado por su cabecera, sin leer el contenido) y está en el mismo Mac que el paquete: quien tenga el Mac puede abrir el respaldo; si el Mac se pierde, el respaldo es irrecuperable.

## 2. Proteger la clave con frase de paso (procedimiento; lo ejecuta la propietaria, en su terminal)
Probado solo con una clave **desechable** (OpenSSL 4.1 de Homebrew; la clave pública derivada coincide antes y después), no con la real.
1. Elegir una frase larga (≥ 6 palabras al azar) y guardarla **solo** en un gestor de contraseñas. No escribirla en chat, historial ni scripts.
2. Crear una copia **nueva**, sin tocar la original (OpenSSL pide la frase en el terminal, sin eco):
```bash
openssl pkcs8 -topk8 -v2 aes-256-cbc -v2prf hmacWithSHA256 -iter 600000 -in work/recovery-keys/<corrida>/recovery-private.pem -out work/recovery-keys/<corrida>/recovery-private.protegida.pem
```
3. Comprobar que la copia nueva abre el paquete **antes de nada más** (pedirá la frase): `openssl cms -decrypt -binary -inform DER -in <paquete>.tar.cms -inkey work/recovery-keys/<corrida>/recovery-private.protegida.pem -out /dev/null`. Para scripts, `scripts/multicloud/lib-cms-key.sh` acepta `--passin env:NOMBRE|file:RUTA|fd:N`; `respaldo-reconstruccion.sh verify` no tiene `--passin`, así que pedirá la frase de forma interactiva.
4. Solo tras el paso 3 y con una copia externa ya hecha, la propietaria decide retirar la clave sin protección (borrado seguro del original). Hasta entonces, **no se sustituye**.
5. Ojo: la frase y la clave van en sitios distintos. Perder la frase equivale a perder la clave.

## 3. Dos destinos independientes para el `.tar.cms` (ya cifrado: es seguro de mover)
| | Destino 1 | Destino 2 |
|---|---|---|
| Qué | **SSD/USB externo** cifrado (APFS cifrado o FileVault), guardado **fuera del domicilio/lugar de trabajo del Mac** | **Nube personal ajena a AWS, OCI y Azure** (p. ej. iCloud Drive o Google Drive de la propietaria, en carpeta privada sin compartir) |
| Independencia | Offline; no depende de ningún proveedor | Otro proveedor y otra cuenta; no depende del Mac |
| Contenido | `.tar.cms` + `.tar.cms.sha256` + `.inventario.md` | Igual |
| Por qué es seguro | El paquete va cifrado (CMS, AES-256) y no contiene la clave privada | Igual; el proveedor solo ve un blob cifrado |
| Verificación | `shasum -a 256 -c` en el destino y una restauración de prueba en otra carpeta | Igual, descargando de nuevo |
Nota: la copia en OCI/S3 **no** sirve como destino independiente (AWS Academy caduca y OCI/Azure son parte del proyecto).

## 4. Dónde guardar la clave privada (nunca junto al paquete)
- La **clave protegida** (§2): una copia en el gestor de contraseñas de la propietaria (como nota/adjunto cifrado) y otra en un USB distinto del Destino 1, guardado en un lugar físico diferente.
- La **frase**: solo en el gestor de contraseñas (+ papel en lugar seguro si la propietaria lo decide).
- Regla: ningún lugar contiene a la vez paquete + clave + frase.
- Aparte, y por separado: claves de OCI (`~/.oci`), claves SSH y capturas originales (no están en el paquete).

## 5. Orden recomendado (cada paso requiere decisión de la propietaria)
1. Generar un paquete **nuevo** con `scripts/ops/respaldo-reconstruccion.sh create` (el actual es anterior a 7 archivos) y verificarlo. 2. Proteger la clave (§2, pasos 1–3). 3. Copiar el paquete a los dos destinos y comprobar su SHA-256. 4. Guardar la clave protegida y la frase (§4). 5. Restaurar **desde la copia externa** una vez, en otra carpeta. Solo entonces el respaldo puede llamarse «recuperable ante la pérdida del Mac».

## 6. Checklist final de custodia (22-nov-2026; la ejecuta la propietaria; sin secretos aquí)
Estado verificado: el paquete `…T044516Z.tar.cms` existe en Mac, Google Drive y OneDrive con SHA-256 idéntico (ver `docs/evidencias/20261122-copia-externa-respaldo/resultado.md` §6). La clave protegida existe en `work/recovery-keys/preupdate-20261008t0113z/`. **Falta** que la clave y la frase vivan fuera del Mac.

| # | Qué custodiar | Dónde está hoy | Destino A (gestor de contraseñas) | Destino B (USB cifrado, lugar físico distinto) |
|---|---|---|---|---|
| 1 | Clave privada protegida `recovery-private.protegida.pem` | `work/recovery-keys/preupdate-…/` | Adjunto cifrado | Copia |
| 2 | Frase de descifrado | Solo la propietaria | Entrada propia (no en la misma que la clave) | Papel opcional, en otro sitio |
| 3 | Certificado `recovery-public.crt` (no es secreto) | idem | Opcional | Copia |
| 4 | Claves OCI: `~/.oci/config` y los 2 pares `nexoeventos_*_api_key*.pem` | `~/.oci/` (fuera del paquete) | Adjuntos cifrados | Copia |
| 5 | SSH: `~/.ssh/nexoeventos_recovery`, `nexoeventos_azure` (+ `.pub`) | `~/.ssh/` | Adjuntos cifrados | Copia |
| 6 | `terraform.tfvars` y estado de Terraform | Dentro del paquete (13 `.tfstate`; sensible) | Ya cubiertos por el paquete cifrado | — |
No custodiar con el proyecto: `~/.ssh/s14-yesenia-*.pem`, `id_rsa`, `id_ed25519` (otros proyectos/uso personal; fuera del alcance de NexoEventos).

### Comprobación de recuperación desde un dispositivo externo (prueba real, ~5 min)
1. En otro equipo (o el Mac con una sesión limpia), obtener del gestor la clave protegida y, del USB, el `.tar.cms` descargado de Drive/OneDrive.
2. Calcular `shasum -a 256 <archivo>.tar.cms` y comparar con `45b9facc…e66`.
3. Descifrar a `/dev/null` (pide la frase en el terminal; no escribirla en comandos):
```bash
openssl cms -decrypt -binary -inform DER -in nexoeventos-reconstruccion-20261122T044516Z.tar.cms -inkey recovery-private.protegida.pem -out /dev/null
```
4. Si termina sin error, la custodia queda **demostrada**. Para la prueba completa: `scripts/ops/probar-restauracion-externa.sh --dir <carpeta> --key <clave> --expect-head a711929` (requiere versionar `--expect-head`; ver decisión de Git).
5. Solo después de 4, la propietaria decide retirar la clave original sin frase (`recovery-private.pem`). No se borra sin su autorización.
Reglas: no subir nada de esta lista a GitHub; ningún lugar guarda a la vez paquete + clave + frase.
