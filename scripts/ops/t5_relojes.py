#!/usr/bin/env python3
"""T5 — evidencia de SINCRONIZACIÓN de relojes (solo lectura): desfase del Mac frente a un servidor NTP público (consulta UDP SNTP, sin cambiar nada) y de la VM de Azure frente al Mac (algoritmo de Cristian con RTT medido,
por SSH con la huella fijada). Las marcas UTC de AWS (CloudWatch/ALB) usan el tiempo de AWS (Amazon Time Sync); aquí se comprueba que Mac y Azure, que generan y observan el experimento, no difieren más de 1 s.
Uso: t5_relojes.py --out work/t5/medidas/relojes.json [--ssh work/t4/ssh.sh] [--max-offset-s 1.0]"""
from __future__ import annotations

import argparse
import json
import socket
import struct
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

NTP_EPOCH = 2208988800


def sntp_offset(server="time.cloudflare.com", timeout=3.0, now=time.time):
    """Desfase local − servidor NTP (s) y RTT (s) con una consulta SNTP v4."""
    pkt = b"\x23" + 47 * b"\0"
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.settimeout(timeout); t0 = now(); s.sendto(pkt, (server, 123)); data, _ = s.recvfrom(512); t3 = now()
    f = struct.unpack("!12I", data[:48]); t1 = f[8] - NTP_EPOCH + f[9] / 2**32; t2 = f[10] - NTP_EPOCH + f[11] / 2**32
    return offset_from(t0, t1, t2, t3)


def offset_from(t0, t1, t2, t3):
    """Fórmulas NTP: desfase del cliente respecto al servidor = −((t1−t0)+(t2−t3))/2; RTT = (t3−t0)−(t2−t1)."""
    return {"offset_s": -((t1 - t0) + (t2 - t3)) / 2, "rtt_s": (t3 - t0) - (t2 - t1)}


def cristian(t_local_before, t_remote, t_local_after):
    """Desfase remoto − local suponiendo asimetría nula: remoto − punto medio local; el error máximo es RTT/2."""
    rtt = t_local_after - t_local_before
    return {"offset_s": t_remote - (t_local_before + rtt / 2), "rtt_s": rtt, "error_max_s": rtt / 2}


def azure_offset(ssh_script, n=5):
    best = None
    for _ in range(n):
        a = time.time(); r = subprocess.run([ssh_script, "date -u +%s.%N"], capture_output=True, text=True, timeout=30); b = time.time()
        try:
            c = cristian(a, float(r.stdout.strip().splitlines()[-1]), b)
        except (ValueError, IndexError):
            continue
        if best is None or c["rtt_s"] < best["rtt_s"]:
            best = c                       # la muestra de menor RTT es la más precisa
    return best


def main(argv=None):
    ap = argparse.ArgumentParser(); ap.add_argument("--out", required=True); ap.add_argument("--ssh"); ap.add_argument("--max-offset-s", type=float, default=1.0); ap.add_argument("--ntp", default="time.cloudflare.com")
    a = ap.parse_args(argv); res = {"utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z", "max_offset_s": a.max_offset_s}
    try:
        res["mac_vs_ntp"] = sntp_offset(a.ntp) | {"servidor": a.ntp}
    except OSError as e:
        res["mac_vs_ntp"] = {"error": type(e).__name__}
    if a.ssh:
        res["azure_vs_mac"] = azure_offset(a.ssh)
    ok = isinstance(res.get("mac_vs_ntp", {}).get("offset_s"), float) and abs(res["mac_vs_ntp"]["offset_s"]) <= a.max_offset_s
    if a.ssh:
        az = res.get("azure_vs_mac"); ok = ok and bool(az) and abs(az["offset_s"]) <= a.max_offset_s + az["error_max_s"]
    res["ok"] = bool(ok); Path(a.out).parent.mkdir(parents=True, exist_ok=True); Path(a.out).write_text(json.dumps(res, indent=1)); print(json.dumps(res)); return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
