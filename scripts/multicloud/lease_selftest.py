#!/usr/bin/env python3
"""AUTOPRUEBA REAL del almacén del lease (OCI Object Storage) — PREPARADA, NO EJECUTADA (requiere autorización cloud explícita).

Qué comprueba contra un bucket REAL de pruebas (nunca el de respaldos):
  0. Comprobaciones previas SOLO DE LECTURA: la CLI de OCI soporta --if-match; el bucket es el de pruebas (lista blanca de nombres), privado y SIN versionado.
  1. Semántica condicional (verify_store_semantics): create duplicado rechazado, CAS con ETag viejo rechazado, lectura inmediata tras escribir, carrera de N escritores → exactamente 1 gana.
  2. Carrera REAL: R rondas × W procesos de la CLI en paralelo contra el MISMO ETag → en cada ronda exactamente 1 éxito (mide latencias p50/p95).
  3. Protocolo del lease con relojes reales (TTL corto): A adquiere, B observa y espera, A deja de renovar, B toma tras ≥ TTL+margen, A pierde al renovar.
  4. Limpieza: borra SOLO los objetos `selftest-*` que esta ejecución creó (con un perfil con permiso de borrado; el perfil del lease NO lo tiene).
Seguridad: por defecto es un PLAN (no llama a la nube). Ejecutar exige NEXO_ALLOW_LEASE_SELFTEST=YES + --confirm con la frase exacta; tope de tiempo; aborta a la primera
anomalía (conservando la evidencia) y no imprime claves ni OCID. Salida JSON con el informe. Códigos: 0 todo correcto · 1 una validación falló · 2 rechazado/precondición · 3 tope de tiempo.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))
from app.failover.lease import LeaseClient, LeaseConfig, init_lease  # noqa: E402
from app.failover.store import OciCliStore, PreconditionFailed, StoreError, verify_store_semantics  # noqa: E402

ALLOWED_BUCKET = re.compile(r"^nexoeventos-lease-test(-[a-z0-9]{1,12})?$")
PHRASE = "EJECUTAR AUTOPRUEBA DEL LEASE EN {bucket}"


class Refused(Exception):
    def __init__(self, msg, code=2):
        super().__init__(msg); self.code = code


def sh(runner, argv):
    cp = runner(argv)
    return cp.returncode, (cp.stdout.decode() if isinstance(cp.stdout, bytes) else cp.stdout or ""), (cp.stderr.decode() if isinstance(cp.stderr, bytes) else cp.stderr or "")


def preflight(oci, ns, bucket, profile, runner):
    if not ALLOWED_BUCKET.match(bucket):
        raise Refused(f"bucket «{bucket}» no permitido: solo nexoeventos-lease-test[-sufijo] (jamás el de respaldos)")
    rc, out, _ = sh(runner, [oci, "--version"])
    if rc != 0:
        raise Refused("la CLI de OCI no responde a --version")
    rc, out, err = sh(runner, [oci, "os", "object", "put", "--help"])
    if rc != 0 or "--if-match" not in out:
        raise Refused("esta CLI de OCI no ofrece --if-match en «os object put»: no se puede hacer CAS")
    rc, out, err = sh(runner, [oci, "os", "bucket", "get", "--profile", profile, "--namespace-name", ns, "--bucket-name", bucket])
    if rc != 0:
        raise Refused("no se pudo leer el bucket de pruebas (¿existe y hay permiso de lectura?)")
    try:
        d = json.loads(out)["data"]
    except (ValueError, KeyError):
        raise Refused("respuesta ilegible al consultar el bucket")
    if str(d.get("versioning", "")).lower() not in ("disabled", ""):
        raise Refused("el bucket tiene versionado: con versionado cada renovación crea versiones y el modelo cambia; use un bucket SIN versionado")
    if str(d.get("public-access-type", "")) != "NoPublicAccess":
        raise Refused("el bucket no es privado (public-access-type != NoPublicAccess)")


def timed(fn):
    t = time.monotonic(); err = None
    try:
        fn()
    except PreconditionFailed as e:
        err = e
    return time.monotonic() - t, err


def race_rounds(make_store, rounds, writers, deadline):
    results, lat = [], []
    for r in range(rounds):
        if time.monotonic() > deadline:
            raise Refused("tope de tiempo excedido durante las rondas de carrera", 3)
        s = make_store(f"selftest-race-{uuid.uuid4().hex[:8]}"); s.create(b"inicio")
        etag = s.read().etag; wins = []; lock = threading.Lock()
        def go(i):
            dt, err = timed(lambda: s.replace(etag, f"w{i}".encode()))
            with lock:
                lat.append(dt)
                if err is None: wins.append(i)
        ts = [threading.Thread(target=go, args=(i,)) for i in range(writers)]
        [t.start() for t in ts]; [t.join() for t in ts]
        results.append(len(wins))
    return results, lat


def lease_protocol(make_store, ttl=6.0, margin=2.0):
    s = make_store(f"selftest-lease-{uuid.uuid4().hex[:8]}"); s.verified = True; init_lease(s, allow_non_atomic=True, ttl_s=ttl, margin_s=margin)
    cfg = LeaseConfig(ttl_s=ttl, margin_s=margin)
    a, b = LeaseClient(s, cfg, holder_id="A"), LeaseClient(s, cfg, holder_id="B")
    rep = {}
    rep["A_adquiere"] = a.acquire().ok and a.is_valid()
    rep["B_no_adquiere_al_inicio"] = not b.acquire().ok
    t0 = time.monotonic(); took = None
    while time.monotonic() - t0 < ttl + margin + 8:
        time.sleep(0.5)
        if b.acquire().ok:
            took = time.monotonic() - t0; break
    rep["B_toma_tras_ttl_mas_margen"] = took is not None and took >= ttl + margin - 0.6
    rep["A_ya_no_es_valido"] = not a.is_valid()
    rep["A_pierde_al_renovar"] = (not a.renew().ok) and a.status()["lost"]
    rep["tiempo_de_toma_s"] = None if took is None else round(took, 2)
    return rep, s.name


def cleanup(oci, ns, bucket, cleanup_profile, names, runner):
    deleted = 0
    for n in names:
        if not n.startswith("selftest-"):
            continue                                                   # jamás se borra nada que no sea de la autoprueba
        rc, _, _ = sh(runner, [oci, "os", "object", "delete", "--profile", cleanup_profile, "--namespace-name", ns, "--bucket-name", bucket, "--object-name", n, "--force"])
        deleted += rc == 0
    return deleted


def run_selftest(ns, bucket, profile, cleanup_profile, rounds=20, writers=16, max_minutes=15, oci="oci", runner=None, log=print, lease_ttl=6.0, lease_margin=2.0):
    runner = runner or (lambda argv: subprocess.run(argv, capture_output=True, timeout=60))
    deadline = time.monotonic() + max_minutes * 60
    created: list[str] = []
    report = {"bucket": bucket, "pasos": {}}
    preflight(oci, ns, bucket, profile, runner); report["pasos"]["0_previas"] = "ok"

    def make_store(name=None):
        name = name or f"selftest-{uuid.uuid4().hex[:8]}"; created.append(name)
        st = OciCliStore(ns, bucket, name, profile, oci_bin=oci, runner=runner); st.name = name; return st

    ok = True
    try:
        sem = verify_store_semantics(lambda: make_store(), writers=writers); report["pasos"]["1_semantica"] = sem
        if not all(sem.values()):
            ok = False; log("FALLÓ la semántica condicional: se detiene y se conserva la evidencia"); return report, 1
        wins, lat = race_rounds(make_store, rounds, writers, deadline)
        report["pasos"]["2_carrera"] = {"rondas": rounds, "escritores": writers, "ganadores_por_ronda": wins, "latencia_p50_s": round(statistics.median(lat), 3), "latencia_p95_s": round(sorted(lat)[int(len(lat) * 0.95) - 1], 3)}
        if any(w != 1 for w in wins):
            ok = False; log("FALLÓ la carrera real: hubo rondas sin exactamente 1 ganador"); return report, 1
        lp, lname = lease_protocol(make_store, lease_ttl, lease_margin); created.append(lname); report["pasos"]["3_lease"] = lp
        if not all(v for k, v in lp.items() if k != "tiempo_de_toma_s"):
            ok = False; log("FALLÓ el protocolo del lease con relojes reales"); return report, 1
        if time.monotonic() > deadline:
            raise Refused("tope de tiempo excedido", 3)
        return report, 0
    finally:
        report["pasos"]["4_limpieza"] = {"objetos_creados": len(created), "borrados": cleanup(oci, ns, bucket, cleanup_profile, created, runner)}


def main(argv=None, runner=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--namespace", required=True); ap.add_argument("--bucket", required=True)
    ap.add_argument("--profile", required=True, help="perfil del lease (crear/leer/sobrescribir; SIN borrar)")
    ap.add_argument("--cleanup-profile", required=True, help="perfil administrador SOLO para borrar los selftest-*")
    ap.add_argument("--rounds", type=int, default=20); ap.add_argument("--writers", type=int, default=16); ap.add_argument("--max-minutes", type=float, default=15)
    ap.add_argument("--oci-bin", default="oci"); ap.add_argument("--confirm"); ap.add_argument("--execute", action="store_true")
    a = ap.parse_args(argv)
    try:
        if not ALLOWED_BUCKET.match(a.bucket):
            raise Refused(f"bucket «{a.bucket}» no permitido")
        if not a.execute:
            print("PLAN (no se llamó a la nube). Para ejecutar: NEXO_ALLOW_LEASE_SELFTEST=YES … --execute --confirm \"" + PHRASE.format(bucket=a.bucket) + "\"")
            print(f"Pasos: previas de solo lectura → semántica → {a.rounds} rondas × {a.writers} escritores → protocolo del lease (≈ 20 s) → limpieza. Tope {a.max_minutes:g} min.")
            return 0
        if os.environ.get("NEXO_ALLOW_LEASE_SELFTEST") != "YES":
            raise Refused("falta NEXO_ALLOW_LEASE_SELFTEST=YES")
        if a.confirm != PHRASE.format(bucket=a.bucket):
            raise Refused(f"confirmación incorrecta: se exige exactamente «{PHRASE.format(bucket=a.bucket)}»")
        if a.writers < 8 or a.rounds < 5:
            raise Refused("parámetros demasiado bajos para una autoprueba significativa (≥ 8 escritores, ≥ 5 rondas)")
        report, code = run_selftest(a.namespace, a.bucket, a.profile, a.cleanup_profile, a.rounds, a.writers, a.max_minutes, a.oci_bin, runner)
        print(json.dumps(report, indent=1, ensure_ascii=False)); return code
    except Refused as e:
        print(f"RECHAZADO: {e}", file=sys.stderr); return e.code


if __name__ == "__main__":
    sys.exit(main())
