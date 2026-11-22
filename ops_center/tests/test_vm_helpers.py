"""Helpers de la VM de recuperación (ensure-swap.sh y safe-dnf.sh) con DRY_RUN y entradas simuladas. Regresión de T3 (22-nov-2026): dnf con todos los repositorios y swap insuficiente dejó la E2.1.Micro sin respuesta."""
import os, subprocess
from pathlib import Path

D = Path(__file__).resolve().parents[2] / "scripts/multicloud/oci-drill"


def run(script, env, *args):
    r = subprocess.run(["bash", str(D / script), *args], capture_output=True, text=True, env={**os.environ, **env}); return r.returncode, r.stdout + r.stderr


def swaps(tmp, kb_list):
    f = tmp / "swaps"; f.write_text("Filename Type Size Used Priority\n" + "".join(f"/dev/zram{i} partition {kb} 0 -2\n" for i, kb in enumerate(kb_list))); return f


def meminfo(tmp, kb):
    f = tmp / "mem"; f.write_text(f"MemTotal: {kb} kB\n"); return f


def test_swap_se_completa_hasta_2gb_cuando_la_imagen_trae_menos(tmp_path):
    env = {"DRY_RUN": "1", "MEMINFO": str(meminfo(tmp_path, 945 * 1024)), "SWAPS": str(swaps(tmp_path, [944 * 1024])), "SWAPFILE": str(tmp_path / "sf")}
    rc, out = run("ensure-swap.sh", env); assert rc == 0 and "añadiendo 1104 MB" in out and "DRY: dd" in out and "count=1104" in out and "DRY: swapon" in out


def test_swap_suficiente_no_se_toca_y_ram_grande_tampoco(tmp_path):
    env = {"DRY_RUN": "1", "MEMINFO": str(meminfo(tmp_path, 945 * 1024)), "SWAPS": str(swaps(tmp_path, [2100 * 1024])), "SWAPFILE": str(tmp_path / "sf")}
    rc, out = run("ensure-swap.sh", env); assert rc == 0 and "suficiente" in out and "DRY:" not in out
    env = {"DRY_RUN": "1", "MEMINFO": str(meminfo(tmp_path, 8_000_000)), "SWAPS": str(swaps(tmp_path, [])), "SWAPFILE": str(tmp_path / "sf")}
    rc, out = run("ensure-swap.sh", env); assert rc == 0 and "no hace falta swap" in out and "DRY:" not in out


def test_sin_swap_crea_los_2gb_completos(tmp_path):
    env = {"DRY_RUN": "1", "MEMINFO": str(meminfo(tmp_path, 498_000)), "SWAPS": str(swaps(tmp_path, [])), "SWAPFILE": str(tmp_path / "sf")}
    rc, out = run("ensure-swap.sh", env); assert rc == 0 and "count=2048" in out and not (tmp_path / "sf").exists()


def repos(tmp, ids):
    d = tmp / "repos"; d.mkdir(exist_ok=True); (d / "ol9.repo").write_text("".join(f"[{i}]\nname={i}\nenabled=1\n\n" for i in ids)); return d


FULL = ["ol9_baseos_latest", "ol9_appstream", "ol9_addons", "ol9_oci_included", "ol9_ksplice"]


def test_safe_dnf_usa_solo_los_repos_minimos_con_limites(tmp_path):
    rc, out = run("safe-dnf.sh", {"DRY_RUN": "1", "REPO_DIR": str(repos(tmp_path, FULL)), "DNF_MEM_MAX": "512M", "DNF_TIMEOUT": "900"}, "-y", "install", "python3.12", "nginx")
    assert rc == 0; line = next(l for l in out.splitlines() if l.startswith("DRY:"))
    assert "--disablerepo=*" in line and "--enablerepo=ol9_baseos_latest" in line and "--enablerepo=ol9_appstream" in line
    assert "ol9_oci_included" not in line and "ol9_ksplice" not in line                      # los repos pesados NO se cargan
    assert "timeout 900" in line and "nice -n 19" in line and "install_weak_deps=False" in line and line.endswith("-y install python3.12 nginx")


def test_safe_dnf_se_detiene_si_falta_un_repo_minimo_en_vez_de_cargar_todos(tmp_path):
    rc, out = run("safe-dnf.sh", {"DRY_RUN": "1", "REPO_DIR": str(repos(tmp_path, ["ol9_baseos_latest", "ol9_oci_included"]))}, "-y", "install", "x")
    assert rc == 3 and "ol9_appstream" in out and "Repositorios disponibles" in out and "DRY:" not in out


def test_safe_dnf_sin_directorio_de_repos_falla_con_codigo_3(tmp_path):
    rc, out = run("safe-dnf.sh", {"DRY_RUN": "1", "REPO_DIR": str(tmp_path / "no-existe")}, "-y", "install", "x"); assert rc == 3


def test_los_instaladores_ya_no_llaman_a_dnf_directamente():
    for f in ("install-postgres.sh", "install-app.sh"):
        for l in (D / f).read_text().splitlines():
            code = l.split(" #")[0]                                           # los comentarios al final de línea no son llamadas
            if "dnf" in code and not code.lstrip().startswith("#") and "safe-dnf" not in code: raise AssertionError(f"{f}: llamada directa a dnf: {l.strip()[:80]}")


def test_quiesce_silencia_makecache_y_ksplice_y_no_toca_nada_mas():
    rc, out = run("quiesce-vm.sh", {"DRY_RUN": "1"}); lines = [l for l in out.splitlines() if l.startswith("DRY:")]
    assert rc == 0 and any("stop dnf-makecache.timer" in l for l in lines) and any("disable ksplice-agent.timer" in l for l in lines) and any("pkill -f ^/usr/bin/python3? /usr/bin/dnf makecache" in l for l in lines)
    assert not any(w in " ".join(lines) for w in ("sshd", "postgres", "nginx", "oracle-cloud-agent", "rm ", "reboot"))             # solo los actualizadores en segundo plano


def test_install_postgres_silencia_los_actualizadores_antes_de_cualquier_dnf():
    s = (D / "install-postgres.sh").read_text(); assert s.index("quiesce-vm.sh") < s.index("ensure-swap.sh") < s.index("safe-dnf.sh")


def test_mecanismo_de_la_frase_fd4_funciona_con_la_correcta_y_falla_con_otra(tmp_path):
    """Mismo mecanismo que app-recovery.sh (read -s → fd 4 → openssl cms -decrypt -passin fd:4) con una clave PROTEGIDA sintética: descarta que el fallo sea del mecanismo."""
    ossl = "/opt/homebrew/bin/openssl" if Path("/opt/homebrew/bin/openssl").exists() else "openssl"
    key, crt, plain, cms = tmp_path / "k.pem", tmp_path / "c.crt", tmp_path / "p", tmp_path / "x.cms"
    subprocess.run([ossl, "req", "-x509", "-newkey", "rsa:2048", "-keyout", str(key), "-out", str(crt), "-days", "2", "-subj", "/CN=t", "-passout", "pass:Frase-Correcta 123!"], check=True, capture_output=True)
    plain.write_bytes(b"x" * 500); subprocess.run([ossl, "cms", "-encrypt", "-binary", "-aes256", "-outform", "DER", "-in", str(plain), "-out", str(cms), str(crt)], check=True, capture_output=True)
    snippet = f'IFS= read -r -s -p "x: " KEYPW; echo; exec 4< <(printf "%s\\n" "$KEYPW"); {ossl} cms -decrypt -binary -inform DER -in {cms} -inkey {key} -passin fd:4 -out /dev/null'
    ok = subprocess.run(["bash", "-c", snippet], input="Frase-Correcta 123!\n", capture_output=True, text=True); bad = subprocess.run(["bash", "-c", snippet], input="Frase-Correcta 123\n", capture_output=True, text=True)
    assert ok.returncode == 0, ok.stderr; assert bad.returncode != 0 and "wrong password" in bad.stderr           # una letra o símbolo de menos reproduce EXACTAMENTE el error observado


def test_app_smoke_usa_el_known_hosts_de_la_ejecucion_no_el_del_usuario():
    """Regresión T3 fase B: «Host key verification failed» porque ssh/scp del reset usaban ~/.ssh/known_hosts (clave de host de una VM anterior en 127.0.0.1:2222)."""
    s = (D / "app-smoke.py").read_text()
    assert s.count("UserKnownHostsFile=") == 2 and s.count("StrictHostKeyChecking=yes") == 2 and "accept-new" not in s


def test_install_app_reinicia_nginx_y_api_al_aplicar_la_etapa_2():
    """Regresión T3 fase B: con --now Nginx (ya activo desde la fase A) no recargaba ni el certificado nuevo ni la configuración sin limit_except."""
    s = (D / "install-app.sh").read_text()
    assert "systemctl restart nexoeventos-api nginx" in s and "enable --now nexoeventos-api nginx" not in s


def test_la_frase_se_verifica_al_principio_y_antes_de_descargar_o_tocar_la_vm(tmp_path):
    """T3 2.º intento: la frase mal escrita se descubría tras ≈ 10 min. Ahora check_pw (openssl pkey, fd 4) corre antes de la primera etapa."""
    s = (D / "app-recovery.sh").read_text()
    assert s.index("&& verify_pw_upfront") < s.index("if want download") and "intento $n de 3" in s and "-passin fd:4 -noout" in s
    ossl = "/opt/homebrew/bin/openssl" if Path("/opt/homebrew/bin/openssl").exists() else "openssl"
    key = tmp_path / "k.pem"; subprocess.run([ossl, "genpkey", "-algorithm", "RSA", "-pkeyopt", "rsa_keygen_bits:2048", "-aes-256-cbc", "-pass", "pass:Frase-Correcta 123!", "-out", str(key)], check=True, capture_output=True)
    snip = f'exec 4< <(printf "%s\\n" "$P"); {ossl} pkey -in {key} -passin fd:4 -noout'
    good = subprocess.run(["bash", "-c", snip], env={**os.environ, "P": "Frase-Correcta 123!"}, capture_output=True); bad = subprocess.run(["bash", "-c", snip], env={**os.environ, "P": "Frase-Correcta 123"}, capture_output=True)
    assert good.returncode == 0 and bad.returncode != 0


def test_quiesce_neutraliza_solo_los_actualizadores_y_los_enmascara():
    rc, out = run("quiesce-vm.sh", {"DRY_RUN": "1"}); assert rc == 0
    for u in ("dnf-makecache.timer", "ksplice-agent.timer"): assert f"mask {u}" in out and f"stop {u}" in out and f"disable {u}" in out
    for ajeno in ("sshd", "ssh", "postgres", "nginx", "nexoeventos", "oracle-cloud-agent", "cloud-init"): assert ajeno not in out


def test_cloud_init_del_primer_arranque_esta_cableado_y_es_igual_de_acotado():
    """Elimina la ventana de carrera arranque→SSH: la neutralización ocurre en el primer arranque, como atributo de la MISMA instancia."""
    root = D.parents[2]; ci = (root / "infra/oci/modules/recovery/cloud-init-quiesce.sh").read_text(); tf = (root / "infra/oci/modules/recovery/main.tf").read_text()
    assert ci.startswith("#!/bin/bash") and "mask --now" in ci and "dnf-makecache.timer" in ci and "ksplice-agent.timer" in ci and "/var/log/nexo-quiesce.log" in ci
    code = "\n".join(l for l in ci.splitlines() if not l.lstrip().startswith("#")).lower()
    for ajeno in ("sshd", "postgres", "nginx"): assert ajeno not in code
    assert 'user_data = base64encode(file("${path.module}/cloud-init-quiesce.sh"))' in tf and tf.count("resource \"") == tf.count("resource \"") and tf.count('resource "oci_core_instance"') == 1
    qv = (D / "quiesce-vm.sh").read_text(); assert all(u in qv for u in ("dnf-makecache.timer", "ksplice-agent.timer"))


def test_quiesce_detiene_kdump_y_devuelve_la_reserva_sin_reiniciar():
    rc, out = run("quiesce-vm.sh", {"DRY_RUN": "1"}); assert rc == 0
    assert "mask kdump.service" in out and "kexec -p -u" in out and "kexec -u" not in out and "echo 0 > /sys/kernel/kexec_crash_size" in out and "reboot" not in out
    assert "kexec_crash_size" in (D.parents[2] / "infra/oci/modules/recovery/cloud-init-quiesce.sh").read_text()
