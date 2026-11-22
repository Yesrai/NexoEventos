#!/usr/bin/env python3
"""T5 — compilador de evidencias (NO habla con ninguna nube). Convierte lo que producen las comprobaciones reales de la ventana de T5 en los 9 criterios de ops_center/criterios/T5.json.
PASS solo si TODAS las mediciones existen y cumplen; una ausente o fallida ⇒ nunca PASS. Un fallo se registra como FAIL con su causa; no se reinterpretan criterios.
Subcomandos:
  azure --history probe-history.jsonl --desde UTC --hasta UTC --out azure.json     (continuidad observada desde Azure)
  evidencia --medidas DIR [--evidence-root work/evidencias]
Archivos en --medidas: resultado.json y solicitudes.json (de scripts/cloud/v2-failover-test.py --allow-replacement), zonas.json, datos.json, azure.json, limpieza.json, costos.json ({"usd": n})."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from ops_center import evidence as E  # noqa: E402

FMT = "%Y-%m-%dT%H:%M:%SZ"
HEALTH_PATHS = ("/livez", "/healthz")


def jload(p):
    try:
        return json.loads(Path(p).read_text())
    except (OSError, ValueError, TypeError):
        return None


def derive(res, reqs):
    """Valores de los criterios que salen del resultado del experimento. Devuelve {criterio: valor}; lo que no se pueda medir NO aparece."""
    v = {}
    if not isinstance(res, dict):
        return v
    ev, fin = res.get("events") or {}, res.get("final") or {}
    abort = ev.get("abort_reason")
    if isinstance(reqs, list) and reqs:
        h = [r for r in reqs if r.get("path") in HEALTH_PATHS]
        if h and not abort:
            v["disponibilidad_livez_pct"] = round(100 * sum(1 for r in h if r.get("status") == 200) / len(h), 2)
    if ev.get("detection_after_stop_s") is not None and not abort:
        v["deteccion_s"] = float(ev["detection_after_stop_s"])
    victim = ev.get("victim"); alb = fin.get("alb") or {}
    sustituida = bool(victim and ev.get("allow_replacement") is True and not abort and victim not in alb and len(alb) == 2 and all(s == "healthy" for s in alb.values())
                      and any("aunch" in str(a) for a in (fin.get("asg_activities_new") or [])))
    v["ec2_reemplazada_por_asg"] = sustituida
    if sustituida and ev.get("capacity_restored_after_stop_s") is not None:
        v["sustitucion_sana_s"] = float(ev["capacity_restored_after_stop_s"])
    return v


def cmd_azure(a):
    t0, t1 = datetime.strptime(a.desde, FMT), datetime.strptime(a.hasta, FMT); rows = []
    for l in Path(a.history).read_text().splitlines():
        try:
            r = json.loads(l); t = datetime.strptime(r["t"], FMT)
        except (ValueError, KeyError):
            continue
        if t0 <= t <= t1:
            rows.append((t, r))
    rows.sort(key=lambda x: x[0]); gaps = [(rows[i + 1][0] - rows[i][0]).total_seconds() for i in range(len(rows) - 1)]
    estados = {}
    for _, r in rows:
        estados[r["aws"]] = estados.get(r["aws"], 0) + 1
    real = bool(rows) and all(any(s.get("code") is not None for s in r.get("sondas", {}).get("aws", [])) for _, r in rows)
    res = {"ciclos": len(rows), "hueco_max_s": max(gaps) if gaps else None, "estados_aws": estados, "primer_ciclo": rows[0][1]["t"] if rows else None, "ultimo_ciclo": rows[-1][1]["t"] if rows else None,
           "sondas_reales": real, "cobertura_s": (rows[-1][0] - rows[0][0]).total_seconds() if len(rows) > 1 else 0,
           "ok": bool(len(rows) >= 5 and gaps and max(gaps) <= 120 and real), "utc": datetime.now(timezone.utc).strftime(FMT)}
    Path(a.out).parent.mkdir(parents=True, exist_ok=True); Path(a.out).write_text(json.dumps(res, indent=1)); print(json.dumps(res)); return 0 if res["ok"] else 1


def cmd_evidencia(a):
    d = Path(a.medidas); tpl = json.loads((ROOT / "ops_center/criterios/T5.json").read_text())
    run = E.EvidenceRun.start(a.evidence_root, "T5", tpl["title"], tpl["criteria"])
    v = derive(jload(d / "resultado.json"), jload(d / "solicitudes.json"))
    for cid, name in (("dos_zonas_y_reparto", "zonas"), ("perdida_de_datos", "datos"), ("azure_observa_continuidad", "azure"), ("limpieza_verificada", "limpieza")):
        m = jload(d / f"{name}.json")
        if m is not None:
            v[cid] = bool(m.get("ok") is True)
    cs = jload(d / "costos.json")
    if cs is not None and isinstance(cs.get("usd"), (int, float)):
        v["costo_dentro_del_techo"] = float(cs["usd"])
    for k, x in v.items():
        run.value(k, x, "automático desde work/t5/medidas")
    for f in sorted(d.glob("*.json")):
        if f.name != "solicitudes.json":
            run.attach(f, redacted=True)
    r = run.finish(); print(f"veredicto T5: {r['veredicto']} · {run.dir}"); return 0 if r["veredicto"] == "PASS" else 1


def main(argv=None):
    ap = argparse.ArgumentParser(); sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("azure"); p.add_argument("--history", required=True); p.add_argument("--desde", required=True); p.add_argument("--hasta", required=True); p.add_argument("--out", required=True)
    p = sub.add_parser("evidencia"); p.add_argument("--medidas", required=True); p.add_argument("--evidence-root", default="work/evidencias")
    a = ap.parse_args(argv)
    return {"azure": cmd_azure, "evidencia": cmd_evidencia}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
