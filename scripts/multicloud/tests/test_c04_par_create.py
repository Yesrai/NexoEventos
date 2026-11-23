"""c04_par_create.py con una CLI de OCI y un portapapeles FALSOS (sin red, sin OCI real). Comprueba que la URL (token inventado) nunca sale por stdout/stderr ni se escribe en
archivos, que solo llega al portapapeles, que región/perfil/tipo/prefijo son los autorizados y que ante cualquier anomalía el PAR creado se revoca."""
import json
import os
import stat
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts/multicloud/c04_par_create.py"
TOKEN = "TOKEN-INVENTADO-SOLO-PRUEBAS-9f3a"
PFX = "backups/c04-20261119/"

FAKE_OCI = r'''#!/usr/bin/env python3
import json, os, sys
a = sys.argv[1:]
log = os.environ["FAKE_LOG"]
open(log, "a").write(json.dumps(a) + "\n")
v = os.environ.get("FAKE_VARIANT", "ok")
def out(d): print(json.dumps(d))
if a[:3] == ["os", "ns", "get"]: out({"data": "espacio123"})
elif a[:3] == ["os", "bucket", "get"]: out({"data": {"public-access-type": "ObjectRead" if v == "publico" else "NoPublicAccess"}})
elif a[:3] == ["os", "preauth-request", "list"]:
    creado = os.path.exists(os.environ["FAKE_LOG"] + ".creado")
    out({"data": [{"name": "otro", "id": "i1"}] if v == "existente" else ([{"name": "c04-escritura-20261119", "id": "idpar"}] if (v == "revocar" or (v == "json_malo" and creado)) else [])})
elif a[:3] == ["os", "preauth-request", "create"]:
    open(os.environ["FAKE_LOG"] + ".creado", "w").write("1")
    if v == "json_malo": print("esto no es json"); sys.exit(0)
    tok = os.environ["FAKE_TOKEN"]; pfx = os.environ["FAKE_PREFIX"]
    style = os.environ.get("FAKE_URI_STYLE", "relativo")
    uri = {
        "relativo": "/p/%s/n/espacio123/b/nexoeventos-recovery/o/%s" % (tok, pfx),
        "codificado": "/p/%s/n/espacio123/b/nexoeventos-recovery/o/%s" % (tok, pfx.replace("/", "%2F")),
        "sin_barra": "/p/%s/n/espacio123/b/nexoeventos-recovery/o/%s" % (tok, pfx.rstrip("/")),
        "absoluto": "https://objectstorage.sa-saopaulo-1.oraclecloud.com/p/%s/n/espacio123/b/nexoeventos-recovery/o/%s" % (tok, pfx),
        "dedicado": "https://espacio123.objectstorage.sa-saopaulo-1.oci.customer-oci.com/p/%s/n/espacio123/b/nexoeventos-recovery/o/%s" % (tok, pfx),
        "host_malo": "https://evil.example.com/p/%s/n/espacio123/b/nexoeventos-recovery/o/%s" % (tok, pfx),
        "otra_region": "https://objectstorage.us-ashburn-1.oraclecloud.com/p/%s/n/espacio123/b/nexoeventos-recovery/o/%s" % (tok, pfx),
        "http": "http://objectstorage.sa-saopaulo-1.oraclecloud.com/p/%s/n/espacio123/b/nexoeventos-recovery/o/%s" % (tok, pfx),
        "bucket_malo": "/p/%s/n/espacio123/b/otro-bucket/o/%s" % (tok, pfx),
        "ns_malo": "/p/%s/n/otroespacio/b/nexoeventos-recovery/o/%s" % (tok, pfx),
        "con_consulta": "/p/%s/n/espacio123/b/nexoeventos-recovery/o/%s?x=1" % (tok, pfx),
        "termina_en_o": "/p/%s/n/espacio123/b/nexoeventos-recovery/o/" % tok,
        "termina_en_o_abs": "https://objectstorage.sa-saopaulo-1.oraclecloud.com/p/%s/n/espacio123/b/nexoeventos-recovery/o/" % tok,
        "prefijo_parcial": "/p/%s/n/espacio123/b/nexoeventos-recovery/o/backups/" % tok,
        "mas_ruta": "/p/%s/n/espacio123/b/nexoeventos-recovery/o/%s" % (tok, pfx + "extra"),
    }[style]
    if v == "prefijo_malo": uri = uri.replace("c04-20261119", "OTRO")
    out({"data": {"id": "idpar", "name": "c04-escritura-20261119", "access-type": "AnyObjectWrite", "object-name": os.environ["FAKE_PREFIX"], "access-uri": uri,
                  "time-created": "ahora", "time-expires": a[a.index("--time-expires") + 1], "full-path": uri}})
elif a[:3] == ["os", "preauth-request", "delete"]: print("")
else: sys.exit(9)
'''
FAKE_PBCOPY = '#!/usr/bin/env python3\nimport os, sys\nif os.environ.get("FAKE_VARIANT") == "sin_pbcopy": sys.exit(1)\nopen(os.environ["FAKE_CLIP"], "wb").write(sys.stdin.buffer.read())\n'


@pytest.fixture
def env(tmp_path):
    b = tmp_path / "bin"; b.mkdir()
    for n, c in (("oci", FAKE_OCI), ("pbcopy", FAKE_PBCOPY)):
        (b / n).write_text(c); (b / n).chmod(0o755)
    work = tmp_path / "cwd"; work.mkdir()
    e = {**os.environ, "PATH": f"{b}:{os.environ['PATH']}", "FAKE_LOG": str(tmp_path / "calls.log"), "FAKE_CLIP": str(tmp_path / "clip.bin"),
         "FAKE_TOKEN": TOKEN, "FAKE_PREFIX": PFX}
    return e, work, tmp_path


def run(env_, *args, variant="ok"):
    e, work, _ = env_
    return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True, cwd=work, env={**e, "FAKE_VARIANT": variant})


def calls(env_):
    p = env_[2] / "calls.log"
    return [json.loads(l) for l in p.read_text().splitlines()] if p.exists() else []


def future():
    return (datetime.now(timezone.utc) + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")


def test_happy_path_url_only_in_clipboard_and_authorized_scope(env):
    r = run(env, "--not-after", future())
    assert r.returncode == 0, r.stderr
    assert TOKEN not in r.stdout + r.stderr and "oraclecloud.com/p/" not in r.stdout + r.stderr
    clip = (env[2] / "clip.bin").read_text()
    assert clip == f"https://objectstorage.sa-saopaulo-1.oraclecloud.com/p/{TOKEN}/n/espacio123/b/nexoeventos-recovery/o/{PFX}"
    create = next(c for c in calls(env) if c[:3] == ["os", "preauth-request", "create"])
    assert create[create.index("--access-type") + 1] == "AnyObjectWrite" and create[create.index("--object-name") + 1] == PFX
    assert "--bucket-listing-action" not in create  # sin listado
    for c in calls(env):
        assert c[c.index("--profile") + 1] == "DEFAULT" and c[c.index("--region") + 1] == "sa-saopaulo-1"
        assert TOKEN not in " ".join(c)
    exp = datetime.strptime(create[create.index("--time-expires") + 1], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    assert 99 * 60 <= (exp - datetime.now(timezone.utc)).total_seconds() <= 100 * 60 + 5
    assert list(env[1].iterdir()) == []  # no se escribió ningún archivo en el directorio de trabajo
    assert "no se muestra" in r.stdout or "NO se muestra" in r.stdout


def test_refuses_when_another_par_exists_or_bucket_is_public_or_it_is_too_late(env):
    assert run(env, "--not-after", future(), variant="existente").returncode == 1
    assert not any(c[:3] == ["os", "preauth-request", "create"] for c in calls(env))
    assert run(env, "--not-after", future(), variant="publico").returncode == 1
    assert not any(c[:3] == ["os", "preauth-request", "create"] for c in calls(env))
    before = len(calls(env))
    late = run(env, "--not-after", "2020-01-01T00:00:00Z")
    assert late.returncode == 1 and "demasiado tarde" in late.stderr and len(calls(env)) == before  # ni siquiera consulta OCI


@pytest.mark.parametrize("variant", ["prefijo_malo", "sin_pbcopy"])
def test_any_anomaly_after_creation_revokes_the_new_par(env, variant):
    r = run(env, "--not-after", future(), variant=variant)
    assert r.returncode == 1 and "REVOCADO" in r.stderr and TOKEN not in r.stdout + r.stderr
    assert any(c[:3] == ["os", "preauth-request", "delete"] for c in calls(env))


def test_revoke_deletes_only_the_named_par(env):
    r = run(env, "--revoke", variant="revocar")
    assert r.returncode == 0 and "revocado" in r.stdout.lower()
    deletes = [c for c in calls(env) if c[:3] == ["os", "preauth-request", "delete"]]
    assert len(deletes) == 1 and deletes[0][deletes[0].index("--par-id") + 1] == "idpar" and "--force" in deletes[0]


import importlib.util

_spec = importlib.util.spec_from_file_location("c04_par_create", SCRIPT)
M = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(M)
CANON = f"https://objectstorage.sa-saopaulo-1.oraclecloud.com/p/{TOKEN}/n/espacio123/b/nexoeventos-recovery/o/{PFX}"


@pytest.mark.parametrize("style", ["relativo", "codificado", "sin_barra", "absoluto", "dedicado", "termina_en_o", "termina_en_o_abs"])
def test_regression_authentic_formats_are_accepted_and_normalized(env, style):
    """Regresión (19-nov): el validador rígido rechazó el access-uri real de OCI. Se admiten las formas documentadas/plausibles (relativa o absoluta, prefijo con `/` o `%2F`,
    con o sin `/` final, anfitrión regional o dedicado) y siempre se entrega al portapapeles la URL CANÓNICA: anfitrión regional y prefijo en barras normales."""
    e, work, tmp = env
    e["FAKE_URI_STYLE"] = style
    r = run((e, work, tmp), "--not-after", future())
    assert r.returncode == 0, r.stderr
    assert (tmp / "clip.bin").read_text() == CANON
    assert TOKEN not in r.stdout + r.stderr


@pytest.mark.parametrize("style", ["host_malo", "otra_region", "http", "bucket_malo", "ns_malo", "con_consulta", "mas_ruta", "prefijo_parcial"])
def test_regression_validation_stays_strict_region_bucket_namespace_prefix_scheme(env, style):
    e, work, tmp = env
    e["FAKE_URI_STYLE"] = style
    r = run((e, work, tmp), "--not-after", future())
    assert r.returncode == 1 and "REVOCADO" in r.stderr
    assert not (tmp / "clip.bin").exists()  # nada llega al portapapeles
    assert any(c[:3] == ["os", "preauth-request", "delete"] for c in calls((e, work, tmp)))
    assert TOKEN not in r.stdout + r.stderr and "evil.example.com" not in r.stderr and "otro-bucket" not in r.stderr  # el diagnóstico es solo estructural
    assert "Diagnóstico estructural" in r.stderr and "token_longitud=" in r.stderr


def test_unparseable_creation_response_still_leaves_no_orphan_par(env):
    r = run(env, "--not-after", future(), variant="json_malo")
    assert r.returncode == 1 and "REVOCADO" in r.stderr
    assert any(c[:3] == ["os", "preauth-request", "delete"] for c in calls(env))


@pytest.mark.parametrize("uri", [
    f"/p/{TOKEN}/n/espacio123/b/nexoeventos-recovery/o/backups/c04-20261119/",
    f"/p/{TOKEN}/n/espacio123/b/nexoeventos-recovery/o/backups%2Fc04-20261119%2F",
    f"https://objectstorage.sa-saopaulo-1.oraclecloud.com/p/{TOKEN}/n/espacio123/b/nexoeventos-recovery/o/backups/c04-20261119/",
])
def test_parser_canonical_output_for_valid_forms(uri):
    assert M.parse_access_uri(uri, "espacio123")["canonica"] == CANON


@pytest.mark.parametrize("uri", [
    "", "   ", None, "/", "/p/", f"/p/corto/n/espacio123/b/nexoeventos-recovery/o/{PFX}",
    f"/p/{TOKEN}/n/espacio123/b/nexoeventos-recovery/o/backups/",
    f"/p/{TOKEN}/n/espacio123/b/nexoeventos-recovery/o/backups/c04-20261119/../x/",
    f"/p/{TOKEN}/n/espacio123/b/nexoeventos-recovery/o/backups//c04-20261119/",
    f"/x/{TOKEN}/n/espacio123/b/nexoeventos-recovery/o/{PFX}",
    f"//evil.example.com/p/{TOKEN}/n/espacio123/b/nexoeventos-recovery/o/{PFX}",
    f"https://user:pw@objectstorage.sa-saopaulo-1.oraclecloud.com/p/{TOKEN}/n/espacio123/b/nexoeventos-recovery/o/{PFX}",
    f"https://objectstorage.sa-saopaulo-1.oraclecloud.com:8443/p/{TOKEN}/n/espacio123/b/nexoeventos-recovery/o/{PFX}",
    f"https://objectstorage.sa-saopaulo-1.oraclecloud.com.evil.example/p/{TOKEN}/n/espacio123/b/nexoeventos-recovery/o/{PFX}",
    f"/p/{TOKEN}/n/espacio123/b/nexoeventos-recovery/o/{PFX}#frag",
    f"/p/{TOKEN} /n/espacio123/b/nexoeventos-recovery/o/{PFX}",
])
def test_parser_rejects_everything_else(uri):
    assert M.parse_access_uri(uri, "espacio123")["canonica"] is None


def test_structure_report_contains_no_values():
    rep = M.structure_report(M.parse_access_uri(f"/p/{TOKEN}/n/espacio123/b/otro-bucket/o/{PFX}", "espacio123"))
    assert TOKEN not in rep and "espacio123" not in rep and "otro-bucket" not in rep and "bucket_ok=False" in rep


def test_regression_access_uri_ending_at_o_is_the_prefix_enforced_server_side_shape():
    """Causa del 19-nov: con un PAR AnyObjectWrite de prefijo, el access-uri real termina en `/o/` (el prefijo no viaja en la ruta). El validador anterior exigía el prefijo en la ruta."""
    r = M.parse_access_uri(f"/p/{TOKEN}/n/espacio123/b/nexoeventos-recovery/o/", "espacio123")
    assert r["forma"] == "vacio" and r["sufijo_vacio"] and r["sufijo_longitud"] == 0 and not r["sufijo_igual_prefijo"]
    assert r["canonica"] == CANON  # única normalización: anexar PREFIX a la ruta vacía; el token, ns y bucket no se tocan
    igual = M.parse_access_uri(f"/p/{TOKEN}/n/espacio123/b/nexoeventos-recovery/o/{PFX}", "espacio123")
    assert igual["forma"] == "igual" and igual["sufijo_igual_prefijo"] and igual["sufijo_barra_final"]
    parcial = M.parse_access_uri(f"/p/{TOKEN}/n/espacio123/b/nexoeventos-recovery/o/backups/", "espacio123")
    assert parcial["forma"] is None and parcial["sufijo_prefijo_parcial"] and parcial["canonica"] is None


def test_structure_report_includes_suffix_booleans_only():
    rep = M.structure_report(M.parse_access_uri(f"/p/{TOKEN}/n/espacio123/b/nexoeventos-recovery/o/", "espacio123"))
    assert "sufijo_vacio=True" in rep and "forma=vacio" in rep and TOKEN not in rep and "c04-2026" not in rep
