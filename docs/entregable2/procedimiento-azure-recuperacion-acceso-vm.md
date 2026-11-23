# Procedimiento B — recuperar el acceso a la VM de Azure conservando el disco (PROPUESTA 4-nov-2026; NADA ejecutado)

Complementa `plan-desbloqueo-azure-obs-3-5.md`. Prioridad: **conservar intactos el disco original y sus datos** (PostgreSQL de Zabbix, Grafana, Zabbix) por encima de cerrar las observaciones 3 y 5. Solo se comprobaron lecturas.

## 1. Prechequeo (hecho, solo lectura)
| Punto | Resultado |
|---|---|
| Disco de SO | 64 GiB (68 719 476 736 B), `StandardSSD_LRS`, Linux, **Gen2 / Trusted Launch**, cifrado con clave de plataforma (no ADE), `centralus`, sin zonas, sin bloqueos; la VM no tiene discos de datos |
| VM | D2s_v4, Ubuntu 24.04 (`24.04.202610210`), Trusted Launch con Secure Boot y vTPM, 1 clave SSH, **sin contraseña**, extensiones deshabilitadas, `osDisk.deleteOption = Detach` (un disco desacoplado no se borra con la VM) |
| Cambio de disco (guía de Microsoft «OS disk swap», `az vm update --os-disk`) | Requisitos: **mismo tamaño**, **cifrado compatible**, SKU soportada por la talla, mismo conjunto de cifrado. **La guía no menciona Trusted Launch** (ni a favor ni en contra); no hace falta parar la VM (aquí está desasignada) |
| CLI | `az snapshot create --incremental`, `az disk create --source … --hyper-v-generation V2 --security-type TrustedLaunch`, `az vm update --os-disk`, `az lock create` disponibles |
| VM temporal | Misma talla e imagen que la original (D2s_v4, Ubuntu 24.04 Gen2 Trusted Launch): ya demostradas en la región; cuota DSv4 **2 de 4** vCPU (la temporal cabe solo si la original sigue desasignada: 4/4) |
| Consola serie | Servicio activo a nivel de suscripción (`disabled: false`), diagnóstico de arranque administrado habilitado, rol `Owner` |
| Dónde está la IP | UFW del invitado (`ufw allow from <IP> … 22/443`, rol `base.yml`) y NSG (variable `admin_cidr`); ningún otro archivo del rol (nginx, sshd, Grafana) usa la IP |
| Qué no se puede comprobar sin ejecutar | Si Azure acepta crear el disco copia con **Trusted Launch** a partir de la instantánea y **adjuntarlo como disco de datos** a una VM Trusted Launch; la guía de `az vm repair` tampoco lo documenta. Es la única incertidumbre real y se resuelve con una prueba barata antes de tocar nada |

## 2. Procedimiento B (el original no se modifica)
> **Paso 1 EJECUTADO el 5-nov 01:25–01:32 UTC (20:25 Perú del 4-nov)**: el adjunto de la copia Trusted Launch como disco de datos **funcionó** y se montó en solo lectura (`clean`, con Grafana/PostgreSQL/Zabbix). **No hubo reparación porque la IP actual de la operadora volvió a ser igual a la original (UFW y NSG ya la permiten).** Paso 2 no necesario. Ver `docs/evidencias/20261104-azure-paso1/`.
> **Paso 0 EJECUTADO el 4-nov (01:14–01:20 UTC)** — instantánea incremental + disco de prueba/reversión creados y verificados, `TrustedLaunch` heredado, bloqueos `CanNotDelete`, original y VM sin cambios (`docs/evidencias/20261104-azure-paso0/`). Hallazgo: `--security-type` no se admite con `CreateOption=Copy`; la seguridad se hereda de la instantánea. Pendiente de comprobar en el Paso 1: adjuntar una copia como disco de datos a la VM temporal y el cambio de disco.
**Paso 0 — respaldo y prueba de restauración (punto de autorización 1; no toca la VM):**
1. `az snapshot create --incremental` del disco de SO (VM desasignada) con etiqueta `proposito=recuperacion-acceso`; esperar `provisioningState = Succeeded`.
2. Crear un disco **de prueba** desde la instantánea (`--hyper-v-generation V2 --security-type TrustedLaunch --sku StandardSSD_LRS`); comprobar `securityType`, tamaño (64 GiB), SKU, cifrado y `diskState = Unattached`. Es a la vez el **disco de reversión**.
3. Poner un bloqueo `CanNotDelete` en la instantánea y en el disco original (evita borrados accidentales, también por Terraform; se quita al final con autorización).
**GO/NO-GO:** si la creación falla o el tipo de seguridad no se conserva → no se sigue; se pasa a la alternativa S (abajo).

**Paso 1 — corrección sobre la COPIA (punto de autorización 2):**
1. Crear un **disco copia de trabajo** (otro disco desde la misma instantánea) y una **VM temporal** (misma talla/imagen, Trusted Launch, sin IP pública, NIC propia en la red existente o en una nueva red temporal, con clave SSH propia y extensiones habilitadas). Adjuntar la copia como disco de datos. Si el adjunto falla (incompatibilidad Trusted Launch) → parar y pasar a S.
2. Con `az vm run-command` sobre la **VM temporal**: `e2fsck -n` de la copia (solo comprobación), montarla en una carpeta, guardar `user.rules.bak`, y cambiar **solo la IP de origen** en `/etc/ufw/user.rules` (UFW guarda la IP en 4 líneas: 2 etiquetas `### tuple ###` y 2 reglas `-A ufw-user-input … -s <IP>`); verificar con `diff` que cambian exactamente esas 4 líneas, que no aparece ninguna otra IP y que no hay reglas nuevas ni `0.0.0.0/0`; desmontar y sincronizar. No se toca `before.rules`, `after.rules`, `ufw.conf`, nginx, sshd ni servicios.
3. Desadjuntar la copia, borrar la VM temporal y su NIC.
**Paso 2 — intercambio (punto de autorización 3):** con la VM original desasignada, `az vm update --os-disk <copia>`; comprobar `storageProfile.osDisk.managedDisk.id`. El disco original queda desacoplado e intacto (`deleteOption = Detach`).
**Paso 3 — verificación (misma autorización que la ventana de Azure):** actualizar `admin-https` (y `admin-ssh` si se usa SSH) a la nueva IP /32, arrancar, comprobar 443 y SSH con verificación de huella, Grafana/Zabbix/PostgreSQL y que los datos siguen ahí (p. ej. número de hosts de Zabbix y de paneles, comparado con `20261028-vm/zabbix-estado-api.json` y `grafana.txt`). Después, la ventana de las observaciones 3 y 5.
**Rollback (verificable en cada punto):** apagar la VM → `az vm update --os-disk <disco original>` (o el disco de reversión creado desde la instantánea) → arrancar y comprobar; el original nunca se borra hasta que lo apruebes. Restaurar NSG con el archivo local `work/operacion/nsg-admin-https-original.json`.

## 3. Alternativa S — consola serie de Azure (oficial; sin VM temporal, pero modifica el disco original)
Según Microsoft: Ubuntu no pide contraseña de root; con la consola serie abierta se reinicia la VM, se mantiene **Esc** para ver GRUB (Ubuntu puede ocultarlo por defecto), se edita la entrada y se cambia `ro` por `rw init=/bin/bash`; entonces se edita `/etc/ufw/user.rules` y se reinicia (`sync; reboot -f`). **Ventajas:** sin disco copia, sin cambio de disco ni diferencia con Terraform, coste ≈ solo la VM encendida unos 20–30 min. **Inconvenientes:** es **interactivo** (lo haces tú en el portal; no puedo operarlo), la guía no menciona Trusted Launch/Secure Boot, GRUB puede estar oculto, y se **edita el disco original** (el respaldo es la instantánea del Paso 0, que también es el rollback). No se recomienda como primera opción por ese último punto; sirve de plan B si el adjunto de la copia falla.

## 4. Cómo evitar que Terraform o Ansible deshagan el cambio
- **El intercambio de disco no deja diferencia esperada:** la VM de Terraform (`infra/azure/modules/vm/main.tf`) no fija el nombre ni el ID del disco de SO (solo caché, SKU y 64 GiB) y no tiene `lifecycle`; **no se puede asegurar sin ejecutar** `terraform plan` tras el cambio (hay que descargar el proveedor `azurerm`): se hará solo de lectura y **no se ejecutará `apply`** sobre la VM sin revisar el plan; si propusiera reemplazar la VM, se descarta (`destroy` seguiría funcionando).
- **La IP es el verdadero riesgo de «revertir»:** el NSG lo gestiona Terraform con `admin_cidr` y el UFW lo fija Ansible con `monitoring_admin_cidr`. Tras el cambio hay que actualizar a la vez los archivos locales ignorados por Git `work/terraform-envs/azure-vm.tfvars` (y los otros `azure*.tfvars`) y `ansible/monitoring-inventory.yml` con la nueva IP; de lo contrario un `apply` o una ejecución de Ansible volverían a la IP antigua. Hacer copia previa de `work/terraform-state/azure/terraform.tfstate`.
- **Bloqueos `CanNotDelete`** en la VM, el disco original y la instantánea durante la operación (se retiran al final).
- No se ejecuta Ansible ni Terraform durante B.

## 5. Coste, tiempo, riesgos y limpieza
| Concepto | Estimación (tarifas públicas, sin verificar) |
|---|---|
| Instantánea incremental (solo datos usados) + disco de reversión + disco copia | ≈ 0,02–0,05 USD por la operación; el disco de reversión (64 GiB StandardSSD ≈ 4,8 USD/mes ≈ 0,16 USD/día) y la instantánea se conservan hasta que se apruebe borrarlos |
| VM temporal D2s_v4 ≈ 40 min | ≈ 0,07 USD (0,108 USD/h) |
| VM original encendida para la verificación y la ventana | ≈ 0,13 USD (≈ 70 min) |
| **Total** | **≈ 0,25–0,30 USD**; si se supera 0,30 USD se pide autorización |
| Tiempo | ≈ 60–90 min de operación (Pasos 0–2) + la ventana de 60–70 min |
| Riesgos | (1) incompatibilidad Trusted Launch al crear/adjuntar la copia → se detecta antes de tocar nada; (2) quedarse sin cuota si se enciende la original con la temporal (4/4 vCPU: no se hace); (3) equivocación al editar → se verifica con `diff` y la copia se descarta si falla; (4) la IP vuelve a cambiar → repetir NSG+UFW |
| Recursos temporales a limpiar | VM temporal, su NIC y su disco, disco copia de trabajo (tras el intercambio es el de la VM); **se conservan** instantánea, disco original y disco de reversión hasta tu aprobación |

## 6. Si B no es viable
Solo si falla el adjunto/creación con Trusted Launch **y** la consola serie no es aceptable: reconstruir (C). Antes, instantánea del disco, copia de `work/terraform-state/azure/`, y los datos regenerables (`work/observability/*.json`, secretos locales, paneles de `gen_dashboards.py`) ya están en el repositorio/local; se perdería el estado interno de Zabbix/Grafana. El `terraform plan` de reconstrucción se prepararía en ese momento (requiere descargar `azurerm`).

## 7. Puntos de autorización
1. **Paso 0:** instantánea, disco de prueba/reversión y bloqueos `CanNotDelete`.
2. **Paso 1:** disco copia de trabajo, VM temporal, edición de la copia con `run-command` y limpieza de la temporal.
3. **Paso 2:** `az vm update --os-disk` en la VM original (desasignada).
4. **Paso 3:** actualización del NSG a la IP nueva, encendido y verificación (la ventana de las observaciones 3 y 5 se pide aparte).
