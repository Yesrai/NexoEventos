#!/usr/bin/env python3
"""Validación REAL del lease por PAR en OCI (aislada). Una identidad administrativa (perfil indicado) SOLO crea y revoca los PAR; toda la prueba de CAS usa únicamente la URL del PAR (sin firma).
Los PAR: ObjectReadWrite sobre UN objeto exacto cada uno, ≤1 h, sin listado. Las URLs van a archivos 0600 y no se imprimen. Siempre revoca los PAR y limpia (todas las versiones) lo creado, aunque algo falle.
Ejecutar con el intérprete de la CLI de OCI. Uso: oci_par_probe.py --admin-profile P --bucket B --prefix hybrid-test/par-probe-YYYYMMDD/ --workdir DIR"""
import argparse, json, os, re, signal, sys, threading, time, urllib.error, urllib.request, uuid
from email.utils import parsedate_to_datetime
from datetime import datetime, timedelta, timezone
from pathlib import Path
import oci

sys.path.insert(0, str(Path(__file__).resolve().parent)); import hybrid_par as HP  # noqa: E402
import lease_race as LR  # noqa: E402   (T1 del 22-nov falló por NameError al faltar este import)


LAT: list = []   # (método, estado, segundos) de CADA petición: permite medir la latencia real de replace/create (margen del lease); no cambia el comportamiento


def http(url, method, data=None, headers=None):
    req = urllib.request.Request(url, data=data, method=method, headers=headers or {}); t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            res = r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        res = e.code, dict(e.headers), b""
    except (urllib.error.URLError, OSError):
        res = 0, {}, b""
    LAT.append((method, res[0], time.monotonic() - t0)); return res


def lat_summary(kind="PUT", ok_status=(200,)):
    xs = sorted(d for m, s, d in LAT if m == kind and s in ok_status)
    if not xs: return {"n": 0, "p50_s": None, "p95_s": None, "max_s": None}
    q = lambda p: xs[min(len(xs) - 1, int(round(p * (len(xs) - 1))))]
    return {"n": len(xs), "p50_s": round(q(0.5), 3), "p95_s": round(q(0.95), 3), "max_s": round(xs[-1], 3)}


def skew_s(date_header, now=None):
    """Desfase |reloj local − reloj del servidor (cabecera HTTP Date)| en segundos; None si no se puede leer (entonces la prueba se DETIENE: no se confía en un reloj no verificado)."""
    try:
        srv = parsedate_to_datetime(date_header); now = now or datetime.now(timezone.utc)
        return round(abs((now - srv).total_seconds()), 3)
    except (TypeError, ValueError):
        return None


def hget(h, name): return next((v for k, v in (h or {}).items() if k.lower() == name.lower()), None)


def write_manifest(wd, a, run, pars, exp):
    """Registro 0600 de lo creado, ANTES de que pueda fallar algo: permite `--cleanup-only` si el proceso muere sin limpiar."""
    m = {"run": run, "bucket": a.bucket, "prefix": a.prefix, "creado_utc": datetime.now(timezone.utc).isoformat(), "caduca_utc": exp.isoformat(), "par_ids": dict(pars)}
    fd = os.open(Path(wd) / "par-probe.manifest.json", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh: json.dump(m, fh)


def lease_race_step(wd, a, t_start, allow_http_localhost=False, cfg=None):
    """Carrera de ADQUISICIÓN del lease (LeaseClient real) sobre el PAR real del objeto «race». El almacén se marca verificado solo porque los CAS de esta misma corrida ya pasaron."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "backend"))
    from app.failover.lease import LeaseConfig, init_lease
    from app.failover.store import ParHttpStore
    par = Path(wd) / "race.par"
    def factory():
        st = ParHttpStore(par, timeout=15, allow_http_localhost=allow_http_localhost); st.verified = True; return st
    cfg = cfg or LeaseConfig(ttl_s=3.0, margin_s=0.8)
    init_lease(factory(), allow_non_atomic=False, ttl_s=cfg.ttl_s, margin_s=cfg.margin_s)
    left = max(10.0, a.max_minutes * 60 - (time.monotonic() - t_start))
    r = LR.run_race(factory, a.lease_race_rounds, a.contenders, cfg, deadline_s=left)
    r["detalle"] = [{k: v for k, v in d.items() if k != "razones_negativas"} for d in r["detalle"]]; return r


def plan_only(c, ns, a, b, cfg):
    """PASO 0 de T1, SOLO LECTURA: no crea PAR ni objetos, no escribe nada. Comprueba lo que T1 necesita y muestra exactamente qué haría. Exit 0 solo si todo está en orden."""
    out = {"modo": "plan-only (solo lectura)", "region": cfg.get("region"), "bucket": {"nombre": a.bucket, "acceso_publico": b.public_access_type, "versionado": b.versioning, "nivel": b.storage_tier}}
    resp = c.get_namespace(); sk = skew_s(hget(dict(resp.headers), "Date")); out["skew_reloj_s"] = sk
    pars = c.list_preauthenticated_requests(ns, a.bucket).data; out["par_activos_en_el_bucket"] = len(pars)
    out["par_probe_bajo_el_prefijo"] = [p.name for p in pars if p.name.startswith("par-probe-")]
    vers = c.list_object_versions(ns, a.bucket, prefix=a.prefix).data.items; out["versiones_bajo_el_prefijo"] = len(vers)
    total = 0; n = 0; start = None
    while True:   # tamaño actual del bucket frente al tope Always Free de Object Storage (20 GiB)
        r = c.list_objects(ns, a.bucket, fields="size", start=start, limit=1000).data
        for o in r.objects: total += o.size or 0; n += 1
        start = r.next_start_with
        if not start: break
    out["objetos_vigentes"] = n; out["bytes_vigentes"] = total
    checks = {"bucket_privado": b.public_access_type == "NoPublicAccess", "bucket_versionado": b.versioning == "Enabled", "reloj_dentro_de_5s": sk is not None and sk <= a.max_skew_s,
              "cero_PAR_activos": len(pars) == 0, "prefijo_vacio": len(vers) == 0, "uso_muy_por_debajo_de_20GiB": total < 2 * 1024 ** 3,
              "prefijo_permitido": a.prefix.startswith("hybrid-test/par-probe-") and a.prefix.endswith("/")}
    out["comprobaciones"] = checks
    run = "<run>"; out["T1_crearia"] = {"par": [f"par-probe-{k}-{run}" for k in ("lease", "attest", "race")], "objetos": [f"{a.prefix}{k}-{run}.json" for k in ("lease", "attest", "race")], "acceso": "ObjectReadWrite sobre UN objeto exacto cada uno, sin listado, caducan ≤ 55 min",
                                  "rondas_cas": a.rounds, "contendientes": a.contenders, "rondas_adquisicion": a.lease_race_rounds, "plazo_global_min": a.max_minutes}
    out["resultado"] = "LISTO" if all(checks.values()) else "NO LISTO"
    print(json.dumps(out, indent=1, default=str)); return 0 if all(checks.values()) else 2


def etag(h): return (h.get("ETag") or h.get("etag") or "").strip('"')


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--admin-profile", required=True); ap.add_argument("--bucket", required=True); ap.add_argument("--prefix", required=True); ap.add_argument("--workdir", required=True)
    ap.add_argument("--contenders", type=int, default=8); ap.add_argument("--rounds", type=int, default=10); ap.add_argument("--lease-race-rounds", type=int, default=20); ap.add_argument("--max-minutes", type=float, default=20.0)
    ap.add_argument("--max-skew-s", type=float, default=5.0); ap.add_argument("--cleanup-only", action="store_true"); ap.add_argument("--plan-only", action="store_true"); a = ap.parse_args()
    t_start = time.monotonic(); signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))   # SIGTERM/SIGINT => limpieza garantizada
    if not a.prefix.startswith("hybrid-test/par-probe-") or not a.prefix.endswith("/"): print("prefijo no permitido"); return 2
    wd = Path(a.workdir); wd.mkdir(parents=True, mode=0o700, exist_ok=True); os.chmod(wd, 0o700)   # las URL de los PAR van a archivos 0600 dentro de un directorio 0700
    cfg = oci.config.from_file(profile_name=a.admin_profile); c = oci.object_storage.ObjectStorageClient(cfg, retry_strategy=oci.retry.NoneRetryStrategy()); ns = c.get_namespace().data
    b = c.get_bucket(ns, a.bucket).data
    if a.plan_only: return plan_only(c, ns, a, b, cfg)
    out = {"bucket_public": b.public_access_type, "bucket_versioning": b.versioning, "tests": {}}
    run = uuid.uuid4().hex[:6]; objs = {"lease": f"{a.prefix}lease-{run}.json", "attest": f"{a.prefix}attest-{run}.json", "race": f"{a.prefix}race-{run}.json"}
    if a.cleanup_only:   # revoca los PAR «par-probe-*» bajo el prefijo y limpia los objetos de ESTE tipo bajo el prefijo; no crea nada ni ejecuta pruebas
        pars = {p.name: p.id for p in c.list_preauthenticated_requests(ns, a.bucket, object_name_prefix=a.prefix).data if p.name.startswith("par-probe-")}
        pat = re.compile(re.escape(a.prefix) + r"(lease|attest|race)-[0-9a-f]{6}\.json$")
        objs = {v.name: v.name for v in c.list_object_versions(ns, a.bucket, prefix=a.prefix).data.items if pat.match(v.name)}
        out["modo"] = "cleanup-only"; return end(c, ns, a, pars, objs, out)
    out["run"] = run
    exp = datetime.now(timezone.utc) + timedelta(minutes=55); pars: dict[str, str] = {}; urls: dict[str, str] = {}
    try:
        # --- crear los 2 PAR (alcance exacto)
        for k, o in objs.items():
            d = oci.object_storage.models.CreatePreauthenticatedRequestDetails(name=f"par-probe-{k}-{run}", access_type="ObjectReadWrite", time_expires=exp, object_name=o, bucket_listing_action=None)
            r = c.create_preauthenticated_request(ns, a.bucket, d).data; pars[k] = r.id
            write_manifest(wd, a, run, pars, exp)
            full = f"https://objectstorage.{cfg['region']}.oraclecloud.com{r.access_uri}"; f = wd / f"{k}.par"; fd = os.open(f, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w") as fh: fh.write(full)
            urls[k] = full
        lst = [{"name": p.name, "object-name": p.object_name, "access-type": p.access_type, "time-expires": p.time_expires.isoformat(), "bucket-listing-action": p.bucket_listing_action}
               for p in c.list_preauthenticated_requests(ns, a.bucket, object_name_prefix=a.prefix).data if p.id in pars.values()]
        HP.ALLOWED_OBJECTS = set(objs.values()); aud = HP.audit(lst, {"public-access-type": b.public_access_type, "versioning": b.versioning}); out["auditoria_par"] = aud
        if not aud["ok"]: out["detenido"] = "los PAR creados no cumplen el alcance exigido"; return end(c, ns, a, pars, objs, out)
        U = urls["lease"]
        # --- If-None-Match y If-Match por PAR
        s, h, _ = http(U, "PUT", b"v0", {"If-None-Match": "*"}); out["tests"]["par_create_if_none_match"] = s; e0 = etag(h)
        out["skew_reloj_s"] = skew_s(hget(h, "Date"))
        if out["skew_reloj_s"] is None or out["skew_reloj_s"] > a.max_skew_s: out["detenido"] = f"reloj no verificable o desfasado más de {a.max_skew_s:g} s respecto del servidor"; return end(c, ns, a, pars, objs, out, urls)
        s, _, _ = http(U, "PUT", b"intruso", {"If-None-Match": "*"}); out["tests"]["par_recreate_if_none_match"] = s
        s, h, _ = http(U, "PUT", b"v1", {"If-Match": e0}); out["tests"]["par_if_match_vigente"] = s; e1 = etag(h)
        s, _, _ = http(U, "PUT", b"obsoleto", {"If-Match": e0}); out["tests"]["par_if_match_obsoleto"] = s
        s, h, body = http(U, "GET"); out["tests"]["par_contenido_intacto_tras_412"] = (s == 200 and body == b"v1" and etag(h) == e1)
        if not (out["tests"]["par_create_if_none_match"] == 200 and out["tests"]["par_recreate_if_none_match"] == 412 and out["tests"]["par_if_match_vigente"] == 200 and out["tests"]["par_if_match_obsoleto"] == 412 and e1 and out["tests"]["par_contenido_intacto_tras_412"]):
            out["detenido"] = "If-Match/If-None-Match por PAR no se comportan como se necesita"; return end(c, ns, a, pars, objs, out)
        # --- contendientes
        cur = e1; rondas = []
        for r in range(a.rounds):
            if time.monotonic() - t_start > a.max_minutes * 60: out["detenido"] = f"plazo global de {a.max_minutes:g} min agotado"; break
            res = {}; bar = threading.Barrier(a.contenders)
            def ct(i, base=cur):
                bar.wait(); s, h, _ = http(U, "PUT", f"r{r}-{i}".encode(), {"If-Match": base}); res[i] = (s, etag(h))
            hs = [threading.Thread(target=ct, args=(i,)) for i in range(a.contenders)]; [x.start() for x in hs]; [x.join() for x in hs]
            gan = [v for v in res.values() if v[0] == 200]; rech = [v[0] for v in res.values() if v[0] != 200]
            rondas.append({"ganadores": len(gan), "rechazos_412": rech.count(412), "otros": len(rech) - rech.count(412)})
            if len(gan) != 1 or rech.count(412) != a.contenders - 1: out["detenido"] = f"comportamiento inesperado en la ronda {r}"; break
            cur = gan[0][1]
        out["contendientes"] = {"n": a.contenders, "rondas_ejecutadas": len(rondas), "siempre_exactamente_uno": len(rondas) == a.rounds and all(x["ganadores"] == 1 for x in rondas), "rechazos_412_total": sum(x["rechazos_412"] for x in rondas), "otros_total": sum(x["otros"] for x in rondas)}
        if a.lease_race_rounds > 0 and not out.get("detenido"): out["lease_race"] = lease_race_step(wd, a, t_start)
        out["latencias_put_exitosos"] = lat_summary("PUT", (200,)); out["latencias_put_rechazados_412"] = lat_summary("PUT", (412,))
        # --- LÍMITE: escritura SIN condición
        s, _, _ = http(U, "PUT", b"sin-condicion"); s2, _, body = http(U, "GET")
        out["escritura_sin_condicion"] = {"http": s, "sobrescribe_el_lease": s == 200 and body == b"sin-condicion"}
        # --- alcance: el PAR del lease no llega a otros objetos ni al listado; el de atestación no escribe el objeto del lease
        out["alcance_par_lease"] = HP.probe(U)
        base = U.split("/o/")[0] + "/o/"
        out["otro_objeto_con_par_lease"] = {"PUT_objeto_hermano": http(base + a.prefix + "otro.json", "PUT", b"x", {"If-None-Match": "*"})[0], "PUT_backups": http(base + "backups/x", "PUT", b"x", {"If-None-Match": "*"})[0], "PUT_secrets": http(base + "secrets/x", "PUT", b"x", {"If-None-Match": "*"})[0]}
        out["par_atestacion_no_toca_lease"] = http(urls["attest"].split("/o/")[0] + "/o/" + objs["lease"], "PUT", b"x", {"If-None-Match": "*"})[0]
    except BaseException as exc:  # noqa: BLE001 — timeout, corte de red, Ctrl-C, SIGTERM: SIEMPRE se revoca y se limpia
        out["interrumpido"] = type(exc).__name__; out["interrumpido_detalle"] = re.sub(r"https?://\S+", "[url]", str(exc))[:200]; out["detenido"] = out.get("detenido") or "ejecución interrumpida: se revoca y se limpia"
    return end(c, ns, a, pars, objs, out, urls)


def end(c, ns, a, pars, objs, out, urls=None):
    """Limpieza que CONTINÚA ante errores de cada paso y devuelve ≠ 0 si queda algo (PAR activos o versiones): nunca se declara «limpio» sin comprobarlo."""
    urls = urls or {}; errs = out.setdefault("limpieza_errores", [])
    run = out.get("run")
    if run:   # un PAR creado cuyo acuse se perdió (timeout) no está en `pars`: se localiza por su nombre y se revoca igual
        lst0 = None
        try: lst0 = c.list_preauthenticated_requests(ns, a.bucket, object_name_prefix=a.prefix).data
        except BaseException as e:  # noqa: BLE001
            errs.append(f"listar PAR huérfanos: {type(e).__name__}")
        for p in lst0 or []:
            if p.name.startswith("par-probe-") and p.name.endswith(f"-{run}") and p.id not in pars.values(): pars[p.name] = p.id
    def step(name, fn):
        try: return fn()
        except BaseException as e:  # noqa: BLE001
            errs.append(f"{name}: {type(e).__name__}"); return None
    for k, pid in pars.items():
        step(f"revocar {k}", lambda pid=pid: c.delete_preauthenticated_request(ns, a.bucket, pid))
    restantes = step("listar PAR", lambda: [p for p in c.list_preauthenticated_requests(ns, a.bucket, object_name_prefix=a.prefix).data if p.id in pars.values()])
    out["par_activos_tras_revocar"] = len(restantes) if restantes is not None else None
    out["estado_url_tras_revocar"] = {k: step(f"GET {k}", lambda u=u: http(u, "GET")[0]) for k, u in urls.items()}
    vers = step("listar versiones", lambda: c.list_object_versions(ns, a.bucket, prefix=a.prefix).data.items)
    if vers is not None:
        esperado = lambda n: n.startswith(a.prefix) and (n in objs.values() or n.endswith("otro.json"))
        ajenos = [v.name for v in vers if not esperado(v.name)]; out["objetos_ajenos_en_prefijo"] = ajenos
        if not ajenos:
            for v in vers: step(f"borrar {v.name[-18:]}", lambda v=v: c.delete_object(ns, a.bucket, v.name, version_id=v.version_id))
    rest = step("recontar versiones", lambda: len(c.list_object_versions(ns, a.bucket, prefix=a.prefix).data.items))
    out["versiones_restantes_en_prefijo"] = rest
    for f in list(Path(a.workdir).glob("*.par")): step("borrar .par", f.unlink)
    limpio = out["par_activos_tras_revocar"] == 0 and rest == 0
    out["limpio"] = bool(limpio)
    if limpio: step("borrar manifiesto", lambda: (Path(a.workdir) / "par-probe.manifest.json").unlink(missing_ok=True))
    else: out["accion_manual"] = "quedan recursos: ejecutar de nuevo con --cleanup-only, o revocar los PAR y borrar las versiones del prefijo desde la consola de OCI"
    print(json.dumps(out, indent=1, default=str)); return 0 if limpio and not out.get("detenido") and not out.get("interrumpido") else (3 if not limpio else 1)


if __name__ == "__main__":
    sys.exit(main())
