# Registro de cierre — integración final de NexoEventos

Fecha de corte: 23-nov-2026 (UTC). Rama de integración: **`integracion-final`**, creada desde `origin/main` (42dd9e0). Repositorio remoto: `Yesrai/NexoEventos` (privado). **Estado de GitHub: nada publicado todavía** (sin push, sin Pull Request nuevo, sin merge a `main`). No se encendió AWS, OCI ni Azure; no se ejecutó `terraform apply`; no se cambió DNS, IAM ni secretos; no se tocó S14.

## 1. Commits incorporados
`origin/main` estaba 34–45 commits por detrás de las ramas locales. Se integraron, sin merges ciegos (ambos merges sin conflictos; se revisó el árbol resultante):

| Origen | Contenido incorporado |
|---|---|
| `entregable2-auditoria` (+ remota, 33 commits) y PR n.º 1 | Auditoría del Entregable 2, V2 en AWS, módulo OCI, escritor único, testigo, respaldo, panel de operaciones, T1–T4, T5 (b4682c3) |
| `cierre-t6-t8` (ea4e477, 5e1fed1) | T6 local (anti-rollback B-T6-1, fencing G5, TLS G9, 11 proveedores reales, bloqueado) y paquete T8 |
| `nexoops` (6ed49a4, 475e437, c607960, 0218fa2) | NexoOps inicial; ya contenido y superado por la rama de T7 (sus cambios sin commit eran una iteración anterior del OTP, que la rama de T7 ya incluye) |
| rama de trabajo T7–T8 (040f116, c1c41d5, 30166fc, ed36881, 99719d6, 310279c + **cbf465a** nuevo) | NexoOps T7 completo; cbf465a cierra los dos cambios locales pendientes (puerto 8770 y espejo de solo lectura) |
| `informe-final-completo` (31d2406) | Paquete del informe, gráficos, inventario de 497 evidencias y matriz de rúbrica; **sin** el ZIP de 30 MB ni el PDF duplicado (se conservan en local) |
| Trabajo nuevo de este cierre | Informe académico definitivo (64 páginas, 39 figuras), expediente A1, README, CI de NexoOps, corrección de `c04-key-custody.sh`, saneamiento de rutas locales y de una IP de red privada |

Ramas **no** integradas a propósito: `backup/pre-reescritura-92f4b06` y `backup/pre-saneo-correo-ab61a4b` (copias de seguridad de historia previa; no se eliminan). Worktree `nexoops`: sus cambios sin commit se dejaron intactos.

## 2. Pruebas (todas locales; ninguna requiere nube encendida)
| Prueba | Resultado | Estado |
|---|---|---|
| `backend/tests` | 343 passed | **PASS** |
| `scripts/multicloud` | 703 passed + 66 subtests; 1 fallo → ver §4 (corregido; 4/4 del archivo pasan) = 704 | **PASS** |
| `nexoops` + `ops_center` | 333 passed (72 de NexoOps, incluidas 4 nuevas de coherencia del espejo) | **PASS** |
| NexoOps en entorno limpio (venv nuevo con el lockfile) | 72 passed | **PASS** |
| `frontend` (vitest) | 44 passed (2 archivos) | **PASS** |
| `terraform init -backend=false` + `validate` en `infra/{aws,aws-recovery,aws-v2,azure,oci,gcp}` | 6/6 válidos | **PASS** (sin apply) |
| Importación de módulos y `compileall` | OK; `REAL_EXECUTION_WIRED=False`, `REAL_WIRING_ENABLED=False` | **PASS** |
| `bash -n` de todos los `.sh` versionados | OK salvo `scripts/repl-lab/parts/lab-entry.sh` (fragmento con `$$` de plantilla *compose*, no es un script independiente) | **PASS** con nota |
| Build de producción del frontend (`vite build`) | no ejecutado en este cierre (lo ejecuta el CI) | **NOT_TESTED** |
| CI de GitHub sobre la rama consolidada | pendiente de push | **NOT_TESTED** |
| Failover/failback real AWS→OCI | no ejecutado; barreras abiertas | **BLOCKED** |
| Login OTP, paneles reales y bloqueo de acciones de NexoOps en Azure | no demostrados (A1) | **NOT_TESTED** |
| Limpieza cloud (T8) y repetición de T5 con caída abrupta | requieren nube | **NOT_TESTED** |

## 3. Expediente A1 (T7) — PARCIAL / INCOMPLETO
Ver [`docs/evidencias/A1-20261123-cierre.md`](../evidencias/A1-20261123-cierre.md): separa pruebas locales (PASS), comprobaciones HTTP externas del 23-nov 04:46Z (PASS, con el servicio activo en ese momento), lecturas de Grafana/Zabbix (indirectas) y el flujo completo en Azure (NOT_TESTED). VM desasignada; apagado automático restaurado a las 17:38 UTC según el cierre. **Discrepancia registrada**: el archivo de estado capturado al abrir la ventana muestra 06:28 UTC; no se archivó una verificación posterior a la restauración.

## 4. Problemas hallados y corregidos durante la consolidación
1. **`scripts/multicloud/c04-key-custody.sh copy`** aceptaba un destino aún inexistente dentro del repositorio (p. ej. `work/x`) y lo **creaba**, porque comprobaba el directorio padre solo si existía. Corregido resolviendo el ancestro existente más cercano; el test `test_copy_is_identical_private_and_never_overwrites` lo detectó en un clon limpio donde `work/` no existe.
2. Falsos fallos de entorno en un clon nuevo (ruta `backend/.venv` y bases de datos de prueba): se resolvieron con enlace temporal al entorno virtual existente; el resultado final fue limpio.
3. NexoOps no tenía job de CI: se añadió `nexoops` a `.github/workflows/ci.yml` (verificado en venv limpio; falta su primera ejecución en GitHub).
4. La carpeta `docs/codex/` se renombró a `docs/t7-t8/` y se actualizaron sus referencias, incluidas las del inventario XLSX.

## 5. Escaneo de seguridad (contenido publicado e historial de los 50 commits nuevos)
Se analizaron las líneas añadidas de `origin/main..HEAD` y del índice: claves privadas, claves AWS, secretos AWS, tokens de testigo/Grafana, *bearer*, contraseñas asignadas, URL de PAR, OCID, correos, OTP/códigos, cookies, ID de suscripción, IP públicas, archivos `.env`/`tfstate`/`tfvars`/`pem`/`cms`/volcados.
- **Coincidencias reales: 0.** Todas las coincidencias son valores de ejemplo o de prueba documentados (`AKIAIOSFODNN7EXAMPLE`, `ti@gmail.com`, rangos TEST-NET, `TOKEN-INVENTADO-…`, fixtures de detectores) o identificadores sintéticos de datos demo.
- **Corregido:** una IP de la red privada Tailscale en dos documentos → `[IP-tailnet-oculta]`; rutas del directorio personal en los generadores del informe → `~`.
- Capturas: solo copias redactadas (cuenta, ARN, IDs, correos, IP). Las capturas del ZIP complementario con tokens, correos o códigos **no** se publican. El DOCX no contiene correos, tokens ni OTP.
- Excluido del repositorio: ZIP de entrega (30 MB), PDF duplicado del informe, `work/`, claves y estados de Terraform.
- **Límite:** el historial ya publicado en `origin/main` y los registros históricos de evidencia conservan rutas del directorio personal en algunos `.log`/`.json`; no contienen credenciales.

## 6. Informe académico
`docs/entrega-final/NexoEventos_Informe_Academico_Final_Con_Evidencias.docx`: 64 páginas, 39 figuras (numeradas 1–39 de forma automática), 14 criterios, T1–T5 reales, T6 BLOCKED, T7/A1 reconciliado con el cierre, sin referencias a herramientas de asistencia. Se actualizó el apartado 6.3 con la discrepancia del apagado automático. La versión anterior queda como respaldo (`…Informe_Final_Completo_Con_Evidencias.docx`). Rúbrica: 14 criterios literales; la hoja declara TOTAL 20 pero suma 18,5; no se alteraron pesos ni se asignó nota (copia de la rúbrica en `docs/entrega-final/fuentes/`).

## 7. Estado de GitHub y Pull Request abierto
- PR n.º 1 «Auditoría del Entregable 2…»: **borrador**, `entregable2-auditoria` → `main`, `MERGEABLE/CLEAN`, 6 comprobaciones de CI en verde en su commit. Contiene solo los 33 commits ya publicados; **no** incluye T5, T6, T7, T8 ni el informe.
- La rama `integracion-final` se construyó sobre `origin/main`, por lo que **no tiene conflictos con `main`** (todos los commits de PR n.º 1 están incluidos).

## 8. Acciones pendientes (requieren autorización)
1. `git push -u origin integracion-final` (sin *force*).
2. Elegir entre abrir un PR nuevo desde `integracion-final` hacia `main` (recomendado; deja el n.º 1 como histórico) o actualizar el n.º 1.
3. Revisar el resultado del CI en GitHub (incluye el job nuevo de NexoOps y Trivy).
4. Merge a `main`.
5. Cierre real de A1 y de T6 solo con nuevas ventanas autorizadas.

## 9. Riesgos restantes
T6 sin prueba real de failover (sin RTO/RPO medido); NexoOps no operativo en Azure; 99,49 % de T5 de una sola ejecución; costos estimados, no facturados; sin *trail* de CloudTrail; MFA de aplicación en diseño; rutas locales en logs históricos ya publicados.
