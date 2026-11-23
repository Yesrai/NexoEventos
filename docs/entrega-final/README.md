# Entrega final — NexoEventos (T8, entrega académica)

Paquete documental final del proyecto. **Idioma:** español. **Fecha de corte:** 23-nov-2026 (UTC).
**Regla del paquete:** todo resultado está rotulado **REAL** (nube con expediente), **LOCAL** (equipo, sin nube), **DISEÑO** (no ejecutado) o **ESTIMADO** (cálculo). Nada local se presenta como real. Sin secretos, correos personales, IP privadas sensibles, tokens ni URL de PAR.

## Estado en una línea

T1 PASS 12/12 · T2 PASS 13/13 · T3 PASS 19/19 (tras 2 FAIL) · T4 PASS 18/18 · T5 PASS 9/9 con 6 EC2 (tras FAIL 95,21 % con 2 EC2 y un aborto por SCP) · **T6 BLOCKED** (failover AWS→OCI no ejecutado; capacidades solo en local) · **T7 LOCAL** (NexoOps probado en local; despliegue A1 en Azure PARCIAL/INCOMPLETO, ver `../evidencias/A1-20261123-cierre.md`) · **T8** documentación entregada (limpieza cloud NOT_TESTED).

## Contenido

| Archivo | Qué contiene |
|---|---|
| [`01-MATRIZ-RUBRICA.md`](01-MATRIZ-RUBRICA.md) | 14 criterios de la rúbrica: peso, evidencia, nivel defendible, límites, acción pendiente |
| [`02-INFORME-TECNICO-FINAL.md`](02-INFORME-TECNICO-FINAL.md) · [`02-INFORME-TECNICO-FINAL.docx`](02-INFORME-TECNICO-FINAL.docx) | informe técnico completo (Word generado con python-docx; las figuras usan los PNG) |
| [`03-INVENTARIO-AWS-OCI-AZURE.md`](03-INVENTARIO-AWS-OCI-AZURE.md) | inventario por nube con su último estado verificado y fuente |
| [`04-PROCEDIMIENTOS.md`](04-PROCEDIMIENTOS.md) | procedimientos operativos, secuencia de respaldo fresco de T6, flujo T6, cierre T8 |
| [`05-RTO-RPO.md`](05-RTO-RPO.md) | solo tiempos medidos; separa recuperación en AWS, reconstrucción en OCI y failover (no medido) |
| [`06-COSTOS.md`](06-COSTOS.md) | costos estimados por ventana, dimensionamiento, optimizaciones |
| [`07-LIMITACIONES-Y-PENDIENTES.md`](07-LIMITACIONES-Y-PENDIENTES.md) | clasificación PASS/FAIL/BLOCKED/NOT_TESTED/LOCAL |
| [`08-INDICE-EVIDENCIAS.md`](08-INDICE-EVIDENCIAS.md) | índice de evidencias T1–T7 con rutas |
| [`09-GUION-EXPOSICION.md`](09-GUION-EXPOSICION.md) | guion de ≈ 15 min y preguntas probables |
| [`10-DEMO.md`](10-DEMO.md) | demo local reproducible (comandos exactos) |
| [`presentacion/NexoEventos-Final.pptx`](presentacion/NexoEventos-Final.pptx) | 22 diapositivas editables con notas del orador |
| [`diagramas/`](diagramas/) | F1 arquitectura multicloud · F2 red por proveedor · F3 seguridad y recuperación · F4 flujo T6 previsto (SVG editables + PNG) |
| [`graficos/`](graficos/) | disponibilidad T5 por intento, detección/recuperación T5, tiempos medidos T1–T5, costos por ventana (PNG) |

### Diagramas y gráficos

| Archivo SVG | PNG |
|---|---|
| `diagramas/01-arquitectura-multicloud.svg` | `diagramas/01-arquitectura-multicloud.png` |
| `diagramas/02-red-por-proveedor.svg` | `diagramas/02-red-por-proveedor.png` |
| `diagramas/03-seguridad-y-recuperacion.svg` | `diagramas/03-seguridad-y-recuperacion.png` |
| `diagramas/04-flujo-t6-previsto.svg` | `diagramas/04-flujo-t6-previsto.png` |
| — | `graficos/t5-disponibilidad-por-intento.png`, `graficos/t5-deteccion-recuperacion.png`, `graficos/tiempos-medidos-t1-t5.png`, `graficos/costos-estimados-por-ventana.png` |

Paleta tomada de `docs/entregable2/diagramas/v2-multicloud.svg` (AWS naranja, OCI rojo, Azure azul; verde = real, morado = local, gris discontinuo = diseño).

## Fuentes principales (no modificadas)

- Resultados reales: `docs/evidencias/T1-20261122-resultado.md` … `docs/evidencias/T5-20261123-resultado.md` (incluidos los intentos fallidos).
- T6: `docs/evidencias/T6-BLOQUEOS-OBLIGATORIOS.md`, `docs/evidencias/T6-PREPARACION-SOLO-LECTURA.md`, `ops_center/criterios/T6.json`, `docs/evidencias/T6-20261123-estado-local.md` (escrito por el frente T6; apareció durante la generación de este paquete).
- T7: worktree `worktree de T7–T8` (rama de trabajo de T7–T8, commit `040f116`).
- Histórico: `docs/entregable2/`, `docs/entregable3/`, `infra/`, `docs/evidencias/MATRIZ-CIERRE-CLOUD.md`, `PROJECT_STATUS.md`.

## Verificación

Todas las rutas citadas entre comillas invertidas en este paquete se comprobaron con un script que hace `ls` de cada una (relativas a la raíz del repositorio, o al worktree hermano si empiezan por ``). Resultado al generar: ver la sección final de `08-INDICE-EVIDENCIAS.md` y el informe de entrega. Resultado: todas las rutas de archivos y carpetas existen; los únicos «no encontrados» del script fueron CIDR, rutas de API (`/healthz`), nombres de rama y nombres de archivo citados sin su carpeta dentro de una frase.

## Inconsistencias detectadas entre fuentes (no corregidas en las fuentes)

1. **Costo total:** `docs/t7-t8/RESULTADOS-Y-COSTOS.md` cita «≈ USD 0,50» (solo T4 + PASS de T5); con los intentos fallidos de T5 la suma de estimaciones es ≈ USD 0,95 (`06-COSTOS.md`).
2. **T8:** `ops_center/criterios/T8.json` define T8 como «Cierre y limpieza» (5 criterios técnicos); en este paquete T8 es además la entrega académica. Los 5 criterios técnicos siguen NOT_TESTED.
3. **T7:** `ops_center/criterios/T7.json` («Flujo operativo desde Azure») no coincide con el alcance de NexoOps (portal local); ninguno de sus 4 criterios está cumplido en nube.
4. **NexoOps:** `docs/nexoops/README.md` dice «33 pruebas» y «SMTP no probado con un proveedor real»; el commit `040f116` tiene 59 pruebas, hoy pasan 66 (copia de trabajo con cambios sin confirmar) y la propietaria confirmó el OTP recibido por Gmail.
5. **Definición de RTO/RPO:** `ops_center/criterios/T6.json` define RTO «desde la inyección del fallo hasta la verificación del nuevo escritor» y RPO como «edad del respaldo usado»; `docs/evidencias/T6-20261123-estado-local.md` §3 propone RTO «desde la detección o la orden hasta la primera escritura aceptada en OCI» y RPO «hora de congelación − última escritura confirmada». Hay que fijar una antes de ejecutar T6.
6. **Regresión:** 683 pruebas (antes de los últimos cambios) frente a 704 (después), ambas exit 0 (`docs/evidencias/T6-local/regresion-final.txt`).
7. **Ruta OCI del 23-oct:** existen dos carpetas, `docs/evidencias/multicloud/oci/20261023-recuperacion-aplicacion/` y `docs/evidencias/multicloud/oci/20261023-cierre-recuperacion-aplicacion/`.

## Cómo regenerar

Los diagramas, gráficos, la presentación y el .docx se generaron con scripts de Python (python-pptx, python-docx, matplotlib) en un entorno temporal fuera del repositorio; los SVG son editables a mano y el .pptx es editable en PowerPoint/Keynote/LibreOffice.

## Paquete final completo (23-nov-2026, rama `informe-final-completo`)

Construido de nuevo **desde las evidencias originales** (no desde este paquete):

| Archivo | Contenido |
|---|---|
| `NexoEventos_Informe_Academico_Definitivo.docx` | **DOCUMENTO DEFINITIVO** (71 páginas, 44 figuras, 44 tablas, 14 criterios de la rúbrica): edición editorial del informe anterior con resumen, problemática, resultados y conclusiones reforzados, y Anexo C con cinco extractos documentales de terminal (Figuras 40–44), trazables a `docs/evidencias/terminal-20261123/` y al expediente T3. Los estados técnicos (T1–T5 PASS, T6 BLOCKED, T7 LOCAL, A1 PARCIAL) no se alteraron |
| `NexoEventos_Informe_Academico_Final_Con_Evidencias.docx` | versión anterior (68 páginas, 39 figuras), conservada sin cambios como respaldo; ya no es el documento de referencia |
| `NexoEventos_Informe_Final_Completo_Con_Evidencias.docx` | versión anterior (51 páginas), conservada como respaldo |
| `NexoEventos_Anexos_Evidencias.pdf` | 38 páginas: capturas auténticas redactadas, criterios de los 11 expedientes, criterios T6–T8, salidas de prueba |
| `INVENTARIO-MAESTRO-EVIDENCIAS.xlsx` / `.md` | 497 evidencias (ID EV-Tn-NNN, ruta, fecha UTC, tipo, resultado, SHA-256, limitación), incluidos los FAIL y sus correcciones |
| `MATRIZ-RUBRICA-EVIDENCIAS.xlsx` | 14 criterios literales de la rúbrica contrastados con la evidencia |
| `REGISTRO-CIERRE-INTEGRACION.md` | registro de la integración final de ramas, pruebas y escaneo de seguridad |
| (no versionado) `NexoEventos_Entrega_Final.zip` | el ZIP de entrega y el PDF del informe se conservan solo en el entorno local; su contenido ya está versionado |
| `graficos-informe/`, `control-calidad/` | gráficos derivados de datos reales; control de calidad, re-ejecuciones de pytest y generadores |

**Corrección:** la tabla de `01-MATRIZ-RUBRICA.md` afirma que los pesos suman 20,0; en la rúbrica oficial suman **18,5** (la hoja declara «TOTAL 20»). Ver capítulo XIV del informe.
