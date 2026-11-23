#!/usr/bin/env bash
# En la VM (root): ejecuta dnf con FALLO ACOTADO para VM pequeñas (T3, 22-nov-2026: dnf con TODOS los repositorios —«OCI Included Packages» pesa 190 MB— dejó una E2.1.Micro sin respuesta >20 min).
#   · SOLO repositorios mínimos (ol9_baseos_latest + ol9_appstream; si falta alguno, se detiene y lista los que hay, sin intentarlo con todos)
#   · cgroup con tope de memoria (si dnf lo supera lo mata el cgroup, no se congela el sistema) · prioridad mínima de CPU y E/S (sshd sigue respondiendo) · límite de tiempo
#   · sin dependencias débiles ni caché. Si una dependencia solo existe en ol9_addons, reintenta UNA vez con ese repositorio.
# Uso: safe-dnf.sh -y install <paquetes…>   Variables: DNF_MEM_MAX (640M) · DNF_SWAP_MAX (1G) · DNF_TIMEOUT (1500 s) · REPO_DIR (/etc/yum.repos.d) · DRY_RUN=1 (imprime el comando)
# Códigos: 0 correcto · 3 repositorios mínimos ausentes · 124 tiempo agotado · 137 muerto por límite de memoria · otro: código de dnf
set -uo pipefail
REPO_DIR="${REPO_DIR:-/etc/yum.repos.d}"; MEM="${DNF_MEM_MAX:-640M}"; SWP="${DNF_SWAP_MAX:-1G}"; TMO="${DNF_TIMEOUT:-1500}"
ids="$(cat "$REPO_DIR"/*.repo 2>/dev/null | sed -n 's/^\[\(.*\)\]$/\1/p' | sort -u)"
has() { grep -qx "$1" <<<"$ids"; }
for r in ol9_baseos_latest ol9_appstream; do has "$r" || { echo "ERROR: falta el repositorio mínimo «${r}». Repositorios disponibles: $(tr '\n' ' ' <<<"$ids")" >&2; exit 3; }; done
build() { local extra=("$@"); CMD=(); command -v systemd-run >/dev/null 2>&1 && CMD+=(systemd-run --scope -q -p "MemoryMax=$MEM" -p "MemorySwapMax=$SWP")
  CMD+=(nice -n 19); command -v ionice >/dev/null 2>&1 && CMD+=(ionice -c3); CMD+=(timeout "$TMO" dnf --disablerepo='*' --enablerepo=ol9_baseos_latest --enablerepo=ol9_appstream); for e in "${extra[@]}"; do [[ -n "$e" ]] && CMD+=(--enablerepo="$e"); done
  CMD+=(--setopt=install_weak_deps=False --setopt=keepcache=0); }
build ""; echo "memoria antes: $(free -m 2>/dev/null | awk '/^Mem:/{print $7" MB disponibles"}')"
if [[ "${DRY_RUN:-}" == "1" ]]; then echo "DRY: ${CMD[*]} $*"; exit 0; fi
t0=$(date +%s); out="$(mktemp)"; "${CMD[@]}" "$@" 2>&1 | tee "$out"; rc=${PIPESTATUS[0]}
if [[ $rc -ne 0 ]] && grep -qiE "nothing provides|No match for argument" "$out" && has ol9_addons; then
  echo "AVISO: dependencia ausente en los repositorios mínimos; se reintenta una vez con ol9_addons"; build ol9_addons; "${CMD[@]}" "$@" 2>&1 | tee "$out"; rc=${PIPESTATUS[0]}
fi
echo "dnf terminó con código $rc en $(( $(date +%s) - t0 )) s; memoria después: $(free -m 2>/dev/null | awk '/^Mem:/{print $7" MB disponibles"}')"; rm -f "$out"
case $rc in 124) echo "ERROR: dnf superó el límite de tiempo (${TMO} s)" >&2;; 137) echo "ERROR: dnf murió por el límite de memoria del cgroup (${MEM})" >&2;; esac; exit $rc
