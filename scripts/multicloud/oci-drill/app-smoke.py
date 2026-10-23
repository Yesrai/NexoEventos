#!/usr/bin/env python3
"""Pruebas funcionales de la aplicación recuperada en OCI, desde la Mac de la propietaria vía el túnel HTTPS de OCI Bastion (https://localhost:8443). Sin ventas ni registros nuevos.
Cuentas de demostración existentes; las contraseñas se piden en la terminal (getpass) o llegan por entorno; NO se guardan ni se imprimen. Tampoco se imprimen cookies, tokens ni QR.
Escribe en la base desechable de OCI solo la fila de acceso de la validación de un ticket (se informa). Uso: app-smoke.py --out <dir> [--base https://localhost:8443]
Variables: NEXO_DEMO_CLIENT_EMAIL, NEXO_DEMO_CLIENT_PASSWORD, NEXO_DEMO_OPERATOR_EMAIL, NEXO_DEMO_OPERATOR_PASSWORD (opcionales; si faltan se piden)."""
import argparse, getpass, json, os, sys, time
from datetime import datetime, timezone
import httpx

ap = argparse.ArgumentParser(); ap.add_argument("--out", required=True); ap.add_argument("--base", default="https://localhost:8443"); a = ap.parse_args()
t0 = time.time(); res = []; BASE = a.base


def ask(env_email, env_pass, label):
    e = os.environ.get(env_email) or input(f"Correo de la cuenta {label}: ").strip()
    p = os.environ.get(env_pass) or getpass.getpass(f"Contraseña de {label} (no se muestra ni se guarda): ")
    return e, p


def check(name, ok, detail=""):
    res.append({"prueba": name, "ok": bool(ok), "detalle": detail}); print(("OK    " if ok else "FALLÓ ") + name + (f" — {detail}" if detail else ""), flush=True)


def client():
    return httpx.Client(base_url=BASE, verify=False, timeout=30, headers={"Origin": BASE})   # certificado autofirmado y efímero


def csrf(c):
    return {"X-CSRF-Token": c.cookies.get("nexoeventos_csrf", "")}


cl, op = client(), client()
r = cl.get("/healthz"); check("healthz (API + BD) = 200", r.status_code == 200, f"HTTP {r.status_code}")
h = {k.lower(): v for k, v in r.headers.items()}
r = cl.get("/"); check("frontend servido por Nginx con cabeceras de seguridad", r.status_code == 200 and "content-security-policy" in {k.lower() for k in r.headers} and "<div id=" in r.text[:2000], f"HTTP {r.status_code}")
email, pw = ask("NEXO_DEMO_CLIENT_EMAIL", "NEXO_DEMO_CLIENT_PASSWORD", "cliente de demostración")
r = cl.post("/api/auth/login", json={"email": email, "password": pw}); check("inicio de sesión de cliente", r.status_code == 200, f"HTTP {r.status_code}")
pw = None
sc = [c for c in r.headers.get_list("set-cookie")]
check("cookie de sesión con Secure y HttpOnly", any("secure" in c.lower() and "httponly" in c.lower() for c in sc), f"{len(sc)} cookies")
r = cl.get("/api/auth/session"); check("sesión válida", r.status_code == 200, f"HTTP {r.status_code}")
r = cl.get("/api/events"); ev = r.json() if r.status_code == 200 else []
check("catálogo de eventos", r.status_code == 200 and len(ev) > 0, f"{len(ev)} eventos publicados")
if ev:
    r = cl.get(f"/api/events/{ev[0]['id']}"); check("detalle de un evento", r.status_code == 200, f"HTTP {r.status_code}")
r = cl.get("/api/me/reservations"); mine = r.json() if r.status_code == 200 else []
check("consulta de reservas del cliente (solo lectura)", r.status_code == 200, f"{len(mine)} reservas")
r = cl.get("/api/me/tickets"); tk = r.json() if r.status_code == 200 else []
check("consulta de tickets del cliente (descifrado con TICKET_ENCRYPTION_KEY original)", r.status_code == 200, f"{len(tk)} tickets")
tok = next((t for t in tk if t.get("qr_token")), None)
if tok:
    eml, opw = ask("NEXO_DEMO_OPERATOR_EMAIL", "NEXO_DEMO_OPERATOR_PASSWORD", "operador de demostración")
    r = op.post("/api/auth/login", json={"email": eml, "password": opw}); check("inicio de sesión de operador", r.status_code == 200, f"HTTP {r.status_code}"); opw = None
    r = cl.post("/api/operator/validate", json={"event_id": tok.get("event_id"), "qr_token": tok["qr_token"]}, headers=csrf(cl)); check("un cliente no puede validar entradas (403)", r.status_code == 403, f"HTTP {r.status_code}")
    r = op.post("/api/operator/validate", json={"event_id": tok.get("event_id"), "qr_token": tok["qr_token"]}, headers=csrf(op))
    check("validación de un ticket recuperado por el operador", r.status_code == 200, f"HTTP {r.status_code}")
    r2 = op.post("/api/operator/validate", json={"event_id": tok.get("event_id"), "qr_token": tok["qr_token"]}, headers=csrf(op))
    check("segundo intento sobre el mismo ticket rechazado o marcado como ya usado", r2.status_code in (200, 400, 409, 422), f"HTTP {r2.status_code}")
else:
    check("validación de ticket", False, "la cuenta de demostración no tiene tickets con QR; usar otra cuenta con tickets")
out = {"ejecutado_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "duracion_s": round(time.time() - t0, 1), "base": "https://localhost:8443 (túnel Bastion)",
       "resultados": res, "todo_ok": all(x["ok"] for x in res)}
os.makedirs(a.out, exist_ok=True); open(os.path.join(a.out, "smoke.json"), "w").write(json.dumps(out, indent=2, ensure_ascii=False) + "\n")
print(f"\n{sum(x['ok'] for x in res)}/{len(res)} correctas; duración {out['duracion_s']} s"); sys.exit(0 if out["todo_ok"] else 1)
