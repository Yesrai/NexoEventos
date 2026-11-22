# T1 — Lease real por PAR en OCI · TARJETA DE AUTORIZACIÓN
> **Estado final (22-nov): 1.ª ejecución FAIL (NameError del probe) → corregido → 2.ª ejecución, autorizada de nuevo, PASS (12/12 criterios, 0 residuos, inventario intacto). Ver `T1-20261122-resultado.md`. T1 CERRADA; no se reejecuta.**

## 0. La acción exacta que se autoriza
Ejecutar **una sola vez**, en el Mac de la propietaria:
```bash
scripts/ops/ejecutar-t1.sh --autorizo "AUTORIZO T1 EN OCI: oci_par_probe.py, bucket nexoeventos-recovery, perfil DEFAULT, 3 PAR temporales"
```
Sin ese argumento el script **solo lee** (modo plan) y muestra la frase. No hay otra forma de lanzar T1 con este flujo. Duración estimada 3–5 min (plazo máximo 20 min); los PAR caducan solos a los 55 min aunque todo falle.

## 1. Qué se crea, dónde y por cuánto tiempo
| Elemento | Detalle |
|---|---|
| Bucket | `nexoeventos-recovery` (OCI `sa-saopaulo-1`); **solo** bajo el prefijo `hybrid-test/par-probe-<AAAAMMDD>/` (validado en el código; cualquier otro prefijo se rechaza) |
| Objetos (3, nuevos) | `lease-<run>.json`, `attest-<run>.json`, `race-<run>.json` (`<run>` = 6 hex aleatorios); contenido de prueba (unos bytes) |
| PAR (3) | `par-probe-lease-<run>`, `par-probe-attest-<run>`, `par-probe-race-<run>`: **ObjectReadWrite sobre UN objeto exacto** cada uno, **sin listado**, caducan en **≤ 55 min** (el auditor del código rechaza > 4 h, otros objetos, `backups/`/`secrets/`, listado) |
| URL de los PAR | solo en archivos 0600 dentro de `work/hybrid/par-probe/` (0700); **no se imprimen ni van a ningún log**; se borran al final |
| Lo que NO se toca | los 21 objetos existentes (471 979 B), `backups/`, `secrets/`, IAM, VCN, ningún recurso de cómputo |

## 2. Permisos utilizados
- **Perfil `DEFAULT`** de `~/.oci/config` (usuario miembro de **Administrators**, verificado en solo lectura). Con él **solo** el probe: `get_namespace`, `get_bucket`, `create/list/delete_preauthenticated_request` (3 + 3), `list_object_versions` y `delete_object` **únicamente de versiones bajo el prefijo** y solo si no hay objetos ajenos allí. Nunca se incorpora al orquestador.
- La prueba de CAS y la de adquisición del lease usan **solo la URL del PAR, sin firma** (lo que usará el adaptador real).
- Pruebas de alcance (esperan **rechazo**): el PAR del lease intenta escribir un objeto hermano, `backups/x` y `secrets/…`; el PAR de atestación intenta escribir el objeto del lease. Si alguna **tuviera éxito** (PAR demasiado amplio) la prueba falla y el objeto creado fuera del prefijo **no** lo limpia el probe: hay que borrarlo a mano (se indicaría en la salida).

## 3. Condiciones de exclusividad que se evalúan en la nube real
1. `If-None-Match: *` crea una vez y rechaza el segundo `create` (412).
2. `If-Match` con ETag vigente acepta (200) y con ETag obsoleto rechaza (412), con contenido intacto.
3. **CAS bajo concurrencia:** 20 rondas × 8 contendientes sobre el **mismo ETag**: exactamente 1 ganador y 7 × 412 en cada ronda (se detiene en la primera anomalía).
4. **Adquisición del lease con `LeaseClient` real:** 20 rondas × 8 clientes nuevos (ttl 3,0 s, margen 0,8 s): todos observan el mismo registro, esperan ttl+margen, y tras una **barrera** llaman a `acquire()` a la vez. En **cada** ronda: P0 nadie toma un lease vigente durante la observación; P1 exactamente 1 ganador; P2 ≤ 1 cliente con lease válido; P3 el registro final nombra al ganador con época anterior+1; P4 los demás reciben una negativa explícita; P5 timeout/error = **inconcluso** (la ronda no cuenta).
5. Esta misma lógica se probó en local con un **control negativo** (un servidor sin If-Match efectivo produce varios ganadores y la prueba lo **detecta**), así que no es una prueba que siempre pase.
6. Límite que se registra tal cual: el PAR permite escribir **sin condición** (`escritura_sin_condicion`); el lease se protege con la firma Ed25519, no con el PAR.

## 4. Criterios medibles de PASS (`ops_center/criterios/T1.json`; **todos** medidos y cumplidos; si falta uno ⇒ PARCIAL, nunca PASS)
| Criterio | Regla |
|---|---|
| `par_creados_y_revocados` | 0 PAR activos y las 3 URL ya no responden 200 |
| `create_duplicado_rechazado` | 200 luego 412 |
| `cas_etag_viejo_rechazado` | 200 (vigente) y 412 (obsoleto), contenido intacto |
| `cas_rondas_con_un_solo_ganador` | ≥ 20 |
| `cas_rondas_con_mas_de_un_ganador` | = 0 |
| `lease_adquisicion_rondas_exclusivas` | ≥ 20 |
| `lease_adquisicion_violaciones` | = 0 (P0–P5, sin inconclusos ni rondas sin ganador) |
| `p95_put_exitoso_s` | ≤ 2,5 s (margen del lease 5 s) |
| `reloj_desfase_s` | ≤ 5 s respecto de la cabecera `Date` del servidor |
| `ejecucion_sin_interrupcion` | sin timeout, plazo agotado ni interrupción |
| `sin_residuos` | `limpio = true` (0 PAR, 0 versiones en el prefijo) |
| `inventario_previo_intacto` | mismos 21 objetos / 471 979 B antes y después, 0 PAR y el modo plan vuelve a dar LISTO |

## 5. Condiciones de aborto (la prueba se detiene, **revoca y limpia**, y el veredicto no es PASS)
| Condición | Qué ocurre |
|---|---|
| Lectura previa distinta de LISTO (bucket público/sin versionado, PAR activo ajeno, prefijo con residuos, reloj > 5 s o ilegible, uso ≥ 2 GiB) | **No se crea nada**; evidencia PARCIAL; código 2 |
| Auditoría de los PAR creados fuera de alcance | se revoca y se limpia; FAIL |
| Estado inesperado en create/CAS/contendientes | se detiene en esa ronda; limpieza |
| **Timeout o pérdida de conectividad** (petición a 20 s ⇒ estado 0; excepción de red) | la ronda es **inconclusa** (no cuenta), se detiene y se limpia; si la limpieza también falla ⇒ ver §6 |
| **Error de reloj** (`Date` ilegible o desfase > 5 s) | se detiene antes de las pruebas |
| Violación P0–P5 | FAIL inmediato |
| Plazo global de 20 min | se detiene y se limpia |
| Ctrl-C / SIGTERM / cualquier excepción | `except BaseException` ⇒ limpieza garantizada; el script imprime el comando `--cleanup-only` |
| Cualquier cargo o aviso de costo en la consola de OCI | detener y revisar |

## 6. Revocación, limpieza y comprobación de cero residuos
1. **Automática, siempre:** revoca los 3 PAR (más cualquier PAR «huérfano» cuyo acuse se perdió, localizado por nombre y `run`), borra **todas las versiones** bajo el prefijo (solo si no hay objetos ajenos), borra los `*.par` locales y el manifiesto. **Cada paso continúa aunque falle el anterior**.
2. **Comprobación propia:** `par_activos_tras_revocar = 0`, `versiones_restantes_en_prefijo = 0`, y cada URL ≠ 200. Exit **0** = limpio y aprobado · **1** = detenido pero limpio · **3** = **quedan residuos** (nunca se declara limpio sin comprobarlo).
3. **Comprobación independiente:** el script repite la **lectura de solo lectura** y compara con la previa (21 objetos / 471 979 B / 0 PAR).
4. **Si hay fallo de limpieza** (exit 3): `scripts/multicloud/hybrid/oci_par_probe.py … --cleanup-only` revoca los `par-probe-*` y borra solo objetos `lease|attest|race-<6 hex>.json` bajo el prefijo; el **manifiesto 0600** (`par-probe.manifest.json`) lista lo creado. Último recurso: consola de OCI → Object Storage → bucket → PAR / versiones.
5. Los PAR caducan solos en 55 min: **backstop** si el Mac muriera a mitad.

## 7. Costo y limitaciones (incertidumbre declarada)
- **Costo esperado: 0.** ≈ 400 peticiones y unos bytes; PAR e IAM sin cargo; Object Storage dentro del tope de 20 GiB (usa 0,5 MB). La lectura de uso de los últimos 30 días muestra **0,0 PEN en todos los servicios**.
- **Incertidumbre:** la fecha de fin del Free Trial **no se puede leer por API**; los límites y las formas visibles son los de un perfil **Always Free** (consistente con trial terminado, **no lo prueba**). T1 solo usa recursos Always Free (Object Storage, PAR), así que no depende del trial.
- **Limitaciones:** demuestra el almacén del lease y la limpieza, **no** un failover; la latencia medida es la de este Mac y esta hora (se repetirá desde AWS en T6); el PAR no impide la escritura sin condición.

## 8. Evidencias que se conservan (`work/evidencias/T1-<UTC>/`, manifiesto SHA-256 verificado)
`meta.json` (criterios, marcas) · `events.jsonl` (timestamps UTC con ms: autorización, inicio/fin del probe) · `capturas/lectura-previa.json` (configuración inicial) · `capturas/probe-salida.json` (resultado completo, sin URL ni OCID) · `capturas/lectura-posterior.json` (estado final) · `probe-stderr.txt` · `resultado.json` / `resultado.md` (veredicto y criterios) · `MANIFIESTO.sha256`. Más la captura de la consola de OCI con 0 PAR (la toma la propietaria, redactada, con fecha y barra de direcciones).

## 9. Verificación local ya hecha para esta tarjeta
- Probe con **cliente OCI falso**: 16 pruebas (limpieza completa, revocación que falla, red caída, PAR huérfano, objeto ajeno, reloj, `--plan-only`) y **carrera de adquisición** con control negativo (4 pruebas).
- `ejecutar-t1.sh` con probe simulado: 6 pruebas (modo plan, frase incorrecta, PASS, aborto previo, FAIL por violación, inventario alterado/residuos).
- **Lectura real de hoy** (`--plan-only` contra OCI, solo lectura): **LISTO** — bucket `NoPublicAccess` + versionado, **0 PAR**, prefijo vacío, reloj +0,16 s, 21 objetos / 471 979 B (`work/pruebas/t1-plan-only-*.json`).
- Defectos corregidos al preparar T1: el probe no creaba el directorio de trabajo con sus padres (habría fallado al primer comando), y no tenía manejo real de excepciones.
