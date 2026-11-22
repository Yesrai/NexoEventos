# T3 — 3.er intento (22-nov-2026, 16:52–17:26 UTC): **PASS (19/19)**
Expediente: `work/evidencias/T3-20261122T172554Z-f812/` (manifiesto SHA-256 verificado, 0 alterados). Registrado con `record-evidence T3 … PASS`; auditoría íntegra. Intentos previos conservados (FAIL intento 1: aborto por dnf; FAIL intento 2: 18/19, OOM de `dnf-makecache`): `work/t3/intento1`, `work/t3/intento2`, `work/evidencias/T3-20261122T163943Z-589d`.

## Hechos medidos
- `terraform apply` 16:52:38→16:53:36 (11 creados). Destrucción 17:23:29→17:25:37 con guarda 0/0/11; **inventario final idéntico** (VCN 1, subred 1, NSG 1, lista 1, 2 tablas, 21 objetos, 0 PAR, 0 IGW/Bastion/instancias).
- Fase A: SHA-256 OK, 136 reservas/136 tickets, 10 huellas OK, claves originales, humo 11/11, 5×403, huella final idéntica; T0→fin 649 s (sin incidentes; frase verificada al principio).
- Fase B (copia desechable): 23/23 — login cliente/operador (cookie Secure+HttpOnly), reserva 201, idempotencia, 409, 422, «mis reservas»+QR, 4 reservas concurrentes (cupos 178→173), QR nuevo aceptado→409, claves originales.
- HTTPS público con certificado fijado; solo 443 alcanzable (22, 80, 3000, 5432, 8000, 8443 no), dos mediciones.
- **Memoria:** 3 mediciones (inicio, tras A, final), OOM 0 desde el arranque, swap 2 GB, temporizadores neutralizados (cloud-init en el primer arranque) y sshd activo.

## Hallazgo y corrección (conservados en `work/t3/intento3/`)
La imagen OL 9.8 reserva 448 MiB para kdump (RAM 498 de 945 MB). Con autorización: `kdump` detenido/enmascarado y reserva devuelta en caliente (`kexec -p -u`, `kexec_crash_size=0`), sin reiniciar: MemTotal 510 644→969 396 kB, MemAvailable 250→714 MB, OOM 0. `quiesce-vm.sh` y el cloud-init ya lo incluyen (cambio local, sin commit).

## Notas honestas
- `recuperacion_inicio` se fijó con el T0 del registro (16:59:54Z) y `recuperacion_fin` con el fin del registro (17:16:10Z); la marca tomada tarde (17:22:54Z) se conserva como `recuperacion_fin_marca_tardia`.
- Los tiempos son de reconstrucción en OCI, no el RTO de un failover AWS–OCI (T6).
