# T1 — Resultados del 22-nov-2026: 1.ª ejecución FAIL (07:03Z) → corrección → 2.ª ejecución **PASS** (07:08–07:12Z)

> **Resultado final de T1: PASS verificable y cero residuos** (ver §«Segunda ejecución»). La primera ejecución se conserva abajo sin cambios.

## Primera ejecución (07:03:54–07:04:14 UTC): **FAIL**

**Veredicto del recolector: FAIL** (no PASS; no se registra T1 como aprobada). Autorización: «AUTORIZO T1 EN OCI: oci_par_probe.py, bucket nexoeventos-recovery, perfil DEFAULT, 3 PAR temporales». Se ejecutó **una sola vez**; no se repite sin nueva autorización.
Expediente: `work/evidencias/T1-20261122T070354Z-f59a/` (0600/0700, manifiesto SHA-256 **verificado: 0 discrepancias**; `resultado.json` sha256 `5bea16c7…`). Sin URL de PAR ni credenciales en la evidencia (búsqueda de `oraclecloud.com`, rutas `/p/…` y claves privadas: 0 coincidencias).

## Cronología UTC
| Hora | Hecho |
|---|---|
| 07:03:54.172 | inicio del expediente · 07:03:54.237 autorización recibida |
| 07:03:56.087 | **lectura previa de solo lectura: LISTO** (21 objetos / 471 979 B, 0 PAR, prefijo vacío) |
| 07:03:56.148 | inicio del probe |
| 07:04:12.564 | fin del probe (16,4 s) — terminó por **excepción `NameError`** (ver causa) con limpieza automática |
| 07:04:13.943 | **lectura posterior: LISTO** (21 objetos / 471 979 B, 0 PAR, 0 versiones en el prefijo) |
| 07:04:14.150 | veredicto FAIL |

## Mediciones reales en OCI
| Criterio | Regla | Valor | Resultado |
|---|---|---|---|
| `create` duplicado rechazado | 200 y 412 | 200 y 412 | CUMPLE |
| ETag vigente / obsoleto, contenido intacto | 200 / 412 | 200 / 412, intacto | CUMPLE |
| Rondas CAS (8 contendientes, mismo ETag) con 1 ganador | ≥ 20 | **20 de 20** (140 rechazos 412; 0 «otros») | CUMPLE |
| Rondas CAS con más de un ganador | 0 | **0** | CUMPLE |
| Desfase de reloj vs servidor | ≤ 5 s | 0,758 s | CUMPLE |
| 3 PAR revocados; URL tras revocar | 0 activos, ≠ 200 | 0 activos; 401, 401, 401 | CUMPLE |
| Sin residuos | `limpio = true` | `true` (0 PAR, 0 versiones) | CUMPLE |
| Inventario previo intacto | 21 / 471 979 B | idéntico, 0 PAR, LISTO | CUMPLE |
| Ejecución sin interrupción | sin excepción | **excepción NameError** | **NO CUMPLE** |
| Rondas de **adquisición del lease** (LeaseClient real) | ≥ 20 | **no se ejecutó** | SIN MEDIR |
| Violaciones P0–P5 | 0 | no se ejecutó | SIN MEDIR |
| p95 de PUT exitoso | ≤ 2,5 s | no se reportó (el resumen se calcula después de la carrera) | SIN MEDIR |
Lo que **sí quedó demostrado en la nube real:** la atomicidad del CAS por PAR bajo concurrencia (20 rondas × 8, siempre exactamente 1 ganador), las condiciones `If-None-Match`/`If-Match`, la revocación de los PAR y la **limpieza completa tras una interrupción** (la prueba de estrés de la limpieza ocurrió de verdad y funcionó). **Lo que NO está demostrado:** la exclusividad de la **adquisición del lease** con el cliente real y la latencia: T1 **no está completo**.

## Estado final de OCI (verificado por la lectura posterior de solo lectura)
Bucket `nexoeventos-recovery`: `NoPublicAccess`, versionado, **0 PAR**, **0 versiones bajo `hybrid-test/par-probe-20261122/`**, **21 objetos / 471 979 B** (igual que antes). Directorio local de trabajo del probe: 0 archivos (URLs y manifiesto borrados). No se tocó ningún respaldo, secreto ni otro recurso. Costo: 0.

## Causa raíz
`oci_par_probe.py` llamaba a `LR.run_race(...)` pero **no importaba `lease_race`** (`NameError: LR`). Yo añadí la carrera de adquisición al probe y mis pruebas cubrían la limpieza y `--plan-only`, pero **ningún test ejecutaba ese camino**, y las pruebas con el intérprete de la CLI no existían. El manejo de excepciones que añadí el día anterior hizo exactamente lo previsto (revocó, limpió y verificó).

## Corrección (solo local; sin nueva ejecución remota)
1. `import lease_race as LR` añadido; `lease_race_step` admite `allow_http_localhost` y `cfg` (para pruebas locales); la salida registra ahora `interrumpido_detalle` (saneado, sin URL).
2. **Prueba de regresión que reproduce el fallo antes de corregir:** `test_probe_race_path.py` detecta `lease_race_step:LR` como nombre global sin definir en `oci_par_probe.py` y, tras la corrección, ejecuta `lease_race_step` contra un servidor PAR local atómico (3 rondas × 4: exclusividad demostrada). Además verifica que ningún script de la prueba (`oci_par_probe`, `lease_race`, `real_factory`) tenga nombres globales sin definir.
3. **Humo con el intérprete real de la CLI de OCI** (Python 3.15.0, SDK real de OCI): importa el probe real y corre la carrera contra un servidor local atómico: exclusividad demostrada (3/3, 0 violaciones). Incorporado como prueba (se omite solo si ese intérprete no existe).
4. `ejecutar-t1.sh` crea ahora todos los archivos de evidencia con `umask 077` (los de la ejecución anterior quedaron 0644: contenían solo conteos y estados, sin URL ni credenciales).
5. Suite relacionada: 22 + 3 pruebas del probe/carrera, todas OK; el resto de baterías previas no se alteró.

## Siguiente paso
Una **nueva autorización específica** de T1 (la autorización recibida cubre una sola ejecución). Cambios respecto de la tarjeta: ninguno de alcance; solo la corrección del import. `REAL_EXECUTION_WIRED = False` y `REAL_WIRING_ENABLED = False` se mantienen. No se ejecutó T2 ni ninguna otra operación Cloud; S14 intacto.


---
# Segunda ejecución (autorizada de nuevo por la propietaria): **PASS** — 2026-11-22 07:08:51 → 07:12:02 UTC
Expediente: `work/evidencias/T1-20261122T070851Z-9aa1/` (0600/0700; manifiesto SHA-256 verificado, 0 discrepancias; `resultado.json` sha256 `ca4c53d725d10a41…`). Registrada en el centro de operaciones (`record-evidence T1 … PASS`; barrera B06_T1 ahora cumplida; auditoría íntegra). Probe y lectura posterior con código de salida 0. Sin URL de PAR ni credenciales en ningún archivo (0 coincidencias).

## Mediciones reales en OCI (todas medidas y cumplidas: 12 de 12)
| Criterio | Regla | Valor |
|---|---|---|
| `create` duplicado / ETag vigente / ETag obsoleto | 200·412 / 200 / 412 | 200·412 / 200 / 412, contenido intacto |
| Rondas **CAS** (8 contendientes, mismo ETag) con 1 ganador | ≥ 20 | **20 de 20**; más de un ganador: **0**; 142 respuestas 412 en total |
| Rondas de **adquisición del lease** (`LeaseClient` real, ttl 3,0 s, margen 0,8 s, barrera) | ≥ 20 | **20 de 20**: en cada ronda 1 ganador, 1 cliente válido, 7 negativas explícitas, 0 inconclusos; épocas **2→21 (+1 exacto, sin retroceder ni repetirse)** |
| Violaciones P0–P5 | 0 | **0** |
| **Latencia de PUT exitoso** (22 muestras) | p95 ≤ 2,5 s | **p50 0,370 s · p95 0,414 s · máx 0,434 s** (PUT rechazados 412: p95 0,456 s) |
| Desfase de reloj local vs servidor | ≤ 5 s | 0,802 s |
| PAR | 3 creados · 3 revocados | auditoría del alcance OK (3 PAR, 0 problemas); tras revocar las 3 URL responden **401**; **0 activos** |
| Pruebas de alcance (esperaban rechazo) | rechazo | hermano / `backups/` / `secrets/` con el PAR del lease: **401, 401, 401**; el PAR de atestación sobre el objeto del lease: **401** |
| Sin residuos / limpieza | 0 PAR, 0 versiones, 0 errores | 0 / 0 / 0; sin objetos ajenos en el prefijo |
| Ejecución sin interrupción | sin timeout/plazo/excepción | cumple |
| Inventario previo intacto | 21 objetos / 471 979 B | idéntico; 0 PAR; LISTO |

## Estado final de OCI (lectura independiente de solo lectura, tras T1)
`nexoeventos-recovery`: `NoPublicAccess`, versionado, **0 PAR**, **0 versiones** bajo `hybrid-test/par-probe-20261122/`, **21 objetos / 471 979 B**, reloj +0,135 s. Directorio local de trabajo del probe vacío. Costo: 0.

## Límites que se registran tal cual
- **El PAR permite escribir sin condición** (`escritura_sin_condicion.sobrescribe_el_lease = true`): el lease se protege con la firma Ed25519 y la época, no con el PAR (diseño ya documentado). Este es un hallazgo medido, no un fallo de T1.
- Latencia medida desde este Mac (red doméstica, ≈ 0,4 s por PUT) en `sa-saopaulo-1`; se **repetirá desde AWS y desde la VM de OCI en T6**. Con ttl 3 s/margen 0,8 s el margen sobra (p95 0,41 s ≪ 2,5 s); para el lease real (ttl 15 s/margen 5 s) hay más holgura.
- Demuestra el almacén del lease y la exclusividad de la adquisición, **no** un failover.
