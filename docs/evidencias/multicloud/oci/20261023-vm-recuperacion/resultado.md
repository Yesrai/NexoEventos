# OCI — entorno de recuperación (VM + Bastion) — 2026-10-23 (UTC)

Estado: **VM y Bastion desplegados y verificados por API; acceso por Bastion y PostgreSQL 18.6 pendientes** (requieren que la propietaria cargue su clave SSH en el agente). Sin restauración, sin frase de paso, sin AWS/Azure.

## Despliegue
- `terraform apply` del plan revisado (3 a crear, 0 cambiar, 0 destruir), sin `-auto-approve`: 79 s en total (lista de seguridad 1 s; VM 47 s; Bastion 1 min 17 s).
- Recursos: VM `nexoeventos-recovery-drill` (`VM.Standard.E2.1.Micro`, Oracle Linux 9, Always Free), volumen de arranque de 50 GB, Bastion `nexorecovery` (STANDARD, `client_cidr` = un único /32 de la propietaria, sesiones de 1 h) y gestión de la lista de seguridad predeterminada.

## Verificación (API)
- VM RUNNING; VNIC sin IP pública (solo IP privada de la subred 10.30.1.0/24), 1 NSG; volumen de arranque AVAILABLE, 50 GB.
- Lista de seguridad predeterminada: 0 reglas de entrada y 0 de salida (antes: SSH e ICMP desde 0.0.0.0/0 y salida total). El tráfico queda definido solo por el NSG: SSH TCP/22 desde 10.30.1.0/24 (donde reside el endpoint del Bastion) y salida TCP 443 solo hacia Oracle Services Network.
- Bastion ACTIVE. Sin Internet Gateway ni NAT Gateway.

## Costo
Forma y volumen Always Free; Bastion y Service Gateway sin cargo; sin IP pública reservada ni balanceador. Estimado USD 0; no verificado en el panel de costos de OCI.

## Acceso por Bastion — BLOQUEADO (2026-10-23 ~16:00–16:25 UTC)
- Sesión de reenvío de puerto creada (ACTIVE, destino <IP privada de la VM>:22; endpoint del Bastion <IP del endpoint de Bastion>, dentro de 10.30.1.0/24). Túnel SSH al Bastion autenticado con la clave de la propietaria (agente SSH).
- Conexión SSH a la VM a través del túnel: `Connection timed out during banner exchange` (repetida) y `Connection closed` con espera larga. El Bastion no logra una sesión SSH con el destino.
- Verificado por API: reglas efectivas del NSG correctas (entrada TCP/22 desde 10.30.1.0/24, salida TCP/443 a Oracle Services), VNIC en ese NSG, lista de seguridad predeterminada vacía, VM RUNNING, plugins de agente `ComputeInstanceRunCommand` y `ComputeInstanceMonitoring` RUNNING (el sistema invitado arrancó). Un comando de diagnóstico por Run Command permaneció en `ACCEPTED` sin ejecutarse.
- Sin diagnóstico definitivo de la causa. No se cambiaron reglas ni se crearon recursos adicionales. PostgreSQL no se instaló.

## Diagnóstico de conectividad (17:12–17:30 UTC)
- Historial de consola capturado (2 veces; recurso efímero de lectura): arranque normal (NetworkManager/cloud-init con IP <IP privada de la VM> y ruta por defecto 10.30.1.1; `Started OpenSSH server daemon`; `Started firewalld`; cloud-init terminado a ~80 s). Un evento de OOM aislado a los ~4.379 s de actividad: `dnf-makecache.service` consumió ~726 MB en la VM de 1 GB sin swap (riesgo para la instalación de PostgreSQL; ver corrección local pendiente).
- Un único reinicio suave (autorizado): RUNNING en 69 s, sesión de Bastion nueva ACTIVE a los 88 s. Tras el reinicio, SSH vía Bastion sigue con `Connection timed out during banner exchange` (6 intentos en ~2 min), con sshd y firewalld ya iniciados según la consola. Descarta saturación de memoria, arranque lento o sshd caído como causa.
- **Hipótesis principal (no demostrada, no se modificó nada):** el endpoint privado del Bastion (<IP del endpoint de Bastion>) vive en la subred y su tráfico saliente hacia la VM está sujeto a la lista de seguridad de la subred. Al vaciar la lista predeterminada (0 reglas de entrada y salida) se eliminó la salida que el endpoint necesita; el NSG de la VM solo gobierna a la VM. Corrección propuesta (requiere autorización): una regla de salida TCP/22 con destino 10.30.1.0/24 en esa lista (con estado), sin entrada ni salida a Internet.
- No se creó conexión de consola serie (innecesaria con este diagnóstico y la consola de OCI no permite iniciar sesión sin contraseña local). Sin reglas modificadas.

## Corrección de conectividad y preparación de PostgreSQL (17:31–17:50 UTC)
- Autorizada y aplicada: una regla de salida (con estado) TCP/22 hacia 10.30.1.0/24 en la lista de seguridad predeterminada, asociada a la subred (verificado por API). Plan: 0 crear, 1 modificar en el sitio, 0 destruir. Sin reglas hacia Internet; la lista queda sin reglas de entrada.
- **Causa confirmada:** el endpoint del Bastion necesitaba esa salida; sin ella SSH no llegaba a la VM. Con la regla, **una única prueba SSH por Bastion funcionó** (Oracle Linux 9.8; 498 MB de RAM útiles; disco raíz 30 GB).
- Corrección local reversible en la VM: `dnf-makecache.timer` deshabilitado y 2 GB de swap adicionales (`/swapfile`; ya existía un swap de 945 MB).
- RPM copiados por scp y verificados (SHA-256 igual que en la estación local). Instalación con `dnf` desde los RPM; dependencias del espejo de Oracle por el Service Gateway (sin Internet). Instalación muy lenta por la poca RAM (aprox. 8–18 min; la marca de fin en `tiempos.txt` es solo de sondeo).
- PostgreSQL 18.6 activo, `listen_addresses=''` (solo socket Unix; sin puerto 5432 escuchando), base `drill` creada y vacía. Firewall del invitado: solo `ssh` y `dhcpv6-client`. Se observa `rpcbind` en el puerto 111, sin exposición externa (sin IP pública ni reglas de entrada).
- Sin restaurar el respaldo, sin frase de paso, sin AWS/Azure.
