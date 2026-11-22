"""T4 — instalador aditivo de la VM de Azure, probado en un árbol SIMULADO (NEXO_ROOT): plan sin cambios, frase obligatoria, Grafana/Zabbix/UFW intactos, include de Nginx idempotente, copia con SHA-256."""
import hashlib
import json
import os
import subprocess
import sys
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "deploy/azure/instalar-t4-en-vm.sh"
FRASE = "INSTALAR T4 EN LA VM DE AZURE"


def vm(tmp):
    r = tmp / "vm"
    for f, t in (("etc/grafana/grafana.ini", "[server]\n"), ("etc/zabbix/zabbix_server.conf", "DBName=zabbix\n"), ("etc/ufw/user.rules", "# rules\n"),
                 ("etc/nginx/sites-enabled/default", "server {\n    listen 443 ssl;\n    location /grafana/ { proxy_pass http://127.0.0.1:3000/; }\n}\n\nmap $http_upgrade $connection_upgrade {\n    default upgrade;\n    ''      close;\n}\n")):
        p = r / f; p.parent.mkdir(parents=True, exist_ok=True); p.write_text(t)
    pkg = tmp / "pkg.tgz"
    with tarfile.open(pkg, "w:gz") as t:
        for d in ("deploy/ops-center", "deploy/witness", "deploy/azure"):
            for f in (ROOT / d).iterdir(): t.add(f, arcname=f"{d}/{f.name}")
    return r, pkg, hashlib.sha256(pkg.read_bytes()).hexdigest()


def run(r, pkg, sha, *extra):
    return subprocess.run(["bash", str(SCRIPT), "--paquete", str(pkg), "--sha256", sha, *extra], capture_output=True, text=True, env={**os.environ, "NEXO_ROOT": str(r)})


def tree(r): return {str(p.relative_to(r)): p.read_bytes() for p in r.rglob("*") if p.is_file()}


def test_modo_plan_no_cambia_nada_y_sin_frase_no_aplica(tmp_path):
    r, pkg, sha = vm(tmp_path); antes = tree(r)
    for extra in ((), ("--aplicar", "frase incorrecta")):
        p = run(r, pkg, sha, *extra); assert p.returncode == 0 and "Modo plan: no se cambió nada" in p.stdout and tree(r) == antes


def test_sha_distinto_no_instala(tmp_path):
    r, pkg, sha = vm(tmp_path); p = run(r, pkg, "0" * 64, "--aplicar", FRASE); assert p.returncode == 2 and not (r / "opt").exists()


def test_aplicar_es_aditivo_grafana_zabbix_ufw_intactos_y_nginx_incluye_una_vez(tmp_path):
    r, pkg, sha = vm(tmp_path); prot = {f: (r / f).read_bytes() for f in ("etc/grafana/grafana.ini", "etc/zabbix/zabbix_server.conf", "etc/ufw/user.rules")}
    p = run(r, pkg, sha, "--aplicar", FRASE); assert p.returncode == 0, p.stderr; assert "Grafana, Zabbix y UFW intactos" in p.stdout
    assert {f: (r / f).read_bytes() for f in prot} == prot
    site = (r / "etc/nginx/sites-enabled/default").read_text(); assert site.count("include snippets/nexo-ops.conf;") == 1 and "location /grafana/" in site and site.index("include snippets") < site.index("map $http_upgrade")      # dentro del server, antes del map
    snip = (r / "etc/nginx/snippets/nexo-ops.conf").read_text(); assert "location /ops/" in snip and "location /witness/" in snip
    assert (r / "usr/lib/zabbix/alertscripts/nexo-alert-azure.py").exists()
    for u in ("ops-center.service", "witness.service", "ops-collector.service", "ops-collector.timer"): assert (r / "etc/systemd/system" / u).exists()
    bk = next((r / "var/backups/nexo-t4").iterdir()); assert (bk / "nginx.tgz").exists() and (bk / "default.orig").exists() and (bk / "huellas-antes.txt").read_text() == (bk / "huellas-despues.txt").read_text()
    p2 = run(r, pkg, sha, "--aplicar", FRASE); assert p2.returncode == 0 and (r / "etc/nginx/sites-enabled/default").read_text().count("include snippets/nexo-ops.conf;") == 1      # idempotente


def test_el_script_no_toca_rutas_protegidas_ni_borra_masivamente():
    s = SCRIPT.read_text()
    import re
    assert re.findall(r"rm -rf (\S+)", s) == ["/opt/nexoeventos/venv;"] and re.findall(r"apt-get \S+ [^\n]*", s) == ["apt-get install -y --no-install-recommends python3-venv"]        # únicas excepciones, acotadas
    for prohibido in ("apt ", "apt upgrade", "dist-upgrade", "zabbix_server.conf >", "grafana.ini >", "ufw ", "systemctl restart zabbix", "systemctl restart grafana", "DROP "): assert prohibido not in s
    assert "nginx -t" in s and "restaura la copia" in s.lower() or "se restaura la copia" in s


def test_unidades_acotadas_y_testigo_solo_en_loopback():
    w = (ROOT / "deploy/witness/witness.service").read_text(); c = (ROOT / "deploy/ops-center/ops-collector.service").read_text()
    assert "WITNESS_HOST=127.0.0.1" in w and "User=nexowitness" in w and "ProtectSystem=strict" in w and "WITNESS_INVOKER_TOKENS_FILE" in w and "AWS_" not in w and "OCI_" not in w
    assert "User=opscenter" in c and "ProtectSystem=strict" in c and "ExecStart=/opt/nexoeventos/venv/bin/python -m ops_center collect" in c
    assert 'WITNESS_HOST", "0.0.0.0"' in (ROOT / "scripts/multicloud/witness/witness_service.py").read_text()
    n = (ROOT / "deploy/witness/nginx-witness.conf").read_text(); assert "127.0.0.1:8760" in n and "limit_except GET POST" in n


# ---- ventana de la VM de Azure (azure-t4-ventana.sh) con un `az` simulado ----
def fake_az(tmp):
    st = tmp / "az-state"; st.mkdir(exist_ok=True); (st / "power").write_text("PowerState/deallocated"); (st / "time").write_text("1738"); (st / "log").write_text("")
    az = tmp / "az"
    az.write_text(f'''#!/usr/bin/env bash
S="{st}"; echo "$*" >> "$S/log"
case "$*" in
 *"get-instance-view"*) cat "$S/power";;
 *"resource show"*"properties.{{"*) printf '{{"status":"Enabled","time":"%s","tz":"UTC","notif":"Disabled","notifMin":30,"target":"vm"}}\n' "$(cat "$S/time")";;
 *"resource show"*) cat "$S/time";;
 *"nsg rule list"*) echo '[["admin-https","Allow","443","1.2.3.4/32"]]';;
 *"resource update"*) echo "$*" | sed -E 's/.*dailyRecurrence.time=([0-9]+).*/\\1/' > "$S/time";;
 *"vm start"*) echo "PowerState/running" > "$S/power";;
 *"vm deallocate"*) echo "PowerState/deallocated" > "$S/power";;
esac
''')
    az.chmod(0o755); return az, st


def win(tmp, *args):
    az, st = fake_az(tmp) if not (tmp / "az").exists() else (tmp / "az", tmp / "az-state")
    return subprocess.run(["bash", str(ROOT / "scripts/observability/azure-t4-ventana.sh"), *args], capture_output=True, text=True, env={**os.environ, "AZ_BIN": str(az), "T4_DIR": str(tmp / "t4")}), st


def test_ventana_check_guarda_el_original_y_no_cambia_nada(tmp_path):
    p, st = win(tmp_path, "--check"); assert p.returncode == 0 and "apagado_automatico=1738" in p.stdout and (tmp_path / "t4/ventana-original.json").exists()
    assert "update" not in (st / "log").read_text() and "vm start" not in (st / "log").read_text()


def test_ventana_iniciar_exige_check_y_frase_y_cerrar_restaura_el_horario(tmp_path):
    p, st = win(tmp_path, "--iniciar", "3"); assert p.returncode == 2                      # sin --check previo
    win(tmp_path, "--check")
    p, st = win(tmp_path, "--iniciar", "3"); assert "Modo plan" in p.stdout and (st / "power").read_text().strip() == "PowerState/deallocated"
    p, st = win(tmp_path, "--iniciar", "3", "--aplicar", "INICIAR VENTANA T4"); assert p.returncode == 0 and (st / "power").read_text().strip() == "PowerState/running" and (st / "time").read_text().strip() != "1738"
    p, st = win(tmp_path, "--cerrar"); assert "Modo plan" in p.stdout and (st / "power").read_text().strip() == "PowerState/running"
    p, st = win(tmp_path, "--cerrar", "--aplicar", "CERRAR VENTANA T4"); assert p.returncode == 0 and "restaurada EXACTAMENTE (1738 UTC" in p.stdout and (st / "power").read_text().strip() == "PowerState/deallocated"


def test_ventana_rechaza_horas_invalidas(tmp_path):
    win(tmp_path, "--check"); assert win(tmp_path, "--iniciar", "9")[0].returncode == 2


def test_ventana_guarda_la_programacion_completa_y_falla_si_no_coincide_al_cerrar(tmp_path):
    win(tmp_path, "--check"); o = json.loads((tmp_path / "t4/ventana-original.json").read_text())
    assert o["programacion"] == {"status": "Enabled", "time": "1738", "tz": "UTC", "notif": "Disabled", "notifMin": 30, "target": "vm"}
    win(tmp_path, "--iniciar", "2", "--aplicar", "INICIAR VENTANA T4")
    az = tmp_path / "az"; az.write_text(az.read_text().replace("Enabled", "Disabled", 1) if False else az.read_text())          # el `az` simulado ya devuelve la programación vigente
    o["programacion"]["notifMin"] = 15; (tmp_path / "t4/ventana-original.json").write_text(json.dumps(o))                       # original distinto de lo restaurado ⇒ no se declara éxito
    p, st = win(tmp_path, "--cerrar", "--aplicar", "CERRAR VENTANA T4"); assert p.returncode == 3 and "FALLA" in p.stderr


# ---- paquete de T4 ----
def empaquetar(tmp, *args):
    p = subprocess.run(["bash", str(ROOT / "deploy/azure/empaquetar-t4.sh"), *args], capture_output=True, text=True, env={**os.environ, "T4_PKG_DIR": str(tmp / "pk")}); assert p.returncode == 0, p.stderr
    return Path(p.stdout.splitlines()[0])


def test_paquete_sin_secretos_ni_estado_y_sha256_correcto(tmp_path):
    pkg = empaquetar(tmp_path); names = tarfile.open(pkg).getnames()
    for malo in (".env", ".pem", ".key", ".tfstate", ".tfvars", "/work/", ".venv", "__pycache__", "ops_center/tests"): assert not any(malo in n for n in names), malo
    assert "deploy/azure/instalar-t4-en-vm.sh" in names and "backend/requirements-production.lock" in names and "ops_center/collector.py" in names
    assert (pkg.parent / (pkg.name + ".sha256")).read_text().split()[0] == hashlib.sha256(pkg.read_bytes()).hexdigest()
    assert oct(pkg.stat().st_mode)[-3:] == "600"


def test_paquete_con_pruebas_incluye_las_del_testigo(tmp_path):
    names = tarfile.open(empaquetar(tmp_path, "--con-pruebas")).getnames(); assert any(n.endswith("test_witness_azure_profile.py") for n in names) and any("ops_center/tests/" in n for n in names)


def test_el_paquete_arranca_con_solo_sus_rutas(tmp_path):
    """Extraído solo, importa el centro y el testigo (nada depende de work/ ni del repositorio completo)."""
    pkg = empaquetar(tmp_path); d = tmp_path / "x"; d.mkdir(); tarfile.open(pkg).extractall(d)
    py = Path(sys.executable)        # el intérprete que ejecuta las pruebas (en CI no existe backend/.venv)
    code = "import sys;sys.path[:0]=[sys.argv[1], sys.argv[1]+'/backend', sys.argv[1]+'/scripts/multicloud/witness'];import ops_center.app, ops_center.collector, witness_service;print('IMPORTA')"
    p = subprocess.run([str(py), "-c", code, str(d)], capture_output=True, text=True, cwd=str(tmp_path)); assert "IMPORTA" in p.stdout, p.stderr


def test_pruebas_del_testigo_en_la_vm_corren_sin_privilegios():
    """T4: como root la prueba de «directorio sin permiso de escritura» no puede medir nada (falló por eso en Azure). Debe ejecutarse como usuario sin privilegios."""
    s = (ROOT / "deploy/azure/pruebas-testigo-en-vm.sh").read_text(); assert "runuser -u opscenter" in s and "pytest" in s
