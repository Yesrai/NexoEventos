import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts/multicloud/oci-drill"))
import plan_guard as pg  # noqa: E402

INST, BAS = "module.recovery.oci_core_instance.recovery[0]", "module.recovery.oci_bastion_bastion.this[0]"
RULE, SL = "module.network.oci_core_network_security_group_security_rule.https_from_subnet[0]", pg.SECLIST


def ch(addr, actions, after=None):
    return {"address": addr, "change": {"actions": actions, "after": after}}


def good_create():
    return {"resource_changes": [
        ch(INST, ["create"], {"shape": "VM.Standard.E5.Flex", "shape_config": [{"ocpus": 1, "memory_in_gbs": 8}], "create_vnic_details": [{"assign_public_ip": "false"}]}),
        ch(BAS, ["create"]), ch(RULE, ["create"], {"direction": "INGRESS", "source": "10.30.1.0/24"}),
        ch(SL, ["update"], {"egress_security_rules": [{"destination": "10.30.1.0/24"}]}), ch("module.network.oci_core_vcn.this", ["no-op"])]}


def test_create_plan_valid_and_every_deviation_is_rejected():
    assert pg.check(good_create(), "create", shape="VM.Standard.E5.Flex", max_ocpus=2, max_mem=16) == []
    k = lambda p, **kw: pg.check(p, "create", shape="VM.Standard.E5.Flex", max_ocpus=kw.get("o", 2), max_mem=16)
    p = good_create(); p["resource_changes"].append(ch("module.network.oci_core_vcn.this", ["delete", "create"])); assert any("FUERA" in e for e in k(p))     # recurso compartido recreado
    p = good_create(); p["resource_changes"].append(ch("module.storage.oci_objectstorage_bucket.recovery", ["update"])); assert any("FUERA" in e for e in k(p))
    p = good_create(); p["resource_changes"][0]["change"]["after"]["create_vnic_details"] = [{"assign_public_ip": "true"}]; assert any("IP pública" in e for e in k(p))
    p = good_create(); p["resource_changes"][0]["change"]["after"]["shape_config"] = [{"ocpus": 8, "memory_in_gbs": 8}]; assert any("tope" in e for e in k(p))
    p = good_create(); p["resource_changes"][0]["change"]["after"]["shape"] = "VM.Standard.E4.Flex"; assert any("forma" in e for e in k(p))
    p = good_create(); p["resource_changes"][2]["change"]["after"]["source"] = "0.0.0.0/0"; assert any("subred privada" in e for e in k(p))
    p = good_create(); p["resource_changes"][3]["change"]["after"]["egress_security_rules"].append({"destination": "0.0.0.0/0"}); assert any("destino inesperado" in e for e in k(p))
    p = good_create(); p["resource_changes"][1]["change"]["actions"] = ["delete"]; assert any("solo se permite el alta" in e for e in k(p))


def test_teardown_only_allows_deleting_the_three_temporary_resources():
    ok = {"resource_changes": [ch(INST, ["delete"]), ch(BAS, ["delete"]), ch(RULE, ["delete"]), ch(SL, ["update"], {"egress_security_rules": []})]}
    assert pg.check(ok, "teardown", shape="x", max_ocpus=2, max_mem=16) == []
    for extra in (ch("module.network.oci_core_vcn.this", ["delete"]), ch("module.network.oci_core_subnet.private", ["delete"]), ch("module.iam.oci_identity_user.uploader", ["delete"]),
                  ch("module.storage.oci_objectstorage_bucket.recovery", ["delete"]), ch(INST, ["create"])):
        bad = {"resource_changes": ok["resource_changes"][:3] + [extra]}
        assert pg.check(bad, "teardown", shape="x", max_ocpus=2, max_mem=16), extra


def test_cli_exit_codes(tmp_path):
    f = tmp_path / "p.json"; f.write_text(json.dumps(good_create()))
    run = lambda *a: subprocess.run([sys.executable, str(ROOT / "scripts/multicloud/oci-drill/plan_guard.py"), *a], capture_output=True, text=True)
    assert run("--mode", "create", "--plan-json", str(f)).returncode == 0
    assert run("--mode", "teardown", "--plan-json", str(f)).returncode == 1
    assert run("--mode", "create", "--plan-json", str(tmp_path / "no.json")).returncode == 2
