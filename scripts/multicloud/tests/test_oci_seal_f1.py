import io, os, re, stat, sys, tempfile, time
from contextlib import redirect_stdout
from pathlib import Path
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts/multicloud/hybrid"))
import oci_seal_lab_f1 as F  # noqa: E402

PRE = {"grupos": ["Administrators", "All Domain Users", "nexoeventos-backup-uploaders"], "usuarios": ["nexoeventos-backup-uploader", "persona@example.com"], "politicas": ["nexoeventos-backup-uploaders", "T:Tenant Admin Policy"], "buckets": ["nexoeventos-recovery"]}


PRE_S = {k: sorted(v) for k, v in PRE.items()}


class FakeCloud:
    """OCI simulado: IAM mínima + Object Storage con la semántica documentada. Registra el ORDEN de los borrados y lo que se intentó."""
    def __init__(self, extra_perms=(), fail=(), propagate_after=0):
        self.id = {k: list(v) for k, v in PRE.items()}; self.extra, self.fail, self.log, self.objs, self.policy_stmts = set(extra_perms), set(fail), [], {}, None
        self.propagate_after, self.calls, self.local = propagate_after, 0, True; self.recovery_touched = False; self.users_keys = {}; self.members = {}
    def identity_snapshot(self): return {k: sorted(v) for k, v in self.id.items()}
    def identity_diff(self, a, b): return {k: {"antes": a[k], "despues": b[k]} for k in a if a[k] != b[k]}
    def recovery_unchanged(self): return not self.recovery_touched
    def bucket_exists(self, n): return n in self.id["buckets"]
    def _chk(self, what):
        if what in self.fail: raise RuntimeError(f"fallo simulado en {what}")
    def create_bucket(self, n): self._chk("create_bucket"); self.id["buckets"].append(n)
    def put_object(self, b, n, d): self.objs[(b, n)] = d
    def create_group(self, n): self._chk("create_group"); self.id["grupos"].append(n); return "g:" + n
    def create_user(self, n): self._chk("create_user"); self.id["usuarios"].append(n); return "u:" + n
    def add_member(self, u, g): self.members["m"] = (u, g); return "m"
    def create_policy(self, n, st): self._chk("create_policy"); self.id["politicas"].append(n); self.policy_stmts = st; return "p:" + n
    def new_api_key(self, u):
        self.users_keys[u] = "aa:bb:cc:dd:ee:ff:00:11:22:33:44:55:66:77:88:99"; return "PUBPEM", self.users_keys[u], Path("/nonexistent/priv.pem")
    def delete_policy(self, pid): self._chk("delete_policy"); self.log.append("policy"); self.id["politicas"].remove(pid[2:]); self.policy_stmts = None
    def delete_api_key(self, u, fp): self._chk("delete_api_key"); self.log.append("api_key"); self.users_keys.pop(u, None)
    def remove_member(self, m): self._chk("remove_member"); self.log.append("member"); self.members.pop(m, None)
    def delete_user(self, uid): self._chk("delete_user"); self.log.append("user"); self.id["usuarios"].remove(uid[2:])
    def delete_group(self, gid): self._chk("delete_group"); self.log.append("group"); self.id["grupos"].remove(gid[2:])
    def delete_bucket_and_objects(self, b): self._chk("delete_bucket"); self.log.append("bucket"); self.id["buckets"].remove(b); self.objs = {k: v for k, v in self.objs.items() if k[0] != b}
    def safety_cleanup(self, op, b): self.log.append("safety:" + op)
    def remove_local_files(self): self.local = False
    def local_files_removed(self): return not self.local
    def writer(self, user_id, fp, priv):
        cloud = self
        class W:
            def execute(self_, op, bucket, name, cond):
                cloud.calls += 1
                if cloud.calls <= cloud.propagate_after or cloud.policy_stmts is None: return "deny"
                perms = set(re.findall(r"request.permission='(\w+)'", cloud.policy_stmts[1])) | cloud.extra; inb = (bucket in cloud.policy_stmts[1] and "target.bucket.name='%s'" % bucket in cloud.policy_stmts[1])
                if op in ("list_other_bucket", "read_other_bucket", "head_other_bucket", "create_bucket", "create_par", "read_iam"): return "allow" if (op in ("create_bucket",) and "BUCKET_CREATE" in cloud.extra) else "deny"
                if not inb: return "deny"
                key = (bucket, name)
                if op == "create":
                    if key in cloud.objs: return "precondition_failed" if cond == "if-none-match" else ("allow" if "OBJECT_OVERWRITE" in perms else "deny")
                    if "OBJECT_CREATE" not in perms: return "deny"
                    cloud.objs[key] = b"x"; return "allow"
                if op == "overwrite": return "allow" if "OBJECT_OVERWRITE" in perms else "deny"
                if op == "delete": return "allow" if "OBJECT_DELETE" in perms else "deny"
                if op in ("read", "list"): return "allow" if "OBJECT_READ" in perms or "OBJECT_INSPECT" in perms else "deny"
                return "deny"
        return W()


@pytest.fixture(autouse=True)
def sin_espera(monkeypatch): monkeypatch.setattr(F.time, "sleep", lambda s: None)


def test_politica_exacta_sin_comodines_y_sin_overwrite_delete_par_ni_bucket():
    b = F.PREFIX + "20261121t000000"; st = F.policy_statements(b, F.PREFIX + "writers-x"); txt = "\n".join(st)
    assert len(st) == 2 and txt.count(f"target.bucket.name='{b}'") == 2 and "*" not in txt and "%" not in txt and PRE["buckets"][0] not in txt
    perms = set(re.findall(r"request.permission='(\w+)'", txt)); assert perms == {"OBJECT_CREATE", "OBJECT_READ", "OBJECT_INSPECT"}
    for prohibido in ("OBJECT_OVERWRITE", "OBJECT_DELETE", "PAR_MANAGE", "BUCKET_CREATE", "BUCKET_UPDATE", "in tenancy", "all-resources", "object-family"): assert prohibido not in txt, prohibido
    for malo in ("nexoeventos-recovery", F.PREFIX + "*", F.PREFIX + "a%"):
        with pytest.raises(AssertionError): F.policy_statements(malo, "g")


def test_camino_feliz_todas_las_garantias_limpieza_en_orden_y_todo_igual_que_al_inicio():
    c = FakeCloud(); r = F.run_f1(c, "t1")
    assert r["ok"] and r["evaluacion"]["todas"] and all(p["ok"] for p in r["pasos"]) and r["evaluacion"]["T9"] == "NO APLICA" and r["evaluacion"]["validated_antirollback_propuesto"] is False
    assert c.log == ["policy", "api_key", "member", "user", "group", "bucket"]                       # primero se retira el ACCESO, al final los datos
    l = r["limpieza"]; assert l["identidad_igual_a_la_inicial"] and l["bucket_existe"] is False and l["recuperacion_identica"] and l["archivos_locales_eliminados"] and l["pendientes"] == []
    assert c.identity_snapshot() == PRE_S                                                              # las identidades PREEXISTENTES ni se tocaron ni se alteraron
    assert not any(p["id"] == "T9" for p in r["pasos"])                                              # T9 no aplica: no se ejecuta


def test_si_el_writer_pudiera_sobrescribir_o_borrar_o_crear_buckets_se_detecta_y_se_revierte():
    for extra, fallan in (({"OBJECT_OVERWRITE"}, {"T3", "T3b"}), ({"OBJECT_DELETE"}, {"T4"}), ({"BUCKET_CREATE"}, {"T11"})):
        c = FakeCloud(extra_perms=extra); r = F.run_f1(c, "t2")
        assert not r["ok"] and {p["id"] for p in r["pasos"] if not p["ok"]} >= fallan, extra
        assert r["limpieza"]["identidad_igual_a_la_inicial"] and r["limpieza"]["bucket_existe"] is False                 # aunque la prueba falle, se limpia
        if "BUCKET_CREATE" in extra: assert "safety:create_bucket" in c.log


def test_fallo_al_borrar_un_recurso_iam_se_informa_exacto_no_se_toca_nada_mas_y_la_limpieza_continua():
    c = FakeCloud(fail={"delete_user"}); r = F.run_f1(c, "t3")
    pend = r["limpieza"]["pendientes"]; assert [p["recurso"] for p in pend] == [f"usuario {F.PREFIX}writer-t3"] and not r["ok"]
    assert "group" in c.log and "bucket" in c.log and "policy" in c.log                               # lo demás SÍ se limpió
    assert r["limpieza"]["identidad_igual_a_la_inicial"] is False and F.PREFIX + "writer-t3" in r["limpieza"]["diferencias"]["usuarios"]["despues"]
    assert set(PRE["usuarios"]) <= set(c.id["usuarios"])                                             # los usuarios preexistentes siguen
    # un fallo en la política (lo primero que se borra) tampoco detiene el resto
    c = FakeCloud(fail={"delete_policy"}); r = F.run_f1(c, "t4"); assert [p["recurso"] for p in r["limpieza"]["pendientes"]] == [f"política {F.PREFIX}writer-policy-t4"] and "bucket" in c.log


def test_fallo_a_mitad_de_la_creacion_solo_limpia_lo_creado_y_la_falta_de_propagacion_aborta():
    c = FakeCloud(fail={"create_policy"}); r = F.run_f1(c, "t5")
    assert "error" in r and "api_key" not in c.log and "policy" not in c.log and c.log == ["member", "user", "group", "bucket"] and c.identity_snapshot() == PRE_S
    c = FakeCloud(propagate_after=10 ** 6); times = iter([0, 0, 301, 301, 301]); orig = F.time.time; F.time.time = lambda: next(times, 301)
    try: r = F.run_f1(c, "t6")
    finally: F.time.time = orig
    assert "no llegó a propagarse" in r["error"] and r["limpieza"]["identidad_igual_a_la_inicial"] and r["pasos"] == []


def test_clave_api_temporal_privada_0600_huella_estilo_oci_y_ninguna_salida_la_contiene(tmp_path):
    pub, fp, priv = F.gen_keypair(tmp_path / "k")
    assert oct(priv.stat().st_mode & 0o777) == "0o600" and oct((tmp_path / "k").stat().st_mode & 0o777) == "0o700" and re.fullmatch(r"([0-9a-f]{2}:){15}[0-9a-f]{2}", fp) and pub.startswith("-----BEGIN PUBLIC KEY-----")
    texto_privado = priv.read_text(); cuerpo = "".join(texto_privado.splitlines()[1:-1])
    r = F.run_f1(FakeCloud(), "t7"); import json; salida = json.dumps(r) + F.plan_text()
    assert cuerpo not in salida and "PRIVATE KEY" not in salida
    with pytest.raises(FileExistsError): F.gen_keypair(tmp_path / "k")                                 # no sobrescribe una clave existente


def test_t9_no_aplica_el_plan_lo_explica_y_el_run_exige_las_dos_llaves():
    p = F.plan_text(); assert "T9 · NO APLICA" in p and "PAR_MANAGE" in p and "sin Compute" in p and "0.05" in p and "T12" in p
    assert F.main(["run"]) == 3 and F.main(["run", "--confirm", "no"]) == 3
    assert len(F.PRUEBAS) >= 13 and all(t[4] in ("allow", "deny", "precondition_failed") for t in F.PRUEBAS) and not any(t[1] == "create_other_bucket" for t in F.PRUEBAS)    # nunca se intenta ESCRIBIR en el bucket protegido
    assert F.main(["plan"]) == 0 and F.main(["politica"]) == 0
