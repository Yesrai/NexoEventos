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


# ───────────── modos «-public» (T3: entrada HTTPS de prueba) ─────────────
PUBADDR = lambda n: "module.public_entry." + n


def good_public():
    sub = "10.30.2.0/24"
    rs = [ch(pg.INST_ADDR, ["create"], {"shape": "VM.Standard.E2.1.Micro", "create_vnic_details": [{"assign_public_ip": "true"}]}),
          ch(pg.BAS_ADDR, ["create"], {"client_cidr_block_allow_list": ["203.0.113.9/32"]}),
          ch(PUBADDR("oci_core_internet_gateway.this[0]"), ["create"], {}), ch(PUBADDR("oci_core_route_table.public[0]"), ["create"], {}),
          ch(PUBADDR("oci_core_security_list.public[0]"), ["create"], {"ingress_security_rules": [], "egress_security_rules": [{"destination": sub, "tcp_options": [{"min": 22, "max": 22}]}]}),
          ch(PUBADDR("oci_core_subnet.public[0]"), ["create"], {"cidr_block": sub, "prohibit_public_ip_on_vnic": False}),
          ch(PUBADDR("oci_core_network_security_group.public[0]"), ["create"], {}),
          ch(PUBADDR("oci_core_network_security_group_security_rule.ssh_from_bastion_subnet[0]"), ["create"], {"direction": "INGRESS", "protocol": "6", "source": sub, "tcp_options": [{"destination_port_range": [{"min": 22, "max": 22}]}]}),
          ch(PUBADDR("oci_core_network_security_group_security_rule.https_out[0]"), ["create"], {"direction": "EGRESS", "protocol": "6", "destination": "0.0.0.0/0", "tcp_options": [{"destination_port_range": [{"min": 443, "max": 443}]}]}),
          ch(PUBADDR('oci_core_network_security_group_security_rule.https_in["203.0.113.9/32"]'), ["create"], {"direction": "INGRESS", "protocol": "6", "source": "203.0.113.9/32", "tcp_options": [{"destination_port_range": [{"min": 443, "max": 443}]}]}),
          ch("module.network.oci_core_vcn.this", ["no-op"])]
    return {"resource_changes": rs}


def idx(p, addr_part): return next(i for i, c in enumerate(p["resource_changes"]) if addr_part in c["address"])


def test_create_public_valido_y_cada_desviacion_se_rechaza():
    assert pg.check_public(good_public(), "create-public") == []
    cases = [
        (lambda p: p["resource_changes"][0]["change"]["after"].update(shape="VM.Standard.E5.Flex"), "NO permitida"),
        (lambda p: p["resource_changes"][0]["change"]["after"].update(create_vnic_details=[{"assign_public_ip": "false"}]), "IP pública"),
        (lambda p: p["resource_changes"][1]["change"]["after"].update(client_cidr_block_allow_list=["0.0.0.0/0"]), "una IP /32"),
        (lambda p: p["resource_changes"][idx(p, "https_in")]["change"]["after"].update(source="0.0.0.0/0"), "TCP 443 desde un /32"),
        (lambda p: p["resource_changes"][idx(p, "https_in")]["change"]["after"].update(source="203.0.113.0/24"), "TCP 443 desde un /32"),
        (lambda p: p["resource_changes"][idx(p, "https_in")]["change"]["after"].update(tcp_options=[{"destination_port_range": [{"min": 22, "max": 22}]}]), "TCP 443 desde un /32"),
        (lambda p: p["resource_changes"][idx(p, "https_in")]["change"]["after"].update(tcp_options=[{"destination_port_range": [{"min": 5432, "max": 5432}]}]), "TCP 443 desde un /32"),
        (lambda p: p["resource_changes"][idx(p, "ssh_from")]["change"]["after"].update(source="0.0.0.0/0"), "SSH solo"),
        (lambda p: p["resource_changes"][idx(p, "https_out")]["change"]["after"].update(tcp_options=[{"destination_port_range": [{"min": 1, "max": 65535}]}]), "única salida"),
        (lambda p: p["resource_changes"][idx(p, "security_list")]["change"]["after"].update(ingress_security_rules=[{"source": "0.0.0.0/0"}]), "reglas de entrada"),
        (lambda p: p["resource_changes"][idx(p, "subnet.public")]["change"]["after"].update(prohibit_public_ip_on_vnic=True), "admitir IP pública"),
        (lambda p: p["resource_changes"].append(ch("module.storage.oci_objectstorage_bucket.recovery", ["update"])), "FUERA de la lista blanca"),
        (lambda p: p["resource_changes"].append(ch("module.network.oci_core_vcn.this", ["delete", "create"])), "FUERA de la lista blanca"),
        (lambda p: p["resource_changes"][idx(p, "internet_gateway")]["change"].update(actions=["delete"]), "solo se permite el alta"),
        (lambda p: p["resource_changes"].pop(idx(p, "internet_gateway")), "falta el alta esperada"),
        (lambda p: p["resource_changes"].pop(idx(p, "https_in")), "ninguna regla HTTPS"),
    ]
    for mut, expect in cases:
        p = good_public(); mut(p); errs = pg.check_public(p, "create-public"); assert any(expect in e for e in errs), (expect, errs)


def test_create_public_limita_el_numero_de_origenes_y_el_tamano_de_a1():
    p = good_public()
    for i in range(5): p["resource_changes"].append(ch(PUBADDR(f'oci_core_network_security_group_security_rule.https_in["198.51.100.{i}/32"]'), ["create"], {"direction": "INGRESS", "protocol": "6", "source": f"198.51.100.{i}/32", "tcp_options": [{"destination_port_range": [{"min": 443, "max": 443}]}]}))
    assert any("demasiados orígenes" in e for e in pg.check_public(p, "create-public"))
    p = good_public(); p["resource_changes"][0]["change"]["after"] = {"shape": "VM.Standard.A1.Flex", "shape_config": [{"ocpus": 4, "memory_in_gbs": 24}], "create_vnic_details": [{"assign_public_ip": "true"}]}
    assert any("A1 por encima del tope" in e for e in pg.check_public(p, "create-public"))


def test_los_modos_antiguos_siguen_prohibiendo_la_entrada_publica():
    p = good_public(); assert pg.check(p, "create", shape="VM.Standard.E2.1.Micro", max_ocpus=2, max_mem=16) != []        # la guarda original rechaza cualquier recurso de public_entry


def test_teardown_public_solo_bajas_de_lo_creado():
    p = good_public(); [c["change"].update(actions=["delete"]) for c in p["resource_changes"] if c["change"]["actions"] == ["create"]]
    assert pg.check_public(p, "teardown-public") == []
    p2 = good_public(); assert any("solo se permite la baja" in e for e in pg.check_public(p2, "teardown-public"))
    p3 = good_public(); [c["change"].update(actions=["delete"]) for c in p3["resource_changes"] if c["change"]["actions"] == ["create"]]; p3["resource_changes"].append(ch("module.network.oci_core_subnet.private", ["delete"]))
    assert any("FUERA" in e for e in pg.check_public(p3, "teardown-public"))


def test_cli_modos_public_aceptan_y_rechazan(tmp_path):
    f = tmp_path / "p.json"; f.write_text(json.dumps(good_public()))
    ok = subprocess.run([sys.executable, str(ROOT / "scripts/multicloud/oci-drill/plan_guard.py"), "--mode", "create-public", "--plan-json", str(f)], capture_output=True, text=True); assert ok.returncode == 0, ok.stdout
    bad = good_public(); bad["resource_changes"][0]["change"]["after"]["shape"] = "VM.Standard.E5.Flex"; f.write_text(json.dumps(bad))
    r = subprocess.run([sys.executable, str(ROOT / "scripts/multicloud/oci-drill/plan_guard.py"), "--mode", "create-public", "--plan-json", str(f)], capture_output=True, text=True); assert r.returncode == 1 and "NO permitida" in r.stdout
