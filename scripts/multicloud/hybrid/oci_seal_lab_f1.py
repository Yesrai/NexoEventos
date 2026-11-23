#!/usr/bin/env python3
"""Fase F1 del laboratorio OCI del sello — PREPARADA, NO EJECUTADA. Comprueba, con LLAMADAS REALES, los permisos efectivos de un writer de solo-crear sobre un bucket de laboratorio nuevo (sin versionado, separado de
nexoeventos-recovery), con IAM MÍNIMA creada y eliminada por el laboratorio. Una identidad administrativa (perfil DEFAULT) crea/borra; el writer usa una clave de API TEMPORAL generada aquí (la privada nunca se imprime ni sale del
directorio 0700 que se borra). La lógica está en `run_f1(cloud)` y se prueba contra un OCI simulado; `SdkF1Cloud` la conecta al SDK real. Autorización: NEXO_ALLOW_CLOUD_CHANGES=YES + --confirm «EJECUTAR F1 LABORATORIO SEAL OCI».
RECURSOS que crearía (todos con prefijo nexo-seal-lab-, y SOLO esos se borran): 1 bucket, 3 objetos ficticios, 1 grupo, 1 usuario (sin contraseña de consola), 1 membresía, 1 clave de API, 1 política. SIN Compute, SIN retención, SIN versionado.
T9 NO APLICA (ver T9_NO_APLICA): crear un PAR exige PAR_MANAGE y, según la documentación de OCI, los permisos del tipo de acceso (OBJECT_OVERWRITE para escritura): ejecutarlo exigiría debilitar la política del writer, que NO se hace."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import time
from pathlib import Path

CONFIRM = "EJECUTAR F1 LABORATORIO SEAL OCI"
PREFIX = "nexo-seal-lab-"
PROTECTED = "nexoeventos-recovery"
COMPARTMENT = "nexoeventos"
BUDGET_USD = 0.05
WORK = Path.home() / ".nexoeventos" / "oci-seal-f1"
T9_NO_APLICA = ("T9 · NO APLICA: «¿un PAR creado por el writer sobrescribe?» exigiría que el writer pudiera CREAR PARs (PAR_MANAGE) y, según la documentación de OCI, tener los permisos del tipo de acceso (OBJECT_OVERWRITE para un PAR de escritura). "
                "El writer de solo-crear no tiene ninguna de las dos cosas y NO se le concede para ejecutar la prueba. Se comprueba en cambio que el writer NO puede crear PARs (T12).")


def names(suffix: str) -> dict:
    return {"bucket": f"{PREFIX}{suffix}", "group": f"{PREFIX}writers-{suffix}", "user": f"{PREFIX}writer-{suffix}", "policy": f"{PREFIX}writer-policy-{suffix}"}


def policy_statements(bucket: str, group: str, compartment: str = COMPARTMENT) -> list[str]:
    """Alcance: el NOMBRE EXACTO del bucket (sin comodines) y solo 3 permisos de objeto. Ni OBJECT_OVERWRITE, ni OBJECT_DELETE, ni PAR_MANAGE, ni BUCKET_*, ni lectura de otros buckets."""
    assert bucket.startswith(PREFIX) and bucket != PROTECTED and "*" not in bucket and "%" not in bucket
    return [f"Allow group {group} to read buckets in compartment {compartment} where target.bucket.name='{bucket}'",
            f"Allow group {group} to manage objects in compartment {compartment} where all {{target.bucket.name='{bucket}', any {{request.permission='OBJECT_CREATE', request.permission='OBJECT_READ', request.permission='OBJECT_INSPECT'}}}}"]


# (id, operación del WRITER, objeto, condición, esperado, qué demuestra)
PRUEBAS = [
    ("T1", "create", "seal-log/0000000001.json", None, "allow", "el writer crea un objeto nuevo (OBJECT_CREATE)"),
    ("T1b", "read", "seal-log/0000000001.json", None, "allow", "el writer lee (OBJECT_READ)"),
    ("T1c", "list", "seal-log/", None, "allow", "el writer lista (OBJECT_INSPECT)"),
    ("T2", "create", "seal-log/0000000001.json", "if-none-match", "precondition_failed", "crear sobre un nombre existente con If-None-Match: 412"),
    ("T3", "overwrite", "seal-log/0000000001.json", None, "deny", "SIN OBJECT_OVERWRITE no puede sobrescribir"),
    ("T3b", "overwrite", "seal-log/0000000002.json", None, "deny", "ni un objeto creado por el administrador"),
    ("T4", "delete", "seal-log/0000000001.json", None, "deny", "SIN OBJECT_DELETE no puede borrar"),
    ("T10", "list_other_bucket", PROTECTED, None, "deny", "no puede listar nexoeventos-recovery"),
    ("T10b", "read_other_bucket", PROTECTED, None, "deny", "no puede leer objetos de nexoeventos-recovery"),
    ("T10c", "head_other_bucket", PROTECTED, None, "deny", "no puede ni consultar metadatos de objetos de nexoeventos-recovery (NO se prueba CREAR allí: un fallo de política escribiría en el bucket protegido)"),
    ("T11", "create_bucket", "nexo-seal-lab-intruso", None, "deny", "no puede crear buckets"),
    ("T12", "create_par", "seal-log/0000000001.json", None, "deny", "no puede crear PAR (sin PAR_MANAGE): por eso T9 no aplica"),
    ("T13", "read_iam", "users", None, "deny", "no puede leer IAM (usuarios/políticas)"),
]
GARANTIAS = {"writer_solo_adicion": ["T3", "T3b", "T4"], "writer_funciona": ["T1", "T1b", "T1c", "T2"], "alcance_exacto_del_bucket": ["T10", "T10b", "T10c", "T11"], "sin_privilegios_extra": ["T12", "T13"]}


def evaluate(results: list[dict]) -> dict:
    by = {r["id"]: r["ok"] for r in results}
    g = {k: all(by.get(i) is True for i in ids) for k, ids in GARANTIAS.items()}
    return {"garantias": g, "todas": all(g.values()), "T9": "NO APLICA", "validated_antirollback_propuesto": False,
            "nota": "F1 solo demuestra los permisos del writer; faltan F2 (retención) y la ejecución completa de la matriz T1–T10 para proponer validated_antirollback. Sigue false."}


def cleanup_order() -> list[str]:
    """Primero se RETIRA EL ACCESO (política), luego la identidad, luego los datos. Cada paso solo toca recursos creados por este laboratorio (nombre con prefijo + OCID creado en esta ejecución)."""
    return ["1. borrar la POLÍTICA (revoca el acceso del writer de inmediato)", "2. borrar la clave de API temporal del usuario", "3. quitar al usuario del grupo (membresía)", "4. borrar el USUARIO", "5. borrar el GRUPO",
            "6. borrar los OBJETOS y el BUCKET (administrador)", "7. verificar: identidades y políticas = las iniciales; el bucket no existe; nexoeventos-recovery idéntico; 8. borrar archivos temporales (clave privada, perfil)"]


# ---------- clave de API temporal ----------
def gen_keypair(directory: Path) -> tuple[str, str, Path]:
    """Genera RSA-2048; devuelve (PEM público, huella MD5 estilo OCI, ruta de la privada 0600). La privada NO se imprime."""
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    directory.mkdir(mode=0o700, parents=True, exist_ok=True); os.chmod(directory, 0o700)
    k = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    priv = directory / "writer.pem"; fd = os.open(priv, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as f: f.write(k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    der = k.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    fp = ":".join(f"{b:02x}" for b in hashlib.md5(der).digest())
    return k.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode(), fp, priv


# ---------- orquestación (probada contra un OCI simulado) ----------
def run_f1(cloud, suffix: str, log=lambda m: None) -> dict:
    n = names(suffix); rep = {"nombres": n, "pasos": [], "limpieza": {}}; made: dict = {}
    antes = cloud.identity_snapshot(); rep["identidad_antes"] = antes
    try:
        cloud.create_bucket(n["bucket"]); made["bucket"] = n["bucket"]
        for o, d in (("seal-log/0000000002.json", b"F1-ficticio-admin"),): cloud.put_object(n["bucket"], o, d)
        made["objetos"] = True
        made["group"] = cloud.create_group(n["group"]); made["user"] = cloud.create_user(n["user"]); made["member"] = cloud.add_member(made["user"], made["group"])
        made["policy"] = cloud.create_policy(n["policy"], policy_statements(n["bucket"], n["group"]))
        pub, fp, priv = cloud.new_api_key(made["user"]); made["api_key"] = fp
        w = cloud.writer(made["user"], fp, priv)
        end = time.time() + 300; ready = False                                                           # la política tarda en propagarse: se espera (acotado) a que el writer pueda CREAR
        while time.time() < end:
            if w.execute("create", n["bucket"], "seal-log/0000000000.json", None) in ("allow", "precondition_failed"): ready = True; break
            time.sleep(10)
        if not ready: raise RuntimeError("la política no llegó a propagarse en 5 min")
        for tid, op, obj, cond, esperado, _ in PRUEBAS:
            tgt = PROTECTED if op.endswith("_other_bucket") else n["bucket"]
            got = w.execute(op, tgt, obj, cond)
            if got == "allow" and op in ("create_bucket", "create_par"): cloud.safety_cleanup(op, n["bucket"])          # un permiso que NO debía existir: se revierte lo creado y la prueba falla
            rep["pasos"].append({"id": tid, "esperado": esperado, "obtenido": got, "ok": got == esperado})
        rep["evaluacion"] = evaluate(rep["pasos"])
    except Exception as e:  # noqa: BLE001
        rep["error"] = f"{type(e).__name__}: {str(e)[:120]}"
    finally:
        pend = []
        def paso(nombre, fn):
            try: fn()
            except Exception as e: pend.append({"recurso": nombre, "error": f"{type(e).__name__}"})          # NO se aborta la limpieza: se sigue con lo demás y se informa EXACTAMENTE lo pendiente
        if made.get("policy"): paso(f"política {n['policy']}", lambda: cloud.delete_policy(made["policy"]))
        if made.get("api_key"): paso(f"clave de API {made['api_key'][:8]}… del usuario {n['user']}", lambda: cloud.delete_api_key(made["user"], made["api_key"]))
        if made.get("member"): paso(f"membresía de {n['user']} en {n['group']}", lambda: cloud.remove_member(made["member"]))
        if made.get("user"): paso(f"usuario {n['user']}", lambda: cloud.delete_user(made["user"]))
        if made.get("group"): paso(f"grupo {n['group']}", lambda: cloud.delete_group(made["group"]))
        if made.get("bucket"): paso(f"bucket {n['bucket']} (y sus objetos)", lambda: cloud.delete_bucket_and_objects(made["bucket"]))
        paso("archivos temporales locales", cloud.remove_local_files)
        despues = cloud.identity_snapshot()
        rep["limpieza"] = {"pendientes": pend, "identidad_igual_a_la_inicial": despues == antes, "bucket_existe": cloud.bucket_exists(n["bucket"]) if made.get("bucket") else False, "recuperacion_identica": cloud.recovery_unchanged(),
                           "archivos_locales_eliminados": cloud.local_files_removed()}
        if not rep["limpieza"]["identidad_igual_a_la_inicial"]: rep["limpieza"]["diferencias"] = cloud.identity_diff(antes, despues)
    rep["ok"] = not rep.get("error") and rep.get("evaluacion", {}).get("todas") is True and not pend and rep["limpieza"]["identidad_igual_a_la_inicial"] and rep["limpieza"]["bucket_existe"] is False and rep["limpieza"]["recuperacion_identica"]
    return rep


def plan_text(suffix: str = "AAAAMMDDtHHMMSS") -> str:
    n = names(suffix)
    out = ["RECURSOS QUE F1 CREARÍA:", f"  bucket {n['bucket']} (Standard, privado, versionado desactivado, sin retención) + 2 objetos ficticios", f"  grupo {n['group']}", f"  usuario {n['user']} (solo clave de API; sin contraseña de consola) + membresía", "  1 clave de API (RSA-2048; privada solo en un directorio 0700 local que se borra)", f"  política {n['policy']}:"]
    out += [f"    {s}" for s in policy_statements(n["bucket"], n["group"])]
    out += ["PRUEBAS (llamadas reales como el writer):"] + [f"  {t[0]:4} {t[1]:20} → {t[4]:20} {t[5]}" for t in PRUEBAS] + ["  " + T9_NO_APLICA, "LIMPIEZA (orden):"] + [f"  {c}" for c in cleanup_order()]
    out += [f"GASTO: techo {BUDGET_USD} USD; sin Compute; Object Storage con bytes; IAM sin coste."]
    return "\n".join(out)


class SdkF1Cloud:
    """Conexión al SDK REAL de OCI (perfil administrativo DEFAULT para crear/borrar; perfil temporal del writer para las pruebas). NO ejecutada hasta que se autorice F1. Solo toca recursos con prefijo nexo-seal-lab- creados en esta ejecución."""
    def __init__(self, profile="DEFAULT"):
        import oci
        self.oci = oci; self.cfg = oci.config.from_file(profile_name=profile); oci.config.validate_config(self.cfg)
        nr = oci.retry.NoneRetryStrategy(); self.os = oci.object_storage.ObjectStorageClient(self.cfg, retry_strategy=nr); self.idc = oci.identity.IdentityClient(self.cfg, retry_strategy=nr)
        self.ns = self.os.get_namespace().data; self.tenancy = self.cfg["tenancy"]
        self.comp = [c for c in self.idc.list_compartments(self.tenancy).data if c.name == COMPARTMENT][0].id
        self._recovery0 = self._recovery_snapshot(); self._probe_obj = None; self._priv = None

    # --- instantáneas (solo lectura)
    def _recovery_snapshot(self):
        b = self.os.get_bucket(self.ns, PROTECTED).data
        objs, start = [], None
        while True:
            r = self.os.list_objects(self.ns, PROTECTED, start=start, fields="name,size,etag,md5", limit=1000).data
            objs += [(o.name, o.size, o.etag, o.md5) for o in r.objects]; start = r.next_start_with
            if not start: break
        self._probe_obj = objs[0][0] if objs else None
        return {"cfg": (b.versioning, b.public_access_type, b.storage_tier), "objs": sorted(objs), "par": len(self.os.list_preauthenticated_requests(self.ns, PROTECTED).data), "rules": len(self.os.list_retention_rules(self.ns, PROTECTED).data.items)}

    def identity_snapshot(self):
        return {"grupos": sorted(g.name for g in self.idc.list_groups(self.tenancy).data), "usuarios": sorted(u.name for u in self.idc.list_users(self.tenancy).data),
                "politicas": sorted(p.name for p in self.idc.list_policies(self.comp).data) + sorted("T:" + p.name for p in self.idc.list_policies(self.tenancy).data), "buckets": sorted(b.name for b in self.os.list_buckets(self.ns, self.comp).data)}

    def identity_diff(self, a, b): return {k: {"antes": a[k], "despues": b[k]} for k in a if a[k] != b[k]}
    def recovery_unchanged(self): return self._recovery_snapshot() == self._recovery0
    def bucket_exists(self, name):
        try: self.os.get_bucket(self.ns, name); return True
        except self.oci.exceptions.ServiceError as e: return e.status != 404

    # --- creación / borrado (solo lo propio del laboratorio)
    def create_bucket(self, name):
        assert name.startswith(PREFIX) and name != PROTECTED
        self.os.create_bucket(self.ns, self.oci.object_storage.models.CreateBucketDetails(name=name, compartment_id=self.comp, public_access_type="NoPublicAccess", storage_tier="Standard", versioning="Disabled"))
    def put_object(self, bucket, name, data): self.os.put_object(self.ns, bucket, name, data, if_none_match="*")
    def create_group(self, name): assert name.startswith(PREFIX); return self.idc.create_group(self.oci.identity.models.CreateGroupDetails(compartment_id=self.tenancy, name=name, description="laboratorio del sello (temporal)")).data.id
    def create_user(self, name): assert name.startswith(PREFIX); return self.idc.create_user(self.oci.identity.models.CreateUserDetails(compartment_id=self.tenancy, name=name, description="laboratorio del sello (temporal)")).data.id
    def add_member(self, user_id, group_id): return self.idc.add_user_to_group(self.oci.identity.models.AddUserToGroupDetails(user_id=user_id, group_id=group_id)).data.id
    def create_policy(self, name, statements):
        assert name.startswith(PREFIX); return self.idc.create_policy(self.oci.identity.models.CreatePolicyDetails(compartment_id=self.comp, name=name, statements=statements, description="laboratorio del sello (temporal)")).data.id
    def new_api_key(self, user_id):
        pub, fp, priv = gen_keypair(WORK); self._priv = priv
        k = self.idc.upload_api_key(user_id, self.oci.identity.models.CreateApiKeyDetails(key=pub)).data; return pub, k.fingerprint, priv
    def delete_policy(self, pid): self.idc.delete_policy(pid)
    def delete_api_key(self, user_id, fp): self.idc.delete_api_key(user_id, fp)
    def remove_member(self, mid): self.idc.remove_user_from_group(mid)
    def delete_user(self, uid): self.idc.delete_user(uid)
    def delete_group(self, gid): self.idc.delete_group(gid)
    def delete_bucket_and_objects(self, bucket):
        assert bucket.startswith(PREFIX) and bucket != PROTECTED
        start = None
        while True:
            r = self.os.list_objects(self.ns, bucket, start=start).data
            for o in r.objects: self.os.delete_object(self.ns, bucket, o.name)
            start = r.next_start_with
            if not start: break
        self.os.delete_bucket(self.ns, bucket)
    def safety_cleanup(self, op, bucket):
        if op == "create_bucket":
            try: self.os.delete_bucket(self.ns, "nexo-seal-lab-intruso")
            except Exception: pass
        if op == "create_par":
            for p in self.os.list_preauthenticated_requests(self.ns, bucket).data:
                if p.name.startswith("nexo-seal-lab-"): self.os.delete_preauthenticated_request(self.ns, bucket, p.id)
    def remove_local_files(self): shutil.rmtree(WORK, ignore_errors=True)
    def local_files_removed(self): return not WORK.exists()

    def writer(self, user_id, fingerprint, priv):
        oci = self.oci; cfg = {"user": user_id, "key_file": str(priv), "fingerprint": fingerprint, "tenancy": self.tenancy, "region": self.cfg["region"]}
        oci.config.validate_config(cfg); nr = oci.retry.NoneRetryStrategy(); osc = oci.object_storage.ObjectStorageClient(cfg, retry_strategy=nr); idc = oci.identity.IdentityClient(cfg, retry_strategy=nr); outer = self

        class W:
            def execute(self_, op, bucket, name, cond):
                try:
                    if op == "create": osc.put_object(outer.ns, bucket, name, b"F1-writer", **({"if_none_match": "*"} if True else {}))
                    elif op == "overwrite": osc.put_object(outer.ns, bucket, name, b"F1-sobrescrito")
                    elif op == "read": osc.get_object(outer.ns, bucket, name)
                    elif op == "list": osc.list_objects(outer.ns, bucket, prefix=name)
                    elif op == "delete": osc.delete_object(outer.ns, bucket, name)
                    elif op == "list_other_bucket": osc.list_objects(outer.ns, PROTECTED)
                    elif op == "read_other_bucket": osc.get_object(outer.ns, PROTECTED, outer._probe_obj)
                    elif op == "head_other_bucket": osc.head_object(outer.ns, PROTECTED, outer._probe_obj)
                    elif op == "create_bucket": osc.create_bucket(outer.ns, oci.object_storage.models.CreateBucketDetails(name=name, compartment_id=outer.comp))
                    elif op == "create_par": osc.create_preauthenticated_request(outer.ns, bucket, oci.object_storage.models.CreatePreauthenticatedRequestDetails(name="nexo-seal-lab-par-intruso", access_type="ObjectRead", time_expires=__import__("datetime").datetime.now(__import__("datetime").timezone.utc) + __import__("datetime").timedelta(minutes=5), object_name=name))
                    elif op == "read_iam": idc.list_users(outer.tenancy)
                    else: return "deny"
                    return "allow"
                except oci.exceptions.ServiceError as e:
                    if e.status == 412: return "precondition_failed"
                    return "deny" if e.status in (401, 403, 404) else f"error_{e.status}"
        return W()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(); ap.add_argument("cmd", choices=["plan", "politica", "run"]); ap.add_argument("--confirm", default=""); a = ap.parse_args(argv)
    if a.cmd == "plan": print(plan_text()); return 0
    if a.cmd == "politica": print("\n".join(policy_statements(PREFIX + "ejemplo", PREFIX + "writers-ejemplo"))); return 0
    if os.environ.get("NEXO_ALLOW_CLOUD_CHANGES") != "YES" or a.confirm != CONFIRM:
        print("RECHAZADO: falta NEXO_ALLOW_CLOUD_CHANGES=YES y la frase exacta.", file=sys.stderr); return 3
    print("RECHAZADO: el cliente del SDK real (SdkF1Cloud) NO está conectado todavía en esta versión: F1 solo está PREPARADA (falla cerrado).", file=sys.stderr); return 2


if __name__ == "__main__":
    sys.exit(main())
