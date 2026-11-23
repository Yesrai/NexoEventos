# C-04 · Fase C — tres ciclos manuales AWS → OCI (19-nov-2026, evidencia saneada)

Sin URL de PAR, token, namespace ni cuentas. Ciclos lanzados a mano (sin timers) desde un supervisor local por SSM; intervalo programado: 12 min entre inicios.

## Causa del defecto previo (PAR)
El `access-uri` real de un PAR `AnyObjectWrite` con prefijo termina en `/o/`: el prefijo lo impone el servidor sobre el NOMBRE del objeto. Corrección: `object_prefix` en `backup.json`
(antepuesto una sola vez en la URL de PUT; el manifiesto no cambia). La URL guardada no se modificó.

## Sonda If-None-Match (una vez, 05:26:32Z)
1.er PUT HTTP 200 · 2.º PUT al mismo objeto HTTP 412 · una sola versión en OCI (12 bytes, sin marca de borrado). No cuenta como respaldo.

## Ciclos
| # | Identificador | Inicio (UTC) | Duración | Bytes cifrados | CMS + manifiesto + firma en OCI | Manifiesto válido / firma / SHA-256 |
|---|---|---|---|---|---|---|
| 1 | nexoeventos-rds-20261119T053032Z | 05:30:32 | 2,2 s | 92 911 | sí (mismo id) | OK |
| 2 | nexoeventos-rds-20261119T054232Z | 05:42:32 | ≈2,1 s | 92 911 | sí (mismo id) | OK |
| 3 | nexoeventos-rds-20261119T055432Z | 05:54:32 | ≈2,1 s | 92 911 | sí (mismo id) | OK |

`c04_verify.py` (perfil de lectura independiente, clave pública fijada): `ok=true`, 3 de 3 esperados, nombres nuevos, sin omitidos. Intervalos: 12,0 y 12,0 min.
`backup_freshness.py --report`: 3 ciclos correctos, 0 fallidos, intervalo medio y máximo 12,0 min, duración máxima 2,164 s.

## RPO observado
**12 min — MEDICIÓN** (mayor hueco entre manifiestos en tres ciclos manuales con un espaciado elegido por nosotros). No es un RPO garantizado: no hay automatización ni demostración de continuidad.

## No probado
RTO (no hubo restauración en OCI), failover AWS–OCI, comportamiento de ciclos desatendidos o con fallos reales de red.

## Integridad
Seis objetos históricos idénticos (nombres y tamaños) antes y después. Bucket: 16 objetos = 6 históricos + 1 sonda + 9 de los tres ciclos.
