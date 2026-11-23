#!/usr/bin/env python3
"""T4 — comprobaciones REALES contra la VM de Azure (HTTPS con el certificado FIJADO; ningún secreto por argumentos ni al chat: los tokens salen del entorno o se piden con getpass en TU terminal).
Escribe las mediciones que consume ejecutar_t4.py (work/t4/medidas/*.json). No cambia nada en AWS/OCI; las solicitudes de prueba del panel quedan auditadas (y las canceladas lo indican).
  panel   --base https://<fqdn>/ops --cafile cert.pem      → panel_sin_aws.json, auditoria.json (roles/denegaciones/cadena), bloqueo.json (ejecución real imposible)
  testigo --base https://<fqdn>/witness --cafile cert.pem [--witness-pub-der F] [--fase pre|post --estado F] [--pytest-vm F]
                                                            → testigo_auth.json (+ testigo_persistencia.json con --fase post)
Entorno: T4_TOKEN_VIEWER, T4_TOKEN_REQUESTER, T4_TOKEN_APPROVER (panel); T4_TOKEN_ATESTADOR, T4_TOKEN_LECTOR (testigo). Para PRUEBAS locales: --allow-http-localhost."""
from __future__ import annotations

import argparse
import base64
import getpass
import json
import os
import secrets
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))


def utc():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Http:
    def __init__(self, base, cafile=None, allow_http_localhost=False, timeout=15):
        u = urllib.parse.urlparse(base)
        if u.scheme != "https" and not (allow_http_localhost and u.scheme == "http" and u.hostname in ("127.0.0.1", "localhost")):
            raise SystemExit("la base debe ser https (http solo a localhost con --allow-http-localhost)")
        self.base = base.rstrip("/"); self.timeout = timeout
        self.ctx = ssl.create_default_context(cafile=cafile) if cafile else ssl.create_default_context()      # certificado FIJADO si se da cafile; nunca se desactiva la verificación

    def req(self, method, path, token=None, body=None):
        h = {"Accept": "application/json"}
        if token: h["Authorization"] = "Bearer " + token
        data = None
        if body is not None: data = json.dumps(body).encode(); h["Content-Type"] = "application/json"
        try:
            with urllib.request.urlopen(urllib.request.Request(self.base + path, data=data, headers=h, method=method), timeout=self.timeout, context=self.ctx) as r:
                raw = r.read(1 << 20); return r.status, (json.loads(raw) if raw else {}), dict(r.headers)
        except urllib.error.HTTPError as e:
            raw = e.read(1 << 16)
            try: return e.code, json.loads(raw), dict(e.headers)
            except ValueError: return e.code, {}, dict(e.headers)


def tok(name, env):
    v = os.environ.get(env)
    if v: return v.strip()
    if sys.stdin.isatty(): return getpass.getpass(f"Token {name} (no se muestra): ").strip()
    raise SystemExit(f"falta {env} (o ejecute en una terminal interactiva)")


def save(out, name, obj):
    out.mkdir(parents=True, exist_ok=True)
    fd = os.open(out / f"{name}.json", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f: json.dump(obj, f, ensure_ascii=False, indent=1)


def check(rows, name, cond, detail=""):
    rows.append({"prueba": name, "ok": bool(cond), "detalle": detail}); return bool(cond)


def cmd_panel(a):
    h = Http(a.base, a.cafile, a.allow_http_localhost); out = Path(a.out); rows = []
    tv, tr, ta = tok("viewer", "T4_TOKEN_VIEWER"), tok("requester", "T4_TOKEN_REQUESTER"), tok("approver", "T4_TOKEN_APPROVER")
    check(rows, "healthz sin credenciales = 200", h.req("GET", "/healthz")[0] == 200)
    check(rows, "overview anónimo = 401", h.req("GET", "/api/ops/overview")[0] == 401)
    check(rows, "token inválido = 401", h.req("GET", "/api/ops/overview", "x" * 40)[0] == 401)
    c, ov, hd = h.req("GET", "/api/ops/overview", tv); check(rows, "viewer lee el estado = 200", c == 200)
    nubes = ((ov.get("nubes") or {}).get("nubes") or {}) if isinstance(ov, dict) else {}
    check(rows, "cabeceras de seguridad presentes", any(k.lower() == "x-content-type-options" for k in hd) and any(k.lower() == "content-security-policy" for k in hd))
    check(rows, "viewer NO puede solicitar = 403", h.req("POST", "/api/ops/recovery-requests", tv, {"tipo": "restaurar_respaldo_en_oci", "reason": "T4: prueba de rol viewer"})[0] == 403)
    c, rq, _ = h.req("POST", "/api/ops/recovery-requests", tr, {"tipo": "restaurar_respaldo_en_oci", "reason": "T4: prueba de rol solicitante", "idempotency_key": "t4-" + secrets.token_hex(4)})
    check(rows, "requester puede solicitar = 201", c == 201, str(rq.get("state"))); rid = rq.get("id", "x")
    check(rows, "requester NO puede aprobar = 403", h.req("POST", f"/api/ops/recovery-requests/{rid}/approve", tr, {"comment": "x"})[0] == 403)
    estado = rq.get("state")
    c, ap, _ = h.req("POST", f"/api/ops/recovery-requests/{rid}/approve", ta, {"comment": "T4: decisión del aprobador (distinto del solicitante)"})
    if estado == "VALIDADA":                      # las barreras de ESA solicitud pasan: el aprobador distinto puede aprobar (APROBADA no ejecuta nada) y se cancela para no dejar un permiso vivo
        check(rows, "el aprobador (distinto del solicitante) aprueba una solicitud VALIDADA", c == 200 and ap.get("state") == "APROBADA", f"HTTP {c} {ap.get('state')}")
        c3, cn, _ = h.req("POST", f"/api/ops/recovery-requests/{rid}/cancel", ta); check(rows, "la solicitud aprobada de prueba se cancela (sin permiso vivo)", c3 == 200 and cn.get("state") == "CANCELADA", f"HTTP {c3} {cn.get('state')}")
    else:
        check(rows, "una solicitud no validada no se puede aprobar", c >= 400 or ap.get("state") != "APROBADA", f"estado {estado}; HTTP {c}")
    c, fo, _ = h.req("POST", "/api/ops/recovery-requests", tr, {"tipo": "failover_aws_a_oci", "reason": "T4: comprobar que el failover queda bloqueado", "idempotency_key": "t4f-" + secrets.token_hex(4)})
    bloqueado = c in (201, 409) and fo.get("state") in ("RECHAZADA_VALIDACION", "CANCELADA", "EXPIRADA") if c == 201 else c >= 400
    check(rows, "failover AWS→OCI queda RECHAZADO por las barreras", bloqueado, f"HTTP {c} {fo.get('state', '')}")
    c2 = h.req("POST", f"/api/ops/recovery-requests/{fo.get('id', 'x')}/approve", ta, {"comment": "x"})[0]; check(rows, "y no se puede aprobar", c2 >= 400, f"HTTP {c2}")
    for p in ("/api/ops/execute", "/api/ops/failover", "/api/ops/dns"):
        check(rows, f"no existe endpoint de ejecución {p}", h.req("POST", p, ta, {})[0] in (404, 405))
    c, au, _ = h.req("GET", "/api/ops/audit", tv); ent = au.get("entradas", []) if c == 200 else []
    den = [e for e in ent if e.get("event") == "acceso_denegado"]
    cad = bool((au.get("verificacion") or {}).get("ok")); check(rows, "cadena de auditoría íntegra", cad); check(rows, "las denegaciones quedaron auditadas (≥ 2)", len(den) >= 2, f"{len(den)}")
    check(rows, "las solicitudes quedaron auditadas", any(e.get("event") in ("solicitada", "validada", "rechazada_validacion", "aprobada", "cancelada") for e in ent), ", ".join(sorted({str(e.get("event")) for e in ent})[:6]))
    ov_txt = json.dumps(ov); b11 = ov.get("barreras_failover") or {}
    check(rows, "B11 (adaptadores reales cableados) en rojo", "B11" in json.dumps(b11) and "REAL_EXECUTION_WIRED=False" in json.dumps(b11) or not b11.get("ejecutable", False), "ejecutable=" + str(b11.get("ejecutable")))
    aws = (nubes.get("aws") or {}); aws_est = aws.get("estado")
    sin_aws = {"ok": bool(rows[0]["ok"] and c == 200 and aws_est == "ERROR"), "utc": utc(), "aws_estado": aws_est, "aws_origen": aws.get("origen"), "nota": "ok SOLO si el panel responde y la sonda REAL de AWS está en ERROR (AWS no responde); no se simula"}
    pruebas_roles = [r for r in rows if r["prueba"] != "cadena de auditoría íntegra"]
    save(out, "panel_sin_aws", sin_aws)
    save(out, "auditoria", {"ok": bool(cad and all(r["ok"] for r in rows if any(w in r["prueba"] for w in ("401", "403", "auditad", "aprob", "cabeceras", "healthz", "viewer", "requester", "cancela")))), "utc": utc(), "pruebas": rows})
    save(out, "bloqueo", {"ok": bool(all(r["ok"] for r in rows if any(w in r["prueba"] for w in ("failover", "ejecución", "B11", "aprobar")))), "utc": utc()})
    print(json.dumps({"pruebas": len(rows), "fallan": [r["prueba"] for r in rows if not r["ok"]], "aws": aws_est}, ensure_ascii=False)); return 0 if all(r["ok"] for r in rows) else 1


def cmd_testigo(a):
    from app.failover.witness import EcdsaP256Verifier, _canon
    h = Http(a.base, a.cafile, a.allow_http_localhost); out = Path(a.out); rows = []
    ta, tl = tok("atestador", "T4_TOKEN_ATESTADOR"), tok("lector", "T4_TOKEN_LECTOR")
    n = secrets.token_hex(16)
    check(rows, "healthz sin credenciales = 200", h.req("GET", "/healthz")[0] == 200)
    check(rows, "attest anónimo = 401", h.req("GET", f"/attest?nonce={n}")[0] == 401)
    check(rows, "attest con token SIN alcance (lector) = 403", h.req("GET", f"/attest?nonce={n}", tl)[0] == 403)
    check(rows, "attest con token desconocido = 403", h.req("GET", f"/attest?nonce={n}", "x" * 40)[0] == 403)
    check(rows, "entry anónimo = 401", h.req("GET", "/entry?seq=1")[0] == 401)
    check(rows, "report con token sin alcance report = 403", h.req("POST", "/report", ta, {"reporter": "operator", "payload": {"kind": "genesis"}, "sig": "00"})[0] == 403)
    c, att, _ = h.req("GET", f"/attest?nonce={n}", ta); check(rows, "attest con token válido = 200", c == 200)
    check(rows, "la atestación devuelve mi reto (anti-reproducción)", att.get("nonce") == n)
    if a.witness_pub_der and c == 200:
        pub = base64.b64decode(Path(a.witness_pub_der).read_text().strip()); body = {k: v for k, v in att.items() if k != "sig"}
        check(rows, "firma de la atestación verificada con la clave pública anclada", EcdsaP256Verifier(pub).verify("witness", _canon(body), att.get("sig", "")))
    else:
        check(rows, "firma de la atestación verificada con la clave pública anclada", False, "falta --witness-pub-der (DER en base64, obtenida de la VM)")
    check(rows, "el testigo está SIN INICIALIZAR (nadie puede informar)", c == 200 and not att.get("watermark"), "watermark vacío")
    ok_auth = all(r["ok"] for r in rows)
    save(out, "testigo_auth", {"ok": ok_auth, "utc": utc(), "pruebas": rows, "nota": "Los tokens no se guardan; la VM no recibe credenciales de AWS ni de OCI."})
    if a.fase == "pre":
        pre = Path(a.estado or (out / "testigo_estado.json")); pre.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(pre, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f: json.dump({"entries": att.get("entries"), "watermark": att.get("watermark"), "utc": utc()}, f)
    if a.fase == "post":
        ant = json.loads(Path(a.estado).read_text()); vm = json.loads(Path(a.pytest_vm).read_text()) if a.pytest_vm and Path(a.pytest_vm).exists() else None
        igual = ant.get("entries") == att.get("entries") and ant.get("watermark") == att.get("watermark")
        save(out, "testigo_persistencia", {"ok": bool(igual and vm and vm.get("ok") is True), "utc": utc(), "estado_igual_tras_reinicio": igual, "pytest_en_la_vm": vm,
                                           "limite": "archivo local: un prefijo restaurado no se detecta localmente (no se declara independencia validada); cabeza anclada fuera de la VM"})
    print(json.dumps({"fallan": [r["prueba"] for r in rows if not r["ok"]]}, ensure_ascii=False)); return 0 if ok_auth else 1


def main(argv=None):
    ap = argparse.ArgumentParser(); sub = ap.add_subparsers(dest="cmd", required=True)
    for n in ("panel", "testigo"):
        p = sub.add_parser(n); p.add_argument("--base", required=True); p.add_argument("--cafile"); p.add_argument("--out", default=str(ROOT / "work/t4/medidas")); p.add_argument("--allow-http-localhost", action="store_true")
        if n == "testigo":
            p.add_argument("--witness-pub-der"); p.add_argument("--fase", choices=("pre", "post")); p.add_argument("--estado"); p.add_argument("--pytest-vm")
    a = ap.parse_args(argv)
    return {"panel": cmd_panel, "testigo": cmd_testigo}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
