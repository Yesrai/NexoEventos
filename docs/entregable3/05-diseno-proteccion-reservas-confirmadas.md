# Entregable 3 · Protección de reservas confirmadas frente a retrasos de replicación y caída del escritor (diseño y plan; 10-nov-2026)

Estado: **ejecutado el 10-nov-2026**; resultados en `06-informe-estrategia-sincrona.md`. (Este documento conserva el diseño original; el estado de protección pasó después a vivir en el witness con CAS y se añadió la compuerta con lectura fresca.) Solo Docker local; sin nubes ni costos; sin commits ni push. Nada de lo siguiente declara RPO cero: define bajo qué condiciones se podría declarar y cómo se comprobará.

## 1. El problema medido
Con replicación lógica asíncrona, la caída del escritor con 3 s de retraso inducido perdió **328 reservas ya confirmadas al cliente** (ventana de 3,0 s). Sin retraso, 0 pérdidas en 3 corridas, pero eso es una observación, no una garantía (informe `04`).

## 2. Estado previo verificado antes de tocar nada
- **Evidencias conservadas:** `docs/entregable3/evidencias/` con 201 archivos y `MANIFIESTO-SHA256-20261110.txt` (todos los hashes verificados), más `repl-20261110-codigo-del-laboratorio-usado-en-A-E.tar.gz` (código exacto que produjo A–E, antes de los cambios de esta fase). Carpetas finales: A+E, B (13/13), C, D; y las corridas fallidas que explican el camino.
- **Estado del laboratorio (solo lectura):** 8 contenedores en marcha; ningún monitor; witness con escritor `pg-aws`, época 1 y lease caducado (nadie enruta); `pg-aws` es el único nodo que acepta conexiones de la aplicación; `pg-oci` está cerrado (`pg_hba` reject) y suscrito; sin `synchronous_standby_names`. No hay dos escritores. Nada se detuvo.

## 3. Hechos medidos en el laboratorio vivo (reversible; restaurado después)
| Hecho | Medida |
|---|---|
| Una suscripción lógica puede ser standby síncrono | `pg_stat_replication`: `sub_oci : streaming : quorum` con `synchronous_standby_names='ANY 1 (sub_oci)'` |
| **La opción `synchronous_commit` de la suscripción es imprescindible** | con el valor por defecto `off`: 4,5 tps y 222 ms por confirmación; con `on`: 2 112 tps y 0,47 ms (asíncrono: 3 760 tps y 0,27 ms). Cifras de una sola máquina |
| Con el seguidor desconectado el COMMIT espera | `wait_event = IPC/SyncRep`; se libera a los ~4 s al volver; mientras espera, la fila **no** es visible ni en la primaria para otras sesiones ni en el seguidor |
| Un retraso real de aplicación retrasa la confirmación | tabla bloqueada 4 s en el seguidor → el COMMIT tardó 3,2 s |
| `min_apply_delay` **no** retrasó los COMMIT síncronos | no sirve para inducir retraso; se usa el bloqueo de tabla |
| Una primaria bloqueada por el síncrono **no está muerta** | la sonda de vida con `synchronous_commit=local` sigue respondiendo; evita promover por error |

## 4. Estrategia
**Replicación síncrona con estados de protección y compuerta de promoción.**
1. Primaria: `synchronous_standby_names = 'ANY 1 (sub_<seguidor>)'`, `synchronous_commit = on`. Suscripción creada con `synchronous_commit = 'on'`. La confirmación al cliente solo ocurre cuando el seguidor ya hizo flush de la transacción.
2. Estados (persistidos en `work/repl-lab/protection.json`; en la nube haría falta un almacén con consenso):
   - **protected**: seguidor síncrono confirmando. Es el único estado en que se podría hablar de RPO cero.
   - **degraded**: se quitó el síncrono por decisión explícita (`LAB_DEGRADE_AFTER_S > 0`) porque el seguidor no estaba disponible; las confirmaciones desde entonces **no tienen copia**.
   - **unprotected**: tras una conmutación todavía no hay seguidor. Las confirmaciones tampoco tienen copia hasta reconstruirlo.
3. Política con el seguidor no disponible: **BLOQUEAR por defecto** (los COMMIT esperan; no se confirma nada sin copia; se sacrifica disponibilidad). Degradar solo si se configura, y queda registrado.
4. **Compuerta de promoción:** el monitor promueve automáticamente solo si el estado es `protected`. Con `degraded`/`unprotected` registra `promocion_bloqueada` y espera una orden explícita (`LAB_UNSAFE_PROMOTE=1`), que se registra como `promocion_insegura_ordenada` con el aviso de que lo confirmado sin protección puede perderse.
5. Tras promover: el nuevo escritor queda `unprotected` y sin ajuste síncrono heredado (si no, todos los COMMIT se bloquearían). Al reconstruir el seguidor (`reseed`) se vuelve a `protected` **solo** con conteos iguales y confirmación síncrona.
6. Las escrituras de verificación (sondas, aislamiento) usan `synchronous_commit=local` para no depender del seguidor.

## 5. Condiciones: qué se garantizaría y qué no
| Condición | ¿Se pretende RPO = 0 para lo confirmado al cliente? | Prueba |
|---|---|---|
| Caída de la primaria con el seguidor sano, conectado y síncrono | **Sí** (se comprobará con repeticiones, no se asume) | F2 |
| Seguidor lento en aplicar (bloqueo de tabla) y caída de la primaria | **Sí**: los COMMIT esperan; nada se confirma sin copia | F3 |
| Seguidor no disponible, política BLOQUEAR | **Sí**, a costa de no escribir | F4 |
| Seguidor no disponible, política DEGRADAR, y luego cae la primaria | **No**: lo confirmado en `degraded` se pierde si se promueve; la compuerta lo impide salvo orden explícita | F5 |
| Tras conmutación hasta reconstruir el seguidor | **No** (`unprotected`) | F6 |
| Caída simultánea de ambos nodos | No hay garantía de disponibilidad; se comprueba solo la durabilidad local tras reiniciar | F7 |
| Pérdida de disco en ambos, corrupción, fallos del almacenamiento, errores del propio PostgreSQL | **No cubierto** | — |

**Transacciones inciertas** (COMMIT local hecho o a medias en el instante de la caída, sin respuesta al cliente): siguen existiendo; no son confirmaciones perdidas. Se cuantifican arrancando la antigua primaria cerrada y comparando (huérfanas). El cliente reintenta con la misma clave de idempotencia; si la fila no estaba en el seguidor se crea otra y la huérfana queda como **duplicado lógico** para el rescate manual.

## 6. Pruebas preparadas (etapa F de `repl_test.py`)
| ID | Qué verifica | Criterio de paso |
|---|---|---|
| F1 | Mecanismo y coste (150 reservas por el borde: síncrono, asíncrono, suscripción con `off`) | seguidor en `quorum`/`sync`; con `off` la mediana es > 3× la de `on` |
| F2 | Caída de la primaria con carga, seguidor sano (3 repeticiones, ~1 400 escrituras cada una) | 0 confirmadas perdidas y 0 huérfanas confirmadas en **cada** repetición |
| F3 | Retraso de aplicación (tabla bloqueada) y caída a mitad | 0 perdidas y 0 confirmaciones al cliente durante el bloqueo |
| F4 | Seguidor desconectado, política BLOQUEAR | COMMIT en `SyncRep`, 0 confirmaciones sin copia, sin degradar ni promover, reanuda al volver |
| F5 | Seguidor desconectado, política DEGRADAR, caída de la primaria | promoción automática bloqueada y registrada; con orden explícita, las perdidas son exactamente confirmadas en la ventana degradada |
| F6 | Conmutación → `unprotected` → reconstrucción → `protected` → retorno planificado | estados correctos y 0 perdidas en el retorno |
| F7 | Caída simultánea de ambos nodos y reinicio | 0 confirmadas ausentes en la primaria reiniciada |

Mantienen las restricciones anteriores: fencing verificado con escrituras reales, arranque cerrado, y A–E se siguen ejecutando en modo asíncrono (`LAB_SYNC=0`) para que sean comparables.

**Qué se podrá afirmar al terminar:** "con la primaria cayendo bajo las condiciones F2, F3 y F4, y en n repeticiones, no se observó ninguna reserva confirmada perdida"; no "RPO cero". Para sostener algo más fuerte haría falta más repeticiones, inyección de fallos más variada (cortes en medio de la transferencia, retrasos de red reales, `kill` en distintos puntos del commit) y una revisión formal del protocolo.

## 7. Costos y riesgos de la estrategia
- **Disponibilidad:** sin seguidor, las escrituras se detienen (política por defecto). Es la decisión CAP explícita; degradar la invierte a cambio de poder perder datos.
- **Latencia:** cada confirmación suma el viaje de ida y vuelta al seguidor. Aquí es despreciable (misma máquina); **entre AWS y OCI será de decenas de milisegundos** y afectará a cada reserva. Hay que medirlo; no se extrapola.
- **Tiempos de espera:** una escritura bloqueada llega al borde con un 504/timeout (HAProxy de entrada 30 s); el cliente reintenta con la misma clave.
- **Valores de `wal_sender_timeout`** y de red real determinan cuánto tarda en notarse un seguidor caído; no probado.
- **¿Es trasladable a AWS RDS?** No verificado. Si RDS no permite fijar `synchronous_standby_names` con un suscriptor lógico externo, esta estrategia no se puede aplicar tal cual: habría que gestionar PostgreSQL en EC2 o aceptar RPO > 0. Debe confirmarse con los permisos reales de AWS Academy.

## 8. Cambios implementados (aún sin ejecutar las pruebas)
`scripts/repl-lab/labctl.py` (estados de protección, `enable_sync`/`disable_sync`/`reprotect`, supervisión del seguidor, compuerta de promoción, sonda con commit local, suscripción síncrona), `repl_test.py` (etapa F y modo por laboratorio), y los parches `patch_sync_*.py`. Validado: sintaxis, existencia de todas las funciones usadas y las funciones auxiliares sobre el laboratorio vivo (habilitar/deshabilitar el síncrono, estado del seguidor, `reprotect`, sonda con la primaria bloqueada), restaurando el estado original. La etapa F completa **no** se ha corrido.

## 9. Qué destruye ejecutar la etapa F (pide autorización)
Cada escenario hace `docker compose -p nexo-repl-lab down -v --remove-orphans` y reconstruye: se pierden **solo** los contenedores, la red y los volúmenes de `nexo-repl-lab` (`pg-aws-data`, `pg-oci-data`, `witness-data`), es decir, datos ficticios de prueba y el estado del witness. Se conservan las evidencias (`docs/`), el código, la clave local (`work/repl-lab/key.env`) y todo lo de otros proyectos. No se instala nada nuevo; la imagen local del backend se reconstruye desde caché con `--network=none`. Duración estimada: unos 25 minutos.
