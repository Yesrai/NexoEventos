# Entregable 3 · Auditoría técnica y backlog (Fase 1) — 11-nov-2026

> **Fechas clave:** RDS se reinicia sola hacia el **18-nov-2026 ~16:52 UTC** · AWS Academy expira ≈ **26-nov-2026** · Free Trial de OCI: vencimiento **sin verificar** (consola).
> **Alcance de la Fase 1:** auditoría y correcciones **locales**. No se encendió AWS/RDS/EC2, no se creó ni modificó nada en OCI/Azure, no se usó E5 ni servicios de pago, no se ejecutó Terraform `apply/destroy`, no se tocó `nexo-repl-lab` ni sus volúmenes (los 11 contenedores existentes verificados intactos antes y después), sin commits ni push, sin instalar dependencias, sin secretos en logs.
> **Regla de este documento:** un criterio no se da por completo por estar documentado; cada fila indica la evidencia **verificable** que existe hoy y la que falta.

## 1. Qué se corrigió realmente (y qué pruebas pasaron)
Línea base local previa (sin cambios de código): backend **97/97** pruebas, **51** comprobaciones de IaC, **26** de coherencia, `terraform validate` OK en `infra/oci`, `infra/aws-v2`, `infra/azure`, `infra/aws-recovery`, `bash -n` y `py_compile` sin errores en todos los scripts.
| ID | Defecto verificado | Corrección | Prueba (local, aislada) |
|---|---|---|---|
| L-01 | `run-from-mac.sh` tenía **fijos** el archivo y la clave de línea base (`0008-estado-20261022`): con el respaldo del 11-nov (136 reservas, 26 usuarios) habría fallado **después** de pedir la frase de paso | `BASELINE_KEY` **obligatoria** (sin valor por defecto), `BASELINE_FILE`, `BUCKET`, `OCI_PROFILE`, `OUT_BASE`; comprobaciones locales **antes** de usar red o pedir la frase; `PREFLIGHT_ONLY=1`; comprueba que el manifiesto corresponde a `BUNDLE` (código 3) | `test-run-from-mac.sh`: **14/14** (éxito con la línea base nueva; clave inexistente → código 2 sin llamadas a oci/ssh; sin `BASELINE_KEY` → rechazo; línea base distinta → 1; clave privada equivocada → 7; archivo alterado → se detiene antes de tocar la VM; manifiesto de otro respaldo → 3; sin RPM → 2; RPM alterado → 2; `PREFLIGHT_ONLY` sin red; ninguna salida con claves) |
| L-02 | `app-recovery.sh` con la misma línea base fija | Mismo mecanismo (`BASELINE_KEY/FILE`, preflight, `PREFLIGHT_ONLY`) | `PREFLIGHT_ONLY` real con el respaldo del 11-nov: código 0; clave mala: código 2; sin clave: rechazo; `bash -n` OK |
| L-03 | `known_hosts` global: cada VM nueva llega por el mismo `127.0.0.1:$LPORT` con otra clave de host → la **2.ª ejecución fallaría** («HOST IDENTIFICATION HAS CHANGED») | `UserKnownHostsFile` **por ejecución** en ambos scripts | Caso de `test-run-from-mac.sh` verifica el argumento en la llamada a `ssh` |
| L-04 | Los RPM de PostgreSQL no se verificaban por hash ni en la Mac ni en la VM (cadena de suministro) | `rpm-checksums.sha256` (3 SHA-256 fijados el 23-oct) + `verify-rpms.sh` (también detecta RPM sobrantes); se ejecuta en el preflight local y en `install-postgres.sh` antes de instalar | `test-oci-drill-helpers.sh`: RPM reales OK; 1 byte alterado, ausente y sobrante se detectan; directorio inexistente → 2 |
| L-05 | El **swap** de la VM Micro no estaba codificado (el 23-oct `dnf` agotó 1 GB de RAM); era un paso manual no reproducible | `ensure-swap.sh` idempotente, llamado por `install-postgres.sh` | `DRY_RUN` con `/proc/meminfo` simulado: RAM 486 MB planea `dd/mkswap/swapon/fstab`; RAM 7,6 GB no crea nada; no crea archivos en `DRY_RUN` |
| L-06 | `db-backup-cms.py` abortaba por línea base fija (corregido el 11-nov) | Huella antes/después sin valores fijos + `linea-base-restauracion.json` | `test_db_backup_cms.py` 9/9 y la ventana AWS real del 11-nov |
| L-07 | Comparación de huella duplicada en 3 sitios, sin pruebas | `compare-fingerprint.py` (`--check`, comparación, códigos 0/1/2) | 6 casos manuales + los de `test-run-from-mac.sh` (descubrió y corregí un defecto propio de argumentos en `--check`) |
**Evidencias:** `docs/entregable3/evidencias/{prueba-local-run-from-mac,prueba-local-oci-drill-helpers}-20261111.txt` y los `*-cambios-20261111.diff` (originales conservados en `work/*.orig-20261111`). Un fallo de **mi propio** simulador de pruebas (casaba `remote-restore.sh` dentro de otro comando y esperaba stdin) colgó la primera ejecución; se detuvo, se limpiaron los artefactos de la prueba (base y directorio temporal propios) y se corrigió.

## 2. Hallazgos de la auditoría
### 2.1 Errores de implementación (existe el componente, pero falla o es incorrecto)
| ID | Hallazgo | Estado |
|---|---|---|
| E-01…E-07 | L-01 a L-07 anteriores | **Corregidos** |
| E-08 | **CORREGIDO el 11-nov (informes 14, 15 y 17).** El informe 15 decía «verify-full solo en local»; la evidencia real `docs/evidencias/20261104-fase-c-d-v2/resultado.md` muestra **verify-full desplegado en las 2 instancias de V2 (TLS 1.3, y con otra CA la conexión falla)** y `backend/app/database.py` lo exige para bases remotas | **Corregido** en los Markdown (D-07). El Word/PDF de `informe-final/` entregado antes **todavía contiene la frase antigua**: hay que regenerarlo |
| E-09 | Las pruebas del 4-nov de autohealing y failover de RDS en V2 (`20261104-b2-…`, `20261104-d2-…`) **terminaron abortadas/parciales** (`both_healthy_again_at: null`, `restore_error`, «tiempo máximo excedido»; `primary_az_changed_at: null`) | **No citarlas como prueba completa**; repetir (C-07) |
| E-10 | `deploy/duckdns/update.sh` actualiza con `ip=` vacío (autodetecta la IP de quien llama): **no sirve para un cambio de DNS a otra nube** | **Resuelto en herramienta nueva** `scripts/multicloud/dns_switch.py` (B-12; el script original se conserva) |
| E-11 | `oci_core_images.ol9` toma la **imagen más reciente** al aplicar: un cambio de imagen puede romper la dependencia `rhel9.8` de los RPM | Pendiente (B-15) |
| E-12 | Sin automatización de la **sesión de Bastion y el túnel** (pasos manuales no registrados) | Pendiente (B-16) |
| E-13 | `app-recovery.sh` descarga las ruedas con `pip download` (**requiere Internet** en la Mac) y `npm run build` (versión de Node no fijada en el script) | Pendiente (B-17) |
| E-14 | La clave privada de AWS (`work/recovery-keys/…`) está **sin frase** y descifra los 10 respaldos CMS de AWS | Pendiente (S-01) |

### 2.2 Componentes todavía NO construidos (no son errores: no existen)
| Componente | Estado real | Evidencia |
|---|---|---|
| Lease/testigo con ETag-CAS en OCI/Azure | **Solo simulado en Docker** (`witness.py`); en nube: no existe | `scripts/repl-lab`, informes 04–06 |
| Compuerta de escritura que falla cerrada en producción | **No existe**: el backend no tiene modo solo-lectura, lease ni fencing (búsqueda en `backend/app`: 0 coincidencias) | `grep` del 11-nov |
| Cambio de DNS entre nubes | **No existe** (E-10) | `deploy/duckdns/update.sh` |
| Punto de entrada público en OCI (IGW/IP/NSG 443/TLS) | **No existe**; subred privada | `infra/oci`, `oci-consulta-solo-lectura-v4` |
| Respaldos periódicos AWS→OCI (RPO medido) | **No existe**: un respaldo puntual por ventana manual | informes 11–13 |
| Réplica lógica hacia OCI desde RDS | **No viable sin verificar**: `rds.logical_replication` es estático (reinicio + grupo de parámetros propio); permisos de Academy sin verificar | informe 07 |
| Monitoreo del entorno OCI y alarmas de frescura del respaldo | **No existe** (solo exportación de métricas) | `scripts/observability/export-oci-metrics.py` |
| Orquestador de failover (sonda → decisión → fencing → promoción → DNS) | **No existe** (en Docker hay un monitor de laboratorio) | informes 04–06 |

## 3. Backlog técnico exhaustivo
Criterios y pesos: 1 (1,0) · 2 (2,0) · 3 (2,0) · 4 (1,5) · 5 (2,5) · 6 (1,5) · 7 (1,0) · 8 (1,5) · 9 (1,5) · 10 (1,5) · 11 (0,5) · 12 (1,0) · 13 (0,5) · 14 (0,5). **P0** = imprescindible/mayor peso, **P1** = alto valor, **P2** = opcional. **☁** = requiere autorización cloud posterior.
### 3.1 Correcciones de documentación (locales; esperan tu confirmación)
| ID | Problema | Criterio | Pri | Solución | Prueba de aceptación | Dep. | Costo |
|---|---|---|---|---|---|---|---|
| D-01 | Azure: «disparada y resuelta en 17 min 54 s» (es solo el disparo) | 7 | P0 | Redactar con disparo 17 min 54 s y resolución 15:02:59 Z | Cifras = `azure/20261028-vm/resultado.md` | — | 0 |
| D-02 | 37/37 es V1 pública, no V2 | 12 | P0 | Distinguir 37/37 (V1) y 15/15 (V2) | Cada cifra con su ruta | — | 0 |
| D-03 | «Multicloud activo» sugiere funcionamiento | 2, 10 | P0 | «Failover multicloud (diseño y simulación)» | `grep` sin «multicloud activo» | — | 0 |
| D-04 | Despliegue OCI sin precisar el respaldo | 4, 10 | P0 | Añadir «con el respaldo del 23-oct» | Texto presente | — | 0 |
| D-05 | RTO Docker 3,1–4,4 s vs 3,3–3,8 s | 6, 12 | P1 | Unificar con la fuente de cada rango | Rango por informe citado | — | 0 |
| D-06 | «8 min 6 s» sin contexto | 6 | P1 | «alarma de CPU alta a los 8 min 6 s de iniciar la carga» | Texto presente | — | 0 |
| D-07 ✔ implementado (§8) | «verify-full solo en local» es **incorrecto** | **5** | **P0** | Citar `20261104-fase-c-d-v2/resultado.md` (V2, TLS 1.3, CA distinta falla) | Cita presente y verificable | — | 0 |
| D-08 | Evidencias del 3–6-nov no usadas: alarmas V1/V2, SNS→correo, detección real de CPU, lifecycle S3, ACM | 5, 6, 7 | P1 | Incorporarlas con etiqueta de entorno y límites | Cada cita enlaza a su `resultado.md` | — | 0 |
| D-09 | Autohealing/failover V2 del 4-nov abortados | 6 | P0 | Declararlos parciales; repetir en C-07 | Texto de límite presente | — | 0 |
| D-10 | Portada incompleta, Anexo C, índice estático | 13, 14 | P0 | Ver informe 17 (modo `--entrega`) | Versión de entrega sin marcas | datos tuyos | 0 |

### 3.2 Construcción local (sin nube; se puede probar offline)
| ID | Tarea | Criterio | Pri | Solución | Prueba de aceptación (medible) | Dep. | Costo |
|---|---|---|---|---|---|---|---|
| B-10 ✔ implementado (§8) | Cliente de **lease con ETag-CAS** (adquirir, renovar, ceder, expirar) con almacén de objetos simulado | 6, 10 | **P0** | Biblioteca pequeña + almacén falso con `If-Match/If-None-Match` | pytest: 2 escritores simultáneos → exactamente 1 gana (1000 iteraciones); lease expirado se toma; renovación tardía pierde; 0 dobles escritores | — | 0 |
| B-11 ✔ implementado (§8) | **Compuerta de escritura** en el backend (modo solo-lectura fail-closed controlado por el lease) | 5, 6, 10 | **P0** | Middleware: sin lease válido/fresco → 503 en métodos de escritura; lecturas siguen | pytest: sin lease → todo POST/PUT/DELETE = 503; con lease → normal; lease caduca → 503 en ≤ TTL; no rompe las 97 pruebas | B-10 | 0 |
| B-12 ✔ implementado (§8) | **Cambio de DNS** explícito (DuckDNS `ip=<IP>`, `--dry-run`, verificación por consulta DNS) | 6, 10 | P0 | `scripts/multicloud/dns_switch.py` con validación de IP y salida sin token | Pruebas con servidor HTTP/DNS falso: IP válida OK; IP privada o inválida rechazada; el token nunca se imprime | — | 0 |
| B-13 ✔ implementado (§8) | **Orquestador de failover** (sonda → decisión → fencing → promoción → DNS) con modo simulación | 6, 9, 12 | P0 | Máquina de estados con pasos idempotentes y registro | Simulación: 100 corridas con fallos inyectados → 0 transiciones inseguras; estados `unknown` → no promueve | B-10..B-12 | 0 |
| B-14 | **Respaldo periódico** (timer en la EC2: volcado → CMS con el certificado de OCI → PAR de escritura) | 9, 10 | P0 | Scripts + prueba con extremos falsos; unidad systemd | Prueba: ciclo completo con objetos falsos < N s; reintento ante fallo; nombre único; sin texto plano en disco | — | 0 |
| B-15 | **Imagen fijada** y cloud-init (swap, SO) en `infra/oci` | 8 | P1 | Variable `image_id` y `user_data` | `terraform validate` + `plan` offline sin cambios no deseados | — | 0 |
| B-16 | **Sesión de Bastion y túnel** automatizados con limpieza | 8, 9 | P1 | `bastion-tunnel.sh` con simulador de `oci` | Prueba: crea/abre/cierra; ante error limpia la sesión | — | 0 |
| B-17 ✔ implementado (§8) | **Verificador de destrucción** (solo lectura) y tope de tiempo | 11 | **P0** | `verify-oci-clean.sh`: falla si queda instancia/volumen/Bastion/IP | Simulador: con recurso residual → código ≠ 0; limpio → 0 | — | 0 |
| B-18 | Reproducibilidad de `app-recovery.sh` (ruedas en caché por hash del lock, Node fijado) | 8 | P1 | Caché local de ruedas y comprobación de versión | Preflight detecta Node/ruedas | — | 0 |
| B-19 | Integrar todas las pruebas nuevas en `scripts/check-local.sh` y el CI | 8, 12 | P1 | Añadir los 3 test scripts | CI/`check-local` ejecuta y pasa | — | 0 |
| B-20 | Alarma de **frescura del respaldo** (edad del último objeto > umbral) | 7, 9 | P1 | Script local + unidad systemd | Prueba con reloj simulado | B-14 | 0 |

### 3.3 Seguridad
| ID | Problema | Criterio | Pri | Solución | Prueba de aceptación | Costo |
|---|---|---|---|---|---|---|
| S-01 | Clave privada de AWS sin frase en `work/` | 5 | P0 | Re-cifrar con frase o moverla a la copia cifrada y quitar la copia en claro; ajustar scripts | `openssl pkey` sin frase falla; scripts piden la frase; respaldo cifrado verificado | 0 |
| S-02 | CloudTrail solo como historial | 5 | P1 | **☁** Trail de eventos de gestión (S3 pequeño) o captura honesta del historial | Trail activo y evento reciente visible, o captura con la limitación declarada | ≈ 0–0,1 USD/mes |
| S-03 | Custodia única de la clave de OCI | 5, 9 | P1 | Procedimiento de custodia alternativa (sobre sellado/segunda copia) | Restauración con la copia de custodia | 0 |
| S-04 | Retención del bucket de OCI (no borrar) | 5, 9 | P2 | **☁** Regla de retención | Intento de borrado denegado | 0 |
| S-05 | Rotación/destrucción de claves tras Academy | 5 | P1 | Runbook | Lista de claves con fecha de rotación | 0 |

### 3.4 Construcción y pruebas que requieren nube (autorización por separado; costos estimados)
| ID | Tarea | Criterio | Pri | Prueba de aceptación | Dep. | Costo estimado |
|---|---|---|---|---|---|---|
| C-01 | **O1-lite** restaurar el respaldo del 11-nov en VM Always Free (Micro/A1) | 9, 10, 12 | P1 | Huella 10/10 igual a `rds-20261111T164610Z`; tiempos por fase; verificador de limpieza = 0 | L-01…L-05, B-17 | 0 USD (cuota ✓; capacidad sin verificar) |
| C-02 | Despliegue de la aplicación en OCI con datos actuales | 4, 10, 12 | P2 | 14/14 humo; huella 10/10 | C-01, claves de aplicación | ≈ 0,05–0,08 USD (E5 con crédito del trial) o 0 (A1 si hay capacidad) — **no se usa E5 sin tu autorización** |
| C-03 | Punto de entrada público en OCI (IGW, NSG 443, TLS) | 3, 10 | P2 | Escaneo: solo 443 abierto; HTTPS válido | C-02 | 0 (IP pública efímera) |
| C-04 | **Ventana AWS**: 3 respaldos periódicos reales con RPO medido | 9 | P0 | RPO = intervalo + transferencia medido en ≥ 3 ciclos; PAR creado y revocado | B-14, PAR en OCI | ≈ 0,07 USD/h × ≈ 1 h |
| C-05 | **Simulacro de failover real AWS→OCI** | 6, 10, 12 | P2 | RTO medido, 0 doble escritura (B-11), DNS verificado | B-10..B-13, C-02, C-03 | ≈ 0,2–0,3 USD; riesgo alto |
| C-06 | Capturas y cierre de evidencias (CloudTrail, EC2, Azure) | 5, 7 | P0 | Capturas con fecha/hora | — | ≈ 0,02–0,05 USD si se abre el laboratorio |
| C-07 | Repetir autohealing y failover de RDS en V2 (reconstruir ALB con `apply` revisado) | 6 | P0 | Instancias reemplazadas y 2 destinos `healthy`; 0 5xx fuera de la ventana medida; failover completo con `primary_az_changed_at` | ALB reconstruido | ≈ 0,15 USD/h × ≈ 1,5 h |
| C-08 | Alarmas y topic de notificación en OCI | 7 | P1 | Alarma de frescura dispara y notifica | B-20 | 0 (nivel gratuito, no verificado) |
| C-09 | Sondas de Zabbix hacia OCI | 7 | P2 | Disponibilidad medida de la entrada de OCI | C-03 | VM de Azure (≈ 0,1 USD/h; sin verificar) |
| C-10 | Estado del Free Trial de OCI | 10, 11 | P0 | Captura de Facturación → Suscripción | — | 0 (acción tuya) |
| C-11 | Segunda copia cifrada fuera del Mac | 9 | P0 | Hash de la copia = original | — | 0 (acción tuya) |

## 4. Estado verificable de cada criterio (no se declara completo lo solo documentado)
| # | Criterio (peso) | Evidencia técnica verificable HOY | Falta para respaldarlo con prueba | Backlog |
|---|---|---|---|---|
| 1 (1,0) | Análisis | Informes E1/E2/E3 | RTO/RPO medidos | D-10 |
| 2 (2,0) | Arquitectura | Terraform validado en 4 raíces; diagramas | Diagrama final coherente con lo real | D-03 |
| 3 (2,0) | Redes | VPC/VCN/Azure por IaC y auditorías | Entrada pública OCI (si se hace failover) y escaneo de puertos | C-03 |
| 4 (1,5) | Cómputo/BD | RDS Multi-AZ, V2, OCI temporal 23-oct | Repetir con datos actuales | C-01, C-02 |
| 5 (2,5) | Seguridad | CMS dual, no-sobrescritura, verify-full en V2 (4-nov), IaC 51 comprobaciones | CloudTrail, clave AWS sin frase, compuerta de escritura | D-07, S-01, S-02, B-11 |
| 6 (1,5) | HA | V2 15/15 (6-nov), escalado, Multi-AZ ≈ 14 s | Autohealing/failover V2 completos; HA entre nubes inexistente | C-07, B-10..B-13, C-05 |
| 7 (1,0) | Monitoreo | Alarmas V1/V2, SNS→correo (4-nov), Azure | Monitoreo de OCI y de respaldo | C-08, B-20 |
| 8 (1,5) | IaC | 4 raíces validan; destroy dirigido con plan guardado | Imagen fijada y automatización de la sesión | B-15, B-16, B-19 |
| 9 (1,5) | Backup/RTO/RPO | Respaldo AWS→OCI, restauración local 8–9 s, OCI 23-oct | RPO periódico medido; restauración vigente en OCI | C-04, C-01 |
| 10 (1,5) | Multicloud | Respaldo+recuperación+despliegue temporal reales | Integración «viva»: nada construido | B-10..B-14, C-02..C-05 |
| 11 (0,5) | Costos | Tarifas y ahorros aplicados | Saldo real | C-10 |
| 12 (1,0) | Pruebas | backend 97/97; locales: run-from-mac 14/14, helpers 8/8, db-backup 9/9, pipeline 16/16; cloud: V2 15/15, OCI 14/14 | Matriz única con enlaces; pruebas de conectividad | B-19 |
| 13 (0,5) | Documentación | Informes 00–19 | Versión final | D-10 |
| 14 (0,5) | Defensa | Guion | Ensayo | — |

## 5. Orden de ejecución por dependencias (mayor peso primero)
1. **Ya hecho (Fase 1):** L-01…L-07 y auditoría. **Siguiente, local y sin costo:** D-01…D-10 (con tu confirmación), **B-17** (control de costos primero), **B-10 → B-11 → B-12 → B-13** (cierra el núcleo de los criterios 6 y 10 sin nube), **B-14 → B-20** (RPO), **S-01**, **B-15, B-16, B-18, B-19**.
2. **Tuyas, sin costo:** C-10, C-11, datos de portada.
3. **Cloud gratuito/muy barato (una ventana consolidada antes del 18-nov 16:52 UTC):** C-06 + C-04 (AWS ≈ 0,1–0,2 USD) y C-01 (OCI 0 USD). Si se hace después del 18-nov, RDS ya estará encendida (≈ 1 USD/día).
4. **Cloud de coste bajo, con autorización explícita y tope:** C-07 (≈ 0,25 USD), C-02 (E5 solo si no hay A1; techo 0,15 USD).
5. **Solo si sobra tiempo y crédito:** C-03, C-05, C-08, C-09.
6. **Cierre:** informe final con evidencias reales, ensayo de defensa.

## 6. Pruebas de aceptación por componente (medibles)
| Componente | Disponibilidad | Consistencia | Recuperación | Seguridad | Monitoreo | Costos |
|---|---|---|---|---|---|---|
| Respaldo AWS→OCI | ≥ 3 ciclos seguidos sin fallo | SHA-256 por salto; huella antes = después | RPO = intervalo + transferencia **medido** | Sin texto plano; sin sobrescribir; PAR con expiración | Frescura < umbral | ≤ 0,15 USD por ventana |
| Restauración (local/OCI) | — | Huella 10/10 | RTO por fase medido; objetivo ≤ 25 min en VM pequeña | Frase solo en terminal; limpieza | — | 0 (Always Free) |
| Lease/compuerta (B-10/B-11) | Lease renovado ≥ 99 % dentro del TTL en simulación | **0 dobles escritores** en 1000 corridas; 503 sin lease | — | Falla cerrada | Estado visible | 0 |
| Failover (C-05, opcional) | RTO medido de la sonda a la primera escritura válida | 0 reservas duplicadas; huérfanas contadas | Retorno planificado verificado | Fencing demostrado en cada paso | Alerta en ≤ N min | ≤ 0,3 USD |
| V2 AWS (C-07) | 2 destinos `healthy`; 0 5xx fuera de la ventana | Huella idéntica tras el failover | Reemplazo de instancia medido | `verify-full` activo | Alarma → correo medida | ≈ 0,25 USD |
| Costos | Verificador de limpieza (B-17) = 0 recursos | — | — | — | — | Cada ventana ≤ tope; consulta de destrucción el mismo día y al siguiente |

## 7. Qué necesita autorización cloud posterior (nada se ejecutó)
1. **C-01 / C-04 / C-06** en una ventana consolidada (AWS y OCI), o por separado. 2. **C-07** (reconstruir el ALB con `apply` revisado). 3. **C-02/C-03/C-05** (solo con tope de costo y E5 únicamente si lo autorizas). 4. **S-02, S-04, C-08** (escrituras pequeñas en AWS/OCI). 5. La verificación de capacidad de OCI solo se obtiene al **intentar crear** la VM.

## 8. Resultados de B-17 y B-10 a B-13 (implementación local, 11-nov-2026)
Restricciones respetadas: sin AWS/RDS/EC2, sin recursos OCI/Azure nuevos, sin E5, sin Terraform `apply/destroy`, sin cambios en DNS público, sin failover real, sin escrituras cloud, `nexo-repl-lab` y sus 11 contenedores intactos (verificado), sin dependencias instaladas, sin commits ni push. **Producción no cambia por defecto:** la compuerta solo actúa con `WRITE_GATE_MODE=enforce`; con el valor por defecto `off` el backend se comporta exactamente como antes (prueba explícita + las 97 pruebas originales siguen pasando).
| ID | Qué se implementó (archivos) | Pruebas ejecutadas (todas locales, simuladas) | Riesgos pendientes | Qué falta validar REALMENTE entre nubes |
|---|---|---|---|---|
| **B-17** Verificador de residuos y costos | `scripts/multicloud/verify_clean.py`: solo lectura; fuentes `--fixture` (simulada) o `--live` con **lista blanca** de comandos (`oci … list`, `aws … describe-*`); **fail-closed** (0 limpio · 1 residual · 2 no verificable); IDs enmascarados; costo/h, acumulado, proyección y tope de tiempo; línea base de recursos esperados (RDS/EC2 detenidos) | `tests/test_verify_clean.py`: **25/25** (limpio; E5 en marcha con costo 0,046 USD/h y tope excedido; TERMINATING no es limpio; volumen huérfano; Bastion; IP reservada; estados desconocidos y datos ausentes → 2; AWS: ALB/NAT/EIP/volumen/RDS; CLI ausente o token caducado → 2 sin filtrar secretos; la lista blanca rechaza `terminate/delete/run-instances/stop`; el código no contiene llamadas de escritura) | Tarifas «sin verificar» marcadas como tales; el formato real de la CLI de OCI se asumió (lista vacía = sin salida); no cubre todos los tipos de recurso (p. ej. imágenes personalizadas, copias de volumen) | Ejecutarlo `--live` una vez contra OCI y AWS reales (solo lectura) y comparar con la consola; necesita `--oci-compartment/--oci-ad` |
| **B-10** Lease con CAS | `backend/app/failover/{store,lease}.py`: contrato `read/create/replace` condicional; almacenes `InMemoryStore`, `FileStore` (flock, procesos reales) y `OciCliStore` (CLI de OCI); **autoprueba** `verify_store_semantics` (el cliente RECHAZA almacenes no verificados); lease con época, plazo medido **desde el envío**, toma por **observación** (sin comparar relojes entre máquinas), resultados inciertos resueltos leyendo, `init_lease` separado (el camino de ejecución nunca usa `create`) | `tests/test_lease.py`: **22/22**: autoprueba pasa en los almacenes de referencia y **detecta un almacén sin CAS**; 200 hilos en `create` → 1 ganador; 24 hilos tomando el mismo ETag → 1 ganador; **8 procesos × 8 rondas** con `FileStore` → 1 ganador; expiración, pérdida sin resurrección, liberación, resultados inciertos; configuración insegura rechazada; **simulación de 300+300+150 corridas** con deriva de reloj, latencia, pausas, particiones y respuestas perdidas: **0 solapes con margen ≥ ρ·ttl; con margen menor aparecen solapes** (ρ=20 %: margen 0 → 76/300, 1 s → 7/300, 2,9 s → 0/300) | La simulación **encontró y corregí un defecto real** (comparar plazos con `or 0.0` fallaba con relojes de origen negativo). **No hay garantía absoluta**: supuestos S1–S3 (CAS atómico, deriva ≤ ρ, pausa entre comprobación y escritura < margen). El adaptador de OCI **no está verificado** contra OCI real; `--no-overwrite` podría no ser atómico (por eso `create` solo se usa en la inicialización manual). Un lease en el MISMO bucket versionado de respaldos **no sirve**: el usuario de carga no puede sobrescribir | (1) `verify_store_semantics` contra el **bucket real** (OCI o Azure) con una carrera real de ≥ 16 escritores; (2) latencias y fallos reales de la API; (3) bucket **sin versionado** y **principal distinto** con permisos de sobrescritura solo sobre el objeto del lease; (4) decidir dónde vive el lease: en OCI, si OCI cae el primario de AWS **deja de escribir** aunque esté sano (consistencia sobre disponibilidad); un tercer dominio (Azure Blob admite If-Match/If-None-Match) evita acoplar el lease a uno de los dos |
| **B-11** Compuerta de escritura | `backend/app/failover/gate.py` + 4 líneas en `app/main.py` (diff en evidencias): **fail-closed** en 3 capas (HTTP: métodos no seguros → 503; **BD: toda sentencia de escritura se rechaza sin lease válido**; **recomprobación justo antes del COMMIT**); guardián con hilo; rol `primary`/`standby` (el standby solo adquiere con archivo de promoción); `/write-gate` solo informa; configuración por entorno, inválida → no arranca; `file` prohibido con `APP_ENV=production` | `tests/test_write_gate.py`: **26/26**: apagada por defecto sin cambios; sin lease → 503 y 0 filas; con lease → 201; **expiración** exacta (9,9 s sí, 10,1 s no); **pérdida** del lease; sentencia de escritura rechazada **aunque se salte HTTP**; **commit abortado si el lease caduca durante la petición (nada persiste)**; **dos instancias sobre la misma BD con 30 peticiones concurrentes: solo el titular escribe (15×201 / 15×503)** y el traspaso es limpio con un hueco sin escritor; almacén caído → nadie escribe tras la expiración; standby con/sin promoción; guardián con hilo (renueva y, si muere, cierra); 15 casos de clasificación SQL. **Backend completo: 145/145** (97 originales + 22 + 26) | Pausa del proceso **entre** la recomprobación del commit y el envío efectivo; la clasificación SQL es conservadora (puede dar falsos positivos como `FOR UPDATE`); las lecturas siguen en un sitio sin lease (pueden ser obsoletas); **AWS y OCI no comparten BD**: el lease impide dos escritores simultáneos pero NO reconcilia datos divergentes ni evita pérdida de reservas confirmadas tras un failover desde un respaldo (RPO = antigüedad del respaldo) | Probar la compuerta **desplegada** (V2 en AWS y la VM de OCI) con tráfico real; medir el tiempo de cierre ante una partición real; comprobar que ningún camino de escritura queda fuera (p. ej. tareas externas que escriban en la BD sin pasar por la app) |
| **B-12** Cambio de DNS | `scripts/multicloud/dns_switch.py` (`plan`/`apply`/`rollback`/`verify`; **no ejecutado**): IP pública IPv4 estricta, lista blanca de dominios y destinos, `NEXO_ALLOW_DNS_CHANGE=YES` + frase exacta, intervalo mínimo, bloqueo contra cambios simultáneos, IP anterior guardada para revertir, espera de propagación en varios resolvedores, TTL supuesto vs observado, token solo por entorno/archivo 0600 y nunca impreso, auditoría sin secretos | `tests/test_dns_switch.py`: **14/14** contra un «DuckDNS» y resolvedores simulados: validación de ~20 IP inválidas; paquete DNS (compresión, truncado, NXDOMAIN); plan sin llamadas; rechazo por falta de entorno/frase/lista blanca; apply correcto (estado 0600, auditoría, token ausente de toda salida); intervalo mínimo y «sin cambios»; KO/caída → estado intacto; rollback; verify con resolvedor atrasado → 1; 2 cambios simultáneos → 1 solo; `--api-base` solo en pruebas | DuckDNS admite **una sola IP por registro** (no hay DNS con comprobación de salud): el TTL y el caché de clientes fijan un piso al RTO; el registro actual de `nexoeventos-demo.duckdns.org` y el TTL real **no se consultaron**; el token de DuckDNS: custodia sin verificar | Un cambio **real** del registro hacia una IP de prueba y vuelta (con autorización), midiendo la propagación con resolvedores reales; confirmar el TTL que sirve DuckDNS; validar el certificado TLS en el destino |
| **B-13** Orquestador de failover | `scripts/multicloud/failover/{orchestrator,sim}.py`: 7 etapas explícitas (PRECHECK, DECIDE, PREPARE_STANDBY, FENCE_AND_ACQUIRE, ENABLE_STANDBY, SWITCH_DNS, VERIFY), con precondiciones, idempotencia (estado en archivo por `run_id`), cancelación segura en cada frontera, hooks de caída; **sin operaciones cloud**: `Adapters` base lanza `NotAuthorized`; CLI `run` rechaza sin entorno/frase y sin adaptadores reales | `tests/test_failover_orchestrator.py`: **19/19**: primario caído → promueve con 1 solo escritor y DNS después; **falso positivo (sondas ciegas, primario vivo) → NO promueve: lo impide el lease**; sondas discrepantes y huella distinta → no actúa; **cancelación en cada una de las 7 fronteras**; **caída antes y después del efecto en cada etapa y reanudación sin duplicar** (el DNS se aplica 1 vez); repetir una ejecución terminada = sin efectos; abortada no se reanuda; el primario que vuelve no recupera la escritura; **400 escenarios aleatorios (cancelaciones, caídas, deriva, particiones): 0 dobles escritores y 0 cambios de DNS prematuros** (65 DONE, 226 ABORTED, 109 CANCELLED, 127 reanudadas) | **Límite demostrado:** si el sitio anterior **no aplica la compuerta** (despliegue incorrecto), el lease no lo detiene: el orquestador lo **detecta** en VERIFY (`old_can_write`), libera el lease nuevo y exige intervención humana — **no se declara seguro el failover**. Las sondas simuladas no reproducen redes reales; la promoción real de datos (restauración en OCI) y la verificación de huella son adaptadores **aún inexistentes** | Construir y probar los adaptadores reales (restauración, sondas externas desde Azure, `dns_switch`, estado del standby) y ejecutar un **simulacro real** AWS→OCI con autorización; medir RTO real; verificar que el sitio anterior queda cerrado por efecto |

### 8.1 Conclusión sobre la seguridad del failover
**NO se declara seguro el failover entre nubes.** Lo que sí está demostrado (en simulación y en pruebas locales con procesos reales): el diseño del lease evita dos escritores válidos a la vez **bajo supuestos explícitos**, falla cerrado y su margen mínimo coincide con la teoría (margen ≥ ρ·ttl). Lo que no puede garantizarse con este diseño: (a) pausas de proceso entre comprobación y escritura mayores que el margen, (b) deriva de reloj mayor que la supuesta, (c) un almacén cuyas escrituras condicionales no sean atómicas (por eso hay autoprueba obligatoria), (d) un sitio anterior sin compuerta, (e) datos divergentes o perdidos entre bases distintas (no hay capa de datos compartida: la época no se puede exigir en la BD).

### 8.2 Hallazgos de diseño que cambian el plan cloud
1. El bucket de respaldos `nexoeventos-recovery` es **versionado** y su usuario **no puede sobrescribir**: el lease necesita **otro bucket sin versionado y otro principal** (permiso de sobrescritura solo sobre un objeto).
2. La CLI de OCI usada antes **no tenía `--if-none-match`**; `--no-overwrite` podría no ser atómico: por eso el camino de ejecución solo usa `If-Match` (soportado por la API de PutObject) y `create` queda para la inicialización manual.
3. Documentación oficial consultada (11-nov): OCI PutObject admite `If-Match`/`If-None-Match: *` y es fuertemente consistente (Standard); S3 y Azure Blob también admiten ambos. **No se verificó el comportamiento real de nuestras cuentas.**
4. El lease debe vivir en un dominio de fallo **distinto** de AWS y, idealmente, de OCI; si vive en OCI y OCI cae, el escritor de AWS se cierra aunque esté sano (decisión consciente: consistencia sobre disponibilidad).

### 8.3 Evidencias (en `docs/entregable3/evidencias/`)
`prueba-local-b17-verify-clean-20261111.txt` (25/25) · `prueba-local-lease-y-compuerta-20261111.txt` (48/48) · `simulacion-lease-margen-20261111.txt` · `prueba-local-b12-dns-switch-20261111.txt` (14/14) · `prueba-local-b13-orquestador-20261111.txt` (19/19) · `main-py-cambios-b11-20261111.diff` · y las de la Fase 1. Backend completo 145/145; originales en `work/*.orig-20261111`.

### 8.4 Siguiente (requiere autorización cloud; nada se ejecutó)
(1) autoprueba `verify_store_semantics` + carrera de 16 escritores en un bucket de lease real (OCI/Azure): escritura pequeña; (2) `verify_clean.py --live` (solo lectura) contra OCI y AWS; (3) cambio de DNS real de prueba y reversión; (4) adaptadores reales y simulacro AWS→OCI (E5 solo si lo autorizas); (5) ✔ regenerar el Word/PDF con la corrección de `verify-full` (hecho en el cierre de etapa, §9).

## 9. Cierre de etapa (11-nov-2026, noche): estado final y lista de tareas
**Pruebas finales de esta sesión (todas verdes, locales):** backend **151/151** (97 originales + lease 22 + compuerta 26 + «cero cambios por defecto» 6) · `verify_clean` **27** · `dns_switch` **14** · orquestador **19** (400 escenarios aleatorios) · autoprueba del lease con CLI simulada **10** · `run-from-mac` **14** · helpers **8** · IaC **51** · coherencia **26** · `terraform validate` OK en las 4 raíces · `bash -n` y `py_compile` OK. Los 11 contenedores de `nexo-repl-lab` intactos antes y después.
**Consulta real de solo lectura (11-nov 19:15 UTC):** `verify_clean.py --live` → **OCI: 0 recursos residuales/pendientes**; **AWS: no verificable** (las credenciales del laboratorio responden pero EC2/RDS devuelven `UnauthorizedOperation/AccessDenied`: el laboratorio no está activo; no se inició Academy). El estado de EC2/RDS/ALB de AWS sigue siendo el último verificado el 11-nov 16:52 UTC (EC2 detenida, RDS detenida, 0 ALB). Evidencia: `verify-clean-live-solo-lectura-20261111.txt`. **No se interpretó la consulta fallida como ausencia de recursos.**
**Garantía «cero cambios por defecto» (verificada):** `WRITE_GATE_MODE` por defecto `off` (la compuerta no existe en la app), ningún archivo de `deploy/`, `ansible/`, `infra/`, `.github/` ni scripts operativos referencia la compuerta, el orquestador ni `dns_switch`; importar los módulos no inicia hilos ni red; `run` del orquestador y `apply` del DNS rechazan sin variable de entorno **y** frase exacta (y sin adaptadores reales no hay forma de operar). **Cambio de IaC:** el módulo `infra/oci/modules/lease` está apagado (`create_lease_test = false`) y **no se aplicó**; `terraform init` actualizó `infra/oci/.terraform.lock.hcl` (hash del proveedor `oci` 9.13.0; contenido generado, reversible con `git checkout`).
### 9.1 Completado
| Tarea | Entorno | Criterios |
|---|---|---|
| Respaldo AWS→OCI del 11-nov, restauración con la clave de OCI, parada de RDS, ALB eliminado, instantánea manual, copia cifrada local verificada | **AWS + OCI reales / Docker** | 9, 10, 11, 4, 8, 5 |
| L-01…L-07 (scripts de OCI parametrizados y probados), B-17, B-10, B-11, B-12, B-13, pruebas de «cero cambios por defecto» | **Local / simulado** | 6, 10, 5, 8, 12, 11 |
| Corrección de la afirmación de `verify-full` (informes 14, 15, 17) | Documentación | 5 |
| Procedimientos A (autoprueba del lease), B (DNS) y C (simulacro) + `lease_selftest.py` + módulo Terraform apagado | **Preparado, NO ejecutado** | 6, 10, 5, 12 |
| Informes 00–20, Word/PDF regenerados (borrador con marcadores de portada) | Documentación | 13, 14, 2, 3 |
### 9.2 Validado solo localmente (no en la nube)
Lease/compuerta/DNS/orquestador (simulación y procesos locales); adaptador `OciCliStore` (CLI simulada); `lease_selftest.py` (CLI simulada); scripts de recuperación de OCI con un contenedor desechable; verificador de residuos con CLI simulada y una consulta real de solo lectura a OCI.
### 9.3 Pendiente (requiere autorización cloud o decisión tuya)
| ID | Tarea | Criterios | Costo estimado |
|---|---|---|---|
| A | Autoprueba real del lease (crear bucket+identidad en OCI, ejecutar, limpiar) — informe 20 §A | 6, 10, 5, 12 | 0 USD |
| B | Cambio de DNS real en un subdominio de pruebas y reversión — informe 20 §B | 6, 10, 12 | 0 USD |
| V | `verify_clean.py --live` de AWS con el laboratorio activo (solo lectura) y confirmar saldo | 11 | 0 USD (abrir Academy puede reencender la EC2) |
| O1 | Restaurar el respaldo del 11-nov en una VM de OCI (Micro/A1; E5 solo con autorización) | 9, 10, 4, 12 | 0 (Always Free) o ≈ 0,05–0,10 USD |
| C-06/C-07 | Capturas (CloudTrail, EC2, Azure) y repetir autohealing/failover de RDS en V2 | 5, 7, 6 | ≈ 0,05–0,3 USD |
| P4/P5 | Construir los **adaptadores reales** y desplegar la compuerta (decidir cómo repartir las credenciales del lease) | 6, 10 | 0 (código local) |
| C | Simulacro real AWS→OCI — informe 20 §C (solo tras A, B, O1, P4, P5) | 6, 10, 9, 12, 7, 5 | ≈ 0,25–0,5 USD |
| S-01…S-05 | Seguridad: clave de AWS sin frase, CloudTrail, custodia de la clave de OCI, retención del bucket, rotación | 5 | ≈ 0 |
| D-01…D-06, D-08…D-10 | Correcciones de redacción del informe 17 §7 (esperan tu confirmación) y datos de portada | 13, 14 | 0 |
### 9.4 Bloqueado
| Bloqueo | Qué lo causa | Qué lo desbloquea |
|---|---|---|
| A, B, C, O1 | Sin autorización cloud | Tu autorización con las frases de cada procedimiento |
| V (AWS) | Laboratorio de Academy no activo | Que lo inicies tú; riesgo: reencender la EC2 |
| C | Faltan P1…P7 (adaptadores reales, compuerta desplegada, VM y entrada pública en OCI, dominio de pruebas) | Completar A, B, O1 y P4/P5 |
| Entrega final | Datos de portada (institución, curso, autores, docente, fecha de entrega) y confirmación de D-xx | Datos tuyos; modo `--entrega` del generador |
| Cifras de costo | Saldo de Academy y estado/vencimiento del Free Trial de OCI sin verificar | Capturas de las consolas |
| Respaldo fuera del Mac | Acción tuya | Copiar `~/NexoEventos-copias-cifradas/` a un disco externo |
### 9.5 Recursos o costos NO verificados
Saldo real de Academy (solo consta el consumo declarado de 21,70 de 50 USD hacia el 10-nov); estado y vencimiento del Free Trial de OCI; estado actual de EC2/RDS/ALB de AWS (último verificado 11-nov 16:52 UTC); tarifas marcadas «sin verificar» en `verify_clean.py`; consumo real de OCI (≈ 0 estimado, no visto en el panel); TTL real de DuckDNS y registro actual del dominio.

## 10. Resumen para retomar el proyecto
**Dónde estamos.** Los datos están protegidos fuera de AWS (respaldo cifrado en OCI, restaurable, verificado) y el gasto de AWS está contenido (ALB eliminado, RDS y EC2 detenidas). La integración «viva» entre nubes (failover) **no existe en la nube**: hay componentes locales probados en simulación. **RDS se reinicia sola hacia el 18-nov ~16:52 UTC; Academy expira ≈ 26-nov.**
**Documentos clave:** `15-informe-consolidado…` (+ `informe-final/*.docx|pdf`), `16-guion-defensa…`, `19-backlog…` (este), `20-procedimientos-cloud-pendientes…`.
**Las tres primeras acciones al retomar (en este orden):**
1. **Sin costo, tuyas:** ver en las consolas el **saldo de Academy** y el **estado/vencimiento del Free Trial de OCI**, confirmar la **fecha de entrega** y los **datos de portada**. Con eso se decide cuánto cloud cabe.
2. **Autorizar el procedimiento A** (autoprueba del lease: bucket e identidad de pruebas en OCI, 0 USD): es el cimiento de todo el failover y, si falla, ahorra construir el resto.
3. **Planificar una sola ventana de AWS antes del 18-nov 16:52 UTC** (verificación de AWS, capturas y, si procede, el procedimiento B): cada hora con RDS encendida cuesta ≈ 0,04 USD y después del 18 se enciende sola.
**Qué NO hacer:** presentar el failover como validado; activar `WRITE_GATE_MODE=enforce` en un entorno real sin pasar por A y C; usar el dominio de producción en pruebas de DNS.

## 9. S-01 — preparación (16-nov-2026; NADA modificado)
**Qué es la clave:** `work/recovery-keys/preupdate-20261008t0113z/recovery-private.pem` (RSA 3072, **sin frase**; corresponde al certificado público `recovery-public.crt`, comprobado por hash de clave pública). Es la clave **CMS de descifrado de respaldos de AWS**. **No es una clave SSH:** no hay SSH en AWS (acceso por SSM) y Ansible usa `amazon.aws.aws_ssm`; Terraform no la usa.
**Quién la usa:** (1) `scripts/cloud/db-backup-cms.py` (verifica que el respaldo descifra; `-inkey` sin `-passin`); (2) descifrado manual/`restore-drill.sh --key` de los respaldos CMS de AWS (`-inkey` sin `-passin` y con `2>/dev/null`: con frase pediría una contraseña oculta y fallaría de forma confusa); (3) documentación 11, 12, 14, 16. **No la usan:** `backup_cycle.py` (solo el certificado público de OCI), el timer, la clave de OCI (`~/.nexoeventos/recovery-oci/`) ni `prepare-recovery-keys.sh` (otra clave).
**Efecto de protegerla:** el certificado público y los CMS existentes **no cambian** (misma clave, solo cambia cómo se guarda); lo único que se rompe son los scripts anteriores si no aceptan frase.
**Procedimiento propuesto (requiere tu autorización para los pasos 2 y 6):**
1. Copia cifrada externa de la clave actual (C-11) y verificación del hash. 2. Crear `recovery-private.enc.pem` **junto a la original** (`openssl pkey -aes-256-cbc`, la frase se escribe en la terminal, nunca en argumentos). 3. Validar: huella de clave pública = certificado; descifrar los CMS locales (`…preupdate-20261019t0628z.cms`, `…alembic0008-20261023T150946Z.cms`) con la clave nueva y comparar el SHA-256 del texto plano con el obtenido con la original; frase errónea ⇒ falla. 4. Adaptar `db-backup-cms.py` y `restore-drill.sh` para aceptar `--passin` (`env:`/`fd:`), sin `2>/dev/null` que oculte el error, con pruebas locales (frase correcta/errónea/ausente sin quedarse colgado). 5. Probar de extremo a extremo en local (restore-drill con la clave nueva). 6. Solo entonces, con tu autorización: archivar la original en un almacén cifrado y retirarla de `work/`. 7. Custodia de la frase (gestor de contraseñas + copia alterna) y prueba de restauración desde la custodia (S-03).
**Recuperación / reversión:** la original no se toca hasta el paso 6; si algo falla se descarta el archivo `.enc.pem`. No requiere sesión de Academy (todo local); los 10 respaldos CMS de AWS que están en S3 se perderán con Academy ≈ 26-nov: descargar y verificar los que importen **antes** (lectura de S3, en la próxima ventana).
