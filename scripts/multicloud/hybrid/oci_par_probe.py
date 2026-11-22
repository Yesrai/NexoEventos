#!/usr/bin/env python3
"""Validación REAL del lease por PAR en OCI (aislada). Una identidad administrativa (perfil indicado) SOLO crea y revoca los PAR; toda la prueba de CAS usa únicamente la URL del PAR (sin firma).
Los PAR: ObjectReadWrite sobre UN objeto exacto cada uno, ≤1 h, sin listado. Las URLs van a archivos 0600 y no se imprimen. Siempre revoca los PAR y limpia (todas las versiones) lo creado, aunque algo falle.
Ejecutar con el intérprete de la CLI de OCI. Uso: oci_par_probe.py --admin-profile P --bucket B --prefix hybrid-test/par-probe-YYYYMMDD/ --workdir DIR"""
import argparse, json, os, sys, threading, urllib.error, urllib.request, uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
import oci

sys.path.insert(0, str(Path(__file__).resolve().parent)); import hybrid_par as HP  # noqa: E402


def http(url, method, data=None, headers=None):
    req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), b""
    except (urllib.error.URLError, OSError):
        return 0, {}, b""


def etag(h): return (h.get("ETag") or h.get("etag") or "").strip('"')


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--admin-profile", required=True); ap.add_argument("--bucket", required=True); ap.add_argument("--prefix", required=True); ap.add_argument("--workdir", required=True)
    ap.add_argument("--contenders", type=int, default=8); ap.add_argument("--rounds", type=int, default=10); a = ap.parse_args()
    if not a.prefix.startswith("hybrid-test/par-probe-") or not a.prefix.endswith("/"): print("prefijo no permitido"); return 2
    wd = Path(a.workdir); wd.mkdir(mode=0o700, exist_ok=True)
    cfg = oci.config.from_file(profile_name=a.admin_profile); c = oci.object_storage.ObjectStorageClient(cfg, retry_strategy=oci.retry.NoneRetryStrategy()); ns = c.get_namespace().data
    b = c.get_bucket(ns, a.bucket).data
    out = {"bucket_public": b.public_access_type, "bucket_versioning": b.versioning, "tests": {}}
    run = uuid.uuid4().hex[:6]; objs = {"lease": f"{a.prefix}lease-{run}.json", "attest": f"{a.prefix}attest-{run}.json"}
    exp = datetime.now(timezone.utc) + timedelta(minutes=55); pars: dict[str, str] = {}; urls: dict[str, str] = {}
    try:
        # --- crear los 2 PAR (alcance exacto)
        for k, o in objs.items():
            d = oci.object_storage.models.CreatePreauthenticatedRequestDetails(name=f"par-probe-{k}-{run}", access_type="ObjectReadWrite", time_expires=exp, object_name=o, bucket_listing_action=None)
            r = c.create_preauthenticated_request(ns, a.bucket, d).data; pars[k] = r.id
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
        s, _, _ = http(U, "PUT", b"intruso", {"If-None-Match": "*"}); out["tests"]["par_recreate_if_none_match"] = s
        s, h, _ = http(U, "PUT", b"v1", {"If-Match": e0}); out["tests"]["par_if_match_vigente"] = s; e1 = etag(h)
        s, _, _ = http(U, "PUT", b"obsoleto", {"If-Match": e0}); out["tests"]["par_if_match_obsoleto"] = s
        s, h, body = http(U, "GET"); out["tests"]["par_contenido_intacto_tras_412"] = (s == 200 and body == b"v1" and etag(h) == e1)
        if not (out["tests"]["par_create_if_none_match"] == 200 and out["tests"]["par_recreate_if_none_match"] == 412 and out["tests"]["par_if_match_vigente"] == 200 and out["tests"]["par_if_match_obsoleto"] == 412 and e1 and out["tests"]["par_contenido_intacto_tras_412"]):
            out["detenido"] = "If-Match/If-None-Match por PAR no se comportan como se necesita"; return end(c, ns, a, pars, objs, out)
        # --- contendientes
        cur = e1; rondas = []
        for r in range(a.rounds):
            res = {}; bar = threading.Barrier(a.contenders)
            def ct(i, base=cur):
                bar.wait(); s, h, _ = http(U, "PUT", f"r{r}-{i}".encode(), {"If-Match": base}); res[i] = (s, etag(h))
            hs = [threading.Thread(target=ct, args=(i,)) for i in range(a.contenders)]; [x.start() for x in hs]; [x.join() for x in hs]
            gan = [v for v in res.values() if v[0] == 200]; rech = [v[0] for v in res.values() if v[0] != 200]
            rondas.append({"ganadores": len(gan), "rechazos_412": rech.count(412), "otros": len(rech) - rech.count(412)})
            if len(gan) != 1 or rech.count(412) != a.contenders - 1: out["detenido"] = f"comportamiento inesperado en la ronda {r}"; break
            cur = gan[0][1]
        out["contendientes"] = {"n": a.contenders, "rondas_ejecutadas": len(rondas), "siempre_exactamente_uno": len(rondas) == a.rounds and all(x["ganadores"] == 1 for x in rondas), "rechazos_412_total": sum(x["rechazos_412"] for x in rondas), "otros_total": sum(x["otros"] for x in rondas)}
        # --- LÍMITE: escritura SIN condición
        s, _, _ = http(U, "PUT", b"sin-condicion"); s2, _, body = http(U, "GET")
        out["escritura_sin_condicion"] = {"http": s, "sobrescribe_el_lease": s == 200 and body == b"sin-condicion"}
        # --- alcance: el PAR del lease no llega a otros objetos ni al listado; el de atestación no escribe el objeto del lease
        out["alcance_par_lease"] = HP.probe(U)
        base = U.split("/o/")[0] + "/o/"
        out["otro_objeto_con_par_lease"] = {"PUT_objeto_hermano": http(base + a.prefix + "otro.json", "PUT", b"x", {"If-None-Match": "*"})[0], "PUT_backups": http(base + "backups/x", "PUT", b"x", {"If-None-Match": "*"})[0], "PUT_secrets": http(base + "secrets/x", "PUT", b"x", {"If-None-Match": "*"})[0]}
        out["par_atestacion_no_toca_lease"] = http(urls["attest"].split("/o/")[0] + "/o/" + objs["lease"], "PUT", b"x", {"If-None-Match": "*"})[0]
    finally:
        pass
    return end(c, ns, a, pars, objs, out, urls)


def end(c, ns, a, pars, objs, out, urls=None):
    urls = urls or {}
    for k, pid in pars.items():
        try: c.delete_preauthenticated_request(ns, a.bucket, pid)
        except oci.exceptions.ServiceError as e: out.setdefault("revocacion_errores", []).append((k, e.status))
    restantes = [p for p in c.list_preauthenticated_requests(ns, a.bucket, object_name_prefix=a.prefix).data if p.id in pars.values()]
    out["par_activos_tras_revocar"] = len(restantes)
    out["estado_url_tras_revocar"] = {k: http(u, "GET")[0] for k, u in urls.items()}
    # limpieza de objetos (todas las versiones) solo bajo el prefijo, solo si no hay nada ajeno
    vers = c.list_object_versions(ns, a.bucket, prefix=a.prefix).data.items
    esperado = lambda n: n.startswith(a.prefix) and any(n.endswith(x) for x in ("otro.json",)) or n in objs.values()
    ajenos = [v.name for v in vers if not esperado(v.name)]; out["objetos_ajenos_en_prefijo"] = ajenos
    if not ajenos:
        for v in vers: c.delete_object(ns, a.bucket, v.name, version_id=v.version_id)
    out["versiones_restantes_en_prefijo"] = len(c.list_object_versions(ns, a.bucket, prefix=a.prefix).data.items)
    for f in Path(a.workdir).glob("*.par"): f.unlink()
    print(json.dumps(out, indent=1, default=str)); return 0


sys.exit(main())
