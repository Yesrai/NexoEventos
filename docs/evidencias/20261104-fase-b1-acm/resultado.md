# Fase B1 — Validación del certificado de V1 e importación en ACM (4-nov-2026, saneado)

**Estado: certificado VALIDADO; importación REALIZADA. Incidencia: ya existía un certificado idéntico en ACM (duplicado creado por un error de comprobación mío).** La clave privada no se mostró, imprimió, guardó ni exportó en ningún momento.

## 1. Validación (SSM, solo inspección; la clave solo se usó para derivar su clave pública y compararla por hash, sin mostrar nada)
| Comprobación | Resultado |
|---|---|
| Dominio / SAN | CN y SAN = `nexoeventos-demo.duckdns.org` (el dominio por defecto del repositorio y de V1, el que usará V2) |
| Emisión / vencimiento | desde 3-oct-2026 hasta **1-ene-2027 23:19 GMT**; **58 días restantes**; vigente ≥ 30 días: SÍ (el comentario del script coincide con el dato real) |
| Emisor y cadena | Let's Encrypt (YE2) → ISRG Root YE → ISRG Root X2; `chain.pem` con 3 certificados; `openssl verify`: **OK** |
| Clave privada ↔ certificado | **corresponden: SÍ** (comparación de hash de la clave pública; privkey 600 root) |
| Tipo de clave | ECDSA P-256, firma ECDSA-SHA384, uso «servidor TLS»: válido para ALB y para importación en ACM |
| Uso actual en V1 | nginx sirve `fullchain.pem` + `privkey.pem` del mismo directorio |

## 2. Importación
- Script `deploy/v2/import-acm-certificate-on-v1.sh` inspeccionado antes: solo pasa **rutas** (`fileb://`) a la CLI, no imprime material criptográfico, sin `set -x`, sin archivos temporales; su única salida es el ARN. Se ejecutó en V1 por SSM (sin modificar nginx, DNS, certificados ni reglas de V1).
- Permisos de Academy: `ImportCertificate` permitido (ejecución real correcta).
- ACM tras la importación: **ISSUED, IMPORTED**, dominio y SAN `nexoeventos-demo.duckdns.org`, ECDSA P-256, vence 2027-01-01, `InUseBy` 0, etiqueta `Name = nexoeventos-v2-nexoeventos-demo.duckdns.org`. ARN: `arn:aws:acm:us-east-1:<cuenta>:certificate/cb25088b-…` (cumple la validación de `certificate_arn` de V2).

## 3. Incidencia (error propio, declarado)
Antes de importar comprobé «0 certificados en ACM» con `list-certificates` **sin filtro de tipo de clave**, que por defecto solo lista RSA-2048 y **oculta los certificados ECDSA**. En realidad **ya existía un certificado idéntico** (mismo dominio, mismos datos y número de serie, importado el 21-oct-2026, ARN `…/b8f2c28e-…`). Resultado: hay **2 certificados equivalentes** en ACM, sin uso (`InUseBy` 0). Coste: ninguno (los certificados importados son gratis). **No he borrado ninguno** (no estaba autorizado). Decisión pendiente: conservar uno y borrar el otro; recomiendo conservar el anterior (`b8f2…`) para V2 y borrar el nuevo, o al revés, da igual (son idénticos). La Fase 0 del 3-nov usó la misma consulta incompleta y por eso decía «no existe»: **corregido** aquí.

## 4. Comprobaciones de V1 tras la importación
EC2 `running`, SSM `Online`, RDS `stopped`; estado de Terraform sin cambios (serie 50); HTTPS de V1 sirve el mismo certificado (vence 1-ene-2027); `GET /` y `/livez` → **200** (~0,3 s). `/healthz` agota el tiempo de espera (12 s), consistente con la separación liveness/readiness mientras la RDS está detenida (**inferencia, no probada aquí**); no se relaciona con la importación.

## 5. Renovación / reimportación (no es automática)
ACM **no renueva** los certificados importados (`RenewalEligibility = INELIGIBLE`). Let's Encrypt renueva en V1 (certbot) y, tras cada renovación, hay que **reimportar con la misma ARN**: `deploy/v2/import-acm-certificate-on-v1.sh <dominio> <ARN>` (ejecutado en V1 por SSM); el ALB usa la nueva versión sin cambiar la ARN. Vence el 1-ene-2027: reimportar antes de esa fecha (y tras la renovación de certbot, que suele ocurrir unos 30 días antes). Si no se hace, el listener HTTPS de V2 serviría un certificado caducado. No hay alarma automática de vencimiento para importados: se recomienda un recordatorio (p. ej. 15-dic-2026) o una alarma de `DaysToExpiry` de ACM (opcional, no creada).
