import json
import os

import pytest

from ops_center import identities as I
from ops_center.audit import AuditLog


def test_cadena_integra_y_detecta_edicion_y_borrado(tmp_path):
    a = AuditLog(tmp_path / "a.jsonl")
    for i in range(4): a.append("u", "ev", n=i)
    assert a.verify()["ok"] and a.verify()["entradas"] == 4
    lines = (tmp_path / "a.jsonl").read_text().splitlines()
    e = json.loads(lines[1]); e["actor"] = "otro"; lines[1] = json.dumps(e)
    (tmp_path / "a.jsonl").write_text("\n".join(lines) + "\n"); assert not a.verify()["ok"]
    (tmp_path / "b.jsonl").write_text("\n".join([lines[0], lines[2], lines[3]]) + "\n"); assert not AuditLog(tmp_path / "b.jsonl").verify()["ok"]


def test_auditoria_no_guarda_secretos_ni_cadenas_enormes(tmp_path):
    a = AuditLog(tmp_path / "a.jsonl"); e = a.append("u", "ev", token="abc", clave_privada="x", nota="y" * 5000)
    assert e["data"]["token"] == "[omitido]" and e["data"]["clave_privada"] == "[omitido]" and len(e["data"]["nota"]) == 300
    assert oct(os.stat(tmp_path / "a.jsonl").st_mode & 0o777) == "0o600"


def test_identidades_exigen_0600_y_no_arrancan_vacias(tmp_path):
    p = tmp_path / "i.json"; p.write_text(json.dumps({"identities": [{"id": "a", "role": "viewer", "token_sha256": I.hash_token("x")}]}))
    os.chmod(p, 0o644)
    with pytest.raises(I.IdentityError): I.load(p)
    os.chmod(p, 0o600); assert "a" in I.load(p)
    p.write_text(json.dumps({"identities": []}))
    with pytest.raises(I.IdentityError): I.load(p)
    p.write_text(json.dumps({"identities": [{"id": "a", "role": "admin", "token_sha256": "0" * 64}]}))
    with pytest.raises(I.IdentityError): I.load(p)


def test_no_existe_rol_ejecutor():
    assert not any("execute" in perms for perms in I.PERMS.values())
    assert I.can("approver", "decide") and not I.can("approver", "request") and not I.can("requester", "decide") and not I.can("viewer", "request")


def test_bloqueo_tras_fallos_repetidos():
    t = [0.0]; a = I.Authenticator({"a": {"role": "viewer", "token_sha256": I.hash_token("ok")}}, max_failures=3, block_s=60, clock=lambda: t[0])
    for _ in range(3): assert a.check("Bearer mal", "ip")[0] is None
    assert a.check("Bearer ok", "ip") == (None, "bloqueado")
    t[0] = 61; assert a.check("Bearer ok", "ip")[0]["id"] == "a"
