#!/usr/bin/env python3
"""Compara la huella de datos de una base restaurada con una línea base. Lo usa run-from-mac.sh (y sirve a cualquier simulacro).
Uso:  compare-fingerprint.py --check <baseline.json> <clave>             # valida la línea base (sin tocar nada)
      compare-fingerprint.py <baseline.json> <clave> <huella-restaurada.txt>   # compara
Códigos de salida: 0 coincide · 1 la huella restaurada difiere · 2 línea base/archivo inválido o ausente (se detecta ANTES de pedir ninguna frase de paso).
La huella son las claves que imprime scripts/multicloud/fingerprint.sql; el archivo restaurado contiene líneas «clave=valor» (se ignoran las demás)."""
import json, re, sys
from pathlib import Path

SQL = Path(__file__).with_name("fingerprint.sql")
EXPECTED = set(re.findall(r"'([a-z_0-9]+)='", SQL.read_text())) if SQL.exists() else set()


def load_baseline(path, key):
    try:
        data = json.loads(Path(path).read_text())
    except FileNotFoundError:
        _die(f"no existe el archivo de línea base: {path}")
    except json.JSONDecodeError as e:
        _die(f"la línea base no es JSON válido: {e}")
    baselines = data.get("baselines")
    if not isinstance(baselines, dict) or key not in baselines:
        _die(f"la clave de línea base «{key}» no existe en {path} (disponibles: {', '.join(sorted(baselines or {})) or 'ninguna'})")
    fp = baselines[key].get("fingerprint")
    if not isinstance(fp, dict) or not fp:
        _die(f"la línea base «{key}» no tiene «fingerprint»")
    missing = sorted(EXPECTED - set(fp))
    if missing:
        _die(f"la línea base «{key}» no incluye las claves esperadas de fingerprint.sql: {', '.join(missing)}")
    return {k: str(v) for k, v in fp.items()}


def _die(msg):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(2)


def main(argv):
    if len(argv) == 3 and argv[0] == "--check":
        fp = load_baseline(argv[1], argv[2])
        print(f"OK    línea base «{argv[2]}» válida ({len(fp)} claves)")
        return 0
    if len(argv) != 3:
        _die("uso: compare-fingerprint.py [--check] <baseline.json> <clave> [huella-restaurada.txt]")
    base = load_baseline(argv[0], argv[1])
    try:
        text = Path(argv[2]).read_text()
    except FileNotFoundError:
        _die(f"no existe la huella restaurada: {argv[2]}")
    now = dict(l.strip().split("=", 1) for l in text.splitlines() if "=" in l)
    if not now:
        _die("la huella restaurada está vacía (la restauración no produjo claves)")
    diff = {k: (base[k], now.get(k)) for k in base if base[k] != now.get(k)}
    if diff:
        print("FALLÓ huella (esperado, obtenido):", diff)
        return 1
    print(f"OK    huella idéntica a la línea base ({len(base)} claves)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
