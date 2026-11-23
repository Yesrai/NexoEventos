# T3 — 3.er intento limpio: autorización exacta (sin ejecutar)
Alcance idéntico al autorizado: las **mismas 11 altas** (VM Always Free E2.1.Micro, Bastion, IGW, subred pública, tabla de rutas, lista de seguridad, NSG y 4 reglas), plan guardado y validado por `plan_guard` (**11/0/0**, comprobado hoy 16:48 UTC con el cambio de cloud-init), inventario base en cero (VCN 1, subred 1, NSG 1, lista 1, 2 tablas, 21 objetos, 0 PAR), IP autorizada sin cambios (/32 del Mac y de Azure). No se tocan recursos existentes ni S14; failover real bloqueado; T4 no se inicia.

## Qué cambia respecto al intento 2 (todo local, probado)
| Condición | Mecanismo | Prueba |
|---|---|---|
| 1. Sin ventana de carrera | **Capa 1:** `cloud-init-quiesce.sh` en el `user_data` de la MISMA instancia: `mask --now` de dnf-makecache y ksplice-agent en el **primer arranque**. **Capa 2:** barrera explícita `memoria --quiesce` (idempotente, por SSH) ANTES de cualquier descarga/instalación. **Capa 3:** `install-postgres.sh` vuelve a ejecutar quiesce antes de ensure-swap y safe-dnf. El primer makecache del SO ocurre ≈ 14 min tras el arranque; las capas 1–2 actúan en < 3 min | test cloud-init cableado; orden quiesce<swap<safe-dnf |
| 2. Servicios | stop + disable + **mask** solo de los 4 units; `sshd`, PostgreSQL, Nginx, nexoeventos y el agente de OCI no se tocan | test «solo los actualizadores»; `sshd_activo` se mide |
| 3. Memoria | `memoria` mide RAM, swap, **OOM desde el arranque de la VM**, temporizadores neutralizados y sshd en **3 puntos**: inicio (tras barrera, antes de instalar), tras fase A y tras fase B. `memoria_sin_oom` exige las 3 (sin la inicial no hay PASS) | 35 pruebas del colector/criterios |
| 4. Errores corregidos | frase: **verificada al principio** (hasta 3 intentos, antes de tocar la VM) + mecanismo fd:4; known_hosts: `app-smoke.py` usa el de la ejecución; Nginx: `restart` en la etapa 2; dnf directo/orden | 15 pruebas `test_vm_helpers.py` · 115 `ops_center` |
| 5. Ejecución completa | fases A (2 frases: se piden al principio) y B, con los 19 criterios originales, sin quitar ninguna prueba | `ops_center/criterios/T3.json` sin cambios (19) |
| 6. Costo/reversión | USD 0 (Always Free); teardown con `teardown-public` (0/0/11) + inventario idéntico | guarda probada en intentos 1 y 2 |
| 7. Evidencias | intentos 1 y 2 y sus causas archivados en `work/t3/intento1`, `intento2`, `work/oci-drill/app-t3-intento2-fase-a`, `work/evidencias/T3-20261122T163943Z-589d`; el intento 3 usa carpetas nuevas | — |

## Secuencia (marcas UTC)
F1 re-verificar respaldo (solo lectura) → F2 `apply` del plan regenerado y re-validado (marca) → F3 IP + túneles → **F3b `memoria --quiesce --out work/t3/memoria-inicio.json`** (debe dar ok; si no, **abortar y destruir**) → F4 **tú**: `bash work/t3/f4-fase-a.sh <IP>` (2 frases al principio) → F5 puertos + `memoria-ro` → F6 **tú**: `bash work/t3/f6-fase-b.sh <IP>` (0 frases) → F7 `memoria` final → F8 destrucción protegida + inventario → F9 evidencia (PASS solo con 19/19).
**Abortos:** plan ≠ 11/0/0; `memoria-inicio` no ok; cualquier OOM; falla de integridad. Si un fallo es corregible dentro de la etapa, se corrige sin crear otra VM; cualquier cambio en la VM se te pide antes.
