# Copia externa del respaldo: instrucciones (preparadas, NO ejecutadas)

22-nov-2026. Sin secretos. Archivos a copiar (en `work/respaldo-cifrado/`): `nexoeventos-reconstruccion-20261122T022238Z.tar.cms` (399.524.048 bytes) y `….tar.cms.sha256`. SHA-256 esperado: `5b201c801dc5101b18416d022a63661628f125cef986b91ed5581ac3b0dbcdfb`. El paquete va cifrado y **no** contiene la clave. Clave protegida: `work/recovery-keys/preupdate-20261008t0113z/recovery-private.protegida.pem` (0600, cifrada con frase de paso). Original sin proteger: intacta, no se borra.

## 1. Qué necesitamos
| Elemento | Para qué |
|---|---|
| **SSD/USB externo A** (≥ 1 GB) | Destino 1: el paquete (+ hash). Cifrado con APFS (cifrado) |
| **Nube personal** (iCloud Drive o Google Drive propio; no AWS/OCI/Azure) | Destino 2: el paquete (+ hash), carpeta privada sin compartir |
| **USB pequeño B**, distinto de A | Copia de la **clave protegida**, guardado en otro lugar físico |
| **Gestor de contraseñas** | La frase de paso y una copia de la clave protegida |
Regla: ningún sitio contiene a la vez paquete + clave + frase.

## 2. Procedimiento más sencillo y seguro
**Destino 1 (SSD cifrado)**
1. Conectar el SSD. Si no está cifrado: Utilidad de Discos → Borrar → formato **APFS (cifrado)** y contraseña propia (esto borra el SSD; usar uno vacío).
2. `cp work/respaldo-cifrado/nexoeventos-reconstruccion-20261122T022238Z.tar.cms* /Volumes/<SSD>/NexoEventos/` (copia el archivo y el hash; no mueve ni borra el original).
3. `cd /Volumes/<SSD>/NexoEventos && shasum -a 256 -c nexoeventos-reconstruccion-20261122T022238Z.tar.cms.sha256` → debe decir `OK`.
4. Expulsar el SSD y guardarlo **fuera del lugar donde está el Mac**.

**Destino 2 (nube personal)**
1. Crear una carpeta privada (sin enlaces compartidos) y subir **solo** el `.tar.cms` y su `.sha256` (arrastrando los archivos).
2. Descargarlos a una carpeta nueva (p. ej. `~/Descargas/prueba-nexo/`) y comprobar `shasum -a 256 -c` allí. La subida solo cuenta si la copia descargada coincide.
3. La nube ve un archivo cifrado; no subir la clave ni la frase.

## 3. Clave protegida y frase
- **Clave protegida:** copia en el USB B (guardado en un lugar distinto del SSD) y adjunta en el gestor de contraseñas (como archivo/nota cifrada). Nunca en la misma nube que el paquete.
- **Frase de paso:** solo en el gestor de contraseñas; opcionalmente en papel, en un sitio seguro separado del USB B. No en chat, correo, notas del Mac ni capturas. Si se pierde la frase, la clave protegida no sirve: conservar también la clave original **hasta** completar la prueba de §4 y decidir con calma si se retira.
- Revisar la custodia 1 vez al año (que el SSD abra, que la frase funcione).

## 4. Prueba de restauración desde la copia externa (en otra carpeta; no toca la copia)
Con el SSD conectado (o la copia descargada de la nube) y el USB B o la clave protegida local:
```bash
scripts/ops/probar-restauracion-externa.sh --dir /Volumes/<SSD>/NexoEventos --key <ruta-de-la-clave-protegida.pem>
```
Pide la frase en el terminal (sin eco). Comprueba: SHA-256 de la copia, descifrado, integridad de las partes, `git bundle`, clonado (commits y HEAD) y archivos contra el manifiesto; todo en un temporal 0700 que se borra al salir. Repetir con la copia descargada de la nube. Solo si ambas dan **PRUEBA COMPLETA** el respaldo puede llamarse recuperable ante la pérdida del Mac.

## 5. Si cambia el proyecto
Cualquier cambio posterior exige un paquete nuevo (`respaldo-reconstruccion.sh create`) y repetir §2 y §4; los paquetes viejos de los destinos se borran solo cuando la propietaria lo decida.
