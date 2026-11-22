#!/usr/bin/env bash
# En la VM (root): silencia los actualizadores EN SEGUNDO PLANO del sistema que, en una VM pequeña, compiten con la instalación (T3, 22-nov-2026): `dnf makecache --timer` carga los metadatos de
# TODOS los repositorios (≈ 500 MB de RSS, 727 MB en swap) unos 14 min después del arranque y dejó la E2.1.Micro sin respuesta; `ksplice-agent.timer` hace lo propio. La VM es TEMPORAL (se destruye).
# Idempotente; no toca nada más. Uso: quiesce-vm.sh        Variables: DRY_RUN=1 (solo imprime) · UNITS (lista de unidades)
set -euo pipefail
UNITS="${UNITS:-dnf-makecache.timer dnf-makecache.service ksplice-agent.timer ksplice-agent.service kdump.service}"
run() { if [[ "${DRY_RUN:-}" == "1" ]]; then echo "DRY: $*"; else "$@" || true; fi; }
for u in $UNITS; do run systemctl stop "$u"; run systemctl disable "$u"; run systemctl mask "$u"; done   # mask: ninguna otra unidad puede reactivarlos
# un `dnf makecache` ya en marcha se detiene (es solo una caché de metadatos; no deja la base de paquetes a medias)
run pkill -f "^/usr/bin/python3? /usr/bin/dnf makecache"   # anclado: no coincide con la shell que lo invoca
# kdump (T3 3.er intento): la imagen OL 9.8 reserva 448 MB para el kernel de volcado (la VM queda con ≈ 498 MB de 945) y `kdump.service` construye un initramfs al arrancar. Una VM temporal no necesita volcados de kernel:
# se detiene kdump y se DEVUELVE la reserva al sistema en caliente (sin reiniciar).
if [[ "${DRY_RUN:-}" == "1" ]]; then echo "DRY: kexec -p -u"; echo "DRY: echo 0 > /sys/kernel/kexec_crash_size"
elif [[ -w /sys/kernel/kexec_crash_size ]] && [[ "$(cat /sys/kernel/kexec_crash_size)" != 0 ]]; then kexec -p -u 2>/dev/null || true; echo 0 > /sys/kernel/kexec_crash_size || true; fi
echo "OK    actualizadores en segundo plano silenciados: $UNITS"
[[ "${DRY_RUN:-}" == "1" ]] || echo "memoria disponible ahora: $(free -m | awk '/^Mem:/{print $7" MB"}')"
