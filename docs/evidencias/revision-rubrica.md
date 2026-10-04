# Revisión frente a los documentos oficiales del Entregable 2

Revisión local del 4 de octubre de 2026 sobre el trabajo posterior a `545a7f3`.

Fuentes oficiales adjuntas, leídas completas:

- `entregable2_cloud_computing_upeu_8rkyhleaul.docx`: estructura y contenido solicitado para la evolución V1 → V2.
- `rubrica_entregable2_cloud_computing_upeu_wqqo1c3quq.docx`: cinco criterios, cuatro puntos máximos por criterio, total 20.

Este documento no asigna puntajes ni inventa cumplimientos. La rúbrica evalúa lo que se implemente y demuestre en el Entregable 2; una propuesta, un script no ejecutado o una captura pendiente no son resultados.

## Requisitos del profesor y mejoras adicionales

| Tipo | Contenido |
|---|---|
| **Requisito oficial** | evolución V1→V2; correcciones a partir del primer entregable; análisis de amenazas y vulnerabilidades; IAM, red, cifrado y monitoreo; escalabilidad, alta disponibilidad y tolerancia a fallos; respaldos/recuperación; pruebas, evidencias, costos y riesgos residuales |
| **Formato oficial pendiente** | el modelo contiene `Equipo XX`. El proyecto es individual y la autora es **Yesenia**; el identificador de equipo se registra como **pendiente de confirmación docente**, sin inventarlo y sin bloquear el trabajo técnico |
| **Mejora propia del proyecto** | Azure como continuidad futura, analítica en GCP, migración entre cuentas, automatización operativa, DuckDNS, prueba de cámara física y repositorio remoto; son útiles, pero los Word no los imponen como proveedores o entregables obligatorios |

## Criterios oficiales

| Criterio oficial | Secciones indicadas | Estado verificable actual | Pendiente exacto para demostrar el descriptor superior |
|---|---|---|---|
| 1. Evolución de V1 a V2 | 2–6 | V1 AWS desplegada, HTTPS y flujo funcional comprobados; problemas y propuestas V2 identificados | documentar la retroalimentación recibida; comparar V1/V2; implementar y medir mejoras V2 significativas, no solo describirlas |
| 2. Amenazas y vulnerabilidades | 8 y 19 | riesgos V1 identificados: instancia única, RDS Single-AZ, sesión Academy, secretos, deriva y costo | producir análisis técnico estructurado (activo, amenaza, vulnerabilidad, probabilidad/impacto, control, riesgo residual) y evidenciar el tratamiento |
| 3. Controles de seguridad | 7, 9, 10 y 14 | HTTPS, cookies seguras, CSRF, Argon2, roles de BD limitados, SSH cerrado, SG→SG, IMDSv2, logs y cifrado de respaldo comprobados | capturas sanitizadas de IAM/red/cifrado/monitoreo; prueba de rate limit; definir/implementar controles V2 justificados; no afirmar MFA si no existe |
| 4. Escalabilidad, disponibilidad y tolerancia a fallos | 11–13 y 15 | SPOF de V1 declarados y escenario de carga preparado | ejecutar 20 VU × 5 min; diseñar V2 coherente para 100→500→1000→5000; justificar redundancia y eliminación de SPOF; medir recuperación de datos y, aparte, servicio completo |
| 5. Evidencias, pruebas y documentación técnica | 16–18 y 20 | pruebas locales/cloud funcionales, matriz EV01–EV11, respaldo y snapshot reales | completar capturas de consola, carga, restauración comparada contra línea base, recuperación completa, costos observados y evidencias antes/después |

## Pendientes por sección oficial

| Sección del modelo | Evidencia disponible | Pendiente |
|---|---|---|
| 2–6: resumen E1, V1, retroalimentación, comparación y V2 | `docs/estado-proyecto.md`, arquitectura V1 y reporte de despliegue | retroalimentación docente explícita; diagrama y componentes V2; tabla comparativa con métricas reales |
| 7: arquitectura V2 | controles V1 documentados | diagrama V2 y decisiones de red/seguridad/cifrado/monitoreo implementadas o claramente marcadas como propuesta |
| 8 y 19: amenazas y riesgos residuales | lista de limitaciones | matriz de riesgos con tratamiento y riesgo residual por activo |
| 9: IAM | LabRole/LabInstanceProfile usados según Academy | evidencia sanitizada; diseño portable sin asumir esos roles en otra cuenta |
| 10: red | VPC, tres subredes, rutas y SG desplegados | EV02–EV04 de consola; propuesta V2 y justificación de segmentación/redundancia |
| 11: escalabilidad | objetivo E01 y script | resultado real de 20 VU × 5 min con p95 y errores; proyección 100/500/1000/5000 |
| 12–13: HA y fallos | SPOF V1 declarados | V2 redundante implementada o limitación honesta; pruebas controladas de falla/recuperación |
| 14: monitoreo y alertas | log groups y alarma creados | EV08, métricas durante carga, umbrales y respuesta operativa |
| 15: respaldo y recuperación | dump cifrado S3, copia externa y snapshot RDS | ensayo cloud: línea base, punto recuperable, datos restaurados, reservas y descifrado de todas las entradas; medir servicio completo por separado |
| 16–18: pruebas, antes/después y resultados | suite funcional pública y matriz | EV11, restauración, capturas antes/después y explicación de desviaciones |
| 20: conclusiones y recomendaciones | limitaciones V1 conocidas | conclusiones basadas en medidas V2, costos observados y decisiones pendientes |

## Evidencia que no debe presentarse como resultado

- Las cifras empresariales (usuarios, concurrencia o volumen) son supuestos del caso.
- `p95 < 2 s`, errores inesperados menores a 1 %, RTO ≤ 60 min y RPO ≤ 24 h son objetivos hasta que se midan.
- PITR disponible no demuestra por sí mismo RPO: el punto recuperable debe compararse con una línea base lógica y con los datos restaurados.
- Restaurar RDS no mide recuperación del servicio completo: faltan aplicación, DNS, HTTPS y prueba funcional.
- Un script local de AWS no es evidencia de ejecución contra AWS.
- El texto `Equipo XX` no se completa hasta recibir el identificador del docente; sí puede avanzarse el resto del entregable.
