#!/usr/bin/env python3
"""Fase F0 del laboratorio OCI del sello (REAL, limitada). Perfil administrativo (DEFAULT) solo para crear/revocar/limpiar. Crea UN bucket temporal `nexo-seal-lab-*` (Standard, privado, SIN versionado, SIN retención), objetos ficticios,
un PAR de LECTURA con listado (≤ 30 min) y, solo para T9b, un PAR de lectura/escritura sobre UN objeto (≤ 10 min) que se revoca de inmediato. Valida el PAR de lectura con el cliente REAL (ParLogStore). No imprime URLs ni las guarda
fuera de un directorio 0700 que se borra. SIEMPRE limpia (finally) y compara nexoeventos-recovery antes/después (solo lectura). Ejecutar con el intérprete de la CLI de OCI.
Uso: oci_seal_lab_f0.py preflight | run --confirm "EJECUTAR F0 LABORATORIO SEAL OCI"  (NEXO_ALLOW_CLOUD_CHANGES=YES)"""
import argparse, json, os, shutil, sys, time, urllib.error, urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
import oci

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "backend"))
from app.failover.seal_log import ParLogStore  # noqa: E402

CONFIRM = "EJECUTAR F0 LABORATORIO SEAL OCI"; PROFILE = "DEFAULT"; REGION = "sa-saopaulo-1"; PROTECTED = "nexoeventos-recovery"; COMPARTMENT = "nexoeventos"
BUDGET_USD = 0.05; COST_ESTIMATE_USD = 0.0001
WORK = Path.home() / ".nexoeventos" / "oci-seal-f0"


def http(url, method="GET", data=None, headers=None):
    req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=20) as r: return r.status, r.read()
    except urllib.error.HTTPError as e: return e.code, b""
    except (urllib.error.URLError, OSError): return 0, b""


def snapshot(c, ns):
    b = c.get_bucket(ns, PROTECTED, fields=["approximateSize", "approximateCount"]).data
    objs, start = [], None
    while True:
        r = c.list_objects(ns, PROTECTED, start=start, fields="name,size,etag,md5,timeCreated", limit=1000).data
        objs += [(o.name, o.size, o.etag, o.md5) for o in r.objects]; start = r.next_start_with
        if not start: break
    pars = len(c.list_preauthenticated_requests(ns, PROTECTED).data); rules = len(c.list_retention_rules(ns, PROTECTED).data.items)
    return {"config": {"versioning": b.versioning, "public": b.public_access_type, "tier": b.storage_tier, "events": b.object_events_enabled, "replication": b.replication_enabled, "kms": b.kms_key_id},
            "objetos": sorted(objs), "n": len(objs), "bytes": sum(o[1] for o in objs), "par_activos": pars, "reglas_retencion": rules, "approx": (b.approximate_count, b.approximate_size)}


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("cmd", choices=["preflight", "run"]); ap.add_argument("--confirm", default=""); a = ap.parse_args()
    cfg = oci.config.from_file(profile_name=PROFILE); oci.config.validate_config(cfg)
    c = oci.object_storage.ObjectStorageClient(cfg, retry_strategy=oci.retry.NoneRetryStrategy()); idc = oci.identity.IdentityClient(cfg); ns = c.get_namespace().data
    rep = {"pasos": {}}
    comps = [x for x in idc.list_compartments(cfg["tenancy"]).data if x.name == COMPARTMENT]
    pre = {"region": cfg["region"], "region_esperada": cfg["region"] == REGION, "compartimento_encontrado": bool(comps), "gasto_estimado_usd": COST_ESTIMATE_USD, "techo_usd": BUDGET_USD, "computo": False}
    existentes = [b.name for b in c.list_buckets(ns, comps[0].id).data] if comps else []
    pre["buckets_existentes"] = existentes; pre["hay_lab_previo"] = any(n.startswith("nexo-seal-lab-") for n in existentes)
    before = snapshot(c, ns); pre["recuperacion_antes"] = {k: before[k] for k in ("config", "n", "bytes", "par_activos", "reglas_retencion")}
    ok = pre["region_esperada"] and pre["compartimento_encontrado"] and not pre["hay_lab_previo"] and COST_ESTIMATE_USD <= BUDGET_USD and before["par_activos"] == 0 and before["reglas_retencion"] == 0
    rep["preflight"] = {**pre, "ok": ok}
    if a.cmd == "preflight" or not ok:
        print(json.dumps(rep, indent=1, default=str)); return 0 if ok else 1
    if os.environ.get("NEXO_ALLOW_CLOUD_CHANGES") != "YES" or a.confirm != CONFIRM:
        print("RECHAZADO: falta NEXO_ALLOW_CLOUD_CHANGES=YES y la frase exacta.", file=sys.stderr); return 3
    bucket = f"nexo-seal-lab-{time.strftime('%Y%m%dt%H%M%S', time.gmtime())}"; rep["bucket"] = bucket
    created = {"bucket": False, "objetos": [], "pars": []}; urls = {}
    WORK.mkdir(mode=0o700, parents=True, exist_ok=True); os.chmod(WORK, 0o700)
    base = f"https://objectstorage.{cfg['region']}.oraclecloud.com"
    def wurl(k, u):
        f = WORK / f"{k}.par"; fd = os.open(f, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as fh: fh.write(u)
        return f
    try:
        c.create_bucket(ns, oci.object_storage.models.CreateBucketDetails(name=bucket, compartment_id=comps[0].id, public_access_type="NoPublicAccess", storage_tier="Standard", versioning="Disabled")); created["bucket"] = True
        b = c.get_bucket(ns, bucket).data; rep["pasos"]["bucket"] = {"versioning": b.versioning, "public": b.public_access_type, "tier": b.storage_tier, "reglas": len(c.list_retention_rules(ns, bucket).data.items)}
        for n, body in (("seal-log/0000000001.json", b"F0-ficticio-1"), ("seal-log/0000000002.json", b"F0-ficticio-2"), ("otro/fuera-del-prefijo.json", b"F0-fuera")):
            c.put_object(ns, bucket, n, body, if_none_match="*"); created["objetos"].append(n)
        # --- PAR de LECTURA con listado (prefijo seal-log/), 30 min
        t_read = oci.object_storage.models.CreatePreauthenticatedRequestDetails(name="hybrid-seal-lab-read", access_type="AnyObjectRead", time_expires=datetime.now(timezone.utc) + timedelta(minutes=30), object_name="seal-log/", bucket_listing_action="ListObjects")
        pr = c.create_preauthenticated_request(ns, bucket, t_read).data; created["pars"].append(pr.id); urls["read"] = base + pr.access_uri; fread = wurl("read", urls["read"])
        import re
        forma = re.sub(r"/p/[^/]+/", "/p/<TOKEN>/", pr.access_uri); forma = re.sub(r"/n/[^/]+/b/[^/]+/", "/n/<ns>/b/<bucket>/", forma)
        rep["pasos"]["par_lectura"] = {"forma_de_la_url": forma, "tipo": pr.access_type, "listado": pr.bucket_listing_action, "expira_utc": pr.time_expires.isoformat(timespec="seconds"), "prefijo": pr.object_name}
        # --- T7: lectura y listado con el cliente REAL
        st = ParLogStore(str(fread), prefix="seal-log/"); nombres = st.names(); leido = st.read("seal-log/0000000001.json"); codigo_raiz, cuerpo = http(urls["read"].split("/o/")[0] + "/o/")
        try: formato = {"claves_raiz": sorted(json.loads(cuerpo).keys()), "claves_objeto": sorted(json.loads(cuerpo)["objects"][0].keys())}
        except Exception: formato = {"claves_raiz": None}
        rep["pasos"]["T7"] = {"listado_con_ParLogStore": nombres, "lectura_ok": leido == b"F0-ficticio-1", "http_listado_raiz": codigo_raiz, "formato": formato, "ok": nombres == ["seal-log/0000000001.json", "seal-log/0000000002.json"] and leido == b"F0-ficticio-1"}
        root = urls["read"].split("/o/")[0] + "/o/"
        # --- T7b: el PAR de lectura NO escribe ni sale de su alcance; ningún PAR llega a nexoeventos-recovery
        t7b = {"PUT_nuevo_en_prefijo": http(root + "seal-log/0000000009.json", "PUT", b"x", {"If-None-Match": "*"})[0], "PUT_sobrescribir_existente": http(root + "seal-log/0000000001.json", "PUT", b"intruso")[0],
               "GET_fuera_del_prefijo": http(root + "otro/fuera-del-prefijo.json")[0]}
        recov = root.replace(f"/b/{bucket}/", f"/b/{PROTECTED}/", 1)
        t7b["GET_listado_en_nexoeventos-recovery"] = http(recov)[0]; t7b["GET_objeto_en_nexoeventos-recovery"] = http(recov + "backups/")[0]
        t7b["objetos_tras_PUT"] = c.get_object(ns, bucket, "seal-log/0000000001.json").data.content == b"F0-ficticio-1" and len([o for o in c.list_objects(ns, bucket).data.objects]) == 3
        t7b["ok"] = all(t7b[k] in (400, 401, 403, 404, 405) for k in t7b if k.startswith(("PUT", "GET"))) and t7b["objetos_tras_PUT"]; rep["pasos"]["T7b"] = t7b
        # --- T9b: PAR de lectura/escritura sobre UN objeto, 10 min; sobrescribe SIN condiciones; se revoca de inmediato
        t_rw = oci.object_storage.models.CreatePreauthenticatedRequestDetails(name="hybrid-seal-lab-rw", access_type="ObjectReadWrite", time_expires=datetime.now(timezone.utc) + timedelta(minutes=10), object_name="seal-log/0000000002.json")
        pw = c.create_preauthenticated_request(ns, bucket, t_rw).data; created["pars"].append(pw.id); urls["rw"] = base + pw.access_uri; wurl("rw", urls["rw"])
        s_ow, _ = http(urls["rw"], "PUT", b"F0-SOBRESCRITO"); posterior = c.get_object(ns, bucket, "seal-log/0000000002.json").data.content
        s_inm, _ = http(urls["rw"], "PUT", b"otro", {"If-None-Match": "*"})
        rep["pasos"]["T9b"] = {"sobrescritura_sin_condicion_http": s_ow, "contenido_posterior": posterior.decode(), "sobrescribio": s_ow == 200 and posterior == b"F0-SOBRESCRITO", "con_If-None-Match_http": s_inm, "alcance": "UN objeto exacto, 10 min", "ok": s_ow == 200 and posterior == b"F0-SOBRESCRITO"}
        c.delete_preauthenticated_request(ns, bucket, pw.id); created["pars"].remove(pw.id)
        time.sleep(2); rep["pasos"]["T9b"]["url_rw_tras_revocar_http"] = http(urls["rw"])[0]
    except Exception as e:  # noqa: BLE001
        rep["error"] = f"{type(e).__name__}: {str(e)[:160]}"
    finally:
        lim = {}
        try:
            for pid in list(created["pars"]):
                try: c.delete_preauthenticated_request(ns, bucket, pid); created["pars"].remove(pid)
                except Exception as e: lim.setdefault("par_pendientes", []).append(pid[-6:])
            time.sleep(2); lim["urls_tras_revocar"] = {k: http(u)[0] for k, u in urls.items()}
            if created["bucket"]:
                try:
                    lim["par_activos_en_el_bucket"] = len(c.list_preauthenticated_requests(ns, bucket).data)
                    start = None
                    while True:
                        r = c.list_objects(ns, bucket, start=start).data
                        for o in r.objects: c.delete_object(ns, bucket, o.name)
                        start = r.next_start_with
                        if not start: break
                    lim["objetos_restantes"] = len(c.list_objects(ns, bucket).data.objects); c.delete_bucket(ns, bucket)
                except Exception as e: lim["bucket_error"] = f"{type(e).__name__}: {str(e)[:100]}"
                try: c.get_bucket(ns, bucket); lim["bucket_existe"] = True
                except oci.exceptions.ServiceError as e: lim["bucket_existe"] = e.status != 404
            after = snapshot(c, ns); lim["recuperacion_identica"] = (after == before); lim["recuperacion_despues"] = {k: after[k] for k in ("n", "bytes", "par_activos", "reglas_retencion")}
            if after != before: lim["recuperacion_diferencias"] = [k for k in before if before[k] != after[k]]
        except Exception as e: lim["error_limpieza"] = f"{type(e).__name__}: {str(e)[:120]}"
        shutil.rmtree(WORK, ignore_errors=True); lim["archivos_locales_eliminados"] = not WORK.exists(); rep["limpieza"] = lim
    print(json.dumps(rep, indent=1, default=str))
    ok = not rep.get("error") and all(rep["pasos"].get(k, {}).get("ok") for k in ("T7", "T7b", "T9b")) and rep["limpieza"].get("bucket_existe") is False and rep["limpieza"].get("recuperacion_identica") is True
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
