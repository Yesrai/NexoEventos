#!/usr/bin/env python3
"""LABORATORIO (PREPARADO, NO EJECUTADO) para validar en OCI REAL el sello antirretroceso. Aquí viven el DISEÑO, las políticas mínimas, la matriz de pruebas reales con su resultado esperado y el evaluador que decide si las garantías
quedaron DEMOSTRADAS. Nada de esto crea recursos: `plan` imprime lo que habría que crear (con autorización específica) y `run_suite(cloud)` ejecuta la matriz contra un objeto `cloud` (en las pruebas locales, un OCI simulado
con la semántica documentada; en la validación real, un cliente del SDK con un perfil POR IDENTIDAD).
Hechos de OCI en los que se apoya (documentación oficial + lo observado en esta cuenta):
  · IAM distingue OBJECT_CREATE de OBJECT_OVERWRITE y OBJECT_DELETE (PutObject sobre un nombre existente exige OVERWRITE). La política `manage objects … where any {request.permission='OBJECT_CREATE',…}` YA se usa en esta
    tenencia (nexoeventos-backup-uploaders) y se observó que ese perfil crea objetos nuevos pero NO puede sobrescribir ni borrar: eso es «solo adición» por IAM, sin depender de una URL.
  · Un PAR NO puede borrar, pero un PAR de lectura/escritura creado por un administrador SÍ sobrescribió (observado el 19-nov); los permisos del CREADOR del PAR se comprueban en cada uso: un PAR creado por una identidad sin
    OBJECT_OVERWRITE podría no poder sobrescribir, pero la documentación exige al creador los permisos del tipo de acceso: HAY QUE PROBARLO (T9). Hasta entonces un PAR de escritura NO se presenta como solo-adición.
  · Un PAR de LECTURA con listado habilitado (por prefijo) no puede escribir: es el mecanismo del LECTOR (AWS) sin claves de OCI en la EC2.
  · Retención (WORM): exige versionado DESACTIVADO (no se puede añadir con versionado activo: por eso NO sirve nexoeventos-recovery, que lo tiene Enabled); una regla con plazo bloquea sobrescribir/borrar cada objeto durante el plazo
    desde su última modificación; SIN BLOQUEAR se puede editar o borrar; BLOQUEARLA tiene un retraso obligatorio de 14 días y es IRREVERSIBLE (solo se elimina con el bucket vacío). Para el laboratorio: regla con plazo SIN bloquear.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field

BUCKET_PREFIX = "nexo-seal-lab-"
FORBIDDEN_BUCKETS = {"nexoeventos-recovery"}
IDENTIDADES = {
    "writer": {"quien": "grupo dinámico (instance principal de la VM de OCI) o usuario de servicio nexo-seal-writer", "permisos": ["OBJECT_CREATE", "OBJECT_INSPECT", "OBJECT_READ"], "uso": "añade la entrada «sealed» al promover"},
    "operator": {"quien": "usuario nexo-seal-operator (persona; clave de API sin conexión)", "permisos": ["OBJECT_CREATE", "OBJECT_INSPECT", "OBJECT_READ"], "uso": "añade la entrada «unsealed» del failback manual (además firma con la clave Ed25519 del operador)"},
    "reader": {"quien": "PAR de LECTURA por prefijo con listado, o usuario nexo-seal-reader", "permisos": ["OBJECT_INSPECT", "OBJECT_READ"], "uso": "AWS lee y lista; no puede escribir"},
    "lab_admin": {"quien": "usuario nexo-seal-lab-admin (persona; solo en el laboratorio)", "permisos": ["BUCKET_UPDATE", "RETENTION_RULE_MANAGE", "PAR_MANAGE", "OBJECT_DELETE", "OBJECT_OVERWRITE", "OBJECT_INSPECT", "OBJECT_READ"], "uso": "crea/borra la regla, los PAR y limpia el laboratorio; NUNCA lo usa un servicio"},
}


def policy_statements(bucket: str, compartment: str = "nexoeventos") -> list[str]:
    assert bucket.startswith(BUCKET_PREFIX) and bucket not in FORBIDDEN_BUCKETS
    cond = lambda perms: "where all {target.bucket.name='%s', any {%s}}" % (bucket, ", ".join(f"request.permission='{p}'" for p in perms))
    out = []
    for grupo, perms in (("nexo-seal-writers", IDENTIDADES["writer"]["permisos"]), ("nexo-seal-operators", IDENTIDADES["operator"]["permisos"]), ("nexo-seal-readers", IDENTIDADES["reader"]["permisos"])):
        out.append(f"Allow group {grupo} to read buckets in compartment {compartment} where target.bucket.name='{bucket}'")
        out.append(f"Allow group {grupo} to manage objects in compartment {compartment} {cond(perms)}")
    out.append(f"Allow group nexo-seal-lab-admins to manage buckets in compartment {compartment} where target.bucket.name='{bucket}'")
    out.append(f"Allow group nexo-seal-lab-admins to manage objects in compartment {compartment} where target.bucket.name='{bucket}'")
    out.append(f"Allow group nexo-seal-lab-admins to manage preauthenticated-requests in compartment {compartment} where target.bucket.name='{bucket}'")
    return out


def plan(bucket: str) -> list[str]:
    """Lo que habría que CREAR (con autorización específica), en orden, y cómo se limpia. NO se ejecuta."""
    return [f"1. bucket {bucket} (compartimento nexoeventos, Standard, privado, VERSIONADO DESACTIVADO) — nunca nexoeventos-recovery",
            "2. grupos nexo-seal-writers/operators/readers/lab-admins, usuarios de servicio y claves de API (privadas solo en su nodo) + las políticas de policy_statements()",
            "3. regla de retención CON plazo (1 día o el mínimo permitido) y SIN bloquear: se valida que bloquea sobrescribir/borrar incluso al administrador",
            "4. PAR de LECTURA por prefijo `seal-log/` con listado (lector) y, SOLO para el control negativo T9b, un PAR de lectura/escritura creado por el administrador y revocado de inmediato. El sello NUNCA se escribe por PAR",
            "5. pruebas T1–T10 (run_suite) y evaluación (evaluate)",
            "LIMPIEZA: borrar PAR, borrar la regla (sin bloquear), borrar los objetos, el bucket, usuarios, grupos y políticas del laboratorio. Costo esperado ≈ 0 (objetos de bytes; sin versionado; sin replicación)."]


# (id, identidad, operación, nombre, condición, resultado esperado, garantía que sostiene)
TESTS = [
    ("T1", "writer", "create", "seal-log/0000000001.json", None, "allow", "writer_crea"),
    ("T2", "writer", "create", "seal-log/0000000001.json", "if-none-match", "precondition_failed", "writer_no_duplica"),
    ("T3", "writer", "overwrite", "seal-log/0000000001.json", None, "deny", "writer_solo_adicion"),
    ("T4", "writer", "delete", "seal-log/0000000001.json", None, "deny", "writer_solo_adicion"),
    ("T5", "operator", "create", "seal-log/0000000002.json", None, "allow", "operator_crea"),
    ("T5b", "operator", "overwrite", "seal-log/0000000002.json", None, "deny", "operator_solo_adicion"),
    ("T6", "reader", "list", "seal-log/", None, "allow", "lector_lista_completo"),
    ("T6b", "reader", "read", "seal-log/0000000001.json", None, "allow", "lector_lee"),
    ("T6c", "reader", "create", "seal-log/0000000003.json", None, "deny", "lector_solo_lectura"),
    ("T6d", "reader", "overwrite", "seal-log/0000000001.json", None, "deny", "lector_solo_lectura"),
    ("T7", "par_read", "list", "seal-log/", None, "allow", "par_lectura_lista"),
    ("T7b", "par_read", "put", "seal-log/0000000009.json", None, "deny", "par_lectura_no_escribe"),
    ("T9", "par_rw_by_writer", "overwrite", "seal-log/0000000001.json", None, "deny_or_create_refused", "par_escritura_solo_adicion"),     # PROBAR: ¿un PAR creado por una identidad sin OVERWRITE sobrescribe? (SIN retención: así no la enmascara)
    ("T9b", "par_rw_by_admin", "overwrite", "seal-log/0000000001.json", None, "allow_without_retention", "control_negativo_par_admin"),    # CONTROL NEGATIVO: sin retención un PAR de admin SÍ sobrescribe
    ("T8pre", "lab_admin", "enable_retention", "", None, "allow", "retencion_activada"),                                                    # solo ahora se activa la regla: las pruebas de IAM (T1–T9) se hacen SIN ella para que no las enmascare
    ("T8", "lab_admin", "overwrite", "seal-log/0000000001.json", None, "deny_while_retention", "retencion_bloquea_al_admin"),
    ("T8b", "lab_admin", "delete", "seal-log/0000000001.json", None, "deny_while_retention", "retencion_bloquea_al_admin"),
    ("T10", "lab_admin", "cleanup_after_rule_delete", "seal-log/0000000001.json", None, "allow", "limpieza_posible"),
]
REQUIRED = ["writer_crea", "writer_no_duplica", "writer_solo_adicion", "operator_crea", "operator_solo_adicion", "lector_lista_completo", "lector_lee", "lector_solo_lectura", "par_lectura_lista", "par_lectura_no_escribe",
            "retencion_activada", "retencion_bloquea_al_admin", "limpieza_posible"]
INFORMATIVE = ["par_escritura_solo_adicion", "control_negativo_par_admin"]


# Qué necesita cada prueba (para decidir qué se puede autorizar primero)
REQUIERE = {"T1": {"iam_nuevo"}, "T2": {"iam_nuevo"}, "T3": {"iam_nuevo"}, "T4": {"iam_nuevo"}, "T5": {"iam_nuevo"}, "T5b": {"iam_nuevo"}, "T6": {"iam_nuevo"}, "T6b": {"iam_nuevo"}, "T6c": {"iam_nuevo"}, "T6d": {"iam_nuevo"},
            "T7": {"par"}, "T7b": {"par"}, "T9": {"iam_nuevo", "par"}, "T9b": {"par"}, "T8pre": {"retencion"}, "T8": {"retencion"}, "T8b": {"retencion"}, "T10": {"retencion"}}
FASES = [("F0 · SOLO administrador existente, sin IAM nueva y sin retención: bucket + objeto + PAR de lectura", ["T7", "T7b", "T9b"]),
         ("F1 · IAM nueva (grupo+política+membresía) SIN retención: solo-adición por permisos", ["T1", "T2", "T3", "T4", "T5", "T5b", "T6", "T6b", "T6c", "T6d", "T9"]),
         ("F2 · retención con plazo SIN bloquear y limpieza", ["T8pre", "T8", "T8b", "T10"])]
IDENTIDADES_EXISTENTES = {
    "nexoeventos-backup-uploader": {"grupo": "nexoeventos-backup-uploaders", "permisos_efectivos": "OBJECT_CREATE, OBJECT_READ, OBJECT_INSPECT y lectura de bucket, SOLO sobre nexoeventos-recovery (condición target.bucket.name); observado: no sobrescribe ni borra",
                                 "en_un_bucket_nuevo": "NINGUNO (la política está atada al nombre del bucket de respaldos)", "claves_api": 1, "uso_actual": "subida de respaldos: NO se reutiliza para el laboratorio sin una política propia"},
    "admin@example.invalid": {"grupo": "Administrators", "permisos_efectivos": "manage all-resources en la tenencia (política «Tenant Admin Policy»), MFA activo, 1 clave de API (perfil DEFAULT)", "en_un_bucket_nuevo": "TODOS: sirve como lab_admin sin cambios de IAM", "uso_actual": "administración"},
}
NO_EXISTEN = ["reader (no hay usuario ni grupo de solo lectura)", "operator", "writer dedicado del sello", "grupos dinámicos (no hay; no se usa OCI Compute en el laboratorio)"]
CAMBIOS_IAM_MINIMOS = ["1 grupo nexo-seal-writers + 1 usuario de servicio nexo-seal-writer-lab (clave de API propia, generada en su nodo) o la reutilización del usuario existente mediante membresía (NO recomendada: mezcla funciones)",
                       "1 política con las 2 sentencias del writer de policy_statements() (read buckets + manage objects con request.permission ∈ {CREATE, INSPECT, READ}) atada al bucket nexo-seal-lab-*",
                       "(opcional en F1) grupo/usuario nexo-seal-operator con las mismas sentencias para probar T5/T5b; el reader del laboratorio es un PAR de lectura creado por el administrador (sin IAM)"]
PERMISOS_BUCKET_AISLADO = ["BUCKET_CREATE + OBJECTSTORAGE_NAMESPACE_READ (crear el bucket Standard, privado, versionado DESACTIVADO —valor por defecto de un bucket nuevo—)", "BUCKET_UPDATE + RETENTION_RULE_MANAGE (F2)", "PAR_MANAGE (F0/F1)",
                           "OBJECT_DELETE + OBJECT_OVERWRITE + OBJECT_VERSION_DELETE si hubiera versiones (limpieza)", "El administrador existente (Administrators) los tiene todos: F0 y F2 no exigen IAM nueva; F1 sí."]


def cleanup_plan(bucket: str) -> list[str]:
    """LIMPIEZA EXACTA, en este orden (cada paso solo toca recursos creados por el laboratorio; se verifica con una lista de solo lectura al final)."""
    assert bucket.startswith(BUCKET_PREFIX) and bucket not in FORBIDDEN_BUCKETS
    return [f"1. listar PAR del bucket {bucket} y borrar SOLO los creados por el laboratorio (nombres hybrid-seal-lab-*); verificar 0",
            f"2. borrar la regla de retención (sin bloquear) del bucket {bucket}; verificar 0 reglas",
            f"3. borrar todos los objetos y versiones del bucket {bucket} (el bucket lo creamos sin versionado: solo objetos); verificar lista vacía",
            f"4. borrar el bucket {bucket}; verificar que no existe y que nexoeventos-recovery sigue con 23 objetos y 472003 bytes (huella previa)",
            "5. IAM del laboratorio: borrar la política, el usuario de servicio (y su clave de API) y el grupo creados para el laboratorio; verificar que solo quedan los 3 grupos y 2 usuarios iniciales",
            "6. borrar del equipo los archivos temporales (URL de PAR, claves del laboratorio) y confirmar permisos/ausencia"]


PRESUPUESTO = {"techo_usd": 0.05, "computo_necesario": False, "detalle": "Object Storage Standard: objetos de pocos bytes (≈ 10 KB en total) durante horas; sin versionado, sin replicación, sin Compute, sin Vault; el bucket de respaldos actual (472 KB, 23 objetos) ni se toca. Coste esperado ≈ 0 (por debajo de cualquier céntimo)."}


def run_suite(cloud) -> list[dict]:
    """`cloud.execute(identidad, operacion, nombre, condicion) -> str` con uno de: allow | deny | precondition_failed | create_refused. Con la retención activa para lab_admin: `deny`."""
    out = []
    for tid, ident, op, name, cond, expected, g in TESTS:
        got = cloud.execute(ident, op, name, cond)
        ok = (got == expected) or (expected == "deny_while_retention" and got == "deny") or (expected == "deny_or_create_refused" and got in ("deny", "create_refused")) or (expected == "allow_without_retention" and got == "allow")
        out.append({"id": tid, "garantia": g, "esperado": expected, "obtenido": got, "ok": ok})
    return out


def evaluate(results: list[dict]) -> dict:
    por = {}
    for r in results: por.setdefault(r["garantia"], []).append(r["ok"])
    garantias = {g: all(v) for g, v in por.items()}
    faltan = [g for g in REQUIRED if g not in garantias]
    falla = [g for g in REQUIRED if g in garantias and not garantias[g]]
    ok = not faltan and not falla
    return {"garantias": garantias, "faltan": faltan, "fallan": falla, "par_de_escritura_es_solo_adicion": garantias.get("par_escritura_solo_adicion", None),
            "validated_antirollback_propuesto": ok,
            "nota": "validated_antirollback SOLO pasa a true tras una ejecución REAL completa de la matriz con todas las garantías requeridas demostradas Y una persona lo declara en la configuración; este evaluador solo lo propone."}


@dataclass
class FakeCloud:
    """OCI simulado con la semántica DOCUMENTADA (no es OCI): permisos por identidad, retención sin bloquear y PAR. Sirve para probar el evaluador y los controles negativos."""
    perms: dict = field(default_factory=lambda: {"writer": {"CREATE", "INSPECT", "READ"}, "operator": {"CREATE", "INSPECT", "READ"}, "reader": {"INSPECT", "READ"}, "lab_admin": {"CREATE", "INSPECT", "READ", "OVERWRITE", "DELETE"}})
    retention_active: bool = False
    retention_effective: bool = True       # False modela un bucket donde la regla NO bloquea (p. ej. con versionado o mal creada)
    par_rw_by_writer_overwrites: bool = False
    objs: dict = field(default_factory=dict)

    def execute(self, ident, op, name, cond):
        P = self.perms.get(ident, set())
        if ident == "par_read":
            return {"list": "allow", "read": "allow"}.get(op, "deny")                                              # un PAR de lectura no escribe
        if ident == "par_rw_by_writer":
            return "create_refused" if not self.par_rw_by_writer_overwrites else "allow"
        if ident == "par_rw_by_admin":
            return "deny" if self.retention_active else "allow"
        if op == "create":
            if name in self.objs: return "precondition_failed" if cond == "if-none-match" else ("allow" if "OVERWRITE" in P else "deny")
            if "CREATE" not in P: return "deny"
            self.objs[name] = 1; return "allow"
        if op == "overwrite": return "deny" if (self.retention_active or "OVERWRITE" not in P) else "allow"
        if op == "delete": return "deny" if (self.retention_active or "DELETE" not in P) else "allow"
        if op == "put": return "deny"
        if op in ("list", "read"): return "allow" if "INSPECT" in P else "deny"
        if op == "enable_retention":
            self.retention_active = self.retention_effective; return "allow" if "OVERWRITE" in P else "deny"
        if op == "cleanup_after_rule_delete": self.retention_active = False; return "allow" if "DELETE" in P else "deny"
        return "deny"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(); ap.add_argument("cmd", choices=["plan", "politicas", "pruebas", "limpieza", "fases"]); ap.add_argument("--bucket", default=BUCKET_PREFIX + "20261121"); a = ap.parse_args(argv)
    if a.bucket in FORBIDDEN_BUCKETS or not a.bucket.startswith(BUCKET_PREFIX):
        print("RECHAZADO: el laboratorio usa un bucket INDEPENDIENTE con prefijo nexo-seal-lab-, nunca nexoeventos-recovery.", file=sys.stderr); return 3
    if a.cmd == "plan": print("\n".join(plan(a.bucket)))
    elif a.cmd == "politicas": print("\n".join(policy_statements(a.bucket)))
    elif a.cmd == "limpieza": print("\n".join(cleanup_plan(a.bucket)))
    elif a.cmd == "fases": print(json.dumps([{"fase": n, "pruebas": ids, "requiere": sorted(set().union(*(REQUIERE[i] for i in ids)))} for n, ids in FASES], indent=1, ensure_ascii=False))
    else: print(json.dumps([dict(zip(("id", "identidad", "operacion", "objeto", "condicion", "esperado", "garantia"), t)) for t in TESTS], indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
