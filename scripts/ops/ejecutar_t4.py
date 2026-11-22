#!/usr/bin/env python3
"""T4 — compilador de evidencias. Lee las mediciones de work/t4/medidas/*.json (cada una la produce una comprobación concreta de la ventana de T4) y evalúa los 18 criterios de ops_center/criterios/T4.json.
Una medición AUSENTE deja el criterio sin medir ⇒ veredicto PARCIAL (nunca PASS). No toca ninguna nube.
Subcomandos:
  colector  --history probe-history.jsonl --desde UTC --hasta UTC --out medidas/colector.json   (ciclos, huecos, estados, origen, tres nubes)
  evidencia --medidas DIR [--evidence-root work/evidencias]
Archivos esperados en --medidas (todos con «ok»: bool y «utc»): inventario, despliegue, servicios, panel_sin_aws, colector, grafana, alerta, correo, testigo_auth, testigo_persistencia, auditoria, bloqueo, nsg, memoria,
reversion, costos ({"usd": n}), vm_final."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from ops_center import evidence as E  # noqa: E402

MAP = {"inventario_previo_solo_lectura": "inventario", "despliegue_aditivo_intacto": "despliegue", "servicios_activos": "servicios", "panel_con_aws_apagado": "panel_sin_aws",
       "grafana_muestra_sondas": "grafana", "alerta_real_disparada": "alerta", "correo_recibido": "correo", "testigo_autenticacion_y_roles": "testigo_auth",
       "testigo_persistencia_y_firma": "testigo_persistencia", "auditoria_integra": "auditoria", "ejecucion_real_bloqueada": "bloqueo", "nsg_sin_cambios_inbound": "nsg",
       "sin_oom_ni_saturacion": "memoria", "reversion_sonda_prueba_retirada": "reversion", "vm_desasignada_apagado_restaurado": "vm_final"}
FMT = "%Y-%m-%dT%H:%M:%SZ"


def jload(p):
    try:
        return json.loads(Path(p).read_text())
    except (OSError, ValueError, TypeError):
        return None


def cmd_colector(a):
    t0, t1 = datetime.strptime(a.desde, FMT), datetime.strptime(a.hasta, FMT)
    rows = []
    for l in Path(a.history).read_text().splitlines():
        try:
            r = json.loads(l); t = datetime.strptime(r["t"], FMT)
        except (ValueError, KeyError):
            continue
        if t0 <= t <= t1:
            rows.append((t, r))
    rows.sort(key=lambda x: x[0])
    gaps = [(rows[i + 1][0] - rows[i][0]).total_seconds() for i in range(len(rows) - 1)]
    span = (rows[-1][0] - rows[0][0]).total_seconds() if len(rows) > 1 else 0
    real = bool(rows) and all(all(any(s.get("error") != "solo https" for s in r["sondas"].get(n, [])) and r["sondas"].get(n) for n in ("aws", "oci")) for _, r in rows)
    oci_standby_ok = bool(rows) and all(r["oci"] == "ADVERTENCIA" for _, r in rows)        # OCI en espera: nunca «OK» por defecto
    snap = jload(a.snapshot) if a.snapshot else None
    nubes = (snap or {}).get("clouds") or {}
    tres = bool(nubes) and all(nubes.get(n, {}).get("estado") in ("OK", "ADVERTENCIA", "ERROR") and nubes.get(n, {}).get("origen") in ("cloud_verificado", "local") for n in ("aws", "oci", "azure")) and bool(snap.get("observed_at"))
    res = {"ciclos": len(rows), "duracion_s": span, "hueco_max_s": max(gaps) if gaps else None, "estados_aws": sorted({r["aws"] for _, r in rows}), "estados_oci": sorted({r["oci"] for _, r in rows}),
           "sondas_reales": real, "oci_en_espera_advertencia": oci_standby_ok, "tres_nubes_con_origen": tres,
           "ok": bool(len(rows) >= 10 and span >= 600 and gaps and max(gaps) <= 120 and real and oci_standby_ok), "utc": datetime.now(timezone.utc).strftime(FMT)}
    Path(a.out).parent.mkdir(parents=True, exist_ok=True); Path(a.out).write_text(json.dumps(res, indent=1)); print(json.dumps(res)); return 0 if res["ok"] else 1


def cmd_alerta(a):
    """Una alerta REAL: problema de Zabbix del host de prueba (problem.get) + línea «publicada» del script de alertas posterior al problema + el host realmente falló (no simulado)."""
    pr = jload(a.problemas) or []; log = [json.loads(l) for l in Path(a.log).read_text().splitlines() if l.strip().startswith("{")] if Path(a.log).exists() else []
    mios = [p for p in pr if "t4-sonda-prueba" in json.dumps(p) or "sonda-t4" in json.dumps(p)]
    t_prob = min((int(p["clock"]) for p in mios if str(p.get("clock", "")).isdigit()), default=None)
    pub = [l for l in log if l.get("accion") == "publicada" and t_prob is not None and datetime.strptime(l["utc"], FMT).replace(tzinfo=timezone.utc).timestamp() >= t_prob]
    res = {"ok": bool(mios and pub), "problemas": len(mios), "publicadas": len(pub), "t_problema_utc": datetime.fromtimestamp(t_prob, timezone.utc).strftime(FMT) if t_prob else None,
           "t_publicada_utc": pub[0]["utc"] if pub else None, "utc": datetime.now(timezone.utc).strftime(FMT)}
    Path(a.out).parent.mkdir(parents=True, exist_ok=True); Path(a.out).write_text(json.dumps(res, indent=1)); print(json.dumps(res)); return 0 if res["ok"] else 1


def cmd_correo(a):
    """El correo solo cuenta con CONFIRMACIÓN HUMANA: quién lo confirma, asunto recibido y hora. Sin ellos, ok=false."""
    ok = bool(a.confirmado_por.strip() and a.asunto.strip() and a.hora_recepcion_utc.strip())
    res = {"ok": ok, "confirmado_por": a.confirmado_por.strip(), "asunto": a.asunto.strip(), "hora_recepcion_utc": a.hora_recepcion_utc.strip(), "utc": datetime.now(timezone.utc).strftime(FMT)}
    Path(a.out).parent.mkdir(parents=True, exist_ok=True); Path(a.out).write_text(json.dumps(res, indent=1)); print(json.dumps(res)); return 0 if ok else 1


def cmd_costos(a):
    cu = a.horas * a.tarifa_hora + a.snapshot_gb_usados * 0.05 * (a.snapshot_dias / 30.0) + a.extra_usd
    res = {"usd": round(cu, 3), "horas": a.horas, "tarifa_hora": a.tarifa_hora, "snapshot_gb": a.snapshot_gb_usados, "snapshot_dias": a.snapshot_dias, "tipo": "estimación con tarifa pública (el cargo real se confirma en el portal)", "utc": datetime.now(timezone.utc).strftime(FMT)}
    Path(a.out).parent.mkdir(parents=True, exist_ok=True); Path(a.out).write_text(json.dumps(res, indent=1)); print(json.dumps(res)); return 0


def cmd_evidencia(a):
    d = Path(a.medidas); tpl = json.loads((ROOT / "ops_center/criterios/T4.json").read_text())
    run = E.EvidenceRun.start(a.evidence_root, "T4", tpl["title"], tpl["criteria"])
    v = {}
    for cid, name in MAP.items():
        m = jload(d / f"{name}.json")
        if m is not None:
            v[cid] = bool(m.get("ok") is True)
    cr = jload(d / "correo.json")
    if cr is not None:
        v["correo_recibido"] = bool(cr.get("ok") is True and str(cr.get("confirmado_por", "")).strip() and str(cr.get("asunto", "")).strip() and str(cr.get("hora_recepcion_utc", "")).strip())
    col = jload(d / "colector.json")
    if col is not None:
        v["sondas_reales_continuas"] = bool(col.get("ok") is True)
        v["tarjetas_tres_nubes_con_origen"] = bool(col.get("tres_nubes_con_origen", False))
    cs = jload(d / "costos.json")
    if cs is not None and isinstance(cs.get("usd"), (int, float)):
        v["costos_dentro_de_presupuesto"] = float(cs["usd"])
    for k, x in v.items():
        run.value(k, x, "automático desde work/t4/medidas")
    for f in sorted(d.glob("*.json")):
        run.attach(f, redacted=True)
    r = run.finish(); print(f"veredicto T4: {r['veredicto']} · {run.dir}"); return 0 if r["veredicto"] == "PASS" else 1


def main(argv=None):
    ap = argparse.ArgumentParser(); sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("colector"); p.add_argument("--history", required=True); p.add_argument("--desde", required=True); p.add_argument("--hasta", required=True); p.add_argument("--out", required=True); p.add_argument("--snapshot", help="cloud-status.json final")
    p = sub.add_parser("alerta"); p.add_argument("--problemas", required=True); p.add_argument("--log", required=True); p.add_argument("--out", required=True)
    p = sub.add_parser("correo"); p.add_argument("--confirmado-por", default=""); p.add_argument("--asunto", default=""); p.add_argument("--hora-recepcion-utc", default=""); p.add_argument("--out", required=True)
    p = sub.add_parser("costos"); p.add_argument("--horas", type=float, required=True); p.add_argument("--tarifa-hora", type=float, default=0.108); p.add_argument("--snapshot-gb-usados", type=float, default=0.0)
    p.add_argument("--snapshot-dias", type=float, default=30.0); p.add_argument("--extra-usd", type=float, default=0.0); p.add_argument("--out", required=True)
    p = sub.add_parser("evidencia"); p.add_argument("--medidas", required=True); p.add_argument("--evidence-root", default="work/evidencias")
    a = ap.parse_args(argv)
    return {"colector": cmd_colector, "alerta": cmd_alerta, "correo": cmd_correo, "costos": cmd_costos, "evidencia": cmd_evidencia}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
