#!/usr/bin/env python3
"""T3 — recuperación y funcionamiento real de NexoEventos en OCI. Herramientas de COMPROBACIÓN Y EVIDENCIA (no crean ni destruyen nada por sí mismas):
  plan                        SOLO LECTURA: preflight local + inventario de OCI + `terraform plan` (create-public) validado por plan_guard → LISTO / NO LISTO
  inventario --out F          instantánea de SOLO LECTURA de los recursos de OCI (antes y después de T3)
  puertos --host IP --out F   prueba TCP desde ESTA máquina (origen autorizado): 443 debe aceptar; 22/80/3000/5432/8000/8443 no
  memoria --ssh-port P --ssh-key K --out F   (VM viva, por el túnel SSH) memoria, swap y eventos OOM del kernel
  marca NOMBRE                registra una marca UTC en work/t3/marcas.json (apply, recuperación, destrucción)
  evidencia --recovery-dir D --inv-antes F --inv-despues F --plan-json F --puertos F --memoria F --teardown-guard F   construye el expediente T3 con veredicto PASS/FAIL/PARCIAL
Los pasos con frase de paso o clave SSH (túneles, app-recovery.sh) los ejecuta la propietaria en SU terminal."""
from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from ops_center import evidence as E  # noqa: E402

PORTS_CLOSED = (22, 80, 3000, 5432, 8000, 8443)
ENV = {**os.environ, "SUPPRESS_LABEL_WARNING": "True", "PYTHONWARNINGS": "ignore"}


def oci(*args, profile="DEFAULT") -> subprocess.CompletedProcess:
    return subprocess.run(["oci", *args, "--profile", profile, "--region", "sa-saopaulo-1"], capture_output=True, text=True, env=ENV, timeout=120)


def count(*args) -> int:
    r = oci(*args, "--query", "length(data)", "--all")
    if r.returncode != 0: raise RuntimeError("oci " + " ".join(args[:3]) + " falló: " + r.stderr.strip()[-120:])
    t = r.stdout.strip(); return int(t) if t.isdigit() else 0          # una lista vacía no imprime nada


def inventory() -> dict:
    ten = next(l.split("=", 1)[1].strip() for l in open(os.path.expanduser("~/.oci/config")) if l.startswith("tenancy"))
    cmp_ = oci("iam", "compartment", "list", "--compartment-id", ten, "--all", "--query", "data[?name=='nexoeventos'].id|[0]", "--raw-output").stdout.strip()
    if not cmp_.startswith("ocid1."): raise RuntimeError("no se encontró el compartimento nexoeventos")
    ns = oci("os", "ns", "get", "--query", "data", "--raw-output").stdout.strip()
    vcn = oci("network", "vcn", "list", "-c", cmp_, "--all", "--query", "data[0].id", "--raw-output").stdout.strip()
    inst = oci("compute", "instance", "list", "-c", cmp_, "--all", "--query", "data[?\"lifecycle-state\"!='TERMINATED'].id|length(@)").stdout.strip()
    inv = {"instancias_no_terminadas": int(inst) if inst.isdigit() else 0,
           "bastions_activos": count("bastion", "bastion", "list", "-c", cmp_, "--bastion-lifecycle-state", "ACTIVE"),
           "vcn": count("network", "vcn", "list", "-c", cmp_), "subredes": count("network", "subnet", "list", "-c", cmp_, "--vcn-id", vcn),
           "internet_gateways": count("network", "internet-gateway", "list", "-c", cmp_, "--vcn-id", vcn), "nsg": count("network", "nsg", "list", "-c", cmp_, "--vcn-id", vcn),
           "listas_de_seguridad": count("network", "security-list", "list", "-c", cmp_, "--vcn-id", vcn), "tablas_de_rutas": count("network", "route-table", "list", "-c", cmp_, "--vcn-id", vcn),
           "par_activos": count("os", "preauth-request", "list", "-ns", ns, "-bn", "nexoeventos-recovery"), "objetos": count("os", "object", "list", "-ns", ns, "-bn", "nexoeventos-recovery")}
    inv["utc"] = E.iso(datetime.now(timezone.utc)); return inv


def tcp(host, port, timeout=4.0):
    try:
        with socket.create_connection((host, port), timeout=timeout): return True
    except OSError: return False


def preflight_local(env=None) -> dict:
    """Comprobaciones LOCALES (sin red): archivos, permisos, RPM y claves. Devuelve {nombre: (ok, detalle)}."""
    r = {}; home = Path.home(); w = ROOT / "work"
    def perm(p): return (p.stat().st_mode & 0o077) == 0
    for name, p in (("tfvars_create", w / "terraform-envs/oci-t3-create.tfvars"), ("tfvars_teardown", w / "terraform-envs/oci-t3-teardown.tfvars"), ("clave_c04_protegida", home / ".nexoeventos/recovery-c04/recovery-private.protected.pem"),
                    ("clave_ssh_recovery", home / ".ssh/nexoeventos_recovery")):
        r[name] = (p.is_file() and perm(p), "existe con permisos 0600" if p.is_file() and perm(p) else f"falta o permisos abiertos: {p.name}")
    for name, p in (("certificado_c04", w / "recovery-keys/preupdate-20261008t0113z/recovery-public.crt"), ("clave_publica_de_firma", w / "c04/c04-backup-sign.pub"), ("clave_ssh_publica", home / ".ssh/nexoeventos_recovery.pub")):
        r[name] = (p.is_file(), "existe" if p.is_file() else f"falta: {p}")
    v = subprocess.run(["bash", str(ROOT / "scripts/multicloud/oci-drill/verify-rpms.sh"), str(w / "oci-drill/rpms")], capture_output=True, text=True)
    r["rpm_postgresql_verificados"] = (v.returncode == 0, "3 RPM x86_64 con SHA-256 fijado" if v.returncode == 0 else v.stderr.strip()[-100:])
    vt = (w / "terraform-envs/oci-t3-create.tfvars").read_text() if (w / "terraform-envs/oci-t3-create.tfvars").exists() else ""
    r["forma_always_free"] = ('recovery_shape          = "VM.Standard.E2.1.Micro"' in vt and "allow_trial_paid_shape  = false" in vt, "E2.1.Micro, sin formas de pago" if "E2.1.Micro" in vt else "forma inesperada")
    r["entrada_sin_0.0.0.0/0"] = ("0.0.0.0/0" not in vt and "entry_allowed_cidrs" in vt, "orígenes /32 explícitos" if "0.0.0.0/0" not in vt else "¡0.0.0.0/0 en entry_allowed_cidrs!")
    # La clave del agente se identifica por su HUELLA (el comentario de la clave puede ser cualquiera): se compara la de ~/.ssh/nexoeventos_recovery.pub con las del agente.
    ag = subprocess.run(["ssh-add", "-l"], capture_output=True, text=True); kf = subprocess.run(["ssh-keygen", "-lf", str(home / ".ssh/nexoeventos_recovery.pub")], capture_output=True, text=True)
    fp = kf.stdout.split()[1] if kf.returncode == 0 and len(kf.stdout.split()) > 1 else None
    loaded = bool(fp and fp in ag.stdout)
    r["clave_ssh_en_el_agente"] = (loaded, "cargada en ssh-agent (huella coincidente)" if loaded else "NO cargada: ejecute ssh-add ~/.ssh/nexoeventos_recovery en su terminal")
    return r


def cmd_plan(a):
    out = {"modo": "PLAN (solo lectura)"}; loc = preflight_local(); out["preflight_local"] = {k: {"ok": v[0], "detalle": v[1]} for k, v in loc.items()}
    inv = inventory(); out["inventario_oci"] = inv
    base_ok = inv["instancias_no_terminadas"] == 0 and inv["bastions_activos"] == 0 and inv["internet_gateways"] == 0 and inv["par_activos"] == 0 and inv["vcn"] == 1 and inv["subredes"] == 1
    out["inventario_base_esperado"] = base_ok
    p = subprocess.run(["bash", str(ROOT / "scripts/multicloud/oci-drill/oci-plan.sh"), "create-public"], capture_output=True, text=True, env={**ENV, "PATH": "/opt/homebrew/bin:" + os.environ["PATH"]})
    out["terraform_plan"] = {"rc_guarda": p.returncode, "resumen": [l for l in p.stdout.splitlines() if l.startswith(("Plan:", "OK ", "PLAN RECHAZADO"))]}
    plan_ok = p.returncode == 0 and any(l.startswith("Plan: 11 to add, 0 to change, 0 to destroy") for l in p.stdout.splitlines())
    ready = base_ok and plan_ok and all(v[0] for k, v in loc.items() if k != "clave_ssh_en_el_agente")
    out["bloqueantes"] = [k for k, v in loc.items() if not v[0]] + ([] if base_ok else ["inventario_base"]) + ([] if plan_ok else ["terraform_plan"])
    out["resultado"] = "LISTO" if ready and not out["bloqueantes"] else ("LISTO salvo la clave SSH en el agente (acción de la propietaria)" if ready else "NO LISTO")
    print(json.dumps(out, indent=1, ensure_ascii=False)); return 0 if ready else 2


def cmd_inventario(a):
    inv = inventory(); fd = os.open(a.out, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f: json.dump(inv, f, indent=1)
    print(json.dumps(inv)); return 0


def cmd_puertos(a):
    res = {"host": "<oculto>", "443": tcp(a.host, 443), **{str(p): tcp(a.host, p, a.timeout) for p in PORTS_CLOSED}, "utc": E.iso(datetime.now(timezone.utc))}
    res["ok"] = bool(res["443"] and not any(res[str(p)] for p in PORTS_CLOSED))
    fd = os.open(a.out, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f: json.dump(res, f, indent=1)
    print(json.dumps(res)); return 0 if res["ok"] else 1


REMOTE_MEM = ("free -m | awk '/^Mem:/{print \"mem_total_mb=\"$2\" mem_disponible_mb=\"$7} /^Swap:/{print \"swap_total_mb=\"$2\" swap_usada_mb=\"$3}'; "
              "echo oom=$(sudo journalctl -k --no-pager 2>/dev/null | grep -ci 'out of memory'); "
              "bad=0; for u in dnf-makecache.timer ksplice-agent.timer; do e=$(systemctl is-enabled $u 2>&1 | head -1); st=$(systemctl is-active $u 2>&1 | head -1); "
              "case \"$e\" in masked|disabled|not-found|*No\\ such*) ;; *) bad=1;; esac; [ \"$st\" = active ] && bad=1; done; echo timers_ok=$((1-bad)); "
              "echo sshd_activo=$(systemctl is-active sshd | grep -c '^active'); echo cloud_init_quiesce=$([ -s /var/log/nexo-quiesce.log ] && echo 1 || echo 0)")


def cmd_memoria(a):
    """Medición de RAM, swap, OOM (kernel, DESDE EL ARRANQUE de la VM) y estado de los actualizadores en segundo plano. --quiesce aplica antes quiesce-vm.sh (idempotente) por SSH."""
    base = ["ssh", "-i", a.ssh_key, "-p", a.ssh_port, "-o", "IdentitiesOnly=yes", "-o", "StrictHostKeyChecking=accept-new", "-o", "ConnectTimeout=60",
            "-o", "UserKnownHostsFile=" + (getattr(a, "known_hosts", None) or os.path.expanduser("~/.ssh/known_hosts")), "opc@127.0.0.1"]
    quiesced = None
    if getattr(a, "quiesce", False):
        q = subprocess.run(base + ["sudo bash -s"], input=(ROOT / "scripts/multicloud/oci-drill/quiesce-vm.sh").read_text(), capture_output=True, text=True, timeout=180); quiesced = (q.returncode == 0)
    r = subprocess.run(base + [REMOTE_MEM], capture_output=True, text=True, timeout=120); kv = dict(x.split("=") for x in r.stdout.split() if "=" in x)
    res = {k: int(v) for k, v in kv.items() if v.isdigit()}
    if quiesced is not None: res["quiesce_aplicado"] = quiesced
    res["ok"] = bool(r.returncode == 0 and res.get("oom") == 0 and res.get("swap_total_mb", 0) > 0 and res.get("timers_ok") == 1 and res.get("sshd_activo") == 1 and quiesced is not False)
    res["utc"] = E.iso(datetime.now(timezone.utc))
    fd = os.open(a.out, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f: json.dump(res, f, indent=1)
    print(json.dumps(res)); return 0 if res["ok"] else 1


def jload(p):
    try: return json.loads(Path(p).read_text())
    except (OSError, ValueError, TypeError): return None


def cmd_marca(a):
    p = Path(a.file); p.parent.mkdir(parents=True, exist_ok=True); data = jload(p) or {}
    if a.name in data: print("la marca ya existe"); return 1
    data[a.name] = E.iso(datetime.now(timezone.utc)); fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f: json.dump(data, f, indent=1)
    print(a.name, data[a.name]); return 0


def secs(marks, a, b):
    try: return round((E.parse(marks[b]) - E.parse(marks[a])).total_seconds(), 1)
    except (KeyError, ValueError, TypeError): return None


def results_ok(res, pred, minimum=1):
    sel = [r for r in res if pred(str(r.get("prueba", "")))]; return bool(len(sel) >= minimum and all(r.get("ok") for r in sel))


def cmd_evidencia(a):
    d = Path(a.recovery_dir); tpl = json.loads((ROOT / "ops_center/criterios/T3.json").read_text())
    run = E.EvidenceRun.start(a.evidence_root, "T3", tpl["title"], tpl["criteria"]); run.event("construccion_del_expediente", recovery_dir=d.name); v = {}
    et, sm = jload(d / "etapas.json"), jload(d / "smoke.json"); plan, inv0, inv1 = jload(a.plan_json), jload(a.inv_antes), jload(a.inv_despues)
    pts, mem, td = jload(a.puertos), jload(a.memoria), jload(a.teardown_guard)
    if plan is not None: v["lectura_previa_lista"] = str(plan.get("resultado", "")).startswith("LISTO")
    if et is not None:
        ok = et.get("resultado") == "OK" and not et.get("etapa_fallida"); stg = et.get("etapas") or {}
        v["recuperacion_c04_sin_fallo"] = ok; v["datos_restaurados_huella_ok"] = bool(ok and "datos" in stg); v["claves_de_aplicacion_originales"] = bool(ok and "secretos" in stg and (d / "claves-instaladas.txt").exists())
        if ok and isinstance(et.get("total_s"), (int, float)): v["rto_recuperacion_total_s"] = float(et["total_s"])      # solo cuenta como RTO una recuperación que TERMINÓ bien (el tiempo de una abortada no es un RTO)
    if sm is not None:
        res = sm.get("resultados") or []; writes = [r for r in res if str(r.get("prueba", "")).startswith("escritura rechazada")]
        v["smoke_solo_lectura_todo_ok"] = bool(sm.get("todo_ok") and len(res) >= 11); v["escrituras_rechazadas_403"] = bool(len(writes) >= 5 and all(w.get("ok") for w in writes))
        v["https_publico_con_certificado_fijado"] = bool(sm.get("tls_verificado") is True and "localhost" not in str(sm.get("base", "localhost")))
    if a.recovery_dir_rw:
        rw = Path(a.recovery_dir_rw); smr = jload(rw / "smoke.json")
        if smr is not None:
            res = smr.get("resultados") or []
            v["fase_escritura_humo_todo_ok"] = bool(smr.get("todo_ok") and len(res) >= 20)
            v["login_cliente_y_operador_ok"] = bool(results_ok(res, lambda n: n.startswith("inicio de sesión de cliente")) and results_ok(res, lambda n: n.startswith("inicio de sesión de operador")) and results_ok(res, lambda n: n.startswith("cookie de sesión con Secure")) and results_ok(res, lambda n: n.startswith("sesión válida")))
            v["reservas_funcionales_ok"] = results_ok(res, lambda n: n.startswith("funcional:"), 7)
            v["qr_con_claves_originales_y_ticket_usado_409"] = bool(results_ok(res, lambda n: n.startswith("tickets del cliente con QR descifrado")) and results_ok(res, lambda n: n.startswith("validación de un ticket ya usado")))
    vr = jload(a.verif_respaldo)
    if vr is not None: v["respaldo_c04_integro"] = bool(vr.get("ok") and vr.get("no_descifra"))
    mk = jload(a.marcas) or {}
    if mk:
        parts = [secs(mk, "apply_inicio", "apply_fin"), secs(mk, "recuperacion_inicio", "recuperacion_fin"), secs(mk, "destruccion_inicio", "destruccion_fin")]
        v["tiempos_de_reconstruccion_registrados"] = bool(all(x is not None and x > 0 for x in parts) and et is not None and bool(et.get("etapas")))
    dl = d / "huella-delta.txt"
    if dl.exists(): v["ninguna_escritura_huella_final_identica"] = dl.stat().st_size == 0
    if pts is not None: v["solo_443_alcanzable_desde_fuera"] = bool(pts.get("ok"))
    mem0 = jload(a.memoria_ro); mem_i = jload(getattr(a, "memoria_inicio", None))
    if mem is not None: v["memoria_sin_oom"] = bool(mem.get("ok") and mem0 is not None and mem0.get("ok") and mem_i is not None and mem_i.get("ok"))      # se exigen las TRES mediciones (al INICIO de la VM, tras la fase de solo lectura y tras la funcional); el OOM se cuenta desde el arranque de la VM
    if inv0 is not None and inv1 is not None:
        keys = [k for k in inv0 if k != "utc"]; same = all(inv0[k] == inv1.get(k) for k in keys); v["inventario_final_igual_al_inicial"] = same
        v["recursos_destruidos_y_verificados"] = bool(same and td is not None and str(td.get("resultado", "")).startswith("OK") and inv1.get("instancias_no_terminadas") == 0 and inv1.get("internet_gateways") == 0 and inv1.get("bastions_activos") == 0)
    for k, x in v.items(): run.value(k, x, "automático desde los archivos de la recuperación")
    for f in ("etapas.json", "smoke.json", "huella-delta.txt", "postgres-version.txt", "stage2.txt"):
        if (d / f).exists(): run.attach(d / f, redacted=True)
    if a.recovery_dir_rw:
        for f in ("smoke.json", "huella-delta.txt", "stage2.txt"):
            if (Path(a.recovery_dir_rw) / f).exists(): run.capture_text("fase2-" + f.replace(".", "_"), (Path(a.recovery_dir_rw) / f).read_text())
    if a.logs and Path(a.logs).is_dir():
        for lg in sorted(Path(a.logs).glob("*.log")): run.capture_text("log-" + lg.stem, lg.read_text(errors="ignore"))     # logs de terraform/túneles, saneados (IP, URL y OCID ocultos)
    for extra in (a.plan_json, a.inv_antes, a.inv_despues, a.puertos, a.memoria, a.memoria_ro, getattr(a, "memoria_inicio", None), a.teardown_guard, a.marcas, a.verif_respaldo):
        if extra and Path(extra).exists(): run.attach(extra, redacted=True)
    r = run.finish(); print(f"veredicto T3: {r['veredicto']} · {run.dir}"); return 0 if r["veredicto"] == "PASS" else 1


def main(argv=None):
    ap = argparse.ArgumentParser(); sub = ap.add_subparsers(dest="cmd", required=True); sub.add_parser("plan")
    p = sub.add_parser("inventario"); p.add_argument("--out", required=True)
    p = sub.add_parser("puertos"); p.add_argument("--host", required=True); p.add_argument("--out", required=True); p.add_argument("--timeout", type=float, default=4.0)
    p = sub.add_parser("memoria"); p.add_argument("--known-hosts"); p.add_argument("--quiesce", action="store_true"); p.add_argument("--ssh-port", default="2222"); p.add_argument("--ssh-key", default=os.path.expanduser("~/.ssh/nexoeventos_recovery")); p.add_argument("--out", required=True)
    p = sub.add_parser("evidencia"); p.add_argument("--recovery-dir", required=True); p.add_argument("--evidence-root", default="work/evidencias")
    for n in ("plan-json", "inv-antes", "inv-despues", "puertos", "memoria", "memoria-ro", "memoria-inicio", "teardown-guard", "marcas", "verif-respaldo", "recovery-dir-rw", "logs"): p.add_argument("--" + n)
    p = sub.add_parser("marca"); p.add_argument("name"); p.add_argument("--file", default=str(ROOT / "work/t3/marcas.json"))
    a = ap.parse_args(argv)
    return {"plan": cmd_plan, "inventario": cmd_inventario, "puertos": cmd_puertos, "memoria": cmd_memoria, "evidencia": cmd_evidencia, "marca": cmd_marca}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
