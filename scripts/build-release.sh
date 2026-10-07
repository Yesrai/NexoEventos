#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
[[ -z "$(git status --porcelain --untracked-files=no)" ]] || {
  echo "Hay cambios rastreados sin commit; crea y revisa el commit antes de empaquetar." >&2
  exit 1
}
RELEASE_ID="$(git rev-parse HEAD)"
OUT="$ROOT/work/releases/nexoeventos-${RELEASE_ID}.tar.gz"
STAGE="$(mktemp -d)"
cleanup() { rm -rf -- "$STAGE"; }
trap cleanup EXIT

npm --prefix frontend ci
npm --prefix frontend run build
git archive HEAD | tar -x -C "$STAGE"
rm -rf -- "$STAGE/frontend/dist"
cp -R "$ROOT/frontend/dist" "$STAGE/frontend/dist"
mkdir -p "$(dirname "$OUT")"
umask 077
tar -czf "$OUT" -C "$STAGE" .
shasum -a 256 "$OUT" >"$OUT.sha256"
echo "Artefacto protegido creado para $RELEASE_ID en work/releases/."
