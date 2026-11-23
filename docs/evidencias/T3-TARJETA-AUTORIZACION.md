# T3 — Recuperación y funcionamiento real de NexoEventos en OCI · TARJETA DE AUTORIZACIÓN (rev. 3)
> **Estado (22-nov, 15:45Z): 1.er intento FAIL en la instalación de PostgreSQL (dnf sin límites saturó la E2.1.Micro >20 min), abortado y DESTRUIDO con cero residuos e inventario idéntico. Corregido en local (safe-dnf con repositorios mínimos, tope de memoria, prioridad baja y límite de 25 min; swap total ≥ 2 GB). Ver `T3-20261122-intento1-resultado.md`. El 2.º intento exige nueva autorización; el riesgo de que Micro sea demasiado lenta persiste y está acotado (≤ 25 min en dnf).**

## 0. Alcance: qué demuestra T3
NexoEventos se **reconstruye desde cero en una VM nueva de OCI** a partir del respaldo C-04 cifrado y firmado, con las **claves de aplicación originales**, y **funciona de verdad** (no basta con que arranque): memoria, PostgreSQL restaurado, API, **login, reservas, idempotencia, inventario bajo concurrencia, QR y validación**; responde por HTTPS público de prueba con certificado **fijado**; todo lo temporal se destruye con inventario idéntico; y queda **medido y documentado** el procedimiento de reconstrucción que usará T6 (`docs/operacion/reconstruccion-oci-para-t6.md`). **No** es un failover (sin lease, DNS ni escritor: T6).

## 1. Dos fases sobre la MISMA VM (una sola reconstrucción)
| Fase | Modo | Qué prueba | Frases de paso |
|---|---|---|---|
| **A — solo lectura** | Nginx bloquea POST/PUT/DELETE/PATCH; base en solo lectura | restauración + huella, claves originales, humo (livez, ready, healthz, frontend, catálogo), **5 escrituras rechazadas (403)**, **huella final idéntica** (ni `access_logs` cambia), HTTPS público con certificado fijado, 443 única puerta, memoria | 2 (datos y claves) |
| **B — funcional (copia desechable en lectura/escritura)** | `--allow-writes` con `START_AT=app2` y `OUT_DIR` de la fase A (reanuda: datos y claves ya están; **sin nuevas frases**) | **login** de cliente y de operador (contraseñas aleatorias solo en memoria, solo en la copia), cookie Secure+HttpOnly, sesión, **reserva nueva (201)**, **idempotencia** (misma clave → 200 y los cupos no bajan), **conflicto de clave con otro cuerpo (409)**, **cantidades inválidas (422)**, «mis reservas» + **QR descifrable**, **4 reservas concurrentes: cupos bajan exactamente 4**, validación del QR nuevo (aceptada → duplicado 409), QR existentes con la clave **original**, ticket usado rechazado con el hash **original** | 0 |
Estas comprobaciones funcionales **ya se validaron contra la aplicación real y PostgreSQL en local** (3 pruebas, incluido un control negativo que detecta un inventario que no baja). Memoria medida **tras cada fase** (Argon2 del login con 1 hash concurrente).

## 2. Verificaciones previas hechas hoy (resultado)
| Tu punto | Resultado |
|---|---|
| 1. Funcionamiento real | Fase B añade login y reservas funcionales (arriba); `memoria_sin_oom` exige OOM = 0 y swap activa **en las dos mediciones** |
| 2. Continuidad hacia T6 | Procedimiento de reconstrucción **escrito y medido por T3** (`reconstruccion-oci-para-t6.md`); crear → destruir → **reconstruir** probado en Terraform (9 pruebas, deja 0 recursos y vuelve a crear); criterio `tiempos_de_reconstruccion_registrados`; lo que T6 añade está enumerado con su etapa |
| 3. Conectividad | Origen del Bastion **= IP A** (comparación local) y HTTPS permitido a **IP A + IP estática de Azure**, **sin `0.0.0.0/0`**; la guarda del plan rechaza cualquier otro puerto/origen. T3 se prueba **desde tu Mac**; la VM de Azure puede estar desasignada: su IP **estática** sigue asignada (las evidencias de Azure muestran que sigue facturando) y su regla queda lista para T4/T6; el acceso Azure→OCI se **mide en T4/T6** (no en T3). PostgreSQL por **socket**, sin regla de entrada; 5432, 22, 80, 3000, 8000 y 8443 se **prueban cerrados** desde fuera. Si tu IP pública cambiara antes de la ejecución, el Bastion rechaza y se **aborta y destruye** (coste 0) |
| 4. Seguridad y restauración | **Respaldo C-04 íntegro** (verificador nuevo, 6 pruebas de manipulación): firma del manifiesto, SHA-256 y tamaño, destinatario único = certificado `CN=NexoEventos backup recovery` (huella `5c6d387b…`, vigente hasta oct-2027), manifiesto de claves con la misma huella, y **MD5 del bucket = copia verificada** (sin descargar ni descifrar nada). Preflight C-04 local OK. La clave protegida y las frases **solo en tu terminal** |
| 5. Costos y recursos | **Plan real: 11 altas, 0 cambios, 0 destrucciones** (nada existente cambia). **Always Free:** `E2.1.Micro` disponible [2 de 2, 0 usadas], 200 GB gratuitos sin uso (boot 50 GB), IP efímera sin cargo, Bastion/IGW sin cargo; la guarda **rechaza formas de pago**. Limpieza con plan guardado + guarda `teardown-public` + inventario comparado |
| 6. Evidencias | ver §6 |

## 3. Secuencia exacta (quién y qué escribe)
| # | Quién | Paso | Escribe en la nube |
|---|---|---|---|
| F0 | Tú | `ssh-add` ✔ (huella verificada) | no |
| F1 | Yo | `ejecutar_t3.py plan` (**LISTO, sin bloqueantes**) · `inventario --out work/t3/inv-antes.json` · `verificar_respaldo_c04.py` ✔ | no |
| F1b | **Tú** (puedes hacerlo ya) | prueba de la frase: `/opt/homebrew/bin/openssl cms -decrypt -binary -inform DER -in work/oci-drill/app-c04-20261119T180457Z/nexoeventos-rds-20261119T055432Z.cms -inkey ~/.nexoeventos/recovery-c04/recovery-private.protected.pem -out /dev/null` (pide la frase; exit 0 ⇒ frase correcta **y** CMS dirigido a esa clave; no escribe nada) | no |
| F2 | Yo | marca `apply_inicio`; `terraform apply` del plan guardado (regenerado y re-validado justo antes); marca `apply_fin`; logs a `work/t3/*.log` | **11 recursos** |
| F3 | Yo | IP pública/privada (lectura); `bastion-tunnels.sh open` | sesiones de Bastion |
| F4 | **Tú** (2 frases) | **Fase A:** `app-recovery.sh --kind c04 …` (marca `recuperacion_inicio`) · copia `work/oci-drill/app-c04-<ts>` → `work/t3/fase1-solo-lectura` | VM |
| F5 | Yo | `puertos`, `memoria --out work/t3/memoria-ro.json` | no |
| F6 | **Tú** (0 frases) | **Fase B:** `OUT_DIR=<fase A> START_AT=app2 RESET_CREDS=1 … app-recovery.sh --allow-writes …` (marca `recuperacion_fin`) | VM (solo la copia) |
| F7 | Yo | `memoria --out work/t3/memoria.json` | no |
| F8 | Yo | marca `destruccion_inicio`; `bastion-tunnels.sh close`; `oci-plan.sh teardown-public` (guarda) → `terraform apply` (destruye los 11); marca `destruccion_fin`; `inventario --out work/t3/inv-despues.json` | **borra los 11** |
| F9 | Yo | `ejecutar_t3.py evidencia …` → PASS/FAIL/PARCIAL; `record-evidence T3` solo si PASS | no |

## 4. Comandos de F4 y F6 (las frases las escribes tú)
```bash
# F4 (fase A, solo lectura)
PUBLIC=<IP pública>; export RECOVERY_TLS_SAN="IP:$PUBLIC" RECOVERY_ORIGIN="https://$PUBLIC" RECOVERY_ARGON2=1 PUBLIC_BASE="https://$PUBLIC" OCI_NS=<ns> LPORT=2222 HPORT=8443 SSH_KEY=~/.ssh/nexoeventos_recovery RPMS=work/oci-drill/rpms
ARGS="--kind c04 --key ~/.nexoeventos/recovery-c04/recovery-private.protected.pem --cert work/recovery-keys/preupdate-20261008t0113z/recovery-public.crt --cert-sha256 5c6d387bbc29ef818e0c3267cf477b32a2b890fda31be2d7c3c3d6cd9d5c7bcf --signer-pub work/c04/c04-backup-sign.pub --bundle nexoeventos-rds-20261119T055432Z --secbundle app-secrets-20261119T172230Z"
scripts/multicloud/oci-drill/app-recovery.sh $ARGS
# F6 (fase B, tras copiar la fase A)
OUT_DIR=<carpeta de la fase A> START_AT=app2 RESET_CREDS=1 scripts/multicloud/oci-drill/app-recovery.sh $ARGS --allow-writes
```

## 5. Criterios medibles de PASS (19; **todos** medidos y cumplidos; los 13 originales + 6 añadidos a petición tuya)
Originales: `lectura_previa_lista` · `recuperacion_c04_sin_fallo` · `datos_restaurados_huella_ok` · `claves_de_aplicacion_originales` · `smoke_solo_lectura_todo_ok` (≥ 11) · `escrituras_rechazadas_403` (≥ 5) · `ninguna_escritura_huella_final_identica` · `https_publico_con_certificado_fijado` · `solo_443_alcanzable_desde_fuera` · `rto_recuperacion_total_s` ≤ 3600 · `memoria_sin_oom` (dos mediciones) · `recursos_destruidos_y_verificados` · `inventario_final_igual_al_inicial`.
Añadidos: `respaldo_c04_integro` · `fase_escritura_humo_todo_ok` (≥ 20) · `login_cliente_y_operador_ok` · `reservas_funcionales_ok` (7) · `qr_con_claves_originales_y_ticket_usado_409` · `tiempos_de_reconstruccion_registrados` (apply, recuperación por etapa y destrucción con marcas UTC). Cualquier criterio sin medir ⇒ **PARCIAL**, nunca PASS.

## 6. Evidencias (`work/evidencias/T3-<UTC>/`, manifiesto SHA-256)
Verificación del respaldo (JSON) · plan de solo lectura · inventarios antes/después · **logs saneados** de `terraform apply`/`destroy` y túneles (IP/URL/OCID ocultos) · `etapas.json` (tiempos reales por etapa) · `smoke.json` fases A y B (con `tls_verificado`) · `huella-delta.txt` de ambas fases (A vacío; B muestra solo los cambios esperados) · `postgres-version.txt` · `stage2.txt` · puertos · **memoria tras cada fase** · veredicto de la guarda de destrucción · marcas UTC · evento a evento con hora UTC. Opcional (tuya, redactadas, con fecha y barra de direcciones): capturas de la consola de OCI con los recursos creados y con 0 al final.

## 7. Abortos (se destruye lo creado y se registra FAIL/PARCIAL)
Plan ≠ 11/0/0 o guarda ≠ OK · inventario base ≠ esperado · **`OUT_OF_HOST_CAPACITY`** o error del apply (destrucción parcial con guarda) · IP del Mac distinta de la autorizada (Bastion rechaza) · firma, SHA-256 o certificado inválidos (antes de descifrar) · frase incorrecta o huella distinta · claves de aplicación no originales · **OOM** o RAM agotada · en fase A: cualquier escritura (huella final ≠ restaurada) · algún puerto distinto de 443 alcanzable · fallo funcional de la fase B · cualquier cargo o aviso de costo · Ctrl-C (la destrucción se ejecuta igual).

## 8. Costo, riesgos y limitaciones
- **Costo esperado: 0 USD** (todo Always Free; uso de OCI de 30 días: 0,0). El fin del Free Trial no es legible por API; T3 no usa formas de pago.
- **Capacidad** de `E2.1.Micro` solo se sabe al crear (aborto limpio). **Memoria 1 GB:** con swap 2 GB y Argon2 = 1; si hay OOM, **T3 falla y no se oculta**; la alternativa A1 (ARM) exigiría RPM aarch64 verificados y decisión aparte.
- **Exposición:** HTTPS a 2 IP /32 durante ≈ 30–60 min; en fase B el servicio escribe **solo en la copia desechable** (datos de demostración del proyecto); certificado efímero fijado; SSH solo por Bastion.
- Respaldo del **19-nov**: T3 demuestra la reconstrucción, **no** el RPO ni un failover. El RTO medido es el de la reconstrucción desde cero.

## 9. Reversión y cero residuos
Plan de destrucción guardado y validado por `teardown-public` (solo bajas de esos 11) · inventario posterior de solo lectura comparado con el previo · si algo quedara: consola de OCI (Compute, VCN → IGW/subred/NSG, Bastion) y repetir el inventario · los respaldos y secretos del bucket **no se tocan**.

## 10. Verificación local ya hecha (hoy)
`plan_guard` 8 · Terraform del módulo **9** (incluye crear→destruir→reconstruir) + plan real 11/0/0 · verificador IaC con 11 mutaciones · verificador del respaldo **6** · herramienta de evidencia T3 **31** · funcional de reservas **3** (contra la app real) · scripts de recuperación sin regresión (127 pruebas relacionadas, helpers 8/8) · preflight C-04 OK · `ejecutar_t3.py plan`: **LISTO sin bloqueantes**.
