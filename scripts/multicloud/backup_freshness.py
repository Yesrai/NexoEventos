#!/usr/bin/env python3
"""Frescura del respaldo (B-20): lee cycles.jsonl de backup_cycle.py y falla si el último ciclo correcto es más viejo que el umbral.
Códigos: 0 fresco · 1 caduco (o el último intento falló y el correcto es viejo) · 2 desconocido (sin registro o ilegible).
Salida de una línea, sin secretos. `--now` permite simular el reloj en las pruebas.
`--env` evalúa solo los registros de ese entorno (un directorio compartido no puede ocultar que un entorno está caduco); `--config` lee state_dir, env y
max_age_min del mismo perfil JSON que usa backup_cycle.py. `--report` imprime en JSON las estadísticas para medir el RPO (C-04): huecos entre ciclos,
duración y el peor caso (fin del siguiente respaldo - inicio de los datos del anterior).
Uso: backup_freshness.py --state-dir /var/lib/nexoeventos/backup --max-age-min 90 [--env aws-academy] [--report]"""
from __future__ import annotations  # Amazon Linux 2023 trae `python3` = 3.9: las anotaciones `X | None` no deben evaluarse en tiempo de ejecución

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


def read_records(state_dir: Path, env: str | None = None) -> list[dict]:
    p = state_dir / "cycles.jsonl"
    out = []
    for line in p.read_text().splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        datetime.strptime(r["finished_at"], "%Y-%m-%dT%H:%M:%SZ")  # valida el formato
        if env is None or r.get("env") == env:
            out.append(r)
    return out


def parse_t(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def rpo_report(recs: list[dict], now: datetime) -> dict:
    ok = [r for r in recs if r.get("ok")]
    gaps, worst = [], 0.0
    for prev, cur in zip(ok, ok[1:]):
        s_prev = parse_t(prev.get("started_at", prev["finished_at"]))
        gaps.append((parse_t(cur.get("started_at", cur["finished_at"])) - s_prev).total_seconds() / 60)
        worst = max(worst, (parse_t(cur["finished_at"]) - s_prev).total_seconds() / 60)
    tail = (now - parse_t(ok[-1].get("started_at", ok[-1]["finished_at"]))).total_seconds() / 60 if ok else None
    durs = [r["duration_s"] for r in ok if "duration_s" in r]
    return {"cycles_ok": len(ok), "cycles_failed": len(recs) - len(ok), "gap_min_mean": round(sum(gaps) / len(gaps), 2) if gaps else None,
            "gap_min_max": round(max(gaps), 2) if gaps else None, "rpo_worst_case_min": round(worst, 2) if gaps else None,
            "since_last_data_snapshot_min": round(tail, 2) if tail is not None else None,
            "duration_s_max": max(durs) if durs else None, "duration_s_mean": round(sum(durs) / len(durs), 2) if durs else None}


def evaluate(state_dir: Path, max_age_min: float, now: datetime, env: str | None = None) -> tuple[int, str]:
    p = state_dir / "cycles.jsonl"
    if not p.exists():
        return 2, "DESCONOCIDO: no hay registro de ciclos."
    last_ok, last_fail_after = None, False
    try:
        for r in read_records(state_dir, env):
            t = parse_t(r["finished_at"])
            if r.get("ok"):
                last_ok, last_fail_after = t, False
            else:
                last_fail_after = True
    except (ValueError, KeyError, json.JSONDecodeError):
        return 2, "DESCONOCIDO: registro ilegible."
    if last_ok is None:
        return 1, "CADUCO: no hay ningún ciclo correcto."
    age = (now - last_ok).total_seconds() / 60
    if age < 0:
        return 2, "DESCONOCIDO: el último ciclo está en el futuro (reloj incoherente)."
    extra = " (el último intento falló)" if last_fail_after else ""
    if age > max_age_min:
        return 1, f"CADUCO: último respaldo correcto hace {age:.0f} min > {max_age_min:g} min{extra}."
    return 0, f"FRESCO: último respaldo correcto hace {age:.0f} min <= {max_age_min:g} min{extra}."


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config")
    ap.add_argument("--state-dir")
    ap.add_argument("--env")
    ap.add_argument("--max-age-min", type=float)
    ap.add_argument("--report", action="store_true", help="estadísticas JSON para medir el RPO")
    ap.add_argument("--now", help="ISO UTC (solo pruebas)")
    a = ap.parse_args(argv)
    if a.config:
        try:
            cfg = json.loads(Path(a.config).read_text())
        except (OSError, ValueError):
            print("DESCONOCIDO: no se pudo leer --config."); return 2
        a.state_dir = a.state_dir or cfg.get("state_dir"); a.env = a.env or cfg.get("env")
        a.max_age_min = a.max_age_min if a.max_age_min is not None else cfg.get("max_age_min")
    if not a.state_dir or a.max_age_min is None:
        print("DESCONOCIDO: faltan --state-dir y --max-age-min (o un --config que los tenga)."); return 2
    now = datetime.strptime(a.now, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc) if a.now else datetime.now(timezone.utc)
    if a.report:
        try:
            print(json.dumps(rpo_report(read_records(Path(a.state_dir), a.env), now), indent=1))
            return 0
        except (OSError, ValueError, KeyError):
            print("DESCONOCIDO: registro ausente o ilegible."); return 2
    code, msg = evaluate(Path(a.state_dir), a.max_age_min, now, a.env)
    print(msg)
    return code


if __name__ == "__main__":
    sys.exit(main())
