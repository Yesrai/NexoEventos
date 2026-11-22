#!/usr/bin/env bash
# Prueba LOCAL (sin nubes, sin contenedores) de verify-rpms.sh y ensure-swap.sh (DRY_RUN) con los RPM reales (solo lectura) y copias en un directorio temporal.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"; cd "$ROOT"; D=scripts/multicloud/oci-drill; T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT
pass=0; failn=0; ok() { echo "OK    $*"; pass=$((pass+1)); }; bad() { echo "FALLÓ $*"; failn=$((failn+1)); }
exp() { local want="$1" name="$2"; shift 2; "$@" >"$T/o.txt" 2>&1 && rc=0 || rc=$?; [[ $rc -eq $want ]] && ok "$name (código $rc)" || { bad "$name (código $rc, esperado $want)"; head -3 "$T/o.txt"; }; }
echo "== verify-rpms.sh"
exp 0 "RPM reales coinciden con la lista fijada" $D/verify-rpms.sh work/oci-drill/rpms
mkdir -p "$T/r"; cp work/oci-drill/rpms/*.rpm "$T/r/"; printf 'X' | dd of="$T/r/postgresql18-libs-18.6-1PGDG.rhel9.8.x86_64.rpm" bs=1 seek=1000 conv=notrunc 2>/dev/null
exp 1 "RPM alterado (1 byte) se detecta" $D/verify-rpms.sh "$T/r"
rm "$T/r/postgresql18-server-18.6-1PGDG.rhel9.8.x86_64.rpm"; exp 1 "RPM ausente se detecta" $D/verify-rpms.sh "$T/r"
mkdir -p "$T/e"; cp work/oci-drill/rpms/*.rpm "$T/e/"; echo x >"$T/e/extra.rpm"; exp 1 "RPM no listado (sobrante) se detecta" $D/verify-rpms.sh "$T/e"
exp 2 "directorio inexistente" $D/verify-rpms.sh "$T/no-existe"
echo "== ensure-swap.sh (DRY_RUN, meminfo simulada)"
printf 'MemTotal:         498000 kB\n' >"$T/mem-pequena"; printf 'MemTotal:        8000000 kB\n' >"$T/mem-grande"
DRY_RUN=1 MEMINFO="$T/mem-pequena" SWAPFILE="$T/swapf" $D/ensure-swap.sh >"$T/s1.txt" 2>&1 && grep -q "DRY: dd" "$T/s1.txt" && grep -q "DRY: swapon" "$T/s1.txt" && grep -q "DRY: añadir" "$T/s1.txt" && ok "RAM 486 MB: planea dd, mkswap, swapon y fstab" || { bad "swap RAM pequeña"; cat "$T/s1.txt"; }
DRY_RUN=1 MEMINFO="$T/mem-grande" SWAPFILE="$T/swapf" $D/ensure-swap.sh >"$T/s2.txt" 2>&1 && grep -q "no hace falta swap" "$T/s2.txt" && ! grep -q "DRY:" "$T/s2.txt" && ok "RAM 7,6 GB: no crea swap" || { bad "swap RAM grande"; cat "$T/s2.txt"; }
[[ ! -e "$T/swapf" ]] && ok "DRY_RUN no creó ningún archivo de swap" || bad "DRY_RUN creó archivo"
echo; echo "Resultado: $pass correctas, $failn fallidas"; [[ $failn -eq 0 ]]
