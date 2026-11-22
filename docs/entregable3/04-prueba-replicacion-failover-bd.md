# Entregable 3 · Replicación PostgreSQL y failover de base de datos en Docker local (10-nov-2026)

Todo se ejecutó en la Mac de la usuaria con Docker. No se usó AWS, Azure, OCI ni Google Cloud; no hubo costos, credenciales cloud ni datos reales; sin commits ni push. Los contenedores, redes y volúmenes de otros proyectos (SUNAT, `nexo-obs-lab`) no se tocaron. Código: `scripts/repl-lab/`. Evidencias (archivos del repositorio, fuera de los volúmenes Docker): `docs/entregable3/evidencias/repl-20261110-*`.

## 1. Veredicto honesto
| Se demostró (en Docker, con las pruebas citadas) | NO se demostró |
|---|---|
| Replicación lógica asíncrona de usuarios, sesiones, eventos, reservas, entradas y asientos (14 tablas idénticas por conteo y huella md5) | RPO cero: la replicación es asíncrona; con retraso inducido se perdieron 328 reservas confirmadas al cliente |
| Conmutación de la base con RTO de **3,1 a 4,4 s** (escritura) y **3,2 a 4,4 s** (lectura) en la caída del escritor con carga | Que esas cifras valgan entre AWS y OCI reales (latencia, VPN, APIs de la nube, RDS) |
| Sin sobreventa ni duplicados con reintentos idempotentes, y el caso "confirmado en la BD, respuesta HTTP perdida" | Ausencia de split-brain: solo **no se observó** doble escritura en el muestreo (ver §6) |
| Aislamiento del antiguo escritor verificado con intentos reales de escritura directa, también tras reiniciarlo y sin monitor | Que el mecanismo de aislamiento sea trasladable a AWS RDS (ver §9) |
| Failback manual: rescate de huérfanas, reconstrucción y retorno planificado | Continuidad sin interrupción: hubo 3–4 s de 503 en cada conmutación |

## 2. Desviaciones respecto al diseño aprobado
1. **Nueve contenedores en lugar de los ocho aprobados**: los ocho permanentes (con el gateway de BD ya dividido en dos sidecars) más `cut-proxy` para la prueba de caída tras confirmar. La aplicación actual exige `sslmode=verify-full` para cualquier BD que no sea local (`backend/app/database.py`), así que el gateway de BD pasó de un `haproxy-db` único a **dos sidecars** (`haproxy-db-aws`, `haproxy-db-oci`) que comparten la red de cada app y escuchan en `127.0.0.1:5432`. Contenedores: `pg-aws`, `pg-oci`, `witness`, `app-aws`, `app-oci`, `haproxy-edge`, `haproxy-db-aws`, `haproxy-db-oci` (+ contenedores bajo demanda: `migrate`, `cut-proxy` para la prueba de caída tras confirmar y, solo en la etapa E, `app-stale` con su sidecar).
2. **Imagen del backend.** `nexoeventos-dev-backend:latest` es del 22-oct y no incluye los manejadores de errores de BD que el repositorio añadió después (commit `ca983f1`, 29-oct). Se construyó `nexo-repl-lab-backend:current` = esa imagen + el código actual de `backend/app` y `backend/alembic` (`Dockerfile.current`, con `--network=none`: sin descargas, sin tocar el repositorio). Las dependencias siguen siendo las del 22-oct.
3. **Arranque cerrado de PostgreSQL** (`parts/lab-entry.sh`): no estaba en el diseño inicial; se añadió tras el hallazgo de B2 (§5).

## 3. Corrección del informe anterior sobre `/api/events`
El informe `03-prueba-local-failover.md` atribuía un HTTP 500 a la aplicación. **Era un artefacto de la imagen antigua.** Etapa E (8 de 8 comprobaciones del bloque A+E): con el código actual y la BD inaccesible, `/api/events`, `/api/events/{id}`, `/api/auth/session` con sesión válida, `/api/me/reservations` y `POST …/reservations` devuelven **503**; `/health` 200 y `/ready` 503. La imagen antigua devuelve 500 en todas las rutas con BD: su `main.py` (md5 `c4d6f7…`) no registra los manejadores de `OperationalError`/`InterfaceError`/`TimeoutError`, que el repositorio (md5 `54a2bc…`) sí registra. No hay corrección que proponer al backend por este punto. El 401 de `/api/auth/session` tampoco era un fallo: se llamó sin cookie.

## 4. Arquitectura y cómo repetirla
Primaria `pg-aws` (simula AWS) y seguidora `pg-oci` (simula OCI), PostgreSQL 18 independientes, replicación lógica asíncrona (`nexo_pub` → `sub_oci`, 14 tablas). Un `witness` guarda escritor, época y lease (6 s) en un volumen. `labctl.py monitor` (el plano de control) sondea al escritor con **escrituras reales**, renueva el lease y, ante 3 sondas fallidas, promueve. HAProxy-BD enruta solo al nodo que el witness declara escritor; sin lease, nadie.
```bash
scripts/repl-lab/lab.sh up                                   # construye imagen local, compose, replicación, witness, apps y HAProxy
python3 scripts/repl-lab/repl_test.py --out docs/entregable3/evidencias/repl-AAAAMMDD --only A,B,C,D,E   # ~40 min
scripts/repl-lab/lab.sh down                                 # elimina SOLO el proyecto nexo-repl-lab (contenedores, red, volúmenes)
```
Promoción: retirar lease → aislar al escritor y comprobarlo → cortar la suscripción → ajustar secuencias → abrir el destino y comprobar una escritura real → otorgar lease con época nueva.

## 5. Fencing: qué falló, qué se hizo y qué quedó verificado
**Fallo real (corrida 3 de B).** El antiguo escritor, reiniciado tras la promoción, aceptó escrituras reales directas (26 de 33 muestras con dos bases escribibles). Causa: el aislamiento ejecutaba `ALTER SYSTEM` junto a otras sentencias en un solo `psql -c`; PostgreSQL las agrupa en una transacción y `ALTER SYSTEM` falla en ella; **el código de salida no se revisaba**. El registro decía "aislado" mientras la escritura real seguía aceptada. Evidencia: `repl-20261110-B-corrida3`.

**Por qué `default_transaction_read_only = on` no es fencing.** Prueba B4: con ese solo ajuste, la propia aplicación lo anula desde su sesión (`SET`/`BEGIN READ WRITE`/`PGOPTIONS`) y escribe. Solo el `pg_hba` cerrado la detiene.

**Mecanismo en capas (implementado y verificado):**
1. `pg_hba` cerrado (`host all all all reject`) en un archivo del volumen del nodo, recargado y **comprobado con una conexión nueva** que debe fallar con "pg_hba.conf rejects" (una negativa por DNS o tiempo agotado no cuenta).
2. `default_transaction_read_only` global (ALTER SYSTEM, recarga y SHOW como tres operaciones separadas con comprobación de efecto), sesiones de la aplicación terminadas y verificadas.
3. Intentos reales de escritura directa con conexión nueva **y** con intento de anular el solo-lectura; ambos deben ser rechazados por `pg_hba`.
4. Detención del contenedor; confirmado = no corre y no acepta escrituras.
5. **Arranque cerrado**: al reiniciar, el nodo consulta al witness y solo abre el acceso de red si lo declara escritor (o época 0); con el witness caído o con otro escritor arranca cerrado. El estado persiste en el volumen.
6. Guardia secundaria del monitor: si un nodo no escritor acepta conexiones de la aplicación, lo cierra y lo verifica (se detecta y cierra en < 1 s en B4).
7. Si cualquier verificación falla o no se puede confirmar: se registra `estado_inseguro` y **no se promueve** (B3 con fallo inyectado).

## 6. Resultados medidos
Todas las comprobaciones de las corridas finales pasaron: **A+E 8/8, B 13/13, C 10/10 y D 5/5** (C2b y D1–D4; la corrida de la que proceden también repitió C y pasó 15/15). Los fallos intermedios y sus causas están en §8.

### Etapa A · replicación y límites (A1–A6)
- Convergencia tras escrituras de la aplicación: 0,18 s; 14 de 14 tablas idénticas.
- **Secuencias no se replican**: `event_seats_id_seq` en 40 en `pg-aws` y 1 en `pg-oci`; una inserción en el seguidor sin ajustar choca con `Key (id)=(1) already exists`. La promoción ajusta todas las secuencias (+1000).
- **DDL no se replica**: un `ALTER TABLE` solo en el origen detiene la replicación (`missing replicated column: "lab_x"`); reanuda 4,0 s tras aplicarlo en el seguidor.
- **Conflicto**: una fila local en el seguidor con la misma clave bloquea todos los cambios posteriores (`conflict=insert_exists`) hasta resolverlo a mano (2,1 s tras resolver).
- **Retraso**: carga de 12 472 tps durante 10 s → retraso máximo 561 KiB (0,004 s en `pg_stat_replication`), alcanza al origen 0,19 s después; una transacción de 300 000 filas es visible en el seguidor 1,18 s después del COMMIT; una transacción abierta **no es visible** en el seguidor (0 filas) hasta el COMMIT (y se perdería si el origen cae antes). Son cifras de una sola máquina.

### Etapa B · fallas seguras (13/13; corrida final)
| Escenario | Resultado medido |
|---|---|
| B0 dos cambios de escritor con la misma época | uno 200, otro 409 |
| B1 witness caído + escritor caído | sin promoción, el seguidor rechaza escrituras reales, HAProxy-BD sin escritor; el monitor siguió vivo (sin excepciones), se promovió 2,8 s después de volver el witness (época persistida) y la aplicación escribió 0,8 s después |
| B2 partición del escritor | RTO de BD (caída → lease) 3,4 s; aislamiento en línea verificado por efecto antes de abrir el destino; la escritura por la pasarela de `app-aws` llegó a `pg-oci`; el antiguo, reiniciado **sin monitor**, arrancó cerrado y rechazó 25 de 25 intentos de escritura real (también con anulación) |
| B3 aislamiento no confirmable (inyectado) | sin promoción, `estado_inseguro` registrado, sin servicio; al sanar la partición el lease volvió al escritor **original** en 0,8 s y el servicio en 1,1 s |
| B4 solo-lectura por GUC | anulable por la app; con `pg_hba` cerrado, rechazada; la guardia del monitor cierra un nodo expuesto |
| B5 witness caído y reinicio del escritor | arranca cerrado (falla cerrada); con el witness vivo que lo declara escritor, abre |

**Sobre "doble escritura".** En B1, B2 y B3 hubo 0 de 41, 40 y 26 muestras con ambos nodos aceptando escrituras reales. El muestreo es de ~3 por segundo y nodo y secuencial: es "**sin doble escritura observada**", no "ausencia de split-brain demostrada". Los volcados están en `escritores-B*.json`.

### Etapa C · caída del escritor con carga de reservas (8 clientes, ~1 400 escrituras y ~300 lecturas por corrida)
| Métrica (corrida final) | natural 1 | natural 2 | natural 3 | con retraso inducido (3 s) |
|---|---|---|---|---|
| **RTO escritura** (orden de caída → primera escritura válida tras el último error) | 3,82 s | 3,08 s | 4,39 s | 3,16 s |
| **RTO lectura** | 3,63 s | 3,19 s | 4,43 s | 3,22 s |
| Detección (primera sonda fallida) | 0,59 s | 0,19 s | 0,55 s | 0,08 s |
| Aislamiento confirmado | 1,71 s | 1,39 s | 1,93 s | 1,14 s |
| Lease otorgado a pg-oci | 2,76 s | 2,35 s | 3,57 s | 2,13 s |
| HAProxy-BD enruta a pg-oci | 3,78 s | 3,18 s | 4,34 s | 3,16 s |
| Errores HTTP escritura / lectura (todos **503**) | 56 / 38 | 56 / 38 | 64 / 46 | 59 / 41 |
| Retraso de replicación máximo antes de caer | 34 KiB | 60 KiB | 66 KiB | 538 KiB |
| **Reservas confirmadas al cliente y PERDIDAS** | **0** | **0** | **0** | **328** (ventana 3,0 s) |
| Huérfanas en la antigua primaria / inciertas / duplicado lógico | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 0 / 0 | 328 / 0 / 0 |
| Sobreventa o duplicados (`reserved_count` = suma de cantidades; 1 reserva por clave) | ninguno | ninguno | ninguno | ninguno |

- Hubo **0 reservas perdidas en 3 corridas naturales**: eso es una observación (n = 3), **no un RPO cero**; el caso con retraso inducido demuestra que una caída con retraso pierde exactamente las reservas confirmadas dentro de la ventana de retraso. Las huérfanas se obtuvieron arrancando la antigua primaria cerrada y comparando claves primarias; las confirmadas perdidas coinciden con las huérfanas confirmadas.
- **Transacciones inciertas** (confirmadas en la antigua primaria, no replicadas y sin respuesta al cliente): 0 en las cuatro corridas de C1; el caso de C2b las provoca a propósito.
- **C2a** caída tras confirmar y antes de responder, con la reserva ya replicada: el cliente no recibió respuesta y reintentó con la misma clave; la respuesta válida fue **200 con la misma reserva** (`replayed: true`), 4,5 s después de la caída; 1 sola reserva.
- **C2b** (etapa D, sin replicar): la reserva original se pierde con la primaria; la misma clave creó **otra** reserva (201) tras 3,7 s; el cliente nunca vio dos, pero queda una **huérfana** en la antigua primaria con `idempotency_key` repetida en la nueva: **duplicado lógico**, detectado en el rescate. No se re-aplica automáticamente.

### Etapa D · failback manual seguro (D1–D4)
1. **D1** la antigua primaria reiniciada a mano arranca cerrada (witness: otro escritor), HAProxy-BD no le envía tráfico y 20 de 20 intentos de escritura real directa (con y sin anulación) se rechazan.
2. **D2** con la antigua primaria arrancada en solo lectura se exportan **fuera de Docker** las filas que solo existen allí (`huerfanas-pg-aws-*.json`: 1 reserva y 1 entrada) y se detecta el duplicado lógico por clave de idempotencia. Solo después se permite reconstruirla.
3. **D3** reconstrucción como seguidora (se descarta la ranura obsoleta, se vacía, se resuscribe con copia inicial): conteos idénticos, rechaza escrituras de la app, el escritor sigue siendo `pg-oci`; **0 promociones automáticas** hacia la antigua.
4. **D4** retorno planificado a `pg-aws` con tráfico: drenado, conteos iguales, aislamiento verificado, lease con época nueva (5); interrupción aproximada de 3,9 s (62 intentos correctos y 32 con error en el periodo), sin huérfanas en la que se retira; luego se reconstruye `pg-oci` como seguidora.

**Procedimiento manual de failback:** (1) no devolver tráfico a la antigua; (2) arrancarla en solo lectura y exportar huérfanas fuera de Docker; (3) decidir caso a caso con negocio (duplicados lógicos); (4) reconstruirla como seguidora; (5) esperar conteos iguales y retraso ~0; (6) retorno planificado con drenado y época nueva; (7) verificar con escrituras reales que solo un nodo escribe. Nunca automático.

## 7. Qué falta para AWS Academy ↔ OCI reales
- Red entre sitios (VPN/peering), puertos y la RDS privada accesible para la suscripción; certificados con nombre estable del gateway de BD y `sslmode=verify-full` (la app lo exige; HAProxy en modo TCP reenvía el TLS tal cual si ambos nodos tienen certificado para ese nombre).
- RDS: grupo de parámetros propio con `rds.logical_replication` (**requiere reinicio**), rol con `rds_replication`, control de ranuras para no llenar el disco, secuencias y DDL fuera de la replicación.
- Witness en un **tercer** sitio (p. ej. Azure) con quórum real de sondas desde fuera de ambos sitios; el controlador debe ser redundante (aquí es un proceso único).
- Gateways redundantes en dos sitios; DNS/balanceador externo hacia ellos.
- Secretos idénticos en ambos sitios (`TICKET_ENCRYPTION_KEY`, `SECURITY_HASH_KEY`).
- Mediciones repetidas sobre infraestructura real; ninguna cifra de este informe es transferible.

## 8. Fallos y correcciones durante las pruebas (todo documentado)
| Fallo | Causa | Estado |
|---|---|---|
| B3 no recuperaba el lease al sanar la partición | `docker network connect` sin `--alias` pierde el nombre DNS del servicio (era de la prueba); confirmado al corregirlo | Corregido |
| B1 falló en una corrida | el monitor moría por una llamada al witness sin proteger (causa muy probable; la salida de error no se conservaba) | Corregido: excepciones registradas y conservadas, pruebas fallan si el monitor muere |
| B2 doble escritura | `ALTER SYSTEM` en bloque de transacción sin revisar el resultado | Corregido: fencing en capas con verificación por efecto |
| Verificación de aislamiento "vacía" en partición | el nombre DNS no resolvía y la negativa se tomaba por rechazo | Corregido: loopback y exigencia del mensaje de `pg_hba` |
| Varias comprobaciones de la prueba | log truncado, carrera con el monitor, referencia de tiempo, relojes monotónico/pared en la métrica de lectura | Corregido; la primera corrida de C/D con la métrica de lectura defectuosa se conserva como `…corrida-previa-metrica-lectura-defectuosa` |
| 503 transitorios al registrar el primer usuario tras recrear el laboratorio (dos corridas) | carrera de arranque (lease/HAProxy); sin causa más precisa | Mitigado con espera y reintentos; una incidencia aislada quedó registrada en una corrida |

## 9. El aislamiento de Docker es solo una simulación
Los mecanismos de §5 usan privilegios que en la nube **no existen o son distintos**: `docker stop`/`network disconnect` como plano de control con credenciales totales; `pg_hba` y `ALTER SYSTEM` bajo nuestro control; arranque cerrado propio. En **AWS RDS**: no se controla `pg_hba` ni el arranque; no hay `ALTER SYSTEM` (se usan grupos de parámetros); aislar requiere permisos de AWS (grupos de seguridad, `rds:StopDBInstance`, modificar la instancia) que el rol de AWS Academy puede no tener; y **si AWS entero cae, no se puede llamar a su API para aislar nada**, de modo que el antiguo escritor podría reaparecer con datos obsoletos. Esto exige un diseño específico AWS–OCI, aún sin hacer ni verificar, por ejemplo: la RDS accesible solo desde un gateway nuestro que consulta al witness antes de abrir (falla cerrada), sin ruta directa para otros clientes; fencing a nivel de red por defecto cerrado; permisos reales de IAM/Academy confirmados; y pruebas de reaparición del escritor sobre esa arquitectura. Hasta entonces, nada de lo medido aquí autoriza a afirmar continuidad entre AWS y OCI.

## 10. Índice de evidencias (`docs/entregable3/evidencias/`)
`repl-20261110-A-y-E-corrida-final`, `…-B-corrida6-final-13de13`, `…-C-corrida-final` (líneas de tiempo, huérfanas, eventos), `…-D-y-C2-corrida-final` (huérfanas exportadas), y las corridas fallidas `…-B-corrida3`, `…-B-corrida4-fencing`, `…-B-corrida5-fencing`, `…-CD-corrida-previa-metrica-lectura-defectuosa`. Cada carpeta incluye `consola.txt`, `resultados-*.json`, `eventos-*.jsonl` con `stdout`/`stderr` del monitor y `escritores-*.json`.
