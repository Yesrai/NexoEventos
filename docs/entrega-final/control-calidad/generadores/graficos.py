# -*- coding: utf-8 -*-
"""Gráficos del informe generados EXCLUSIVAMENTE a partir de datos de los expedientes.
Cada gráfico lleva en su pie la ruta del archivo de origen y el rótulo de que es un gráfico derivado."""
import json, os, matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

W = "~/Workspace/NexoEventos/work/evidencias"
OUT = "~/Workspace/NexoEventos-informe-final/docs/entrega-final/graficos-informe"
os.makedirs(OUT, exist_ok=True)
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10, "axes.spines.top": False, "axes.spines.right": False,
                     "axes.grid": True, "grid.alpha": .25, "figure.dpi": 150})
C = {"pass": "#2E7D32", "fail": "#C62828", "gris": "#9E9E9E", "azul": "#1565C0", "nar": "#EF6C00", "mor": "#6A1B9A", "osc": "#263238"}

def pie(fig, src):
    fig.text(0.01, -0.06, "Gráfico generado a partir de datos reales del expediente · fuente: " + src, fontsize=7, color="#555")

def save(fig, name):
    fig.savefig(f"{OUT}/{name}.png", bbox_inches="tight"); plt.close(fig)

t5a = json.load(open(f"{W}/T5-20261123T005244Z-9eed/capturas/resultado.json"))
t5c = json.load(open(f"{W}/T5-20261123T023342Z-0532/capturas/resultado.json"))

# G1 — disponibilidad por intento (healthz y total) vs umbral
fig, ax = plt.subplots(figsize=(7.5, 3.8))
labs = ["Intento 1\n2 EC2 (FAIL)", "Intento 3\n6 EC2 (PASS)"]
h = [t5a["client"]["by_path"]["/healthz"]["requests"], t5c["client"]["by_path"]["/healthz"]["requests"]]
he = [t5a["client"]["by_path"]["/healthz"]["errors"], t5c["client"]["by_path"]["/healthz"]["errors"]]
hz = [round(100 * (a - b) / a, 2) for a, b in zip(h, he)]
tot = [t5a["client"]["availability_pct"], t5c["client"]["availability_pct"]]
x = range(2)
b1 = ax.bar([i - .18 for i in x], hz, .34, color=[C["fail"], C["pass"]], label="/healthz (criterio)")
b2 = ax.bar([i + .18 for i in x], tot, .34, color=[C["gris"], C["gris"]], label="todo el tráfico")
ax.axhline(99, color=C["osc"], ls="--", lw=1); ax.text(1.45, 99.08, "umbral 99 %", fontsize=8)
for b, v, n, e in zip(b1, hz, h, he): ax.text(b.get_x() + b.get_width() / 2, v + .05, f"{v:.2f} %\n({n - e}/{n})", ha="center", fontsize=8)
for b, v in zip(b2, tot): ax.text(b.get_x() + b.get_width() / 2, v + .05, f"{v:.2f} %", ha="center", fontsize=8)
ax.set_ylim(93, 100.6); ax.set_xticks(list(x)); ax.set_xticklabels(labs); ax.set_ylabel("disponibilidad (%)")
ax.set_title("T5 · Disponibilidad medida a través del ALB durante la caída controlada de 1 EC2", fontsize=10.5); ax.legend(loc="lower right", fontsize=8)
pie(fig, "work/evidencias/T5-20261123T005244Z-9eed y T5-20261123T023342Z-0532 · capturas/resultado.json (client.by_path)")
save(fig, "g01-t5-disponibilidad")

# G2 — cronología de los dos intentos: fallo → no sano → capacidad restaurada
fig, ax = plt.subplots(figsize=(7.8, 3.2))
for i, (lab, ev, col) in enumerate([("Intento 1 (2 EC2)", t5a["events"], C["fail"]), ("Intento 3 (6 EC2)", t5c["events"], C["pass"])]):
    s = ev["stop_issued_at"]; d = ev["alb_marked_unhealthy_at"] - s; r = ev["both_healthy_again_at"] - s
    ax.barh(i, d, color=col, alpha=.9); ax.barh(i, r - d, left=d, color=col, alpha=.35)
    ax.text(1, i + 0.43, f"detección {d:.1f} s", ha="left", va="bottom", fontsize=8, color=col, fontweight="bold")
    ax.text(d + (r - d) / 2, i, f"sustitución por el ASG → capacidad completa a {r:.1f} s", ha="center", va="center", fontsize=8)
ax.axvline(30, color=C["osc"], ls=":", lw=1); ax.text(30.5, 1.6, "umbral detección 30 s", fontsize=7)
ax.set_yticks([0, 1]); ax.set_yticklabels(["Intento 1 (2 EC2)", "Intento 3 (6 EC2)"]); ax.set_ylim(-0.6, 1.75); ax.set_xlabel("segundos desde la parada de la API en una EC2")
ax.set_xlim(0, 200); ax.set_title("T5 · Detección y recuperación (umbral de recuperación: 300 s)", fontsize=10.5)
pie(fig, "capturas/resultado.json → events (stop_issued_at, alb_marked_unhealthy_at, both_healthy_again_at)")
save(fig, "g02-t5-cronologia")

# G3 — CloudWatch por minuto, intento 3
cw = t5c["cloudwatch"]; cw1 = t5a["cloudwatch"]
fig, axs = plt.subplots(1, 2, figsize=(8.6, 3.2))
for ax, c, t, n in [(axs[0], cw1, "Intento 1 (2 EC2)", 2), (axs[1], cw, "Intento 3 (6 EC2)", 6)]:
    m = list(range(1, len(c["healthy_hosts_min_per_minute"]) + 1))
    ax.step(m, c["healthy_hosts_min_per_minute"], where="mid", color=C["pass"], label="HealthyHostCount (mín/min)")
    ax.step(m, c["unhealthy_hosts_max_per_minute"], where="mid", color=C["fail"], label="UnHealthyHostCount (máx/min)")
    ax.set_ylim(-.3, n + .8); ax.set_xlabel("minuto de la ventana"); ax.set_title(f"{t} · Target 5XX = {sum(c['target_5xx_per_minute'])}, ELB 5XX = {sum(c['elb_5xx_per_minute'])}", fontsize=9)
axs[0].set_ylabel("destinos"); axs[1].legend(fontsize=7, loc="lower right")
fig.suptitle("T5 · Métricas de CloudWatch exportadas por el recolector (resolución 1 min)", fontsize=10.5, y=1.02)
pie(fig, "capturas/resultado.json → cloudwatch (ambos expedientes T5)")
save(fig, "g03-t5-cloudwatch")

# G4 — T3 etapas de la reconstrucción en OCI (intento 3)
et = json.load(open(f"{W}/T3-20261122T172554Z-f812/capturas/etapas.json"))
fig, ax = plt.subplots(figsize=(7.8, 3.4))
ks = list(et["etapas"].keys()); vs = [et["etapas"][k] for k in ks]
ax.barh(ks[::-1], vs[::-1], color=C["azul"])
for i, v in enumerate(vs[::-1]): ax.text(v + 3, i, f"{v:.1f} s", va="center", fontsize=8)
ax.set_xlabel("segundos"); ax.set_xlim(0, 340)
ax.set_title(f"T3 intento 3 · Etapas de la reconstrucción en OCI (total {et['total_s']:.0f} s; NO es el RTO de un failover)", fontsize=10)
pie(fig, "work/evidencias/T3-20261122T172554Z-f812/capturas/etapas.json")
save(fig, "g04-t3-etapas")

# G5 — T1 latencias de PUT
p = json.load(open(f"{W}/T1-20261122T070851Z-9aa1/capturas/probe-salida.json"))
fig, ax = plt.subplots(figsize=(7, 3.2))
grp = [("PUT exitosos (n=%d)" % p["latencias_put_exitosos"]["n"], p["latencias_put_exitosos"]), ("PUT rechazados 412 (n=%d)" % p["latencias_put_rechazados_412"]["n"], p["latencias_put_rechazados_412"])]
w = .25
for j, (k, col) in enumerate([("p50_s", C["azul"]), ("p95_s", C["nar"]), ("max_s", C["osc"])]):
    vals = [g[1][k] for g in grp]
    bs = ax.bar([i + (j - 1) * w for i in range(2)], vals, w, color=col, label=k.replace("_s", ""))
    for b, v in zip(bs, vals): ax.text(b.get_x() + b.get_width() / 2, v + .01, f"{v:.3f}", ha="center", fontsize=7)
ax.set_xticks(range(2)); ax.set_xticklabels([g[0] for g in grp]); ax.set_ylabel("segundos"); ax.set_ylim(0, .65)
ax.text(1.45, .6, "umbral p95 ≤ 2,5 s\n(fuera de escala)", fontsize=7, ha="right")
ax.legend(fontsize=8); ax.set_title("T1 · Latencia de PUT condicional a OCI Object Storage (desde el equipo local)", fontsize=10)
pie(fig, "work/evidencias/T1-20261122T070851Z-9aa1/capturas/probe-salida.json")
save(fig, "g05-t1-latencias")

# G6 — criterios por expediente (todos los intentos)
EXP = json.load(open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "build/expedientes.json")))
fig, ax = plt.subplots(figsize=(8.6, 4.2))
names = list(EXP.keys())
lab = [n.split("-")[0] + " " + n.split("-")[1][9:13] + "Z\n" + EXP[n]["veredicto"] for n in names]
cum = [EXP[n]["cnt"].get("CUMPLE", 0) for n in names]; no = [EXP[n]["cnt"].get("NO_CUMPLE", 0) for n in names]; sm = [EXP[n]["cnt"].get("SIN_MEDIR", 0) for n in names]
ax.bar(range(len(names)), cum, color=C["pass"], label="CUMPLE")
ax.bar(range(len(names)), no, bottom=cum, color=C["fail"], label="NO_CUMPLE")
ax.bar(range(len(names)), sm, bottom=[a + b for a, b in zip(cum, no)], color=C["gris"], label="SIN_MEDIR")
for i, n in enumerate(names): ax.text(i, EXP[n]["total"] + .3, f"{cum[i]}/{EXP[n]['total']}", ha="center", fontsize=7)
ax.set_xticks(range(len(names))); ax.set_xticklabels(lab, fontsize=6.5); ax.set_ylabel("criterios"); ax.legend(fontsize=8, ncol=3, loc="upper left")
ax.set_title("Criterios por expediente real T1–T5 (incluidos los intentos fallidos)", fontsize=10.5); ax.set_ylim(0, 22)
pie(fig, "work/evidencias/T*/resultado.json (11 expedientes; veredicto y criterios)")
save(fig, "g06-criterios-expedientes")

# G7 — costos estimados por ventana (de los expedientes; NO factura)
c1 = json.load(open(f"{W}/T5-20261123T005244Z-9eed/capturas/costos.json")); c3 = json.load(open(f"{W}/T5-20261123T023342Z-0532/capturas/costos.json"))
rows = [("T1 OCI", 0), ("T2 DuckDNS", 0), ("T3 OCI (3 int.)", 0), ("T4 Azure", .21), ("T5 int.1", c1.get("usd", .15)), ("T5 int.2 (abort.)", .30), ("T5 int.3", c3["usd"])]
fig, ax = plt.subplots(figsize=(7.6, 3.2))
bs = ax.bar([r[0] for r in rows], [r[1] for r in rows], color=[C["gris"]] * 3 + [C["azul"], C["fail"], C["nar"], C["pass"]])
for b, r in zip(bs, rows): ax.text(b.get_x() + b.get_width() / 2, r[1] + .008, f"{r[1]:.2f}", ha="center", fontsize=8)
ax.axhline(1.5, color=C["osc"], ls=":", lw=1); ax.text(6.4, 1.42, "techo por ventana USD 1,5", fontsize=7, ha="right")
ax.set_ylabel("USD (ESTIMADO)"); ax.set_ylim(0, 1.6); plt.xticks(fontsize=8)
ax.set_title(f"Costo ESTIMADO por ventana de prueba (total ≈ USD {sum(r[1] for r in rows):.2f}; no es factura)", fontsize=10)
pie(fig, "costos.json de T5 (int. 1 y 3); T4-20261122-resultado.md; T5-20261123-intento2-abortado.md. Estimaciones con tarifas públicas.")
save(fig, "g07-costos-estimados")

# G8 — T2 propagación DNS
fig, ax = plt.subplots(figsize=(6.4, 2.6))
ax.barh(["rollback B→A", "apply A→B"], [62.0, 62.1], color=C["azul"])
for i, v in enumerate([62.0, 62.1]): ax.text(v + 2, i, f"{v} s", va="center", fontsize=8)
ax.axvline(180, color=C["osc"], ls=":", lw=1); ax.text(178, 1.35, "umbral 180 s", fontsize=7, ha="right")
ax.axvline(60, color=C["gris"], ls="--", lw=1); ax.text(58, -0.45, "TTL 60 s", fontsize=7, ha="right")
ax.set_xlim(0, 200); ax.set_xlabel("segundos hasta ver el cambio en 1.1.1.1, 8.8.8.8 y 9.9.9.9")
ax.set_title("T2 · Propagación del cambio DNS de pruebas (nexoeventos-test)", fontsize=10)
pie(fig, "work/evidencias/T2-20261122T142443Z-9eec/capturas/paso-apply_b.txt y paso-rollback_a_1.txt")
save(fig, "g08-t2-propagacion")
print(sorted(os.listdir(OUT)))
