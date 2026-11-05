# Paso 1 — copia del disco y comprobación del UFW (5-nov-2026 01:25–01:32 UTC; 4-nov 20:25 Perú; saneado)

**Estado: COMPLETADO. No hizo falta reparar: la IP pública actual de la operadora vuelve a ser IGUAL a la IP original** (la de la regla `admin-https` y la de las reglas UFW de la VM). El disco original, la VM y los respaldos quedaron intactos.

## Antes
VM original `deallocated`; disco original sin diferencias respecto de `disco-original-antes.json` (comparación completa salvo `etag`); instantánea `Succeeded` (Trusted Launch); 3 bloqueos `CanNotDelete`; cuota DSv4 2/4 vCPU; el inventario de Ansible coincide con el NSG original.

## Qué se hizo
| Hora UTC | Hecho |
|---|---|
| 01:25 | **Disco de trabajo** `disk-trabajo-vm-nexoeventos-obs-os-20261104` creado desde la instantánea (copia independiente; el disco de reversión `disk-prueba-…` no se tocó): 64 GiB, `StandardSSD_LRS`, Gen2, `TrustedLaunch` heredado |
| 01:25–01:26 | Grupo temporal `rg-tmp-reparacion-nexoeventos`, red aislada 10.99.0.0/28 y **VM temporal** `vm-tmp-reparacion` (D2s_v4, Ubuntu 24.04, Trusted Launch con Secure Boot y vTPM, **sin IP pública, sin NSG propio**, extensiones habilitadas, clave SSH desechable fuera del repositorio) + apagado automático a los 60 min |
| 01:27 | **`az vm disk attach` del disco de trabajo como disco de datos: correcto** (compatibilidad Trusted Launch demostrada para el adjunto) |
| 01:28 | Inspección con `az vm run-command` en la **VM temporal** con el sistema de archivos montado **solo en lectura** (`mount -o ro`); `e2fsck -n` solo comprueba |
| 01:30–01:31 | Disco de trabajo **desacoplado** (`Unattached`); VM temporal eliminada (su disco y NIC con `deleteOption = Delete`); grupo temporal eliminado (solo contenía la red temporal) |

## Resultado de la inspección (copia del disco)
- Particiones intactas (`sdb1` ext4 raíz 63 GiB, EFI, BOOT, BIOS boot); **`e2fsck -n`: «clean», 114 968 archivos, 2 338 687 de 16 514 811 bloques** (≈ 9 GiB usados).
- Contenido: Ubuntu, hostname de la VM, y directorios de **Grafana, PostgreSQL y Zabbix presentes**.
- **Reglas UFW (IP enmascarada):** `allow tcp 22` y `allow tcp 443` con origen = **la IP actual de la operadora** (4 líneas: 2 etiquetas `### tuple ###` y 2 reglas `-A ufw-user-input … -s <IP>` ); **0 reglas de 22/443 sin origen** (nada abierto a todo Internet); la IP aparece **solo** en `/etc/ufw/user.rules` dentro de `/etc`.
- Ninguna edición: la copia no se montó en lectura/escritura, no se creó ningún respaldo `.bak` ni se tocaron `before.rules`, nginx, sshd ni servicios. (Un primer intento de la salida enmascarada falló por una sustitución propia de bash en `sh`; se corrigió y se repitió solo la lectura.)

## Comprobaciones finales
Disco original: **0 diferencias**; VM original: **0 diferencias**, `deallocated`; NSG `admin-https` idéntica a la original; 3 bloqueos intactos; grupos de la suscripción: 2 (el temporal ya no existe); clave SSH desechable y los scripts con la IP **eliminados** del equipo. **No se ejecutó** `az vm update --os-disk`, ni Terraform, ni se encendió la VM original, ni se tocó AWS/OCI.

## Coste y recursos que siguen facturando (estimaciones con tarifas públicas)
- VM temporal ≈ 5 min × 0,108 USD/h ≈ **0,01 USD** (+ disco y NIC temporales, centavos); sin recursos temporales vivos.
- Siguen en el grupo principal (15 recursos): instantánea (≤ 0,11 USD/día; esperado ≈ 0,01–0,02), disco de prueba/reversión (≈ 0,16 USD/día) y **disco de trabajo (≈ 0,16 USD/día, ya sin utilidad)**, más disco original, IP y Log Analytics de siempre. Total adicional ≈ 0,33–0,43 USD/día mientras existan. Borrarlos requiere quitar los bloqueos y tu autorización.

## ¿Paso 2?
**No hace falta** (no hay disco reparado que intercambiar): con la IP actual igual a la original, NSG, UFW y la clave SSH ya funcionan como el 28-oct. Siguiente paso: la ventana de las observaciones 3 y 5 (con comprobación de IP al empezar, porque tu proveedor la puede cambiar), y después, con tu autorización, retirar bloqueos y borrar instantánea y discos temporales.
