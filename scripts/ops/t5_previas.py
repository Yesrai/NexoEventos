#!/usr/bin/env python3
"""T5 — comprobaciones PREVIAS al fallo (solo lectura de AWS + GET al ALB). Escribe work/t5/medidas/{previas,zonas,datos-antes}.json y NO provoca ningún fallo."""
import hashlib, json, os, socket, ssl, subprocess, sys, time
from datetime import datetime, timezone
from pathlib import Path
import httpx
ROOT = Path(__file__).resolve().parents[2]; OUT = ROOT / "work/t5/medidas"; OUT.mkdir(parents=True, exist_ok=True); DOMAIN = "nexoeventos-demo.duckdns.org"
os.environ.setdefault("AWS_PROFILE", "nexoeventos-lab"); os.environ["AWS_PAGER"] = ""
def aws(*a): return json.loads(subprocess.check_output(["aws", *a, "--output", "json"], text=True) or "{}")
def utc(): return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
import argparse
_ap = argparse.ArgumentParser(); _ap.add_argument("sufijo", nargs="?", default="antes"); _ap.add_argument("--instances", type=int, default=2); _A = _ap.parse_args()
SUF, NINST = _A.sufijo, _A.instances
def save(n, o): (OUT / f"{n}-{SUF}.json").write_text(json.dumps(o, indent=1, ensure_ascii=False))
sys.path.insert(0, str(ROOT / "scripts/cloud"))
import importlib.util
spec = importlib.util.spec_from_file_location("M", ROOT / "scripts/cloud/v2-measure.py"); M = importlib.util.module_from_spec(spec); spec.loader.exec_module(M)
rows = []; ok_all = True
def chk(name, ok, det=""): global ok_all; rows.append({"prueba": name, "ok": bool(ok), "detalle": det}); ok_all &= bool(ok); print(("OK   " if ok else "FALLA"), name, det)
alb = aws("elbv2", "describe-load-balancers", "--names", M.LB_NAME)["LoadBalancers"][0]; dns = alb["DNSName"]
ips = sorted({a[4][0] for a in socket.getaddrinfo(dns, 443, socket.AF_INET)})
# 1. dos EC2 sanas en dos zonas
th = M.target_health(); ids = sorted(th); inst = aws("ec2", "describe-instances", "--instance-ids", *ids)
zones = {i["InstanceId"]: i["Placement"]["AvailabilityZone"] for r in inst["Reservations"] for i in r["Instances"]}
chk(f"{NINST} destinos sanos en el ALB", len(th) == NINST and all(v == "healthy" for v in th.values()), str({k[-6:]: v for k, v in th.items()}))
chk("2 zonas de disponibilidad (y reparto equilibrado entre ellas)", len(set(zones.values())) == 2 and max(list(zones.values()).count(z) for z in set(zones.values())) - min(list(zones.values()).count(z) for z in set(zones.values())) <= 1, str(sorted(zones.values())))
# 2. ASG puede identificar y reemplazar
asg = aws("autoscaling", "describe-auto-scaling-groups", "--auto-scaling-group-names", M.ASG_NAME)["AutoScalingGroups"][0]
chk(f"ASG: health check por ELB, mín=deseada={NINST}, instancias InService/Healthy", asg["HealthCheckType"] == "ELB" and asg["MinSize"] == NINST and asg["DesiredCapacity"] == NINST and all(i["LifecycleState"] == "InService" and i["HealthStatus"] == "Healthy" for i in asg["Instances"]),
    f"gracia {asg['HealthCheckGracePeriod']} s, máx {asg['MaxSize']}")
# 3. HTTPS con el certificado del dominio (verificación completa, sin desactivarla)
import certifi
ctx = ssl.create_default_context(cafile=certifi.where())      # CA públicas (el intérprete del venv no trae almacén del sistema); verificación completa
try:
    with socket.create_connection((ips[0], 443), 10) as s, ctx.wrap_socket(s, server_hostname=DOMAIN) as t:
        cert = t.getpeercert(); chk("HTTPS: certificado verificado para " + DOMAIN, True, f"vence {cert['notAfter']}; {t.version()}")
except Exception as e: chk("HTTPS: certificado verificado para " + DOMAIN, False, type(e).__name__)
# 4. RDS disponible
rds = aws("rds", "describe-db-instances", "--db-instance-identifier", "nexoeventos-academy-postgres")["DBInstances"][0]
chk("RDS disponible y Multi-AZ", rds["DBInstanceStatus"] == "available" and rds["MultiAZ"], rds["DBInstanceStatus"])
# 5. tráfico por el ALB: 200 GET con conexión nueva por solicitud (reparto) y huella del catálogo
real = socket.getaddrinfo; state = {"i": 0}
def fake(host, *a, **k):
    if host == DOMAIN: state["i"] += 1; return real(ips[state["i"] % len(ips)], *a, **k)
    return real(host, *a, **k)
socket.getaddrinfo = fake
t0 = time.time(); start = datetime.fromtimestamp(t0 - 5, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"); codes = []; body = None
for i in range(200 if NINST == 2 else 100 * NINST):
    try:
        with httpx.Client(headers={"Connection": "close"}, timeout=15) as c:
            r = c.get(f"https://{DOMAIN}/api/events"); codes.append(r.status_code); body = body or r.content
    except httpx.HTTPError: codes.append(-1)
chk("GET /api/events por el ALB = 200 (conexión nueva por solicitud)", all(c == 200 for c in codes), f"{codes.count(200)}/{len(codes)}")
ev = json.loads(body) if body else []; h = hashlib.sha256(json.dumps(ev, sort_keys=True).encode()).hexdigest()
with httpx.Client(timeout=15) as c: ready = c.get(f"https://{DOMAIN}/ready").status_code; live = c.get(f"https://{DOMAIN}/livez").status_code
chk("/livez=200 y /ready=200 (aplicación y base de datos)", ready == 200 and live == 200, f"livez {live}, ready {ready}")
end = datetime.fromtimestamp(time.time() + 3, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
dist = {}   # el recuento se hace EN la instancia (awk por ventana): SSM trunca la salida a 24 kB y «cat/tail» perdía las líneas recientes (artefacto de las primeras mediciones)
a0, b0 = start.replace("Z", "+00:00"), end.replace("Z", "+00:00")
for i in ids:
    out = M.ssm_output(i, "awk -v a='%s' -v b='%s' '{ if (match($0,/^[0-9T:+-]+/)) { t=substr($0,RSTART,RLENGTH); if (t>=a && t<b && $0 ~ /path=\\/api\\/events/) n++ } } END { print n+0 }' /var/log/nginx/nexoeventos-access.log" % (a0, b0))
    dist[i[-6:]] = {"requests": int(out.split()[0]) if out.split() else -1}
tot = sum(v["requests"] for v in dist.values()) or 1
chk("las dos instancias reciben solicitudes (reparto del ALB)", all(v["requests"] > 0 for v in dist.values()), str({k: f"{v['requests']} ({100*v['requests']//tot} %)" for k, v in dist.items()}))
save("previas", {"ok": ok_all, "utc": utc(), "alb_dns_ocultable": "ALB V2", "pruebas": rows})
save("zonas", {"ok": all(r["ok"] for r in rows if "zonas" in r["prueba"] or "reparto" in r["prueba"] or "destinos sanos" in r["prueba"]), "utc": utc(), "zonas": sorted(zones.values()), "reparto": {k: v["requests"] for k, v in dist.items()}})
save("datos", {"utc": utc(), "eventos_publicados": len(ev), "huella_catalogo_sha256": h, "ready": ready, "rds": rds["DBInstanceStatus"]})
print(json.dumps({"ok": ok_all, "eventos": len(ev), "huella": h[:16], "alb_dns": dns}))
sys.exit(0 if ok_all else 1)
