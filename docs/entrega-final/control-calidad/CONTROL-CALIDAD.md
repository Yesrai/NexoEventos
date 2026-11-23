# Control de calidad — paquete de entrega final de NexoEventos

Fecha: 2026-11-23T05:15Z · rama `informe-final-completo` (worktree `NexoEventos-informe-final`, base `cierre-t6-t8` @ 5e1fed1). Ninguna operación cloud, ningún `terraform apply`, ningún push ni merge. T6 y T7 no se modificaron (worktrees ajenos solo leídos).

## 1. Conversión y páginas
| Documento | Páginas | Observaciones |
|---|---:|---|
| Informe (PDF exportado por LibreOffice 26.8 desde el DOCX, con índices actualizados por macro) | 51 | páginas sustantivas (Resumen ejecutivo → Conclusiones): 9–46 = **38**; 8 páginas de portada, control e índices; 5 de referencias, glosario y Anexo A |
| Anexos (PDF) | 38 | 47 capturas/recortes auténticos, 11 expedientes, criterios T6–T8, salidas de prueba |

## 2. Índices, numeración y referencias
- Índices automáticos (campos TOC de Word, actualizados con LibreOffice): contenido, tablas (41), figuras (19) y evidencias en recuadro (11). Marcadores sin actualizar: 0.
- Numeración continua de tablas, figuras y evidencias: True (informe), True (anexos).
- Referencias «Tabla N»/«Figura N» del texto que no existen: 0 (informe), 0 (anexos).
- Páginas casi vacías (< 250 caracteres): ninguna (informe), ninguna (anexos).
- Cada figura lleva número, título, fuente, fecha, ID de evidencia y explicación; los gráficos indican «Gráfico generado a partir de datos reales» y el archivo de origen. No se generó ninguna imagen que imite una consola cloud.

## 3. Revisión visual (páginas renderizadas a PNG y revisadas)
Se renderizaron todas las páginas y se revisaron en hojas de contacto. Problemas encontrados y corregidos durante la revisión:
1. Anchos de columna ignorados por LibreOffice (faltaba `tblGrid` y diseño fijo) → columnas comprimidas en 6 tablas. **Corregido** (anchos explícitos en la cuadrícula).
2. Cuatro referencias cruzadas a tablas desfasadas tras insertar tablas → **corregidas** y verificadas por script (0 rotas).
3. Página en blanco antes del capítulo XV y otra casi vacía tras IX → **corregidas** (salto «antes del título» en lugar de saltos manuales; subsección 9.6 añadida).
4. Celda de regresión con texto crudo de pytest → **reemplazada** por un resumen.
5. Leyendas de gráficos superpuestas a las etiquetas del eje → **corregido**.
Portada, índices, tablas partidas entre páginas (con fila de encabezado repetida), imágenes y pies de figura: revisados.

## 4. Rúbrica: los 14 criterios
- Criterios de la rúbrica oficial localizados literalmente en el informe: **14/14**; filas completas en `MATRIZ-RUBRICA-EVIDENCIAS.xlsx`: **14/14**.
- **Inconsistencia de la fuente:** los 14 puntajes suman **18,5**, mientras la hoja declara «TOTAL 20». El paquete T8 anterior (`01-MATRIZ-RUBRICA.md`) afirmaba 20,0: era incorrecto. Se documenta en el capítulo XIV; no se reescala ni se asigna nota.
- La rúbrica no está en el repositorio: se tomó de `~/Downloads/rúbrica proyecto_qod3szrctm.xlsx` (tres copias idénticas, SHA-256 945dec8d…8d7bae); se incluye una copia en el ZIP (`fuentes/`).

## 5. Verificación de cifras contra datos crudos
- 11 manifiestos `MANIFIESTO.sha256` verificados: 0 discrepancias.
- T5 intento 3 (`capturas/resultado.json`): `/healthz` 396 solicitudes, 2 errores → 99,49 %; total 824/816 → 99,03 %; detección 38,9 − 29,3 = 9,6 s; capacidad 154,3 − 29,3 = 125,0 s; costo 0,294 USD (estimación). T1–T4 y T5 intento 1 contrastados igual.
- Costo total estimado: 0 + 0 + 0 + 0,21 + 0,152 + 0,30 + 0,294 ≈ **USD 0,95** (no es factura).
- Regresión re-ejecutada (23-nov): backend/tests 343 passed; scripts/multicloud 704 passed + 66 subtests; NexoOps 68 passed.

## 6. Secretos y datos sensibles
- Búsqueda automática en todo el contenido de texto del ZIP y en el texto de los PDF (IPv4, OCID, URL de PAR, claves AWS, claves privadas, UUID, correos, Bearer, contraseñas). Coincidencias restantes: **11** en las evidencias (más 3 en este mismo documento, que cita esos ejemplos), todas falsos positivos revisados a mano: datos ficticios de pruebas unitarias (`a@gmail.com`, `ti@gmail.com`, `smtp.gmail.com`, PAR de ejemplo `…/p/X/n/ns/b/bk/o/lease.json`, IP de example.com `93.184.216.34`).
- Copias redactadas en el ZIP (13 archivos; su línea del manifiesto ya no coincide, y el SHA-256 del original está en el inventario): IP públicas efímeras de VM de OCI destruidas, IP de Tailscale, ID de suscripción de Azure y la ruta del directorio personal.
- Capturas: son las copias ya redactadas del repositorio; se revisaron visualmente las de mayor riesgo (grupo de acciones con correo, políticas IAM): datos tapados.
- PDF, DOCX, XLSX y MD del paquete: sin correo de la autora ni ruta personal.

## 7. Apertura de archivos y ZIP
- `INVENTARIO-MAESTRO-EVIDENCIAS.md`: OK md: 517 líneas
- `INVENTARIO-MAESTRO-EVIDENCIAS.xlsx`: OK xlsx: Inventario (498 filas), Resumen (42 filas), Leyenda (8 filas)
- `MATRIZ-RUBRICA-EVIDENCIAS.xlsx`: OK xlsx: Matriz (17 filas), Rúbrica oficial (literal) (16 filas), Leyenda (5 filas)
- `NexoEventos_Anexos_Evidencias.pdf`: OK pdf: 38 páginas
- `NexoEventos_Entrega_Final.zip`: OK zip: 507 archivos, testzip=None
- `NexoEventos_Informe_Final_Completo_Con_Evidencias.docx`: OK docx: 430 párrafos, 53 tablas, 19 imágenes
- `NexoEventos_Informe_Final_Completo_Con_Evidencias.pdf`: OK pdf: 51 páginas
- ZIP: 507 archivos, 30,726,251 bytes, `testzip` sin errores; archivos prohibidos (tfstate, .terraform, tfvars, volcados, .cms, .pem, .key, .env): **0**. El SHA-256 del ZIP está en `NexoEventos_Entrega_Final.zip.sha256` (el ZIP contiene este archivo, por lo que su hash no puede figurar dentro de él).

## 8. Hashes de los entregables
| Archivo | SHA-256 |
|---|---|
| `NexoEventos_Informe_Final_Completo_Con_Evidencias.docx` | `ba5931ff03dacd4a63a5a6ea600ad5e864d114a980f510871cdfeb440a9f3bfa` |
| `NexoEventos_Informe_Final_Completo_Con_Evidencias.pdf` | `e6be80071b88bdf1e97b011121b5b51826cf0d45519e1c4b6b0d49a0415da183` |
| `NexoEventos_Anexos_Evidencias.pdf` | `00b01bd4ca5ccff45e3f0399529a7c216dbe37d3dbedab1b71354b55f2a199b5` |
| `INVENTARIO-MAESTRO-EVIDENCIAS.xlsx` | `8b841ca97720ec999ab95004293f634cd5c303364d765e8f830650e517bcddf9` |
| `INVENTARIO-MAESTRO-EVIDENCIAS.md` | `41061d3d256f51d6eaebb803ab788b0559bf32389cf56da06ab39d2b1be17a07` |
| `MATRIZ-RUBRICA-EVIDENCIAS.xlsx` | `60fd5201c65b9b2d36cc888597549bdd411935299ef17aabd41bb08d431f8917` |

## 9. Evidencia faltante o indirecta (declarada)
- **T6:** sin ejecución en nube; RTO/RPO de failover NO medidos.
- **T7 / A1:** despliegue de NexoOps en Azure en curso e incompleto; sin expediente ni capturas fechadas (evidencia indirecta). No se verificó que la VM vuelva a quedar desasignada.
- **T8:** verificación de limpieza cloud y revocación de tokens: NOT_TESTED.
- **Costos:** solo estimaciones; sin Cost Explorer ni Cost Management.
- **Portada:** el código de estudiante no consta en el repositorio.
- **Capturas del chat:** no se adjuntó ningún ZIP de capturas en esta sesión; no se usaron.
- Inventario: 497 evidencias; 33 clasificadas como indirectas.
