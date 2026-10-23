# 07 — Simulacro de restauración en OCI (propuesta para revisión)

Estado: **propuesto, no aplicado**. Sin Compute creado, sin `apply`.

## VM temporal
- Forma: `VM.Standard.E2.1.Micro` (Always Free, x86_64, 1 GB), Oracle Linux 9.8, volumen de arranque 50 GB, **sin IP pública**, subred privada `10.30.1.0/24`, NSG existente. Alternativa si la RAM no alcanza: `VM.Standard.A1.Flex` 1 OCPU/6 GB (Always Free; exige RPM aarch64). Límites leídos en São Paulo (AD-1): `vm-standard-e2-1-micro-count` 2 disponibles, `standard-a1-core-count` 41, memoria A1 277 GB (límites del Free Trial; Always Free real: 4 OCPU/24 GB A1 y 2 micro, 200 GB de bloque).
- Se crea para el simulacro y se destruye al terminar (`create_recovery_vm=true` → `false`).

## PostgreSQL 18 sin Internet
- La subred no tiene Internet Gateway ni NAT; el único destino de salida es Oracle Services Network por el Service Gateway (TCP 443), que incluye el espejo yum de Oracle.
- PostgreSQL 18 no está en los repositorios de Oracle. Los RPM oficiales PGDG (`postgresql18`, `-libs`, `-server`, x86_64 el9) se descargan en la estación local (fuente: download.postgresql.org), se verifican con la clave GPG de PGDG y se copian a la VM por SSH; las dependencias del sistema salen del espejo de Oracle por el Service Gateway. El servidor queda con `listen_addresses=''` (solo socket Unix).
- **Pendiente de aprobación**: la descarga de los RPM (y el chequeo de que los de PGDG instalan sin dependencias fuera del espejo de Oracle).

## Acceso y claves
- Acceso: OCI Bastion (gratuito) con sesión de reenvío de puerto al puerto 22 de la VM y clave SSH dedicada de la propietaria (con frase de paso); `client_cidr` = una sola IP /32 de la propietaria; sesiones de 1 h. Ningún puerto público.
- Descifrado: **solo en la estación local**. El CMS de OCI se descifra con la clave de recuperación (pide la frase de paso en la terminal) y el volcado en claro viaja por el túnel SSH a un archivo en tmpfs de la VM, donde se verifica su SHA-256, se restaura y se destruye. La clave privada nunca se copia a OCI.
- La lista de seguridad por defecto de la VCN (SSH/ICMP desde 0.0.0.0/0, salida total) se vacía en el mismo plan; el tráfico lo definen solo las reglas del NSG.

## Prueba y RTO
`scripts/multicloud/oci-drill/run-from-mac.sh` (descarga con el perfil de carga → verifica SHA-256 del cifrado contra el manifiesto → instala PostgreSQL → descifra localmente y restaura → compara la huella con la línea base `0008-estado-20261022` de `baseline-restauracion.json`). Criterios: `06-restauracion-criterios.md`. Tiempos registrados (`tiempos.txt`): creación de la VM (`terraform apply`), instalación de PostgreSQL, restauración y verificación. **RTO del simulacro = desde el inicio del `apply` de la VM hasta la huella verificada**; el RTO de solo restauración (con VM ya existente) se informa aparte.

## Costo potencial
VM micro, volumen 50 GB (dentro de 200 GB), Bastion y Service Gateway: USD 0 dentro de Always Free; Object Storage ~92 KB. Riesgos: dejar la VM encendida tras el Free Trial si se cambia la forma; A1 por encima de 4 OCPU/24 GB. No hay NAT, IP pública reservada ni balanceador.

## RPM de PostgreSQL 18 (preparados y verificados el 2026-10-23)
Origen: `download.postgresql.org/pub/repos/yum/18/redhat/rhel-9-x86_64/`, versión **18.6-1PGDG.rhel9.8** (misma versión menor que el `pg_dump` del respaldo). Copia local en `work/oci-drill/rpms/` (fuera de Git). Verificación en un contenedor Oracle Linux 9 x86_64: firmas GPG correctas con la clave del repositorio PGDG (`08b40d20`) y `dnf install` resuelve las dependencias con los repositorios de Oracle; `postgres --version` y `pg_restore --version` = 18.6. La clave se obtuvo del mismo sitio por HTTPS (confianza al primer uso): compare su huella con la publicada en postgresql.org si desea una verificación independiente.
| RPM | SHA-256 |
|---|---|
| postgresql18-18.6-1PGDG.rhel9.8.x86_64.rpm | `ae57ba32d87fa3c311da9545bc85682ae04dc41cfbabf60d7f6c185099604f8a` |
| postgresql18-libs-18.6-1PGDG.rhel9.8.x86_64.rpm | `7a4d55c02b8bab1b359aa25ce53d81db77cd39026a980dd8f0210031a5c31654` |
| postgresql18-server-18.6-1PGDG.rhel9.8.x86_64.rpm | `f7f1915d63756f6a37f3f2e5cc84d03893d0d7a55dab8ac350871bd1c48a0754` |

## Resultado (2026-10-23)
Simulacro ejecutado con éxito: huella idéntica a la línea base 0008 (10/10), fase de restauración 24 s. Detalle, intentos fallidos, diferencia entre tiempo de restauración y tiempo integral, e higiene en `docs/evidencias/multicloud/oci/20261023-simulacro-restauracion/resultado.md`. Correcciones necesarias respecto a lo propuesto: regla de salida TCP/22 hacia la subred en la lista de seguridad predeterminada (el endpoint del Bastion la necesita), swap y `dnf-makecache` deshabilitado en la VM de 1 GB, `cd` dentro del `sudo`.
