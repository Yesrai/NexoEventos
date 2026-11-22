# Entregable 3 · Protección de reservas confirmadas con replicación síncrona: informe de pruebas en Docker (10-nov-2026)

Todo se ejecutó en el laboratorio local `nexo-repl-lab` (Docker en la Mac de la usuaria): sin AWS, Azure, OCI ni Google Cloud, sin costos, sin credenciales cloud, datos ficticios, sin instalaciones nuevas, sin tocar SUNAT ni otros proyectos, sin commits ni push. Diseño y plan: `05-diseno-proteccion-reservas-confirmadas.md`. Código: `scripts/repl-lab/`. Evidencias: `docs/entregable3/evidencias/repl-20261110-*` con `MANIFIESTO-SHA256-20261110.txt`.

## 1. Resumen honesto
| Pregunta | Respuesta |
|---|---|
| ¿Es la replicación realmente síncrona vista desde la primaria? | **Sí, demostrado en Docker (F0).** Con el seguidor retenido, el COMMIT esperó 3,09 s en `IPC/SyncRep` y al volver el seguidor ya había confirmado (`flush_lsn` 0/1CC9870 ≥ LSN de la transacción 0/1CC93C0). El control asíncrono volvió en 0,11 s con `flush_lsn` 0/1CC9AB0 < 0/1CC9B38 |
| ¿Se perdieron reservas confirmadas en modo `protected`? | **Ninguna observada** en 5 caídas de la primaria con carga (≈ 7 500 reservas confirmadas). Con el mismo escenario de 3 s en modo asíncrono fueron 328 |
| ¿Se puede declarar RPO cero? | **No.** Es una ausencia observada en muestras pequeñas, bajo condiciones definidas (§5). No es una garantía ni una prueba |
| ¿Sigue habiendo interrupción? | Sí: RTO de 3,3 a 3,8 s en escritura y de 3,4 a 3,8 s en lectura con errores 503; no es disponibilidad continua |
| ¿Se puede trasladar a AWS Academy RDS y OCI? | **No verificado** (§8). Tres bloqueos posibles sin confirmar |

## 2. Estado de las pruebas
La etapa F (F0–F9, incluidos F4b, F5c y la matriz F5x) pasó **33 de 33** en su corrida 4; F4R pasó **5 de 5**. Antes hubo tres corridas con fallos que se corrigieron y se conservan: 28/33, 31/33 y las anteriores (§7). Las etapas A–E (A+E 8/8, B 13/13, C 10/10, D 5/5) corresponden al informe `04` y se ejecutaron en modo asíncrono.

## 3. Estrategia implementada
- Primaria con `synchronous_standby_names = 'ANY 1 (sub_<seguidor>)'`; suscripción con `synchronous_commit='on'`.
- Estado de protección **en el witness**, con compare-and-set por secuencia y época: `protected`, `degrading`, `degraded`, `reprotecting`, `promoting`, `unprotected`, `unknown`. Cualquier cambio de escritor lo invalida (`unknown`).
- **Degradar sin carreras:** primero la intención (`degrading`, con CAS), después se desactiva el síncrono y se verifica, después `degraded`. Si hay una promoción en curso (`promoting`) o el estado cambió, la degradación aborta sin tocar la configuración.
- **Compuerta de promoción automática:** relee el estado fresco justo antes de decidir; exige `protected`, escritor y época coherentes y una verificación de menos de 15 s; reclama la promoción con un CAS exclusivo (`protected → promoting`). Si no, registra `promocion_bloqueada` con las razones. La promoción insegura exige una orden explícita (`LAB_UNSAFE_PROMOTE=1`).
- **Política por defecto con el seguidor caído: esperar** (los COMMIT esperan, no se confirma nada sin copia). Degradar solo si se configura (`LAB_DEGRADE_AFTER_S`) y queda registrado.
- **Recuperación** de estados intermedios (`degrading`, `reprotecting`, `promoting`, `unknown`) según la configuración efectiva; un fallo al consultar el estado se omite y no se interpreta como un cambio.
- **Reprotección:** seguidor habilitado y transmitiendo, síncrono habilitado y **barrera de LSN** (el seguidor confirmó todo el WAL previo); no exige conteos iguales.
- **Limpieza verificada** de `synchronous_standby_names` en cualquier nodo que deja de ser primario (reconstrucción, rescate de huérfanas, retorno planificado).
- Se conserva el fencing en capas del informe `04` (`pg_hba` cerrado, arranque cerrado, escrituras reales de verificación).

## 4. Resultados medidos
### Caída de la primaria con carga y seguidor sano (F2 ×3, F2b, F3), modo `protected`
| Métrica | F2-1 | F2-2 | F2-3 | F2b (3 s) | F3 (apply retrasado) |
|---|---|---|---|---|---|
| RTO escritura / lectura | 3,38 / 3,51 s | 3,70 / 3,61 s | 3,79 / 3,77 s | 3,29 / 3,39 s | 3,35 / 3,46 s |
| Detección → aislamiento → lease → HAProxy-BD | 0,09 → 1,32 → 2,42 → 3,44 s | 0,45 → 1,62 → 2,69 → 3,71 s | 0,54 → 1,66 → 2,75 → 3,78 s | 0,04 → 1,20 → 2,28 → 3,33 s | 0,03 → 1,20 → 2,34 → 3,39 s |
| Errores HTTP escritura / lectura | 56×503 / 39×503 | 56×503 / 37×503 | 56×503 / 40×503 | 48×503 + 8 red / 39×503 | 56×503 / 37×503 |
| Intentos no exitosos reintentados con la misma clave | 56 | 56 | 56 | 56 | 56 |
| Confirmadas al cliente | 1 581 | 1 596 | 1 602 | 1 358 | 1 340 |
| Latencia de confirmación p50 / p95 | 9,7 / 33,7 ms | 10,5 / 32,3 ms | 9,9 / 24,6 ms | 11,5 / 37,9 ms | 11,7 / 37,7 ms |
| **Confirmadas perdidas** | **0** | **0** | **0** | **0** (asíncrono: 328) | **0** |
| Huérfanas en la antigua primaria / **inciertas** | 0 / 0 | 0 / 0 | 0 / 0 | 1 / 1 | 1 / 1 |
| Sobreventa o duplicados | ninguno | ninguno | ninguno | ninguno | ninguno |
En F3 no hubo ninguna confirmación al cliente mientras la tabla estaba bloqueada en el seguidor. La latencia de confirmación por el borde fue similar con síncrono y con asíncrono (4,8 vs 4,5 ms de mediana en F1) en este montaje de una sola máquina; **entre nubes será mayor** por el viaje de ida y vuelta.

### Seguidor no disponible (F4, F4b, F4R)
Con la política de esperar y la suscripción deshabilitada, o el contenedor del seguidor detenido: un COMMIT esperando en `SyncRep`, **0 confirmaciones nuevas (201) sin copia**, sin promoción (la primaria estaba viva), y al volver el seguidor se reanudó (493 y 26 confirmaciones) con 0 perdidas. F4R repitió 5 veces el invariante exacto (toda reserva confirmada tras deshabilitar el seguidor debe existir ya en el seguidor): **0 confirmaciones en la ventana en las 5 repeticiones.**
*Observación no resuelta:* en la corrida 3 de F, F4 contó 5 confirmaciones en esa ventana. Es probable que fueran respuestas 200 de repeticiones de claves ya replicadas o commits anteriores a que el comando de deshabilitar surtiera efecto (la ventana se contaba desde antes de que el comando volviera), pero esa corrida no guardó el detalle y **no pude comprobarlo**. En las 6 mediciones posteriores bien definidas (F4 corrida 4 y F4R ×5) no se repitió.

### Degradación, carreras y fallos en puntos críticos (F5, F5c, F5x)
- **F5:** el orden registrado fue `degrading` (…660,250) → síncrono desactivado (…660,521) → `degraded` (…660,526). Con la primaria caída la promoción automática quedó **bloqueada** con sus razones. Al ordenar la promoción insegura se perdieron **511 reservas confirmadas**, todas posteriores al registro de `degrading` (la primera, 0,243 s después): lo confirmado sin protección. Es el límite de la garantía, no un defecto.
- **F5c:** en 30 carreras simultáneas entre degradar y promover sobre el mismo estado (CAS en el witness) ganó exactamente una transición cada vez (18 degradaciones, 12 promociones, 0 dobles, 0 sin ganador).
- **F5x:** 6 combinaciones (fallo en `after_intent`, `after_disable`, `after_record`, con caída del controlador o de la primaria) con carga: en todas la promoción automática quedó bloqueada (sin lease ni promoción) y no se confirmó nada más tras la caída. La combinación `after_intent` + caída de la primaria bloquea aunque no habría pérdida (falso bloqueo conservador); requiere decisión manual.

### Recuperación y failback (F6, F7, F8)
- **F6:** tras la conmutación el estado quedó `unprotected` y sin síncrono heredado; **0 reservas perdidas**. La antigua primaria que reapareció sola conservaba `ANY 1 (sub_oci)` obsoleto pero arrancó cerrada (0 escrituras directas aceptadas, 0 promociones hacia ella, el escritor siguió siendo `pg-oci`). La reconstrucción limpió el síncrono (verificado) en 2,7 s sin bloquearse y devolvió `protected`; el retorno planificado perdió 0.
- **F7:** caída simultánea de ambos nodos: 496 confirmadas, **0 ausentes** tras reiniciar la primaria (durabilidad local; no es una garantía de disponibilidad).
- **F8:** con el estado de protección `unknown` en el momento de la caída, **no se promovió**, se registró el motivo y no se confirmó nada más.
- Se observó además que el monitor **restablece la protección por sí solo** en unos 2 s (unknown → unprotected → reprotecting → protected con barrera de LSN) si las condiciones se cumplen.

### Caída después del COMMIT y antes de la respuesta HTTP (F9)
- **F9a:** con replicación síncrona, si la respuesta existe la reserva ya está en el seguidor; tras la caída el reintento con la misma clave devolvió 200 con la misma reserva (3,8 s).
- **F9b:** con el COMMIT esperando al seguidor cuando cae la primaria, el cliente no recibió confirmación; el reintento creó la reserva en la nueva primaria (201) y la fila de la antigua es una transacción **incierta** (huérfana con la misma clave: duplicado lógico detectado en el rescate, nunca una confirmación perdida).

## 5. Qué se puede y qué no se puede afirmar
**Se observó** (modo `protected`, seguidor sano o caído sin degradar, caídas de la primaria con ~1 400 reservas por prueba): 0 reservas confirmadas al cliente ausentes tras la conmutación, en 5 caídas con carga, más F2b (escenario de 3 s), F3, F7 y F9.
**No se demuestra RPO cero.** Límites de esa afirmación:
- **Pocas repeticiones:** 5 caídas con carga. Con 0 fallos en 5 pruebas independientes, el límite superior al 95 % de la probabilidad de que una caída pierda algo es de unos 45–60 %; por transacción (regla de tres) ≈ 0,04 %, pero las transacciones de una misma caída no son independientes.
- **Un solo tipo de fallo repetido:** `docker kill` del contenedor. No se probaron cortes de red reales con latencia, corrupción, fallos de disco ni errores del propio PostgreSQL.
- **Garantía condicional:** solo con seguidor síncrono conectado y al día, fallo único, `fsync` activo y almacenamiento sin pérdida; **no** en modo `degraded`, `unprotected`, tras una promoción insegura ordenada, con doble fallo con pérdida de disco o con el controlador/witness fallando a la vez.
- **Controlador y witness únicos** en el laboratorio; el estado de protección vive en un solo witness.
- **Falsos bloqueos conservadores** (p. ej. `after_intent`): disponibilidad sacrificada por seguridad.

## 6. Riesgos restantes
1. **Disponibilidad:** sin seguidor, las escrituras esperan; el RTO medido (≈ 3–4 s) incluye 503 y no es disponibilidad continua.
2. **Latencia real entre nubes:** cada confirmación suma el RTT; no medido.
3. **Modo `degraded`/`unprotected`:** pérdida posible; las 511 reservas de F5 lo ilustran. Nunca debe activarse sin política explícita.
4. **Transacciones inciertas:** existen y producen duplicados lógicos que exigen reconciliación manual.
5. **Controlador/witness únicos** (SPOF) y su estado de protección sin consenso replicado.
6. **Ventana de verificación (15 s):** si el síncrono se alterara fuera del controlador dentro de esa ventana y justo cayera la primaria, no se detectaría.
7. **Fencing de Docker es una simulación** (informe `04` §9).
8. **Mis propios defectos de prueba y de control** encontrados en el camino (§7) muestran que la lógica es delicada y que hacen falta más pruebas y una revisión externa.

## 7. Fallos intermedios y correcciones (todo conservado)
| Corrida | Hallazgo | Causa | Estado |
|---|---|---|---|
| F0 intento 1 | control asíncrono "no pasó" | medido tarde (tras terminar el bloqueo) | corregido; la parte síncrona ya cumplía |
| Corrida 1 (F5) | confirmadas sin copia mientras el registro decía `protected` | el estado se registraba después de desactivar el síncrono | corregido: intención primero + CAS en el witness |
| Corrida 1 (F6) | la reconstrucción se bloqueaba | `synchronous_standby_names` obsoleto en la antigua primaria | corregido: limpieza verificada |
| Corrida 2 (F2-3) | no hubo promoción | una consulta fallida (primaria muerta en ese instante) se leyó como "síncrono cambiado" y degradó | corregido: se omite el ciclo; falló de forma segura |
| Corrida 2 (F5x) | monitor ocupado 10 s | reprotección habilitaba el síncrono con el seguidor sin transmitir | corregido: exige seguidor transmitiendo |
| Corrida 2 (F6) | "1 reserva perdida" | defecto de medición (lista leída después de la BD) | corregido; no era pérdida |
| Corrida 3 (F8) | promoción inesperada | el monitor restableció la protección antes de la caída (la promoción era correcta); la prueba no mantenía la incertidumbre | corregido (monitor pausado) |
| Corrida 3 (F4) | 5 confirmaciones en la ventana | **no resuelto**; no se repite (ver §4) | observación abierta |

## 8. Compatibilidad pendiente con AWS Academy RDS y OCI
**No se ha verificado nada contra AWS ni OCI.** Lo que habría que comprobar, en este orden:
1. **¿Permite RDS fijar `synchronous_standby_names`?** Búsqueda en la documentación: la tabla de parámetros publicada es parcial ("algunos, no todos") y lista `synchronous_commit` como dinámico pero no menciona `synchronous_standby_names`; no encontré una afirmación oficial en ningún sentido. La comprobación fiable es de **solo lectura**: `aws rds describe-db-parameters --db-parameter-group-name <grupo personalizado de PostgreSQL 18> --query "Parameters[?ParameterName=='synchronous_standby_names']"` y mirar `IsModifiable` (requiere credenciales de Academy; no ejecutado). Si es no modificable, **la estrategia no es trasladable a RDS tal cual** (alternativas: PostgreSQL gestionado por el equipo en EC2, o aceptar RPO > 0 con asíncrono).
2. **Suscriptor externo como standby síncrono de RDS:** exige que el `application_name` de la suscripción figure en ese parámetro; sin él no hay síncrono.
3. **`rds.logical_replication`:** parámetro estático (reinicio) en un grupo de parámetros propio; slots inactivos pueden llenar el disco; RDS es privada: hace falta un camino de red (VPN/peering) y un rol con `rds_replication`.
4. **Permisos de AWS Academy:** el rol del lab puede no permitir crear grupos de parámetros, modificar la instancia ni cambiar grupos de seguridad (fencing); y la sesión de Academy caduca y apaga recursos: los componentes de decisión (witness, controlador, gateway) no pueden vivir allí.
5. **Latencia y red AWS–OCI** (VPN, MTU, RTT) y su efecto en cada COMMIT síncrono; `wal_sender_timeout` y detección de seguidor caído sobre red real.
6. **TLS `verify-full`** (la app lo exige para BD remotas) con un nombre estable del gateway de BD y certificados en ambos nodos.
7. **Fencing real** (no Docker): sin acceso a `pg_hba` ni arranque en RDS; si cae todo AWS no se puede llamar a su API. Diseño específico pendiente (RDS accesible solo desde un gateway propio que consulta al witness; red cerrada por defecto).

## 9. Qué habría que implementar realmente entre las dos nubes
- Witness con **quórum en un tercer sitio** (p. ej. Azure) y controlador **redundante** con el estado de protección replicado por consenso.
- Gateways de BD redundantes en ambos sitios con la comprobación del witness; DNS o balanceador externo hacia ellos.
- PostgreSQL primario y seguidor con **replicación síncrona confirmada** (si RDS no lo permite: instancia propia) y la **barrera de LSN** para reprotegerse.
- **Fencing real** por API de cada nube + red cerrada por defecto + arranque cerrado.
- Política explícita (y firmada por el negocio) para `degraded`, promoción insegura y reconciliación de **duplicados lógicos** por clave de idempotencia.
- Medición repetida sobre infraestructura real (latencia, caídas reales, cortes de red), más repeticiones y fallos más variados, y revisión externa del protocolo.
- Secretos idénticos (`TICKET_ENCRYPTION_KEY`, `SECURITY_HASH_KEY`) y frontend con reintentos con `Idempotency-Key`.

## 10. Reproducir
```bash
scripts/repl-lab/lab.sh up                                                               # laboratorio
python3 scripts/repl-lab/repl_test.py --out docs/entregable3/evidencias/repl-AAAAMMDD --only F      # etapa F (~55 min; recrea nexo-repl-lab)
python3 scripts/repl-lab/repl_test.py --out docs/entregable3/evidencias/repl-AAAAMMDD --only F4R    # 5 repeticiones de F4
scripts/repl-lab/lab.sh down                                                              # elimina SOLO nexo-repl-lab
```

## 11. Evidencias
`repl-20261110-F0-demostracion-sincrona` (F0), `…-F-corrida4-33de33` (etapa F completa), `…-F4R-5-repeticiones`, y las corridas intermedias `…-F-corrida1-parcial-hallazgos`, `…-F-corrida2-coordinacion-28de33`, `…-F-corrida3-31de33`, `…-F0-intento1-control-mal-medido`. Cada una incluye `consola.txt`, `resultados-*.json`, `eventos-*.jsonl` con `stdout`/`stderr` del controlador, volcados de escritores y las huérfanas exportadas.
