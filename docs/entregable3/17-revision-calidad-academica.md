# Entregable 3 · Revisión de calidad académica del informe (11-nov-2026)

> **Fechas clave:** RDS se reinicia sola hacia el **18-nov-2026 ~16:52 UTC** · AWS Academy expira ≈ **26-nov-2026**.
> > **ACTUALIZACIÓN 11-nov (cierre de etapa):** se aplicó la corrección **D-07** (`verify-full` probado en V2 el 4-nov). Las demás correcciones del §7 **siguen pendientes de tu confirmación**, salvo que al incorporar los componentes de failover el informe 15 sustituyó «Multicloud activo» por «Failover multicloud (diseño, simulación y componentes locales)» (D-03) y declaró expresamente que el failover no está validado en la nube. El informe 15, el Word y el PDF se regeneraron con esos cambios; los datos de portada siguen como marcadores.

**Alcance:** solo revisión y preparación local. No se generó ninguna versión definitiva; `informe-final/` (Word y PDF del borrador) sigue idéntico al entregado; los Markdown 14, 15 y 16 no se tocaron. Sin nubes, sin Docker, sin commits ni push.

## 1. Datos que debes completar en la portada (no se inventó ninguno)
| # | Campo | Cómo aparece hoy en el borrador | Qué debes proporcionar |
|---|---|---|---|
| 1 | Institución / facultad | Resaltado amarillo: «UNIVERSIDAD / FACULTAD — completar» | Nombre oficial completo (universidad, facultad/escuela) |
| 2 | Curso | «Curso: Cloud Computing» (tomado del contexto del proyecto; **confirmar** el nombre oficial y, si se exige, el código/sección) | Nombre oficial del curso |
| 3 | Autor(es) | «[completar]» | Nombres completos de **todos** los integrantes, en el orden requerido (y código de estudiante si el curso lo pide) |
| 4 | Docente | «[completar]» | Nombre y grado del docente |
| 5 | Fecha de entrega | «[sin confirmar]» (la fecha de entrega **no está confirmada**) | Fecha exacta indicada por el curso |
| 6 | Fecha del documento | «11 de noviembre de 2026» (fecha del borrador) | Decidir si en la entrega se usa la fecha de entrega o la de la última revisión |
| 7 | Estado del documento | «Borrador para revisión humana (no es la nota)» | Se **elimina** en la versión de entrega (no es un dato que proporcionar) |
| 8 | Título | «NexoEventos — Entregable 3 — Informe técnico consolidado — Integración AWS Academy – OCI: respaldo, recuperación y límites de la solución multicloud» | Confirmar o ajustar el título exigido |
| 9 | Elementos opcionales no incluidos | — | Logo institucional, carátula con formato propio del curso, normas de citación (APA u otras), si el curso las exige |
**Cómo se aplicarán** (cuando me los proporciones): se rellena `docs/entregable3/herramientas/portada-plantilla.json` (campos `institucion`, `curso`, `autores`, `docente`, `fecha_entrega`, `fecha_documento`) y se genera la versión de entrega con `--entrega --portada <archivo>`. El generador **rechaza** la versión de entrega si falta algún campo o queda algún «[…]» (probado: plantilla vacía → rechazo; sin portada → rechazo).

## 2. Anexo C interno: identificación y preparación de su retirada
- **Dónde está:** última sección del Word/PDF, «Anexo C. Coherencia y puntos de revisión humana (retirar antes de entregar)», págs. 9–10 (5 viñetas). También figura como entrada del índice.
- **Qué contiene:** equivalencias de vocabulario entre documentos, nota de pesos, cifras coincidentes, datos pendientes de revisión humana y la indicación de retirarlo.
- **Conservación como documentación de trabajo:** su texto íntegro queda en el generador (`ANEXO_C`, líneas del Anexo C de `herramientas/build_informe_e3.py`) y se reproduce en el §6 de este documento. El borrador Word/PDF actual **conserva** el Anexo C.
- **Preparación de la retirada:** nuevo modo `--entrega` del generador (no ejecutado para la versión definitiva): omite el Anexo C **y su entrada de índice**, y retira además todo lo interno: la marca «Borrador para revisión» del encabezado, el aviso de borrador y la fila «Estado del documento» de la portada, la línea «Fuente: …md» de la portada y la nota «Índice estático…». **Probado solo en una carpeta temporal con datos ficticios:** 0 menciones de «Anexo C», «borrador», «[completar]» o «Fuente: 15» en el cuerpo y el encabezado; con el borrador (sin banderas) todo sigue igual.
- **Se mantiene en la entrega:** el pie con las fechas clave (reinicio de RDS ≈ 18-nov 16:52 UTC y expiración de Academy ≈ 26-nov): confirma si debe seguir visible en un documento académico o se retira.

## 3. Auditoría: ¿se presentan simulaciones Docker como producción multicloud?
Revisé el informe 15, el guion 16, los tres diagramas y el diagrama multicloud de E2 (`docs/entregable2/diagramas/v2-multicloud.svg`, que es honesto: «OCI recuperación», «AWS producción»; no muestra failover). **Veredicto: ninguna afirmación de los criterios de mayor peso presenta Docker como producción entre nubes**; las menciones de conmutación/failover/RPO aparecen siempre con la etiqueta [Docker] o [Diseño], o en negativo. Ajustes de precisión recomendados:
| Criterio (peso) | Afirmación actual | Entorno real | Veredicto | Ajuste propuesto |
|---|---|---|---|---|
| 5 Seguridad (2,5) | Cifrado dual, no-sobrescritura, IAM mínimo | AWS + OCI reales | **OK** | Mantener; las limitaciones (CloudTrail sin trail; `verify-full` probado en V2 el 4-nov, V1 sin verificar) están declaradas (corrección del 11-nov) |
| 2 Arquitectura (2,0) | §4 viñeta «**Multicloud activo** (testigo con lease…)» | Diseño + Docker | **Ajustar** | La palabra «activo» puede leerse como multicloud en funcionamiento. Renombrar a «**Failover multicloud (diseño y simulación)**» |
| 3 Redes (2,0) | «Entre nubes: no hay VPN ni peering» | Real (negativo) | **OK** | — |
| 6 HA (1,5) | «V2 … probado (6-nov 15/15; escalado; failover Multi-AZ ≈ 14 s)»; HA entre nubes solo [Diseño]/[Docker] | AWS real / Docker | **OK** | — |
| 6 / §8 | «Simulado en Docker: RTO 3,1–4,4 s, 0 reservas perdidas (≈ 7 500), 328 con retraso inducido» | Docker | **OK, precisar** | Unificar el rango de RTO: 3,1–4,4 s (informe 04) y 3,3–3,8 s (informe 06, corrida final de F); añadir «en 3–5 repeticiones: no es una garantía» |
| 10 Multicloud (1,5) | «Respaldo AWS→OCI real, seguro y verificable; despliegue en OCI (23-oct)» | AWS + OCI reales | **OK** | En el §1, ítem «(2) despliegue de la aplicación en una VM temporal de OCI (23-oct)»: añadir «**con el respaldo del 23-oct, no con el del 11-nov**» |
| 9 Backup (1,5) | «restauración … 8–9 s [Docker local]»; «32 min 42 s [OCI]» | Docker / OCI | **OK** | Mantener la separación; no mezclar 8–9 s con RTO de producción (ya se aclara) |
| 4 Cómputo/BD (1,5) | «sobre PostgreSQL restaurado [OCI, 23-oct]» | OCI real | **OK** | — |
| Resumen y diagrama 1 | «Lo que no existe: failover real…» y capa D «DISEÑADO + SIMULADO» | — | **OK** | — |
| Guion 16 | Q2 (≈ 7 500 reservas), Q3 (3–4 s «solo entre contenedores Docker»), §4 frases a evitar | Docker | **OK** | — |

## 4. Cifras heredadas de E2 (y otras) que necesitan confirmación, con su evidencia original
Verificadas contra los archivos originales; «Matiz» = el valor existe pero el informe 15 lo expresa de forma imprecisa.
| Cifra en el informe 15 | Evidencia original | Valor en la evidencia | Estado | Acción |
|---|---|---|---|---|
| Funcional **37/37** | `docs/evidencias/validacion-publica-20261019-e88f179-b/resultado.md` | «TODO OK, 37/37», 19-oct | **Matiz:** es la validación pública de **V1**, no de V2 | En §10: «37/37 (V1 pública, 19-oct)» y «15/15 (V2, 6-nov)» |
| **15/15** (V2) | `docs/evidencias/20261106-prueba-real-v2/resultado.md` (+ `validacion-v2-20261106/`) | «15 de 15 OK», reparto 49 %/51 %, 0 errores 5xx | Coincide | — |
| Escalado «alarma a **8 min 6 s**» | `docs/evidencias/escalado-v2-20261022/resultado.md` | `AlarmHigh → ALARM` a los 8 min 6 s | **Matiz:** es el tiempo hasta la alarma desde el inicio de la carga | Redactar «alarma de CPU alta a los 8 min 6 s de iniciar la carga» |
| Failover Multi-AZ «**≈ 14 s**» con huella idéntica | `docs/evidencias/multicloud/aws/20261023-rds-multiaz/failover/resultado.md` | «Interrupción ≈ 14 s» (desde la EC2); huella antes/después idéntica | Coincide | Indicar «una ejecución, sin carga de escritura» |
| Azure «disparada y resuelta en **17 min 54 s**» | `docs/evidencias/multicloud/azure/20261028-vm/resultado.md` | 17 min 54 s = **disparo** desde el inicio de la carga; **resuelta** a las 15:02:59 Z | **ERROR de redacción:** 17 min 54 s no es «disparada y resuelta» | Corregir: «disparada a los 17 min 54 s del inicio de la carga y resuelta a las 15:02:59 Z» (§8; el diagrama 03 dice «1 disparada y resuelta» y es correcto) |
| Carga «≤ **50 usuarios**» | `docs/evidencias/medicion-v2-20261022/resultado.md` | «50 usuarios no saturan ni V1 ni V2» (≈ 1,4 req/s por usuario) | Coincide | Mantener que ≥ 100 es proyección |
| Fallos A–D (ALB `unhealthy` a los **20,0 s**) | `docs/evidencias/tolerancia-fallos-v2-20261022/resultado.md` | 20,0 s tras la orden | Coincide | Citar el valor si se detalla |
| OCI **32 min 42 s**, **14/14**, huella 10/10 | `docs/evidencias/multicloud/oci/20261023-recuperacion-aplicacion/resultado.md` (+ `smoke.json`) | 32 min 42 s desde el `apply`; 14/14; huella 10/10; los tiempos **incluyen fallos y correcciones** | Coincide | Añadir «incluye ≈ 20 min de fallos propios y su corrección» (transparencia) |
| OCI restauración **24 s** | `…/20261023-simulacro-restauracion/resultado.md` (`tiempos-intento-exitoso.txt`) | «fase de restauración (medida por el script) 24 s»; el descifrado+restauración fueron 3 s | Coincide | Aclarar que es la fase del script, no el RTO completo |
| RPO/«R01» (E2): 21 min 4 s / 3 min 32 s | `docs/evidencias/EV07/resultado-restauracion-2026-10-10.md` | 3 min 32 s = desfase T0 − punto recuperable (**RPO demostrado**); 21 min 4 s = recuperación de **datos**, no del servicio | **No está en el informe 15** | Opcional: citarlo en el criterio 9 como evidencia de RPO medido |
| Consumo de Academy «**21,70 de 50 USD**» | Sin evidencia en el repositorio (lo declaraste tú, ≈ 10-nov) | Declarado | **Sin evidencia** | Aportar la captura del saldo real (fecha y hora visibles) |
| Docker: A+E 8/8, B 13/13, C 10/10, D 5/5, F 33/33, F4R 5/5; 328 perdidas; ≈ 7 500 sin pérdidas | Informes 04 y 06; `evidencias/repl-20261110-*` | Coinciden | Coincide | Mantener etiquetadas [Docker] |
| Costos: ventana ≈ 0,02 USD; ALB −0,04 y RDS −0,035 USD/h; residual 0,015–0,025 USD/h | Informes 09–12; `aws-ventana-respaldo-rds-20261111.txt` | Estimaciones con tarifas públicas | Estimación (no facturación) | Mantener el rótulo «estimado» |

## 5. Lista de comprobación final para revisar en Microsoft Word
**Antes de abrir:** copia el `.docx` (no edites el original); anota la versión de Word.
**Apertura y compatibilidad**
- [ ] Abre sin mensajes de reparación ni «modo de compatibilidad» inesperado.
- [ ] La fuente de todo el texto es Arial (no sustituida); los bloques de código en Courier New.
- [ ] Idioma de corrección: español (Perú); revisa la ortografía subrayada.
**Estructura**
- [ ] Portada: sin resaltados amarillos ni «[completar]»; datos del §1 completos.
- [ ] Índice: 17 entradas (16 si se retira el Anexo C); los números de página coinciden con cada encabezado (el índice es **estático**: se corrige a mano si cambian las páginas).
- [ ] Numeración «Página X de Y» presente desde la página 2; la portada sin encabezado.
- [ ] Encabezado y pie correctos; el pie conserva (o no, según decidas) las fechas clave.
**Tablas**
- [ ] Matriz de 14 criterios: columnas legibles, «Costo» sin cortes; las 14 filas con peso y suma 20,0.
- [ ] Todas las tablas repiten la fila de encabezado al cambiar de página y no parten filas.
- [ ] Ninguna tabla se sale del margen derecho.
**Figuras**
- [ ] Figuras 1–3 nítidas al 100 % y al 200 %; sin texto cortado ni solapado; con leyenda.
- [ ] Texto alternativo presente en cada imagen (clic derecho → Texto alternativo).
**Contenido**
- [ ] Las correcciones del §3 y del §4 aplicadas (Azure 17 min 54 s; 37/37 = V1; «Failover multicloud»; «con el respaldo del 23-oct»).
- [ ] Cada afirmación de nube lleva etiqueta [AWS]/[OCI]/[Azure]/[Docker]/[Diseño]; ninguna simulación Docker aparece sin etiqueta.
- [ ] Sin contraseñas, claves, tokens, números de cuenta ni correos (buscar con Ctrl+B: «key», «token», «@», números de 12 dígitos).
- [ ] Las rutas de evidencia del Anexo A existen en el repositorio entregado (o se adjuntan).
- [ ] Anexo C ausente en la versión de entrega.
**PDF**
- [ ] Exporta a PDF desde Word y compara con el PDF generado: mismo número de páginas y mismos saltos.
- [ ] Propiedades del documento: título y autor correctos (hoy «Equipo NexoEventos»).

## 6. Copia de trabajo del Anexo C (se conserva fuera de la versión de entrega)
1. **Vocabulario entre documentos.** La matriz `14-matriz-cumplimiento-y-plan-minimo.md` usa Cumplido / Parcial / Pendiente; el informe usa los niveles de la rúbrica. Equivalencias: Cumplido ≈ Excelente (criterios 1, 4, 8); «Cumplido con límites» ≈ Excelente defendible (9); Parcial ≈ Bueno (2, 3, 5, 6, 7, 10, 11, 12, 13); Pendiente ≈ En proceso (14: el guion ya existe, falta el ensayo).
2. **Pesos.** Proceden de la columna «Puntaje» de la rúbrica original y suman 20,0; coinciden en los tres documentos.
3. **Cifras coincidentes entre 15, 14 y 16:** restauración local 8–9 s; OCI 32 min 42 s; conmutación de BD 3–4,4 s solo en Docker; 328 frente a 0 reservas perdidas; reinicio de RDS ≈ 18-nov 16:52 UTC; expiración ≈ 26-nov.
4. **Datos pendientes de revisión humana:** portada; saldo real de Academy; cifras de E2 (ver §4); decisión sobre el criterio 10; índice estático.
5. **Retirar** este anexo de la versión de entrega.

## 7. Correcciones de texto propuestas (NO aplicadas; esperan tu confirmación)
Se aplicarían en el generador/Markdown de trabajo (los originales permanecen hasta que lo autorices), no en los archivos ya entregados:
1. §8: «(1 disparada y resuelta en 17 min 54 s)» → «(1 disparada a los 17 min 54 s del inicio de la carga y resuelta a las 15:02:59 Z)».
2. §10, fila Funcional: «37/37; 15/15 (6-nov)» → «37/37 (V1 pública, 19-oct); 15/15 (V2, 6-nov)».
3. §4: «**Multicloud activo** (testigo…)» → «**Failover multicloud (diseño y simulación)**: testigo…».
4. §1: añadir «con el respaldo del 23-oct» en el ítem (2).
5. §8 y §3: unificar «RTO de BD 3,1–4,4 s (informe 04; 3,3–3,8 s en la corrida final del informe 06), solo entre contenedores Docker».
6. §8: «escalado 2→3→2 (alarma a 8 min 6 s)» → «escalado 2→3→2 (alarma de CPU alta a los 8 min 6 s de iniciar la carga)».
7. §9: añadir «tiempos de OCI incluyen fallos propios y su corrección» y, opcional, el RPO medido de EV07 (3 min 32 s).
8. §12: «593+ archivos» → «≈ 600 archivos» (el manifiesto crece con cada evidencia).

## 8. Qué necesito de ti para la versión definitiva
(a) los datos del §1; (b) tu confirmación de las correcciones del §7 (todas o cuáles); (c) la captura del saldo de Academy y confirmar las cifras de E2 del §4; (d) decisión sobre mantener el pie con las fechas clave en la entrega. Con eso genero la versión de entrega (Word y PDF) y repito la verificación visual. **Nada se genera hasta entonces.**
