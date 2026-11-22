# Dictamen sobre el lote `docs/entregable3` (22-nov-2026)

Auditoría específica de los 640 archivos sin seguimiento de `docs/entregable3` (638 versionables + 2 binarios privados). Sin valores sensibles en este documento. **Repositorio GitHub: PRIVADO** (`isPrivate: true`, sin forks; comprobado con `gh repo view`, solo lectura; la API pública sin credenciales devuelve 404).

## 1. Clasificación por finalidad
| Grupo | Archivos | Finalidad | Dictamen |
|---|---|---|---|
| Documentos `00`–`20` + recordatorio (`.md`) | 22 | Académica y técnica: diagnóstico, viabilidad AWS↔OCI, plan de respaldo, matriz de cumplimiento, informe consolidado, guion de defensa, backlog, procedimientos preparados | **Versionar** |
| `diagramas/` (3 PNG + 3 SVG) | 6 | Diagramas de arquitectura (no son capturas de pantalla) | **Versionar** |
| `herramientas/` (`build_informe_e3.py`, `portada-plantilla.json`) | 2 | Generador del informe; la plantilla de portada está **vacía** (0 datos personales) | **Versionar** |
| `evidencias/repl-*` y `local-*` (16 corridas) | 565 | Evidencia reproducible de replicación, fencing y failover en Docker local (jsonl, log, json) | **Versionar** |
| `evidencias/` sueltas | 43 | Consultas de solo lectura, pruebas locales, diffs, scripts sustituidos, Terraform del ALB, respaldo RDS | **Versionar** (con el saneado de §3) |
| `evidencias/MANIFIESTO-SHA256-20261110.txt` | 1 | Integridad de la evidencia: **607/607 archivos verifican** (0 fallos, 0 faltantes) | **Versionar** |
| `informe-final/*.docx`, `*.pdf` | 2 | Binarios derivados de `15-informe-consolidado-entregable3.md`, regenerables con `build_informe_e3.py` | **FUERA** (convención del repositorio: 0 binarios `.docx/.pdf/.pptx` versionados; sin revisar su contenido interno) |

## 2. Datos sensibles: resultado de la revisión
| Categoría | Resultado |
|---|---|
| Claves privadas, tokens, JWT, AKIA/ASIA reales | **0 reales.** Las coincidencias están en 5 archivos `auditoria-estatica-*` y en `14-matriz…`: son **ejemplos de prueba del filtro de enmascarado** (`AKIAIOSFODNN7EXAMPLE`, etc.), documentado en la propia matriz |
| Correos | **0 personales.** Solo `127.0.0.1` dentro de diffs y ejemplos `persona@example.com` |
| IDs de cuenta / ARN | 1 ARN en `auditoria-estatica-viabilidad-aws-v2.txt`: **ficticio** (ejemplo del enmascarado) |
| IPs públicas | Resolvedores DNS genéricos y la IP ficticia de ejemplo; sin IPs de servidores propios |
| IPs privadas (394) | Redes de los contenedores de laboratorio local (`172.29.x`); no son infraestructura real |
| OCID | 3, de las auditorías estáticas (ejemplos del enmascarado) |
| Dominio `*.duckdns.org` | 3 documentos; el mismo subdominio ya está en **65 archivos publicados** en `origin`: sin riesgo nuevo |
| Capturas con cuentas o correos | **Ninguna**: no hay capturas de pantalla en el lote (solo 3 diagramas) |
| Nombres, institución, universidad | **0** coincidencias en el lote; plantilla de portada vacía |
| Infraestructura real (IDs `sg-/subnet-/vpc-`, DNS del ALB eliminado) | **2 archivos** (`terraform-plan/apply-destroy-alb-target-20261111.txt`). Lo ya publicado no contiene ningún ID de ese tipo (0), así que se **sanearon** (§3) |

## 3. Corrección aplicada al lote (registrada)
En los 2 archivos de Terraform se sustituyeron 4 IDs de red por marcadores numerados (`<sg-1>`, `<subnet-1>`, `<vpc-1>`…) y el nombre DNS del ALB eliminado por `<dns-alb-eliminado>`. El resto del contenido (plan, acciones, resultados) no cambió. Se **actualizaron sus 2 líneas del manifiesto SHA-256** y el manifiesto vuelve a verificar **607/607**. Los originales sin sanear siguen en el respaldo cifrado (paquete anterior) y no se publican.

## 4. Generados, duplicados y referencias
- **145 pares idénticos** `.jsonl` / `.stdout.log` (el ejecutor escribe la misma salida dos veces) y **142 `.stderr.log` vacíos** (= «sin errores»). Todos están en el manifiesto de integridad: **se conservan** (quitarlos rompería el manifiesto; ≈ 7 MB en total, sin coste).
- Referencias: 44 citas a `evidencias/…`; **0 archivos concretos inexistentes** (las que no resuelven son prefijos abreviados o marcadores `AAAAMMDD`). Referencias de `.md` a los binarios del informe final: ninguna.

## 5. Dictamen
**Versionable: los 638 archivos** (22 documentos, 6 diagramas, 2 herramientas, 608 de evidencias incluido el manifiesto), tras el saneado de §3; el repositorio es privado y no se encontró información personal, institucional, confidencial ni credenciales. **Debe permanecer privado: `informe-final/*.docx` y `*.pdf`.** Condición para cambiar la visibilidad del repositorio a público en el futuro: repetir esta auditoría completa y revisar `docs/evidencias` en su conjunto.
