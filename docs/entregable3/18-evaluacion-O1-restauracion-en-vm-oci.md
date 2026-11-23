# Entregable 3 · Evaluación de O1: restaurar el respaldo del 11-nov en una VM de OCI (11-nov-2026)

> **Fechas clave:** RDS se reinicia sola hacia el **18-nov-2026 ~16:52 UTC** · AWS Academy expira ≈ **26-nov-2026**. **O1 no necesita AWS** (el respaldo ya está en OCI): no hay que encender RDS ni EC2.
> **Estado: SOLO ANÁLISIS. Nada se ejecutó**: no se consultó ninguna nube (se usó la evidencia local del 23-oct y la consulta de solo lectura del 10-nov), no se creó ni modificó nada en OCI/Azure/AWS, Docker intacto, sin commits ni push. **Requiere tu autorización explícita antes de cualquier operación en la nube.**

## 1. Qué dice la rúbrica y qué toca O1
Texto de los niveles (hoja «Rúbrica» del archivo original, pesos de la columna «Puntaje»):
| Criterio (peso) | Excelente | Bueno | En proceso | ¿Lo toca O1? |
|---|---|---|---|---|
| **10 Arquitectura AWS–OCI / multicloud (1,5)** | «Existe integración real, segura y demostrable entre proveedores» | «Integración funcional limitada» | «Recursos en ambas nubes pero integración débil» | **Sí (marginal)** |
| **9 Backup, RTO/RPO y recuperación (1,5)** | «Estrategia documentada y recuperación probada exitosamente» | «Backup funcional con recuperación parcialmente validada» | «Solo existe backup» | **Sí (refuerza)** |
| **12 Pruebas técnicas (1,0)** | «…recuperación con evidencias» (entre otras pruebas) | «Ejecuta mayoría de pruebas» | «Pruebas incompletas» | Sí (refuerza) |
| **4 Cómputo, almacenamiento y BD (1,5)** | «correctamente seleccionados, configurados e integrados» | «pequeñas deficiencias» | «Integración parcial» | Marginal |
| 6 HA y escalabilidad (1,5) · 5 Seguridad (2,5) · 3 Redes (2,0) · 2 Arquitectura (2,0) | — | — | — | **No** (O1 no crea HA entre nubes, ni red, ni cambia la seguridad) |
En juego: **5,5 puntos de peso** en criterios que O1 «toca», pero la evidencia actual ya sostiene 9 como «Excelente (defendible)» y 10 como «Bueno». O1 **no** crea integración «viva» (réplica, failover): no puede mover el 10 a «Excelente» por sí sola.

## 2. Qué evidencia nueva aportaría exactamente
1. **Restauración del respaldo del 11-nov *dentro de OCI*** (hoy solo se restauró en Docker local): cadena completa con el mismo artefacto — AWS (11-nov) → bucket de OCI → VM de OCI con PostgreSQL 18 → huella 10/10 frente a la línea base `rds-20261111T164610Z` (136 reservas, 26 usuarios).
2. **Cierre de la limitación de la capa B/C** del informe: pasaría de «restaurado en Docker local; en OCI solo con el respaldo del 23-oct» a «restaurado en OCI con el respaldo vigente».
3. **Repetibilidad:** una segunda ejecución del procedimiento, ya corregido, con **tiempos medidos de punta a punta** (la restauración de datos del 23-oct tardó 2 h 15 min por fallos; el RTO «limpio» de 15–25 min **nunca se midió**).
4. (Solo con E5) humo de la aplicación sobre esos datos (14 pruebas) — requiere el paquete cifrado de claves de aplicación del 23-oct.
**No aporta:** failover, HA, red privada entre nubes, RPO programado, respaldos periódicos, ni mejora de seguridad.

## 3. Qué aporta repetirlo si ya hubo despliegue en OCI el 23-oct
El 23-oct se demostró la **capacidad** (restauración 24 s, aplicación 14/14, 32 min 42 s con fallos). Repetirlo demuestra **repetibilidad con datos actuales** y valida los arreglos hechos (orden de instalación, regla de salida del Bastion, comprobación previa). Es un refuerzo, no una evidencia nueva de capacidad: un evaluador que ya vea el 23-oct puede considerarlo redundante. Riesgo: si falla, se documenta el fallo (transparente, pero no suma).

## 4. ¿Cabe en Always Free (A1 o Micro)? — sin asumir capacidad
| Opción | Cuota (consulta del 10-nov) | Capacidad real | Alcance |
|---|---|---|---|
| **Micro** `VM.Standard.E2.1.Micro` (Always Free, 1 GB) | 2 disponibles, 0 usadas | **Sin verificar hoy.** Funcionó el 23-oct (restauración de datos 24 s; PostgreSQL 18 con swap, instalación 8–18 min) | **Solo datos** (sin aplicación: la RAM no alcanza) |
| **A1.Flex** (Always Free) | 41 núcleos / 277 GB | **OUT_OF_HOST_CAPACITY el 23-oct** en 1/2/4 OCPU; hoy desconocido | Datos + aplicación si hubiera capacidad |
| **E5.Flex** 1 OCPU/8 GB (de pago con crédito del Free Trial) | 13 núcleos / 208 GB | Disponible el 23-oct | Datos + aplicación |
La capacidad de hosts solo se conoce **intentando crear** (el «informe de capacidad» es una operación de creación; no se ejecutó). Intentar A1/Micro cuesta 0 USD si falla. La plantilla ya exige `allow_trial_paid_shape = true` (por defecto `false`) para usar E5.
**Incógnita crítica:** estado y saldo del **Free Trial de OCI** — no se pueden leer con el perfil (se ven en la consola: Facturación → Suscripción). La cuenta base se creó ≈ 22–23-oct; **si** el trial dura 30 días, vencería ≈ 21–22-nov (**no verificado**). Con la cuenta sin actualizar a Pago por uso no hay cargos a tarjeta, pero las formas de pago dejarían de poder usarse; las Always Free seguirían.

## 5. Costo máximo si solo vale E5 (prueba de 30–60 min)
Tarifas públicas guardadas en `08-recuperacion-aplicacion-oci.md` (no verificadas con la facturación de OCI):
| Concepto | Costo |
|---|---|
| E5: 1 OCPU 0,03/h + 8 GB × 0,002/GB·h | 0,046 USD/h |
| Volumen de arranque 50 GB (10 VPU/GB) | ≈ 0,0029 USD/h |
| **Total** | **≈ 0,049 USD/h** |
| **60 min de ejecución** | **≈ 0,05 USD** |
| Techo recomendado para toda la sesión (≈ 90 min con creación y destrucción) | **≈ 0,08 USD** (límite duro: 0,15 USD ≈ 3 h) |
| Si se olvidara destruir | ≈ 1,17 USD/día (≈ 8,2 USD/semana): por eso la destrucción es parte del procedimiento |
| Red: IP pública | **ninguna** (VM privada con Bastion); egreso ≈ KB; Bastion y Service Gateway sin cargo |
| Referencia | 23-oct: ≈ 1 h 10 min ⇒ ≈ 0,06 USD |
Con Micro o A1 Always Free: **0 USD**. Se paga con créditos del Free Trial, no con tarjeta (cuenta sin actualizar).

## 6. Procedimiento (NO ejecutado; cada operación en la nube requiere tu autorización)
**Preparación local previa — ✔ HECHA el 11-nov (informe 19, L-01…L-05):** `run-from-mac.sh` y `app-recovery.sh` ya aceptan `BASELINE_KEY/FILE`, verifican los RPM por hash y tienen swap y `known_hosts` por ejecución. Texto original de la preparación: `scripts/multicloud/oci-drill/run-from-mac.sh` tenía **fijos** el archivo y la clave de línea base (`docs/multicloud/baseline-restauracion.json` / `0008-estado-20261022`): con el respaldo del 11-nov (huella distinta) **fallaría**. Hay que parametrizarlos (`BASELINE_FILE`, `BASELINE_KEY`) y probar en Docker/offline; actualizar `oci-recovery.tfvars` (`bastion_client_cidr` con tu IP pública actual /32) y confirmar los RPM verificados en `work/oci-drill/rpms` (3 SHA-256 de `07`).
| Etapa | Acción | Compuerta |
|---|---|---|
| **G0** | Comprobaciones (solo lectura): sin instancias ni volúmenes huérfanos; los 2 objetos del 11-nov presentes en el bucket; **Free Trial/saldo visto por ti en la consola**; decidir forma y techo de costo | Sin trial/saldo claros → NO E5 |
| **G1** | `terraform plan` guardado de `infra/oci` con `create_recovery_vm = true` (solo VM, Bastion y reglas; **0 destrucciones**) | Revisar el plan contigo |
| **G2** | `terraform apply` del plan guardado (marca de tiempo T0) | Autorización explícita |
| **G3** | Sesión de Bastion (/32, 1 h) + SSH; swap; instalación de PostgreSQL 18.6 con los RPM verificados | ≤ 25 min o cancelar |
| **G4** | `run-from-mac.sh` (descarga con el perfil de carga → SHA-256 → descifrado **en tu Mac** con tu frase → restauración en la base `drill` → huella) | Tú introduces la frase |
| **G5** | Validación: huella **10/10** igual a la línea base nueva; hash del volcado en claro = manifiesto; sin volcados en claro en la VM; sin TCP 5432 | Cualquier diferencia → parar |
| **G6** | Evidencias: tiempos por fase, huella, versiones, salida de verificación por API antes y después | Sin claves, OCID ni datos personales |
| **G7** | **Destrucción completa:** `terraform plan -destroy` revisado → `apply` (`preserve_boot_volume=false`) → verificación por API (ver §8) | Siempre, aunque falle algo |

## 7. Plan de cancelación
| Disparador | Acción |
|---|---|
| `Out of host capacity` (Micro/A1) | Máximo 2 intentos separados 5 min; si persiste: destruir lo parcial, registrar y **no pasar a E5 sin nueva autorización** |
| Trial vencido, saldo bajo o forma de pago no disponible | Parar; sin E5 |
| `apply` > 10 min o recursos parciales | `terraform destroy` del plan revisado y verificación |
| SSH por Bastion falla > 20 min | Destruir (la causa del 23-oct —lista de seguridad vacía— ya está corregida con la regla de salida TCP/22, así que un fallo sería nuevo) |
| Instalación de PostgreSQL > 25 min o huella distinta | Parar, conservar la evidencia del fallo y destruir |
| Sesión > 60 min (E5) o 90 min (Micro/A1) desde T0, o cualquier cargo/aviso inesperado | **Destruir primero, depurar después** |

## 8. Cómo evitar que quede algo cobrando
- **Recursos que pueden cobrar:** instancias, volúmenes de arranque/bloque y sus copias, IP públicas reservadas, NAT, balanceadores, imágenes personalizadas. **Ninguno de los tres últimos se crea.** Bastion, Service Gateway y el bucket (≈ 0,1 MB) no cobran.
- **Destrucción:** `terraform destroy` con plan revisado y `preserve_boot_volume = false`; el estado queda solo con la base (VCN, subred, SGW, bucket, usuario de carga).
- **Verificación independiente por API (solo lectura), el mismo día:** `compute instance list` (todas `TERMINATED`), `bv boot-volume list` y `bv volume list` (ninguno disponible), `bastion list` (`DELETED`), `network public-ip list` (0), `compute instance-console-history` (no deja recurso). Repetir al día siguiente.
- **Control en la consola:** Facturación → Análisis de costos (el perfil no lee el consumo) y, opcionalmente, un **presupuesto de 1 USD con alerta** (es una escritura: solo con tu autorización).
- **Plan B ante dudas:** si no se logra verificar la destrucción por API, parar y consultarte antes de cerrar la sesión.

## 9. Comparación de escenarios (sin prometer nota)
| | **A. Entregar con la evidencia actual** | **B. O1-lite (Micro/A1 Always Free, solo datos)** | **C. O1 con E5 (datos + aplicación)** |
|---|---|---|---|
| Costo en nube | 0 | **0 USD** | ≈ 0,05–0,08 USD de crédito del trial (techo 0,15) |
| Tiempo tuyo | 0 | ≈ 1,5–2,5 h (+ preparación local de ≈ 1 h) | ≈ 2,5–4 h |
| Evidencia nueva | Ninguna | Restauración del respaldo **vigente** en OCI (huella 10/10) + tiempos medidos | Lo anterior + humo de la aplicación 14/14 con datos actuales |
| Criterios que mejoran | — | 9 y 12 (refuerzo de evidencia); 10 (cierra «restaurado solo en Docker») | 4, 9, 10, 12 (refuerzo) |
| Cambia el nivel de la rúbrica | Se mantiene lo valorado: 9 «Excelente defendible», 10 «Bueno» | Posible refuerzo de 9; **el 10 no pasa a «Excelente»** por no haber integración viva | Igual que B; el 10 sigue dependiendo de cómo el profesor valore respaldo + recuperación |
| Riesgos | Ninguno nuevo | Capacidad no verificada, instalación lenta en 1 GB, Bastion, olvidos de limpieza, exposición de la frase | Además: trial/saldo, costo |
| Compite con | — | La defensa y el documento final | Ídem y con más tiempo |
Mejora concreta y honesta: **cerrar la limitación «restaurado en OCI solo con el respaldo antiguo»** y tener una medición limpia del RTO de datos. No mejora los criterios de mayor peso (5, 2, 3).

## 10. Recomendación
1. **Prioridad 1 (ya):** cerrar el documento final y la defensa (datos de portada, correcciones del informe 17, captura del saldo de Academy, ensayo): afectan 2, 3, 5, 11, 13 y 14 — los criterios de mayor peso — sin costo ni riesgo.
2. **Ejecutar O1 solo como «O1-lite» (Micro o A1, Always Free, solo datos), no con E5**, y solo **después** del paso 1 y **con margen antes de la entrega**: cuesta 0 USD, cierra una limitación real y es fácil de limpiar. No recomiendo E5 (de pago, depende del trial y no añade criterios de peso).
3. **Antes de decidir** necesito de ti: (a) estado del Free Trial y fecha de vencimiento en la consola; (b) la fecha de entrega; (c) tu IP pública actual /32 para el Bastion en el momento de ejecutar; (d) disponibilidad de ≈ 2 h seguidas.
4. Si la fecha de entrega es muy próxima o el trial vence antes, **no ejecutar O1**: la evidencia actual (respaldo real AWS→OCI, restauración local con la clave de OCI, despliegue en OCI del 23-oct) es coherente y está declarada con sus límites.

**Qué haré solo con tu autorización:** (i) parametrizar `run-from-mac.sh` y probarlo offline (sin nube); (ii) G0 y plan de Terraform guardado; (iii) la ejecución G2–G7.
