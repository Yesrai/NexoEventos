#!/usr/bin/env python3
"""Exporta de SOLO LECTURA las métricas reales de OCI Monitoring (VM temporales de recuperación y bucket privado) a un JSON listo para cargar en Zabbix (push-history.py).
No modifica OCI. Requiere la CLI `oci` y un perfil con permiso de lectura de métricas (por defecto DEFAULT).
Uso: export-oci-metrics.py [--profile DEFAULT] [--start 2026-10-23T14:00:00Z] [--end 2026-10-24T03:00:00Z] [--out work/observability/oci-metrics.json]"""
import argparse, datetime as dt, json, os, pathlib, subprocess, sys

ap = argparse.ArgumentParser(); ap.add_argument("--profile", default="DEFAULT"); ap.add_argument("--start", default="2026-10-23T14:00:00Z"); ap.add_argument("--end", default="2026-10-24T03:00:00Z")
ap.add_argument("--out", default="work/observability/oci-metrics.json"); ap.add_argument("--compartment-name", default="nexoeventos"); a = ap.parse_args()
env = {**os.environ, "OCI_CLI_SUPPRESS_FILE_PERMISSIONS_WARNING": "True", "SUPPRESS_LABEL_WARNING": "True", "PYTHONWARNINGS": "ignore"}


def oci(*args):
    r = subprocess.run(["oci", "--profile", a.profile, *args], capture_output=True, text=True, env=env)
    if r.returncode:
        sys.exit(f"oci {' '.join(args[:3])}: {r.stderr.strip()[-300:]}")
    return json.loads(r.stdout) if r.stdout.strip() else {}


tenancy = next(l.split("=", 1)[1].strip() for l in open(os.path.expanduser("~/.oci/config")) if l.startswith("tenancy="))
cid = oci("iam", "compartment", "list", "--compartment-id", tenancy, "--name", a.compartment_name)["data"][0]["id"]
# (namespace, consulta, clave de Zabbix, agregación de series de varias dimensiones)
Q = [("oci_computeagent", "CpuUtilization[1m].mean()", "nexo.hist.cpu_pct"), ("oci_computeagent", "MemoryUtilization[1m].mean()", "nexo.hist.mem_pct"),
     ("oci_computeagent", "NetworksBytesIn[1m].sum()", "nexo.hist.net_in_bytes"), ("oci_computeagent", "NetworksBytesOut[1m].sum()", "nexo.hist.net_out_bytes"),
     ("oci_objectstorage", "PutRequests[5m].sum()", "nexo.hist.oci_put_requests"), ("oci_objectstorage", "GetRequests[5m].sum()", "nexo.hist.oci_get_requests"),
     ("oci_objectstorage", "ClientErrors[5m].sum()", "nexo.hist.oci_client_errors"), ("oci_objectstorage", "FirstByteLatency[5m].mean()", "nexo.hist.oci_first_byte_ms")]
points, notes = [], []
for ns, q, key in Q:
    d = oci("monitoring", "metric-data", "summarize-metrics-data", "--compartment-id", cid, "--namespace", ns, "--query-text", q, "--start-time", a.start, "--end-time", a.end).get("data", [])
    n = 0
    for s in d:
        for p in s["aggregated-datapoints"]:
            ts = int(dt.datetime.fromisoformat(p["timestamp"]).timestamp())
            points.append({"host": "oci-historico", "key": key, "clock": ts, "value": p["value"]}); n += 1
    notes.append(f"{ns} {q}: {len(d)} series, {n} puntos")
    print(notes[-1])
for ns, name in (("oci_objectstorage", "StoredBytes"), ("oci_objectstorage", "ObjectCount")):
    have = oci("monitoring", "metric", "list", "--compartment-id", cid, "--namespace", ns, "--name", name).get("data", [])
    notes.append(f"{ns} {name}: {'disponible' if have else 'no publicada por el servicio en esta cuenta/ventana (omitida)'}")
    if have:
        key = "nexo.hist.bucket_bytes" if name == "StoredBytes" else "nexo.hist.bucket_objects"
        for s in oci("monitoring", "metric-data", "summarize-metrics-data", "--compartment-id", cid, "--namespace", ns, "--query-text", f"{name}[1h].max()", "--start-time", a.start, "--end-time", a.end).get("data", []):
            for p in s["aggregated-datapoints"]:
                points.append({"host": "oci-historico", "key": key, "clock": int(dt.datetime.fromisoformat(p["timestamp"]).timestamp()), "value": p["value"]})
out = pathlib.Path(a.out); out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps({"schema": 1, "source": "OCI Monitoring (solo lectura)", "exported_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "window": {"start": a.start, "end": a.end}, "notes": notes, "points": points}, indent=1))
os.chmod(out, 0o600); print(f"{len(points)} puntos → {out}")
