# Claves de firma del lease (no son la clave C-04)

**Qué protegen y qué no.** La exclusión mutua entre las dos bases la dan el CAS del almacén y la espera `ttl+margen` (ver `backend/app/failover/lease.py`); NO dependen de las firmas.
Las firmas permiten solo (1) la liberación voluntaria inmediata (traspaso planificado) y (2) no dejar que registros ajenos muevan el techo de épocas. Sin firmas el sistema sigue siendo seguro, pero todo
traspaso espera `ttl+margen`.

**Esquema recomendado: Ed25519.** Cada nodo guarda solo SU clave privada y las claves PÚBLICAS de los demás.
No hace falta compartir secretos: un nodo comprometido no puede firmar como otro. HMAC existe como alternativa (cada nodo guarda todas las claves; peor aislamiento).

**Generación (solo cuando se autorice; hoy solo se ha probado con material ficticio):**
`NEXO_ALLOW_KEY_GENERATION=YES lease_keys.py generate --out-dir <carpeta FUERA del repositorio> --scheme ed25519 --confirm "GENERAR CLAVES DEL LEASE"` →
carpeta 0700, archivos 0600, aleatoriedad de `os.urandom`, nunca imprime claves, rechaza carpetas dentro de git o no vacías. `verify-pair` firma en un nodo y verifica en el otro.

**Distribución.** AWS recibe `aws/lease-signing.key` + `aws/lease-peers.json` (pública de OCI); OCI recibe `oci/…` análogo. Rutas por entorno:
`WRITE_GATE_LEASE_SIGNING_KEY_FILE`, `WRITE_GATE_LEASE_PEER_PUBKEYS_FILE`, `WRITE_GATE_LEASE_STATE_FILE` (ETag propio persistido para reinicios). Transporte: nunca por chat ni Git; copia directa a cada nodo
(SSM/SCP con confirmación de huella). Tras copiar, borrar la carpeta de origen. En AWS: archivo 0600 del usuario del servicio, no en SSM Parameter Store en claro.

**Rotación (sin parada).** 1) Generar el par nuevo del nodo. 2) Añadir su clave pública NUEVA a la lista del otro nodo (`{"oci": [vieja, nueva]}`) y reiniciar el otro nodo. 3) Cambiar la privada del nodo.
4) Cuando ya no existan registros firmados con la vieja (≥ 1 ttl), retirar la pública vieja. Periodicidad sugerida: 90 días o tras cualquier sospecha.

**Nodo comprometido.** Con Ed25519 el atacante puede firmar como ESE nodo (no como el otro); puede además escribir en la base de su nodo y renovar su propio lease: las firmas no lo impiden. Respuesta: parar el nodo,
revocar su credencial del almacén (PAR/identidad), retirar su pública de la lista del otro, rotar. Con HMAC el compromiso expone las claves de AMBOS.

**No confundir** con la clave privada C-04 (descifra respaldos): otra función, otra custodia, jamás se copia a estos nodos.
