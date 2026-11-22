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
