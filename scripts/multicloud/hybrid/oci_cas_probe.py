#!/usr/bin/env python3
"""Prueba REAL de compare-and-swap en OCI Object Storage con el SDK autenticado (sin PAR), limitada a UN prefijo exclusivo. Ejecutar con el intérprete de la CLI de OCI (trae el SDK).
Comprueba: If-None-Match:* (no sobrescribir), If-Match con ETag obsoleto (412), If-Match vigente (OK) y N contendientes simultáneos sobre el MISMO ETag (debe ganar exactamente uno). Después intenta
borrar SOLO los objetos creados en esta ejecución (con If-Match de su último ETag). No toca backups/ ni secrets/. No imprime credenciales.
Uso: oci_cas_probe.py --profile P --bucket B --prefix hybrid-test/cas-probe-YYYYMMDD/ [--contenders 8 --rounds 10]"""
import argparse, json, sys, threading, time, uuid
import oci

PREFIJO_OK = "hybrid-test/cas-probe-"


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--profile", required=True); ap.add_argument("--bucket", required=True); ap.add_argument("--prefix", required=True)
    ap.add_argument("--contenders", type=int, default=8); ap.add_argument("--rounds", type=int, default=10); ap.add_argument("--extra-object", action="append", default=[]); a = ap.parse_args()
    if not a.prefix.startswith(PREFIJO_OK) or not a.prefix.endswith("/") or ".." in a.prefix:
        print("prefijo no permitido"); return 2
    cfg = oci.config.from_file(profile_name=a.profile); oci.config.validate_config(cfg)
    c = oci.object_storage.ObjectStorageClient(cfg, retry_strategy=oci.retry.NoneRetryStrategy()); ns = c.get_namespace().data
    b = c.get_bucket(ns, a.bucket).data
    out = {"region": cfg["region"], "bucket_public": b.public_access_type, "bucket_versioning": b.versioning, "tests": {}}
    created: dict[str, str] = {}
    def put(name, body, **kw):
        r = c.put_object(ns, a.bucket, name, body, **kw); created[name] = r.headers["etag"]; return r.headers["etag"]
    def code(fn):
        try: fn(); return 200
        except oci.exceptions.ServiceError as e: return e.status
    run = uuid.uuid4().hex[:8]; lease = f"{a.prefix}lease-{run}.json"
    # 1) If-None-Match
    out["tests"]["create_if_none_match"] = code(lambda: put(lease, b"v0", if_none_match="*"))
    out["tests"]["recreate_if_none_match_rechazado"] = code(lambda: put(lease, b"intruso", if_none_match="*"))
    e0 = created[lease]
    # 2) If-Match
    e1 = c.put_object(ns, a.bucket, lease, b"v1", if_match=e0).headers["etag"]; created[lease] = e1
    out["tests"]["if_match_vigente"] = 200
    out["tests"]["if_match_obsoleto_rechazado"] = code(lambda: c.put_object(ns, a.bucket, lease, b"v-obsoleto", if_match=e0))
    cur = c.get_object(ns, a.bucket, lease); out["tests"]["contenido_intacto_tras_412"] = cur.data.content == b"v1" and cur.headers["etag"] == e1
    # 3) contendientes simultáneos sobre el mismo ETag
    rondas = []
    for r in range(a.rounds):
        base = created[lease]; res = {}; bar = threading.Barrier(a.contenders)
        def contender(i):
            bar.wait()
            try:
                res[i] = ("ok", c.put_object(ns, a.bucket, lease, f"gana-{r}-{i}".encode(), if_match=base).headers["etag"])
            except oci.exceptions.ServiceError as e:
                res[i] = ("rechazado", e.status)
            except Exception as e:
                res[i] = ("error", type(e).__name__)
        hs = [threading.Thread(target=contender, args=(i,)) for i in range(a.contenders)]; [h.start() for h in hs]; [h.join() for h in hs]
        ganadores = [v for v in res.values() if v[0] == "ok"]; rechazos = [v[1] for v in res.values() if v[0] == "rechazado"]
        if ganadores: created[lease] = ganadores[0][1]
        if len(ganadores) != 1 or any(x != 412 for x in rechazos) or len(rechazos) != a.contenders - 1:
            rondas.append({"ganadores": len(ganadores), "rechazos_412": sum(1 for x in rechazos if x == 412), "otros": len(res) - len(ganadores) - sum(1 for x in rechazos if x == 412), "INESPERADO": True}); break
        rondas.append({"ganadores": len(ganadores), "rechazos_412": sum(1 for x in rechazos if x == 412), "otros": len(res) - len(ganadores) - sum(1 for x in rechazos if x == 412)})
    out["contendientes"] = {"n": a.contenders, "rondas": a.rounds, "ganadores_por_ronda": [x["ganadores"] for x in rondas], "rondas_ejecutadas": len(rondas), "siempre_exactamente_uno": len(rondas) == a.rounds and all(x["ganadores"] == 1 for x in rondas),
                            "rechazos_412_total": sum(x["rechazos_412"] for x in rondas), "otros_errores_total": sum(x["otros"] for x in rondas)}
    # 4) limpieza SOLO de lo creado aquí + el objeto huérfano identificado antes (--extra-object): se borran TODAS sus versiones (el bucket está versionado) y nada más.
    esperados = {n for n in created} | {a.prefix + x for x in a.extra_object}
    vers = c.list_object_versions(ns, a.bucket, prefix=a.prefix).data.items
    ajenos = [v.name for v in vers if v.name not in esperados]
    out["objetos_ajenos_en_prefijo"] = ajenos
    limp = []
    if ajenos:
        out["limpieza"] = "OMITIDA: hay objetos en el prefijo que esta prueba no creó"
    else:
        for v in vers:
            try: c.delete_object(ns, a.bucket, v.name, version_id=v.version_id); limp.append((v.name.rsplit("/", 1)[-1], "borrada", "marcador" if v.is_delete_marker else "version"))
            except oci.exceptions.ServiceError as e: limp.append((v.name.rsplit("/", 1)[-1], e.status, e.code))
        out["limpieza"] = limp
    out["versiones_restantes_en_prefijo"] = len(c.list_object_versions(ns, a.bucket, prefix=a.prefix).data.items)
    out["objetos_restantes_en_prefijo"] = [o.name for o in c.list_objects(ns, a.bucket, prefix=a.prefix).data.objects]
    print(json.dumps(out, indent=1)); return 0


sys.exit(main())
