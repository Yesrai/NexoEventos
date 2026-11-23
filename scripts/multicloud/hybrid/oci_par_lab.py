#!/usr/bin/env python3
"""Pasos A1/A2 de la prueba híbrida: crea los 2 PAR de LABORATORIO (ObjectReadWrite sobre UN objeto exacto cada uno, ≤ 1 h, sin listado), inicializa los 2 objetos sintéticos y comprueba alcance y operaciones
condicionales. Una identidad administrativa (--admin-profile) SOLO crea y revoca los PAR; jamás se incorpora al orquestador. Las URLs van a archivos 0600 en una carpeta 0700 fuera del repositorio y NO se imprimen.
Si cualquier comprobación de seguridad falla: se revocan los PAR creados y se informa. Ejecutar con el intérprete de la CLI de OCI (trae el SDK).
  create  --admin-profile P --bucket B --out-dir D       revoke  --admin-profile P --bucket B --out-dir D
La autoprueba por objetos hermanos (`.selftest-<uuid>`) NO es posible con PAR de objeto exacto: la semántica If-Match/If-None-Match se verifica aquí sobre el objeto de atestación, antes de su uso real."""
import argparse, json, os, sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
import oci

sys.path.insert(0, str(Path(__file__).resolve().parent)); import hybrid_par as HP  # noqa: E402
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "backend"))
from app.failover.lease import Record  # noqa: E402

OBJ = {"lease": "hybrid-test/writer-lease.json", "attest": "hybrid-test/fence-attestation.json"}
MINUTES = 58


def secret_file(path: Path, text: str):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f: f.write(text)


def revoke(c, ns, bucket, ids):
    left = []
    for pid in ids:
        try: c.delete_preauthenticated_request(ns, bucket, pid)
        except oci.exceptions.ServiceError as e:
            if e.status != 404: left.append(pid)
    return left


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("cmd", choices=["create", "revoke"]); ap.add_argument("--admin-profile", required=True); ap.add_argument("--bucket", required=True); ap.add_argument("--out-dir", required=True)
    a = ap.parse_args(); out = Path(a.out_dir); state_f = out / "par-state.json"
    cfg = oci.config.from_file(profile_name=a.admin_profile); c = oci.object_storage.ObjectStorageClient(cfg, retry_strategy=oci.retry.NoneRetryStrategy()); ns = c.get_namespace().data
    if a.cmd == "revoke":
        st = json.loads(state_f.read_text()); left = revoke(c, ns, a.bucket, st["par_ids"])
        activos = [p.id for p in c.list_preauthenticated_requests(ns, a.bucket, object_name_prefix="hybrid-test/").data if p.id in st["par_ids"]]
        codes = {k: HP._status(HP.read_url(str(out / f"{k}.par"))) for k in OBJ if (out / f"{k}.par").exists()}
        print(json.dumps({"revocados": not left and not activos, "par_activos": len(activos), "estado_url_tras_revocar": codes}, indent=1)); return 0 if not activos else 1
    rep = {"pasos": {}}
    b = c.get_bucket(ns, a.bucket).data
    rep["bucket"] = {"public": b.public_access_type, "versioning": b.versioning}
    existentes = [p.id for p in c.list_preauthenticated_requests(ns, a.bucket).data]; objs = c.list_object_versions(ns, a.bucket, prefix="hybrid-test/").data.items
    if b.public_access_type != "NoPublicAccess" or b.versioning != "Enabled" or existentes or objs:
        rep["detenido"] = "precondiciones: bucket privado y versionado, 0 PAR y hybrid-test/ vacío"; rep["par_existentes"] = len(existentes); rep["objetos_en_hybrid_test"] = len(objs); print(json.dumps(rep, indent=1)); return 1
    out.mkdir(mode=0o700, parents=True, exist_ok=True); os.chmod(out, 0o700)
    exp = datetime.now(timezone.utc) + timedelta(minutes=MINUTES); ids, urls = [], {}
    try:
        for k, o in OBJ.items():
            d = oci.object_storage.models.CreatePreauthenticatedRequestDetails(name=f"hybrid-lab-{k}-{exp:%H%M}", access_type="ObjectReadWrite", time_expires=exp, object_name=o, bucket_listing_action=None)
            r = c.create_preauthenticated_request(ns, a.bucket, d).data; ids.append(r.id); urls[k] = f"https://objectstorage.{cfg['region']}.oraclecloud.com{r.access_uri}"; secret_file(out / f"{k}.par", urls[k])
        secret_file(state_f, json.dumps({"par_ids": ids, "expira_utc": exp.isoformat(), "objetos": OBJ}))
        # 1) metadatos
        lst = [{"name": p.name, "object-name": p.object_name, "access-type": p.access_type, "time-expires": p.time_expires.isoformat(), "bucket-listing-action": p.bucket_listing_action} for p in c.list_preauthenticated_requests(ns, a.bucket, object_name_prefix="hybrid-test/").data if p.id in ids]
        HP.ALLOWED_OBJECTS = set(OBJ.values()); aud = HP.audit(lst, {"public-access-type": b.public_access_type, "versioning": b.versioning}); rep["pasos"]["auditoria_metadatos"] = aud
        if not aud["ok"]: raise RuntimeError("auditoría de metadatos")
        # 2) alcance (solo GET)
        pr = {k: HP.probe(u) for k, u in urls.items()}; rep["pasos"]["alcance_get"] = {k: v["codigos"] for k, v in pr.items()}
        cruz = {"lease->atestacion": HP._status(urls["lease"].split("/o/")[0] + "/o/" + OBJ["attest"]), "atestacion->lease": HP._status(urls["attest"].split("/o/")[0] + "/o/" + OBJ["lease"])}; rep["pasos"]["cruce_get"] = cruz
        if not all(v["ok"] for v in pr.values()) or any(v not in (401, 403, 404) for v in cruz.values()): raise RuntimeError("alcance excede el objeto exacto")
        # 3) semántica condicional sobre el objeto de ATESTACIÓN (vacío) y después su contenido inicial
        U = urls["attest"]; http = HP_http
        s0, h0, _ = http(U, "PUT", b"semantica-v0", {"If-None-Match": "*"}); s1, _, _ = http(U, "PUT", b"intruso", {"If-None-Match": "*"})
        et = lambda h: next((v for k, v in h.items() if k.lower() == "etag"), "").strip('"'); e0 = et(h0); s2, h2, _ = http(U, "PUT", b"semantica-v1", {"If-Match": e0}); s3, _, _ = http(U, "PUT", b"obsoleto", {"If-Match": e0})
        sg, hg, bg = http(U, "GET"); e2 = et(h2)
        ini = json.dumps({"v": 1, "ok": False, "epoch": None, "at": 0, "tables_total": None, "tables_covered": None}).encode()
        s4, _, _ = http(U, "PUT", ini, {"If-Match": e2})
        rep["pasos"]["semantica_en_atestacion"] = {"crear_if_none_match": s0, "recrear_if_none_match": s1, "if_match_vigente": s2, "if_match_obsoleto": s3, "contenido_intacto_tras_412": bg == b"semantica-v1", "contenido_inicial": s4}
        if not e0 or not e2 or (s0, s1, s2, s3, s4) != (200, 412, 200, 412, 200) or bg != b"semantica-v1": raise RuntimeError("semántica condicional")
        # 4) inicializar el lease (una sola vez) y comprobar sin modificarlo
        L = urls["lease"]; sl, hl, _ = http(L, "PUT", Record(None, 0, 0, 15.0, 5.0, True).dump(), {"If-None-Match": "*"}); sl2, _, _ = http(L, "PUT", b"intruso", {"If-None-Match": "*"}); sl3, _, _ = http(L, "PUT", b"obsoleto", {"If-Match": "etag-inexistente"})
        sgl, _, bl = http(L, "GET"); rec = Record.load(bl) if sgl == 200 else None
        rep["pasos"]["lease_inicial"] = {"crear": sl, "recrear_412": sl2, "if_match_falso_412": sl3, "registro": {"titular": rec.holder, "epoca": rec.epoch, "liberado": rec.released} if rec else None}
        if (sl, sl2, sl3) != (200, 412, 412) or rec is None or rec.holder is not None or rec.epoch != 0: raise RuntimeError("inicialización del lease")
        rep["expira_utc"] = exp.isoformat(timespec="seconds"); rep["archivos_url"] = {k: str(out / f"{k}.par") for k in OBJ}; rep["ok"] = True
        print(json.dumps(rep, indent=1)); return 0
    except Exception as e:  # noqa: BLE001
        left = revoke(c, ns, a.bucket, ids)
        for k in OBJ:
            (out / f"{k}.par").unlink(missing_ok=True)
        rep["detenido"] = f"{type(e).__name__}: {e}"; rep["par_revocados"] = not left; rep["ok"] = False; print(json.dumps(rep, indent=1, default=str)); return 1


def HP_http(url, method, data=None, headers=None):
    import urllib.request, urllib.error
    req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=20) as r: return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e: return e.code, dict(e.headers), b""
    except (urllib.error.URLError, OSError): return 0, {}, b""


sys.exit(main())
