# Procedimientos exactos T2–T4 (prerrequisitos, pasos, aceptación, reversión) — 22-nov-2026

**NADA ejecutado.** Cada etapa pide su autorización, usa el recolector (`python -m ops_center evidence-start Tn --root work/evidencias` … `evidence-finish`) y sus criterios están en `ops_center/criterios/Tn.json`. Un valor sin medir = PARCIAL. T1 está en `PRIMERA-OPERACION-CLOUD.md`.

## T2 · Cambio real de DNS en `nexoeventos-test` (0 USD)
> **Reemplazado por `T2-TARJETA-AUTORIZACION.md`.** Corrección: la «IP de documentación» sugerida aquí es **rechazada** por `dns_switch.py` (solo IPv4 globales); se usa una IP pública real «b».
| | |
|---|---|
| **Prerrequisitos** | T1 en PASS no es obligatorio, pero se hace después para no mezclar fallos. Subdominio `nexoeventos-test` creado **por ti** en DuckDNS (no se usa `nexoeventos-demo`); dos IP públicas **inocuas** (p. ej. la de tu casa y una de documentación) solo como valores de registro; `work/dns-switch/config-prueba.json` (JSON de `entregable3/20` §B.1, fuera de Git) con `allowed_domains=["nexoeventos-test"]`, `assumed_ttl_s=60`, `min_interval_s=300`; token en `work/dns-switch/token` con 0600 (nunca en el chat) |
| **Autorización** | `AUTORIZO el cambio de DNS de prueba en nexoeventos-test` |
| **Pasos** | 1) `dns_switch.py plan --config … --domain nexoeventos-test --target b` (solo lectura; guardar salida). 2) `NEXO_ALLOW_DNS_CHANGE=YES dns_switch.py apply --target b --confirm "CAMBIAR DNS nexoeventos-test A <IP-B>" --token-file work/dns-switch/token`. 3) `dns_switch.py verify --expect-ip <IP-B>` (mide propagación en 1.1.1.1/8.8.8.8/9.9.9.9). 4) intento de un segundo `apply` inmediato (debe ser **rechazado** por el intervalo mínimo; código 3). 5) `NEXO_ALLOW_DNS_CHANGE=YES dns_switch.py rollback --confirm "REVERTIR DNS nexoeventos-test A <IP-A>" …` y `verify --expect-ip <IP-A>`. Marcas del recolector: `dns_cambiado`, `dns_verificado`, `dns_revertido` |
| **Aceptación** | dominio de pruebas únicamente · propagación ≤ 180 s (3 × TTL asumido) en los 3 resolvedores · rollback correcto · segundo cambio rechazado · el token no aparece en ninguna salida ni archivo (buscar el token en `work/evidencias/T2-*`; resultado 0 coincidencias) |
| **Riesgos** | DuckDNS admite **una IP por registro** y no tiene health check; el TTL real no se conoce hasta medirlo; un `apply` sobre el dominio equivocado → el script lo rechaza por lista blanca |
| **Reversión** | `rollback` (guarda la IP anterior antes de cambiar); si DuckDNS devolviera KO el estado no cambió; verificar con `dig +short nexoeventos-test.duckdns.org @1.1.1.1` |
| **Costo** | 0 USD |

## T3 · VM de OCI con el respaldo del 11-nov, app y entrada pública con TLS (≈ 0,10 USD) — **BLOQUEADA por G9**
| | |
|---|---|
| **Bloqueo** | `infra/oci` solo crea VM **privada** (sin IGW). Antes de T3 hay que **escribir y revisar** un módulo opcional (apagado por defecto) con IGW, subred pública, NSG (443 abierto; 22 solo a tu IP /32; sin otros puertos) e IP pública, con `terraform validate` local y plan revisado. No se escribe sin tu visto bueno al alcance |
| **Prerrequisitos** | G9 resuelta y revisada; trial/crédito de OCI vigente; cuota de cómputo disponible (forma E5.Flex 1 OCPU/8 GB; el 10-nov varias formas mostraban 0 y A1 sin capacidad: **verificar con lectura antes**); respaldo del 11-nov y claves disponibles (`work/oci-transfer/`, clave C-04 con tu frase); Bastion/SSH según `entregable3/18`; T1 en PASS |
| **Autorización** | específica con tope de **0,30 USD y 3 h**, hora límite escrita |
| **Pasos** | `terraform -chdir=infra/oci plan -var-file=<tuyo> -var create_recovery_vm=true … -out=work/…` → mostrar el resumen (solo VM, disco, IP, IGW, subred, NSG; **0 destruir**) → `apply` del plan guardado → restauración con `run-from-mac.sh`/`app-recovery.sh` → `curl` HTTPS a `/livez` y `/api/events`; escritura de prueba (debe dar **503** con compuerta en standby) |
| **Aceptación** | huella 10/10 igual a `linea-base-restauracion-rds-20261111.json` · `/livez` y `/api/events` 200 por HTTPS · escritura 503 · restauración ≤ 3600 s (objetivo del proyecto, por confirmar) · recursos destruidos y verificados |
| **Reversión** | plan guardado de destrucción (solo esos recursos) + `verify_clean.py --live`; cerrar IGW/IP |
| **Riesgos** | entrada pública (NSG mínimo, destruir al terminar); sin cuota; el certificado TLS será autofirmado/efímero (no es el de producción); tiempo |

## T4 · Azure en vivo: sondas y panel hacia V2 y OCI (≈ 0,11 USD/h × 2 h + fijos 0,33–0,43 USD/día)
| | |
|---|---|
| **Prerrequisitos** | paquete `work/ops-center-release/ops-center-*.tar.gz` (SHA-256 verificado; **construido**, ver abajo); acceso a la VM: IP /32 vigente en el NSG o Tailscale (`azure-acceso-tailscale.md`); crédito de Azure for Students; `azure-window-preflight.sh` en GO; `azure-vm-watchdog.sh --check` correcto |
| **Autorización** | `AUTORIZO encender vm-nexoeventos-obs e instalar el centro de operaciones (ventana de 2 h)` |
| **Pasos** | 1) `azure-set-shutdown-window.sh --hours 2 --no-plan` y `azure-vm-watchdog.sh` (apagado de seguridad). 2) `az vm start -g rg-nexoeventos-observabilidad -n vm-nexoeventos-obs`; esperar servicios. 3) copiar el paquete a la VM (scp/Tailscale) y `deploy/ops-center/instalar-en-vm.sh --paquete … --sha256 …` (**modo plan**), revisar, luego repetir con `--aplicar "INSTALAR CENTRO DE OPERACIONES EN LA VM"`; guardar los 3 tokens en el gestor. 4) añadir `nginx-ops.conf` al server HTTPS, `nginx -t`, recargar. 5) abrir `https://<VM>/ops/` y comprobar estado, barreras y solicitud de prueba. 6) **independencia:** con AWS apagado, el panel debe responder y mostrar «No verificado» para AWS. 7) sondas de Zabbix a `/livez` de V2 y de OCI (requieren T3 y la ventana AWS; antes de eso se prueban contra un endpoint de prueba) y recolector que escriba `status/cloud-status.json`. 8) provocar una alerta real (detener a propósito el servicio sondeado) y confirmar el correo. 9) `ops_center verify-audit`; 10) `evidence-finish`. |
| **Aceptación** | `Tn.json` de T4: panel con AWS apagado · tarjetas de las tres nubes con origen y hora · alerta real disparada y correo recibido · auditoría íntegra · VM desasignada y apagado automático restaurado (`azure-verify-clean.sh --expect vm-off`) |
| **Reversión** | `systemctl disable --now ops-center`; quitar `/ops/` de Nginx; `azure-vm-watchdog.sh`; `az vm deallocate …`; `azure-verify-clean.sh --expect vm-off` |
| **Riesgos** | la VM D2s_v4 factura 0,108 USD/h encendida (el watchdog depende del Mac encendido); `az vm run-command` está bloqueado por la propia VM (todo por SSH/Tailscale); el correo depende de Azure Monitor |
| **Límite** | las sondas «en vivo» a V2/OCI solo tienen sentido con esos sitios encendidos: el estado de AWS/OCI se demostrará en la ventana de T5/T6, no antes |
