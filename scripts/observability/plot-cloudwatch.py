#!/usr/bin/env python3
"""Gráficos SVG verificables a partir de las SERIES ORIGINALES exportadas por export-cloudwatch.py (esquema 2). Cada gráfico muestra la fuente, el periodo UTC, la resolución OBSERVADA
(la real de los datos, que puede ser mayor que la pedida si CloudWatch ya los agregó) y el número de puntos. No interpola ni rellena: los huecos se dejan como huecos (la línea se corta si falta
más de 2,5 veces la resolución) y cada punto original se dibuja como marca. No usa red ni nube.
Uso: plot-cloudwatch.py --in work/observability/aws-cloudwatch.json --out docs/evidencias/multicloud/aws/AAAAMMDD-cloudwatch/graficos | --selftest"""
import argparse, datetime as dt, html, json, pathlib, sys

ap = argparse.ArgumentParser(); ap.add_argument("--in", dest="inp"); ap.add_argument("--out"); ap.add_argument("--selftest", action="store_true"); a = ap.parse_args()
UTC = dt.timezone.utc
def hhmm(t): return dt.datetime.fromtimestamp(t, UTC).strftime("%d-%b %H:%M")


def svg_chart(s, W=900, H=300):
    pts = sorted(s["points"]); xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
    x0, x1 = min(xs), max(xs); y0, y1 = min(0, min(ys)), max(ys) * 1.08 or 1; L, R, T, B = 70, 20, 62, 44
    fx = lambda x: L + (x - x0) / max(x1 - x0, 1) * (W - L - R); fy = lambda y: T + (1 - (y - y0) / max(y1 - y0, 1e-12)) * (H - T - B)
    res = s["observed_resolution_s"] or 0; gap = 2.5 * res if res else None
    segs, cur = [], []
    for (x, y), prev in zip(pts, [None] + xs[:-1]):
        if cur and gap and prev is not None and x - prev > gap: segs.append(cur); cur = []
        cur.append((fx(x), fy(y)))
    segs.append(cur)
    title = f'{s["namespace"]}/{s["metric"]} ({s["stat"]}) · recurso {s["resource"]}'
    sub = f'Fuente: CloudWatch GetMetricData (solo lectura) · {hhmm(x0)} a {hhmm(x1)} UTC · resolución observada {res} s (pedida {s["requested_period_s"]} s) · {len(pts)} puntos originales'
    flag = "" if res <= s["requested_period_s"] else f'  ⚠ CloudWatch ya agregó estos datos a {res} s'
    o = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" font-family="Helvetica, Arial, sans-serif" font-size="12"><rect width="{W}" height="{H}" fill="#fff"/>',
         f'<text x="{L}" y="20" font-size="14" font-weight="bold">{html.escape(title)}</text><text x="{L}" y="38" fill="#555">{html.escape(sub + flag)}</text>']
    for k in range(5):
        yv = y0 + (y1 - y0) * k / 4; yy = fy(yv); o.append(f'<line x1="{L}" y1="{yy:.1f}" x2="{W-R}" y2="{yy:.1f}" stroke="#e3e3e3"/><text x="{L-6}" y="{yy+4:.1f}" text-anchor="end" fill="#555">{yv:.3g}</text>')
    for k in range(5):
        xv = x0 + (x1 - x0) * k / 4; xx = fx(xv); o.append(f'<text x="{xx:.1f}" y="{H-24}" text-anchor="middle" fill="#555">{hhmm(int(xv))}</text>')
    for sg in segs:
        if len(sg) > 1: o.append('<polyline fill="none" stroke="#2b6cb0" stroke-width="1.4" points="' + " ".join(f"{x:.1f},{y:.1f}" for x, y in sg) + '"/>')
    for x, y in pts: o.append(f'<circle cx="{fx(x):.1f}" cy="{fy(y):.1f}" r="1.8" fill="#17406e"/>')
    o.append(f'<text x="{L}" y="{H-6}" fill="#777" font-size="11">Cada marca es un punto original; no se interpola ni se rellena. Los huecos se muestran como huecos.</text></svg>')
    return "\\n".join(o)


if a.selftest:
    s = {"namespace": "AWS/EC2", "metric": "CPUUtilization", "stat": "Average", "resource": "…abcd", "requested_period_s": 60, "observed_resolution_s": 60, "window": "w", "n": 4,
         "points": [[1792404000, 10.0], [1792404060, 12.0], [1792404120, 11.0], [1792405800, 40.0]]}   # el último punto deja un hueco de 28 min
    out = svg_chart(s); import xml.dom.minidom; xml.dom.minidom.parseString(out)
    assert out.count("<polyline") == 1 and out.count("<circle") == 4 and "no se interpola" in out   # el hueco corta la línea: 1 segmento de 3 puntos y 1 punto aislado
    print("selftest OK (SVG válido; los huecos no se interpolan; resolución y fuente rotuladas)"); sys.exit(0)
d = json.load(open(a.inp)); assert d.get("schema") == 2, "se requiere el esquema 2 (series originales)"
out = pathlib.Path(a.out); out.mkdir(parents=True, exist_ok=True); idx = []
for i, s in enumerate(d["series_original"]):
    if len(s["points"]) < 2: continue
    name = f'{i:03d}-{s["namespace"].replace("/", "_")}-{s["metric"]}-{s["resource"].strip("…")}.svg'
    (out / name).write_text(svg_chart(s)); idx.append(f'| [{name}]({name}) | {s["namespace"]}/{s["metric"]} ({s["stat"]}) | {s["resource"]} | {s["window"].replace(",", " → ")} | {s["observed_resolution_s"]} s | {s["n"]} |')
(out / "README.md").write_text("# Gráficos de CloudWatch (series originales)\\n\\nGenerados por `scripts/observability/plot-cloudwatch.py` desde `export-cloudwatch.py` (esquema 2). Sin interpolación. Resolución observada = la real de los datos.\\n\\n| Gráfico | Métrica | Recurso (enmascarado) | Ventana UTC | Resolución observada | Puntos |\\n|---|---|---|---|---:|---:|\\n" + "\\n".join(idx) + "\\n")
print(len(idx), "gráficos →", out)
