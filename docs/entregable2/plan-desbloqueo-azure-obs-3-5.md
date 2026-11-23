# Plan de desbloqueo de las observaciones 3 y 5 de Azure (PROPUESTA 4-nov-2026; nada ejecutado)

## Diagnóstico (solo lectura)
- La IP pública actual de la operadora **no coincide** con el /32 original de la regla `admin-https` (ni siquiera comparten el /16: otra red/proveedor). La opción de volver a la IP original solo funciona si la operadora puede conectarse otra vez desde la red usada el 28-oct.
- El acceso a la VM está limitado en **tres capas con la misma IP**: NSG (modificable desde Azure), **UFW del guest** (`ufw allow from {{ monitoring_admin_cidr }}`; el único punto de la IP que no se puede cambiar desde Azure) y las claves SSH. `az vm run-command` y las extensiones están **deshabilitados de forma permanente** (`allowExtensionOperations = false`), la VM no tiene contraseña (solo 1 clave SSH) y es **Trusted Launch / Gen2**, con un solo disco de SO de 64 GiB (`StandardSSD_LRS`; no hay discos de datos). Todo (PostgreSQL de Zabbix, Grafana, Zabbix) está en ese disco.
- Para la observación 3 el correo de **alertas reales de Azure Monitor** ya se probó el 4-nov con `alerta-vm-up` y `alerta-vm-mem` (pendiente de confirmar los correos); la alerta de **CPU** concreta exige carga dentro del guest.

## Alternativas evaluadas
| # | Alternativa | Preserva disco/Grafana/datos | Coste | Riesgo | Viabilidad |
|---|---|---|---|---|---|
| A | Volver a la red/IP original | Sí (sin tocar nada) | 0 | Ninguno; depende de la IP | Solo si la operadora puede usar esa red |
| B | **Corrección sin conexión de UFW** sobre una **copia** del disco: instantánea → copia → montarla en una VM temporal → cambiar solo la IP en `/etc/ufw/user.rules` → cambiar el disco de la VM (el original se conserva) | **Sí**: copia exacta del disco; el original queda como respaldo y se puede volver atrás | ≈ 0,1 USD (VM temporal pequeña ≈ 30–40 min + instantánea) | Medio: el disco/VM son Trusted Launch (no está documentado en la guía oficial de `az vm repair` que lo soporte); la VM temporal debe ser Trusted Launch Gen2; el cambio de disco deja diferencia con Terraform (no aplicar `terraform apply` a la VM; `destroy` sigue funcionando) | **Recomendada**, con una prueba previa barata (crear disco desde la instantánea con el mismo tipo de seguridad) que decide si seguir |
| B' | Lo mismo con `az vm repair create/run/restore` (oficial) | Sí | ≈ 0,15–0,2 USD (la VM de reparación es del mismo tamaño D2s_v4 y crea un grupo, red, NSG y disco nuevos) | Instala una extensión de `az`; no consta soporte Trusted Launch; menos control | Alternativa a B |
| C | Reconstruir con Terraform (`admin_cidr` nuevo) + Ansible | **No**: se pierde el estado interno (historial de eventos de Zabbix, usuarios/ajustes de Grafana). Lo regenerable: paneles (`gen_dashboards.py`), configuración de Zabbix (`zabbix_configure.py`, idempotente), secretos locales (`work/ansible-secrets`), cargas históricas (`work/observability/*.json`: AWS, k6, failover, OCI) | ≈ 0,2–0,3 USD (≈ 2 h de VM) | Alto: destruye el disco; necesita descargar el proveedor `azurerm`, ejecutar Ansible por SSH con verificación de huella por la consola serie y puede volver a quedar atado a una IP que cambia | Solo si B falla |
| D | Cambiar el NSG/UFW por otra vía (Bastion, extensiones, restablecer contraseña) | — | — | UFW sigue filtrando por IP; extensiones deshabilitadas | **No viable** |

## Recomendación concreta (menor riesgo)
1. **Hoy, sin coste:** confirma por Gmail los correos de las alertas del 4-nov (`alerta-vm-mem` 17:50, `alerta-vm-up` Resolved 17:57 y Fired 18:03, hora de Perú). Si llegan, la observación 6 se cierra y la 3 queda demostrada para **entrega de alertas reales de Azure Monitor por correo**, con el límite declarado de que no fueron de CPU.
2. **Intenta A** (conectarte a la red de la ventana del 28-oct y avisarme; compruebo en lectura si la IP coincide). Si coincide, repetimos la ventana tal como estaba prevista (carga por SSH, Grafana, restauración).
3. **Si no hay A: B** en dos pasos con puntos de parada: (i) *prueba previa* (instantánea del disco + disco copia con el mismo tipo de seguridad; ≈ 0,02 USD; no toca la VM); (ii) solo si pasa, VM temporal Trusted Launch con el disco copia, cambio de la IP de `user.rules`, cambio de disco, arranque de la VM original y comprobación de acceso, y retirada de lo temporal. El disco original se conserva hasta que lo apruebes borrar.
4. **C solo como último recurso**, con instantánea previa del disco y `terraform plan` para revisión (no se prepara hoy porque B no está descartada; hace falta descargar el proveedor `azurerm`).
5. Para que no se repita: tras desbloquear, fijar el CIDR en un solo sitio (`admin_cidr`/`monitoring_admin_cidr`), documentar que la IP de la operadora es dinámica y repetir NSG+UFW a la vez en cada ventana.

## Autorizaciones que haría falta pedir (nada hoy)
- B(i): crear una instantánea y un disco copia (recursos temporales y facturables de centavos).
- B(ii): crear una VM temporal pequeña, ejecutar un comando de edición solo de `/etc/ufw/user.rules` en la copia, cambiar el disco de la VM y borrar los recursos temporales; `az vm start`/`deallocate` de la VM original.
