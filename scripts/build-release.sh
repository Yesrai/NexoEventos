#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
GIT_BIN=""
for git_candidate in "$(command -v git 2>/dev/null || true)" /usr/bin/git; do
  if [[ -x "$git_candidate" ]] && "$git_candidate" --version >/dev/null 2>&1; then
    GIT_BIN="$git_candidate"
    break
  fi
done
[[ -n "$GIT_BIN" ]] || { echo "No se encontró un Git ejecutable." >&2; exit 1; }
NODE_BIN_DIR=""
for node_dir in /opt/homebrew/opt/node@24/bin "$(dirname "$(command -v node 2>/dev/null || echo /nonexistent/node)")"; do
  if [[ -x "$node_dir/node" && -x "$node_dir/npm" ]] && \
    [[ "$($node_dir/node --eval 'process.stdout.write(process.versions.node.split(".")[0])')" == 24 ]]; then
    NODE_BIN_DIR="$node_dir"
    break
  fi
done
[[ -n "$NODE_BIN_DIR" ]] || {
  echo "Se requiere Node.js 24 para crear el artefacto; no se modificaron versiones globales." >&2
  exit 1
}
export PATH="$NODE_BIN_DIR:$PATH"
[[ -z "$($GIT_BIN status --porcelain --untracked-files=no)" ]] || {
  echo "Hay cambios rastreados sin commit; crea y revisa el commit antes de empaquetar." >&2
  exit 1
}
RELEASE_ID="$($GIT_BIN rev-parse HEAD)"
OUT="$ROOT/work/releases/nexoeventos-${RELEASE_ID}.tar.gz"
STAGE="$(mktemp -d)"
cleanup() { rm -rf -- "$STAGE"; }
trap cleanup EXIT

npm --prefix frontend ci
npm --prefix frontend run build
"$GIT_BIN" archive HEAD | tar -x -C "$STAGE"
rm -rf -- "$STAGE/frontend/dist"
cp -R "$ROOT/frontend/dist" "$STAGE/frontend/dist"
mkdir -p "$(dirname "$OUT")"
umask 077
tar -czf "$OUT" -C "$STAGE" .
shasum -a 256 "$OUT" >"$OUT.sha256"
echo "Artefacto protegido creado para $RELEASE_ID en work/releases/."
