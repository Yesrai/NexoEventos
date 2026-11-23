# Reconstrucción de OCI antes de T6 — procedimiento (preparado el 22-nov-2026; lo ensaya T3)

**Principio:** T3 destruye todo lo temporal (criterio de cero residuos). La reconstrucción de OCI para T6 **no se improvisa**: es **exactamente** la secuencia de T3, con los mismos scripts, la misma guarda de Terraform y la misma evidencia, cambiando solo el respaldo (uno **fresco**) y el modo final (estado «standby» en lugar de solo lectura). T3 es el **ensayo medido** de este procedimiento: sus marcas UTC (apply, recuperación por etapa, destrucción) fijan cuánto tarda y cuándo hay que empezar.

## 1. Cuándo se reconstruye
**Una sola vez**, el día de la ventana única de AWS (T5–T7), antes de encender AWS: la VM de OCI debe estar lista y verificada cuando empiece T6 (sondeos de Azure, lease, DNS de pruebas). T4 (centro de operaciones y testigo en Azure) no necesita la VM de OCI viva: sus pruebas contra OCI en vivo se hacen en esa misma ventana. Duración esperada: medida en T3 (referencia: 810 s con E5.Flex el 19-nov; Micro será mayor).

## 2. Secuencia (idéntica a T3)
| # | Paso | Comando / herramienta | Quién |
|---|---|---|---|
| R0 | Respaldo fresco en OCI (RPO) | `backup_cycle.py` / `respaldo` C-04 con AWS encendida (se mide en T6) | yo (ventana AWS) |
| R1 | Verificar integridad del respaldo **sin descifrar** | `scripts/ops/verificar_respaldo_c04.py --remote …` (firma, SHA-256, destinatario del CMS, MD5 del bucket) | yo |
| R2 | Comprobación previa de solo lectura | `scripts/ops/ejecutar_t3.py plan` (preflight local + inventario base + `terraform plan` create-public validado por la guarda: **11 altas / 0 cambios / 0 destrucciones**) | yo |
| R3 | Clave SSH en el agente y prueba de la frase de la clave C-04 | `ssh-add ~/.ssh/nexoeventos_recovery`; descifrado de prueba a `/dev/null` (la frase la escribes tú) | tú |
| R4 | Crear (11 recursos) | `terraform apply` del plan guardado; marcas `ejecutar_t3.py marca apply_inicio/apply_fin` | yo, con autorización |
| R5 | Túneles Bastion y recuperación C-04 | `bastion-tunnels.sh open`; `app-recovery.sh --kind c04 …` (con `RECOVERY_TLS_SAN`, `RECOVERY_ORIGIN`, `RECOVERY_ARGON2=1`, `PUBLIC_BASE`) | tú (frases) |
| R6 | Verificación | humo de solo lectura público con certificado fijado; `puertos`; `memoria` | yo |
| R7 | Evidencia | `ejecutar_t3.py evidencia …` | yo |
`oci-plan.sh teardown-public` + guarda `teardown-public` deshace todo (probado en Terraform: crear → destruir → reconstruir deja 0 recursos y vuelve a crear).

## 3. Lo que T6 añade (no es improvisación: está enumerado y tiene su etapa)
| Requisito de la VM de OCI en T6 | Dónde se cierra |
|---|---|
| Respaldo fresco (RPO ≤ 90 min) y verificado | R0–R1 |
| Aplicación en modo **standby** con compuerta en modo `enforce` (variable de modo de la compuerta), lease (`ParHttpStore` + claves Ed25519 de este nodo) y `fenced_db` | etapa «adaptadores reales» (G1/G5-OCI), **después de T4 y antes de T6**; hoy `install-app.sh` solo instala la variante de solo lectura |
| IP de OCI conocida para el DNS de pruebas (`allowed_targets` «b») y para las sondas de Azure | la IP pública es efímera: tras R4 se actualiza `work/dns-switch/config-prueba.json` (o, si se decide, una **IP pública reservada gratuita**: el límite permite 1 y quedaría estable para NSG, DNS y sondas) |
| Testigo y sello | T4 y etapa de sello |
| Promoción a lectura/escritura **solo** tras lease + sello + vallado + testigo | orquestador, barreras del centro de operaciones |

## 4. Qué debe quedar probado por T3 para poder confiar en este procedimiento
Los 19 criterios de T3, en particular: integridad previa del respaldo, recuperación C-04 con claves originales, humo de solo lectura y **funcional** (login, reservas, idempotencia, concurrencia, QR), memoria sin OOM en las dos fases, solo 443 alcanzable, destrucción verificada con inventario idéntico y **tiempos registrados** (`tiempos_de_reconstruccion_registrados`).
