# T3 — 2.º intento (22-nov-2026, 15:52–16:40 UTC): **FAIL (18/19 criterios) — destruido con inventario final idéntico**
Evidencia: `work/evidencias/T3-20261122T163943Z-589d/` (veredicto FAIL; **no** se ejecutó `record-evidence`). T3 NO es PASS.

## Línea de tiempo (UTC)
| Hora | Hecho |
|---|---|
| 15:52:28 → 15:53:23 | `terraform apply` (11 creados, 54 s) |
| 15:55:40 → 16:04:38 | Fase A: descarga, build, copia, PostgreSQL 18, etapa 1 de la app |
| 16:04 → 16:22 | **Incidente 1:** la frase de la clave C-04 se escribió mal (`bad decrypt … maybe wrong password`); respaldo y firma intactos, sin restos en claro, BD no creada. Evidencia: `work/t3/incidente-frase-fase-a/` |
| 16:07:49 / 16:21:41 | **Hallazgo:** `dnf-makecache.timer` del SO (733 MB RSS) → carga 36 y **OOM-killer sobre `dnf-makecache.service`** (no un proceso de NexoEventos) |
| 16:22 | `quiesce-vm.sh` (autorizado): temporizadores `dnf-makecache` y `ksplice-agent` deshabilitados |
| 16:22:45 → 16:23:41 | Reanudación solo desde «datos» (autorizada): SHA-256 OK, 136 reservas / 136 tickets, 10 huellas OK, claves originales, humo 11/11, 5 escrituras 403, huella final idéntica |
| 16:31:50 → 16:36:00 | Fase B (copia desechable L/E): **incidente 2** (`known_hosts` del usuario en el reset de credenciales) e **incidente 3** (Nginx no se reiniciaba al pasar A→B: certificado y bloqueo de escrituras antiguos); ambos corregidos con prueba de regresión. Resultado final **23/23** (login, cookie Secure+HttpOnly, reserva 201, idempotencia, 409, 422, QR, 4 concurrentes: cupos 178→173, QR nuevo aceptado→409, claves originales) |
| 16:37:30 → 16:39:11 | Destrucción con guarda (0/0/11): 11 destruidos; inventario final **idéntico** al inicial |

## Único criterio NO cumplido
`memoria_sin_oom`: `oom=1` (16:21:41Z) en ambas mediciones. Causa: servicio del sistema `dnf-makecache` en una VM de 945 MB. No se reinterpreta el criterio para aprobar. Mitigación ya en el código: `quiesce-vm.sh` se ejecuta antes de cualquier instalación.

## Notas de medición
- `rto_recuperacion_total_s` = 1670,6 s (T0 → fin fase A; incluye ≈18 min de incidente de la frase). Suma neta de etapas ≈ 583 s; fase B ≈ 5 min. Ninguna es el RTO de un failover AWS–OCI.
- Doble escritor: la copia OCI es una base aislada sin ninguna conexión a AWS; en la fase A, Nginx rechazó toda escritura (403) y la huella no cambió.
- Correcciones locales (sin commit): `quiesce-vm.sh`, `app-smoke.py` (known_hosts de la ejecución), `install-app.sh` (restart), `ejecutar_t3.py --known-hosts`, 3 pruebas nuevas (12 pasan en `test_vm_helpers.py`).
