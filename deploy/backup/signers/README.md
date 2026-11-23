# Claves PÚBLICAS verificadoras de los manifiestos de respaldo (llavero)
Solo claves **públicas** y sus huellas. La clave privada de cada firmante vive únicamente en la máquina que firma (EC2, `/etc/nexoeventos/c04/backup-sign.pem`, 0600) y **nunca** se copia ni se versiona.

| Id | Algoritmo | Huella SHA-256 (clave pública, DER) | Generada | Firma respaldos de | Estado |
|---|---|---|---|---|---|
| c04-backup-sign | EC P-256 | `2a9fdbf1615005f49869b8e9888d8f24da804e5b7346da83455e1e86642994fd` | 2026-11-19 03:57 UTC (EC2 V1) | ciclos de C-04 (`nexoeventos-rds-*`) | activa |

Conservación: esta carpeta (en Git cuando la propietaria autorice el commit) + copia local en `work/c04/` + la huella en la evidencia de C-04. Si la EC2 se detiene, los respaldos **siguen siendo verificables** con esta clave pública. Si la EC2 se **reemplaza o se termina** (se pierde la clave privada), se genera una clave nueva, se añade una fila aquí y **no se retira** la anterior: los respaldos antiguos se verifican con la clave de su época. Verificar: `openssl dgst -sha256 -verify c04-backup-sign.pub -signature <manifiesto>.manifest.json.sig <manifiesto>.manifest.json` o `c04_verify.py --signer-pub`.
