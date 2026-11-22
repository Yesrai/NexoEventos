# T3 — 1.er intento (22-nov-2026, 15:06–15:45 UTC): **FAIL / abortado en la instalación de PostgreSQL — destruido con cero residuos**

Expediente: `work/evidencias/T3-20261122T154813Z-c535/` (0600/0700; manifiesto SHA-256 verificado, 0 discrepancias; `resultado.json` sha256 `4f14047cbccc9f08…`; sin IP ni OCID en ningún archivo). Un primer expediente del mismo intento (`…T154757Z-ccfe`) se conserva: marcaba el RTO como cumplido con el tiempo de una recuperación **abortada**; es un error del recolector, corregido en el segundo (que es el válido). Autorización: T3 según la tarjeta rev. 2. **Veredicto: FAIL** (19 criterios: 4 CUMPLEN, 4 NO CUMPLEN, 11 SIN MEDIR).

## Cronología UTC
| Hora | Hecho |
|---|---|
| 15:00–15:05 | F1: plan LISTO sin bloqueantes (11/0/0), inventario previo guardado, respaldo íntegro; **F1b: frase correcta (`F1b_OK`)** |
| 15:06:50 → 15:07:49 | **F2: `terraform apply`: 11 creados, 0 cambiados, 0 destruidos (59 s)**; la VM `E2.1.Micro` se creó (había capacidad) |
| 15:08–15:14 | VM RUNNING, IP pública y privada; el plugin de Bastion del agente figura `STOPPED` (no bloquea: las sesiones de reenvío de puerto no lo necesitan); túneles SSH y HTTPS **ACTIVE**; SSH correcto: x86_64, Oracle Linux 9.8, **RAM 945 MB (485 libres), swap 944 MB, 0 eventos OOM, disco 30 GB** |
| 15:16:35 | inicio de la recuperación (fase A): descarga y verificación (7 s), construcción (5 s), copia (33 s), **RPM verificados en la VM** |
| 15:17:40 → | `dnf -y install` de PostgreSQL. A 1 min: `dnf` 409 MB de RSS, 241 MB libres, swap 120 MB usados, carga 0,6, 0 OOM |
| 15:19 → 15:43 | **`sshd` deja de responder** («Connection timed out during banner exchange», también con 120 s de espera) mientras `dnf` sigue sin terminar: **> 23 min** |
| 15:43:19 | **aborto decidido** (condición de la tarjeta «RAM agotada»); recuperación detenida; túneles cerrados |
| 15:43:39 → 15:45:35 | plan de destrucción **0 altas / 0 cambios / 11 destrucciones**, aprobado por la guarda `teardown-public`; `terraform apply`: **11 destruidos** (1 min 56 s) |
| 15:45 | inventario posterior de solo lectura: **idéntico al previo** (0 instancias, 0 Bastion, 0 IGW, 1 VCN, 1 subred, 1 NSG, 1 lista de seguridad, 2 tablas de rutas, 0 PAR, 21 objetos); sin procesos ni puertos locales abiertos |

## Qué quedó demostrado y qué no
Demostrado en la nube real: la **configuración de red y la guarda** (11/0/0, creación en 59 s, destrucción con cero residuos), el **Bastion con reenvío de puerto**, el SSH, la **verificación de los RPM en la VM**, el **paquete firmado e íntegro**, la **frase correcta** y la **reversibilidad** (crear → destruir → inventario idéntico). **No demostrado:** instalación de PostgreSQL, restauración, claves de aplicación, humo (solo lectura y funcional), HTTPS público, puertos, memoria, RTO. **T3 no está completo.**

## Causa raíz
1. **`dnf` sin límites en una VM de 945 MB y 1/8 de OCPU.** Cargaba los metadatos de **todos** los repositorios (`OCI Included Packages` 190 MB + Ksplice 39 MB + BaseOS + AppStream…) para resolver las dependencias de PostgreSQL; con esa CPU y memoria el sistema dejó de atender a `sshd` más de 20 minutos (sin evento OOM del kernel observado: es **saturación**, no una muerte por OOM). El script ya advertía que el 23-oct esta forma sufrió `dnf` sin swap; el 22-nov faltaron **límites**.
2. **`ensure-swap.sh` no actuó:** se salía con «ya hay swap activa» porque la imagen trae 944 MB; con 2 GB habría más margen.
3. Mi tarjeta daba por acotado el riesgo de memoria con «swap + Argon2 = 1» y la medición; **no había un límite de tiempo ni de memoria para el paso más pesado**, de modo que el fallo tardó 25 minutos en detectarse.

## Corrección (solo local; sin nueva ejecución remota)
- `safe-dnf.sh` (nuevo): **solo `ol9_baseos_latest` y `ol9_appstream`** (si falta alguno se detiene y lista los repositorios, sin probar con todos), dentro de un **cgroup con tope de memoria** (`systemd-run --scope`, 640 MB + 1 GB de swap máx.: si lo supera lo mata el cgroup, el sistema sigue vivo), **prioridad mínima de CPU y E/S** (`sshd` sigue respondiendo y se puede diagnosticar), **límite de 25 min**, sin dependencias débiles ni caché, y un único reintento con `ol9_addons` si una dependencia solo está allí. Lo usan `install-postgres.sh` y `install-app.sh` (nada llama a `dnf` directamente; hay una prueba que lo exige).
- `ensure-swap.sh`: garantiza **swap total ≥ 2 GB** (añade la diferencia: 1104 MB sobre los 944 MB de la imagen).
- `app-recovery.sh`: SSH con `ServerAliveInterval/CountMax` (no queda colgado indefinidamente).
- Pruebas nuevas `test_vm_helpers.py` (7): complemento de swap, repositorios mínimos con límites, repo ausente → código 3, y que no haya llamadas directas a `dnf`. Las 8 pruebas anteriores de los helpers siguen pasando.
- Recolector: el tiempo de una recuperación **abortada** ya no cuenta como RTO (prueba nueva).

## Riesgo que persiste (declarado)
Los repositorios mínimos y los límites **acotan** el fallo (≤ 25 min y con la VM viva), pero **no garantizan** que la forma Micro (1/8 de OCPU) termine la instalación en un tiempo razonable: la misma etapa tardó 105 s con E5.Flex el 19-nov; en Micro puede ser muy superior. El segundo intento es un experimento acotado. Si vuelve a fallar por tiempo o memoria, la forma Micro no es viable para T3 y la alternativa A1 (2 OCPU/12 GB, ARM) exige decisión aparte: RPM aarch64 verificados, ruedas aarch64 y capacidad incierta.

## Estado
Costo: 0. OCI en su estado inicial. `REAL_EXECUTION_WIRED = False`, `REAL_WIRING_ENABLED = False`; T4–T8 sin tocar; S14 intacto. **Una segunda ejecución de T3 requiere nueva autorización.**
