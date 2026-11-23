#!/usr/bin/env python3
"""Pruebas funcionales de la aplicación recuperada en OCI, desde la Mac de la propietaria vía el túnel HTTPS de OCI Bastion (https://localhost:8443). Sin ventas ni registros nuevos.
Con --reset-creds: genera EN MEMORIA contraseñas aleatorias para dos cuentas de demostración, las convierte en hashes Argon2 (pwdlib, igual que el backend) y actualiza solo esos dos
password_hash de la COPIA DESECHABLE de OCI (vía SSH; reset-two-passwords.py). Las contraseñas no se imprimen, guardan ni registran. Sin esa opción pide las contraseñas con getpass.
Prueba: login, catálogo, reservas, descifrado del QR (TICKET_ENCRYPTION_KEY original) y validación de un ticket YA USADO (SECURITY_HASH_KEY original): se espera 409 'Entrada ya utilizada'
(already_used), que no consume nada; solo registra una fila en access_logs de la copia.
Uso: app-smoke.py --out <dir> [--base https://localhost:8443] [--reset-creds --ssh-port 2222 --ssh-key ~/.ssh/nexoeventos_recovery]"""
import argparse, getpass, json, os, secrets, subprocess, sys, time
from datetime import datetime, timezone
import httpx

CLIENT = "smoke-1791073267-26124@example.com"; OPERATOR = "operador.demo@example.com"
ap = argparse.ArgumentParser(); ap.add_argument("--out", required=True); ap.add_argument("--base", default="https://localhost:8443"); ap.add_argument("--cafile", help="certificado a FIJAR (acceso público de prueba); sin él, túnel local con certificado efímero sin verificar")
ap.add_argument("--reset-creds", action="store_true"); ap.add_argument("--read-only", action="store_true", help="recuperación aislada: solo lecturas; comprueba además que las escrituras son RECHAZADAS"); ap.add_argument("--ssh-port", default="2222"); ap.add_argument("--ssh-key", default=os.path.expanduser("~/.ssh/nexoeventos_recovery")); a = ap.parse_args()
t0 = time.time(); res = []; BASE = a.base; extra = {}


def check(name, ok, detail=""):
    res.append({"prueba": name, "ok": bool(ok), "detalle": detail}); print(("OK    " if ok else "FALLÓ ") + name + (f" — {detail}" if detail else ""), flush=True)


def ssh(cmd, stdin=None):
    return subprocess.run(["ssh", "-i", a.ssh_key, "-p", a.ssh_port, "-o", "IdentitiesOnly=yes", "-o", "ConnectTimeout=30", "-o", "StrictHostKeyChecking=yes", "-o", "UserKnownHostsFile=" + os.path.join(a.out, "known_hosts"), "opc@127.0.0.1", cmd], input=stdin, capture_output=True, text=True)


def sql_read(q):
    r = ssh("sudo -u postgres env PGOPTIONS='-c default_transaction_read_only=on' bash -c \"cd /var/lib/pgsql && /usr/pgsql-18/bin/psql -d nexoeventos -At\"", stdin=q)
    return r.stdout.strip()


if a.read_only:
    # Modo de solo lectura (recuperación aislada, sin doble escritor): sin credenciales ni sesiones. Lecturas públicas + prueba de que NINGÚN verbo de escritura llega a la API.
    cl = httpx.Client(base_url=BASE, verify=(a.cafile or False), timeout=30, headers={"Origin": BASE})
    r = cl.get("/livez"); check("livez (proceso de la API) = 200 con status ok", r.status_code == 200 and r.json().get("status") == "ok", f"HTTP {r.status_code}")
    r = cl.get("/ready"); check("ready (API + PostgreSQL) = 200 con status ready", r.status_code == 200 and r.json().get("status") == "ready", f"HTTP {r.status_code}")
    r = cl.get("/healthz"); check("healthz (API + BD) = 200", r.status_code == 200, f"HTTP {r.status_code}")
    r = cl.get("/"); check("frontend servido por Nginx con cabeceras de seguridad", r.status_code == 200 and "content-security-policy" in {k.lower() for k in r.headers} and "<div id=" in r.text[:2000], f"HTTP {r.status_code}")
    r = cl.get("/api/events"); ev = r.json() if r.status_code == 200 else []; check("petición real de lectura: /api/events devuelve el catálogo", r.status_code == 200 and len(ev) > 0, f"{len(ev)} eventos publicados")
    if ev:
        r = cl.get(f"/api/events/{ev[0]['id']}"); check("detalle de un evento", r.status_code == 200, f"HTTP {r.status_code}")
    for verb, path in (("POST", "/api/auth/login"), ("POST", "/api/auth/register"), ("PUT", "/api/events/1"), ("DELETE", "/api/events/1"), ("PATCH", "/api/events/1")):
        r = cl.request(verb, path, json={})
        check(f"escritura rechazada: {verb} {path} → 403 (Nginx en solo lectura)", r.status_code == 403, f"HTTP {r.status_code}")
    out = {"ejecutado_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "duracion_s": round(time.time() - t0, 1), "modo": "solo lectura", "base": BASE, "tls_verificado": bool(a.cafile), "resultados": res, "todo_ok": all(x["ok"] for x in res)}
    os.makedirs(a.out, exist_ok=True); open(os.path.join(a.out, "smoke.json"), "w").write(json.dumps(out, indent=2, ensure_ascii=False) + "\n")
    print(f"\n{sum(x['ok'] for x in res)}/{len(res)} correctas; duración {out['duracion_s']} s"); sys.exit(0 if out["todo_ok"] else 1)
if a.reset_creds:
    from pwdlib import PasswordHash
    ph = PasswordHash.recommended()
    pw = {CLIENT: secrets.token_urlsafe(24), OPERATOR: secrets.token_urlsafe(24)}
    payload = json.dumps({e: ph.hash(p) for e, p in pw.items()})
    scp = subprocess.run(["scp", "-i", a.ssh_key, "-P", a.ssh_port, "-o", "IdentitiesOnly=yes", "-o", "StrictHostKeyChecking=yes", "-o", "UserKnownHostsFile=" + os.path.join(a.out, "known_hosts"), os.path.join(os.path.dirname(os.path.abspath(__file__)), "reset-two-passwords.py"), "opc@127.0.0.1:app/"], capture_output=True)
    r = ssh("sudo /opt/nexoeventos/backend/.venv/bin/python /home/opc/app/reset-two-passwords.py", stdin=payload)
    payload = None
    try:
        info = json.loads(r.stdout.strip().splitlines()[-1])
    except Exception:
        info = {}
    ok = r.returncode == 0 and info.get("filas_actualizadas") == 2 and info.get("hash_de_hashes_de_otras_cuentas_igual") is True
    extra["credenciales_restablecidas_solo_en_la_copia_de_contingencia"] = {"cuentas": [OPERATOR, CLIENT], **info, "aviso": "contraseñas aleatorias solo en memoria; hashes Argon2; producción de AWS no tocada"}
    check("contraseñas de 2 cuentas restablecidas SOLO en la copia de OCI (otras cuentas intactas)", ok, json.dumps(info) if ok else (r.stderr.strip().splitlines() or ["error"])[-1][:120])
    if not ok:
        sys.exit(1)
else:
    pw = {}
    for e, label in ((CLIENT, "cliente"), (OPERATOR, "operador")):
        pw[e] = os.environ.get("NEXO_DEMO_CLIENT_PASSWORD" if e == CLIENT else "NEXO_DEMO_OPERATOR_PASSWORD") or getpass.getpass(f"Contraseña de {e} ({label}; no se muestra ni se guarda): ")


def client():
    return httpx.Client(base_url=BASE, verify=(a.cafile or False), timeout=30, headers={"Origin": BASE})   # certificado autofirmado y efímero


def csrf(c):
    return {"X-CSRF-Token": c.cookies.get("nexoeventos_csrf", "")}


cl, op = client(), client()
r = cl.get("/livez"); check("livez (proceso de la API) = 200 con status ok", r.status_code == 200 and r.json().get("status") == "ok", f"HTTP {r.status_code}")
r = cl.get("/ready"); check("ready (API + PostgreSQL) = 200 con status ready", r.status_code == 200 and r.json().get("status") == "ready", f"HTTP {r.status_code}")
r = cl.get("/healthz"); check("healthz (API + BD) = 200", r.status_code == 200, f"HTTP {r.status_code}")
r = cl.get("/"); check("frontend servido por Nginx con cabeceras de seguridad", r.status_code == 200 and "content-security-policy" in {k.lower() for k in r.headers} and "<div id=" in r.text[:2000], f"HTTP {r.status_code}")
r = cl.post("/api/auth/login", json={"email": CLIENT, "password": pw[CLIENT]}); check("inicio de sesión de cliente", r.status_code == 200, f"HTTP {r.status_code}")
sc = r.headers.get_list("set-cookie"); check("cookie de sesión con Secure y HttpOnly", any("secure" in c.lower() and "httponly" in c.lower() for c in sc), f"{len(sc)} cookies")
r = cl.get("/api/auth/session"); check("sesión válida", r.status_code == 200, f"HTTP {r.status_code}")
r = cl.get("/api/events"); ev = r.json() if r.status_code == 200 else []; check("catálogo de eventos", r.status_code == 200 and len(ev) > 0, f"{len(ev)} eventos publicados")
if ev:
    r = cl.get(f"/api/events/{ev[0]['id']}"); check("detalle de un evento", r.status_code == 200, f"HTTP {r.status_code}")
r = cl.get("/api/me/reservations"); mine = r.json() if r.status_code == 200 else []; check("consulta de reservas del cliente (solo lectura)", r.status_code == 200 and len(mine) > 0, f"{len(mine)} reservas")
r = cl.get("/api/me/tickets"); tk = r.json() if r.status_code == 200 else []
tok = next((t for t in tk if isinstance(t.get("qr_token"), str) and len(t["qr_token"]) >= 20), None)
check("tickets del cliente con QR descifrado (TICKET_ENCRYPTION_KEY original)", r.status_code == 200 and tok is not None, f"{len(tk)} tickets")
if tok:
    r = cl.post("/api/operator/validate", json={"event_id": tok["event_id"], "qr_token": tok["qr_token"]}, headers=csrf(cl)); check("un cliente no puede validar entradas (403)", r.status_code == 403, f"HTTP {r.status_code}")
    r = op.post("/api/auth/login", json={"email": OPERATOR, "password": pw[OPERATOR]}); check("inicio de sesión de operador", r.status_code == 200, f"HTTP {r.status_code}")
    r = op.get("/api/operator/events"); ids = [e.get("id") for e in r.json()] if r.status_code == 200 else []; check("el operador ve el evento del ticket", tok["event_id"] in ids, f"{len(ids)} eventos asignados")
    r = op.post("/api/operator/validate", json={"event_id": tok["event_id"], "qr_token": tok["qr_token"]}, headers=csrf(op))
    detail = (r.json().get("detail") if r.headers.get("content-type", "").startswith("application/json") else "") or ""
    check("validación de un ticket ya usado → already_used (409 'Entrada ya utilizada'; token verificado con SECURITY_HASH_KEY original)", r.status_code == 409 and "utilizada" in detail.lower(), f"HTTP {r.status_code}")
if tok:   # reservas REALES sobre la copia desechable: reserva nueva, idempotencia, inventario bajo concurrencia, ciclo reserva → QR → validación (app_functional.py; validado antes contra la aplicación real)
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); import app_functional as AF
    def new_client():
        c = client(); c.cookies.update(cl.cookies); return c
    op_ids = [e.get("id") for e in op.get("/api/operator/events").json()] if op.get("/api/operator/events").status_code == 200 else []
    extra["funcional"] = AF.functional_checks(cl, op, ev, op_ids, check, csrf, new_client)
pw = None
if a.reset_creds:
    extra["access_logs_por_resultado_tras_las_pruebas"] = sql_read("select result||'='||count(*) from access_logs group by result order by 1;").splitlines()
out = {"ejecutado_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "duracion_s": round(time.time() - t0, 1), "base": BASE + (" (público, certificado FIJADO)" if a.cafile else " (túnel Bastion, certificado efímero sin verificar)"), "tls_verificado": bool(a.cafile), **extra,
       "resultados": res, "todo_ok": all(x["ok"] for x in res)}
os.makedirs(a.out, exist_ok=True); open(os.path.join(a.out, "smoke.json"), "w").write(json.dumps(out, indent=2, ensure_ascii=False) + "\n")
print(f"\n{sum(x['ok'] for x in res)}/{len(res)} correctas; duración {out['duracion_s']} s"); sys.exit(0 if out["todo_ok"] else 1)
