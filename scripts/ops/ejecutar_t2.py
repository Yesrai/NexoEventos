#!/usr/bin/env python3
"""T2 — cambio REAL de DNS en el subdominio de PRUEBAS (DuckDNS): actualización, resolución y reversión. Un solo punto de entrada.
  Sin --autorizo: MODO PLAN (solo lectura): valida archivos, lista blanca y el punto de partida (consultas DNS de lectura) y muestra la frase exacta. No cambia nada.
  Con --autorizo "<frase exacta>": negativos de seguridad → plan → apply A→B → verify → segundo cambio (debe rechazarse) → rollback B→A → verify → plan final, con evidencia.
SEGURIDAD: la lista blanca debe contener SOLO el subdominio de pruebas; si un apply se emitió, SIEMPRE se intenta la reversión (también ante errores o Ctrl-C). El token se lee de un archivo 0600 por dns_switch.py y nunca se imprime."""
from __future__ import annotations

import argparse
import json
import os
import re
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "scripts" / "multicloud"))
import dns_switch as DS  # noqa: E402
from ops_center import evidence as E  # noqa: E402

FRASE = "AUTORIZO T2 EN DUCKDNS: dns_switch.py, subdominio nexoeventos-test, cambio A a B y reversión"
PROD = {"nexoeventos-demo"}


class Abort(Exception):
    pass


def phrase(action, domain, ip):
    return DS.expected_phrase(action, domain, ip)


class Runner:
    def __init__(self, a):
        self.a = a; self.steps = []; self.token = None; self.changed = False; self.restored = False
        self.cfg_path = Path(a.config); self.tok_path = Path(a.token_file)

    # ---------------- utilidades
    def sh(self, label, cmd, change=False, extra=()):
        env = {k: v for k, v in os.environ.items() if k not in ("NEXO_ALLOW_DNS_CHANGE", "DUCKDNS_TOKEN")}
        if change: env["NEXO_ALLOW_DNS_CHANGE"] = "YES"
        if self.a.api_base: env["NEXO_DNS_TEST"] = "1"
        argv = [sys.executable, str(ROOT / "scripts/multicloud/dns_switch.py"), cmd, "--config", str(self.cfg_path), "--domain", self.a.domain, "--state-dir", str(self.state_dir), *extra]
        if self.a.api_base: argv += ["--api-base", self.a.api_base]
        if cmd in ("apply", "rollback"): argv += ["--token-file", str(self.tok_path)]
        if cmd in ("apply", "rollback", "verify"): argv += ["--timeout", str(self.a.propagation_timeout), "--interval", str(self.a.poll_interval)]
        t0 = datetime.now(timezone.utc); r = subprocess.run(argv, capture_output=True, text=True, env=env, timeout=600)
        st = {"label": label, "cmd": cmd, "rc": r.returncode, "out": r.stdout, "err": r.stderr, "t0": E.iso(t0), "t1": E.iso(datetime.now(timezone.utc))}
        self.steps.append(st); return st

    def prepare(self):
        for p, what in ((self.cfg_path, "configuración"), (self.tok_path, "token")):
            if not p.is_file(): raise Abort(f"falta el archivo de {what}: {p}")
            if p.stat().st_mode & 0o077: raise Abort(f"el archivo de {what} debe tener permisos 0600")
        self.cfg = DS.load_config(str(self.cfg_path))
        self.state_dir = Path(self.a.state_dir or self.cfg["state_dir"])
        if self.cfg["allowed_domains"] != [self.a.domain] or self.a.domain in PROD or not self.a.domain.startswith("nexoeventos-test"):
            raise Abort("la lista blanca debe contener SOLO el subdominio de pruebas (nexoeventos-test…); el dominio de producción no puede figurar")
        t = self.cfg["allowed_targets"]
        if set(t) != {"a", "b"} or t["a"] == t["b"]: raise Abort("allowed_targets debe tener exactamente «a» (IP actual de partida) y «b» (IP distinta)")
        self.A, self.B = t["a"], t["b"]; self.token = DS.read_token(argparse.Namespace(token_file=str(self.tok_path)))
        if self.cfg["min_interval_s"] < 120: raise Abort("min_interval_s debe ser ≥ 120 s")

    @staticmethod
    def current(out):
        m = re.search(r"IP actual \(resolvedores\): (\S+)", out); return m.group(1) if m else None

    @staticmethod
    def secs(out):
        m = re.search(r"propagación[^\n]*? en ([0-9.]+) s", out); return float(m.group(1)) if m else None

    def tls_check(self):
        """Apretón de manos TLS VERIFICADO con el proveedor (sin enviar petición ni token). Con --api-base (pruebas locales, http) no aplica."""
        if self.a.api_base: return {"ok": True, "detalle": "omitido (proveedor simulado)"}
        import socket
        try:
            with socket.create_connection(("www.duckdns.org", 443), timeout=8) as sk:
                with DS._verified_ctx().wrap_socket(sk, server_hostname="www.duckdns.org") as t: return {"ok": True, "tls": t.version(), "verificacion": "activa"}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "detalle": f"{type(e).__name__}: {str(e)[:120]}"}

    # ---------------- modo plan
    def plan(self):
        self.prepare()
        out = {"modo": "PLAN (solo lectura)", "dominio": self.a.domain, "lista_blanca": self.cfg["allowed_domains"], "min_interval_s": self.cfg["min_interval_s"], "ttl_supuesto_s": self.cfg["assumed_ttl_s"], "resolvedores": self.cfg["resolvers"]}
        st = self.sh("plan", "plan", extra=["--target", "b"]); cur = self.current(st["out"]); out["rc_plan"] = st["rc"]
        out["parte_de_A"] = (cur == self.A)
        out["tls_proveedor"] = self.tls_check()          # prerrequisito añadido tras el FAIL del 22-nov (el Python no tenía almacén de certificados)
        out["resultado"] = "LISTO" if (st["rc"] == 0 and cur == self.A and out["tls_proveedor"]["ok"]) else "NO LISTO"
        if not out["tls_proveedor"]["ok"]: out["motivo"] = "no se puede verificar el certificado TLS de DuckDNS desde este intérprete"
        if cur != self.A: out["motivo"] = "el dominio no apunta (de forma coherente en los 3 resolvedores) a la IP «a» de la configuración"
        print(json.dumps(out, indent=1)); print("\nPara ejecutar T2: --autorizo \"" + FRASE + "\""); return 0 if out["resultado"] == "LISTO" else 2

    # ---------------- ejecución
    def execute(self):
        self.prepare(); a = self.a; d = a.domain
        tpl = json.loads((ROOT / "ops_center/criterios/T2.json").read_text()); run = E.EvidenceRun.start(a.evidence_root, "T2", tpl["title"], tpl["criteria"]); self.run = run
        run.event("autorizacion_recibida"); run.mark("inicio")
        v = {}
        signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
        try:
            v["dominio_de_pruebas"] = True
            v["produccion_rechazada"] = self._neg_prod()
            n2 = self.sh("negativo_sin_variable", "apply", change=False, extra=["--target", "b", "--confirm", phrase("apply", d, self.B)])
            v["sin_variable_rechazada"] = (n2["rc"] == 2 and "NEXO_ALLOW_DNS_CHANGE" in n2["err"])
            n3 = self.sh("negativo_confirmacion", "apply", change=True, extra=["--target", "b", "--confirm", "CAMBIAR DNS nexoeventos-test A 1.2.3.4"])
            v["confirmacion_incorrecta_rechazada"] = (n3["rc"] == 2 and "confirmación incorrecta" in n3["err"])
            p = self.sh("plan_inicial", "plan", extra=["--target", "b"]); v["punto_de_partida_verificado"] = bool(p["rc"] == 0 and self.current(p["out"]) == self.A)
            if not v["punto_de_partida_verificado"]: raise Abort("el dominio no parte de la IP A en los 3 resolvedores: NO se cambia nada")
            if not all(v[k] for k in ("produccion_rechazada", "sin_variable_rechazada", "confirmacion_incorrecta_rechazada")): raise Abort("fallaron los negativos de seguridad: NO se cambia nada")
            run.mark("dns_aplicando"); self.changed = True        # desde aquí, ante cualquier fallo se intenta revertir
            ap = self.sh("apply_b", "apply", change=True, extra=["--target", "b", "--confirm", phrase("apply", d, self.B)]); t_apply = time.monotonic()
            run.mark("dns_aplicado"); v["propagacion_apply_s"] = self.secs(ap["out"]) if ap["rc"] == 0 else None
            if ap["rc"] != 0: raise Abort(f"apply no terminó limpio (código {ap['rc']}): se revierte")
            vb = self.sh("verify_b", "verify", extra=["--expect-ip", self.B]); v["resolvedores_coinciden_en_B"] = (vb["rc"] == 0)
            run.mark("b_verificado")
            if time.monotonic() - t_apply < self.cfg["min_interval_s"] - 15:
                s2 = self.sh("segundo_cambio", "apply", change=True, extra=["--target", "a", "--confirm", phrase("apply", d, self.A)])
                v["segundo_cambio_rechazado"] = (s2["rc"] == 3 and "intervalo mínimo" in s2["err"]); run.mark("segundo_cambio_probado")
            else: run.event("segundo_cambio_no_probado", motivo="intervalo mínimo ya cumplido")
            self.rollback(v)
        except (Abort, KeyboardInterrupt, Exception) as exc:  # noqa: BLE001
            run.event("interrupcion", tipo=type(exc).__name__, detalle=str(exc)[:200]); print("ERROR:", type(exc).__name__, str(exc)[:200], file=sys.stderr)
        finally:
            if self.changed and not self.restored:
                try:
                    chk = self.sh("comprobacion_antes_de_revertir", "plan", extra=["--target", "b"])
                    if chk["rc"] == 0 and self.current(chk["out"]) == self.A:     # el cambio nunca llegó a producirse (p. ej. el proveedor respondió KO): no hay nada que revertir
                        self.restored = True; v["rollback_correcto"] = True; v["ip_final_igual_a_inicial"] = True; run.event("sin_cambio_que_revertir")
                    else: self.rollback(v)
                except BaseException as e2:  # noqa: BLE001
                    run.event("rollback_fallido", tipo=type(e2).__name__); print("¡REVERSIÓN FALLIDA! Restaure A a mano en el panel de DuckDNS y revise el expediente:", run.dir, file=sys.stderr)
        return self.finish(v)

    def _neg_prod(self):
        env = {k: v for k, v in os.environ.items() if k != "NEXO_ALLOW_DNS_CHANGE"}
        r = subprocess.run([sys.executable, str(ROOT / "scripts/multicloud/dns_switch.py"), "plan", "--config", str(self.cfg_path), "--domain", "nexoeventos-demo", "--target", "b", "--state-dir", str(self.state_dir)],
                           capture_output=True, text=True, env=env, timeout=60)
        self.steps.append({"label": "negativo_produccion", "cmd": "plan(nexoeventos-demo)", "rc": r.returncode, "out": r.stdout, "err": r.stderr, "t0": E.iso(datetime.now(timezone.utc)), "t1": E.iso(datetime.now(timezone.utc))})
        return r.returncode == 2 and "lista blanca" in r.stderr and not re.search(r"IP actual", r.stdout)

    def rollback(self, v):
        d = self.a.domain; run = self.run
        for attempt in (1, 2):
            rb = self.sh(f"rollback_a_{attempt}", "rollback", change=True, extra=["--confirm", phrase("rollback", d, self.A)])
            if rb["rc"] == 0: break
            run.event("rollback_reintento", intento=attempt, rc=rb["rc"])
        run.mark("dns_revertido"); v["propagacion_rollback_s"] = self.secs(rb["out"]) if rb["rc"] == 0 else None
        va = self.sh("verify_a", "verify", extra=["--expect-ip", self.A]); pf = self.sh("plan_final", "plan", extra=["--target", "b"])
        ok_a = (va["rc"] == 0); cur = self.current(pf["out"])
        v["rollback_correcto"] = bool(rb["rc"] == 0 and ok_a and cur == self.A); v["ip_final_igual_a_inicial"] = (cur == self.A)
        self.restored = bool(v["rollback_correcto"]); run.mark("a_verificado")

    def finish(self, v):
        run = self.run; run.mark("fin")
        try:   # auditoría de dns_switch: apply y rollback con hora UTC de ESTA ejecución
            ents = [json.loads(l) for l in (self.state_dir / f"{self.a.domain}.audit.jsonl").read_text().splitlines()]
            mine = [e for e in ents if e.get("utc", "")[:19] >= run.meta["started_utc"][:19]]
            v["auditoria_dns_switch_registrada"] = any(e.get("action") == "apply" for e in mine) and any(e.get("action") == "rollback" for e in mine)
        except (OSError, ValueError): v["auditoria_dns_switch_registrada"] = False
        for s in self.steps:   # capturas saneadas (el saneador oculta IP, URL y tokens)
            run.capture_text(f"paso-{s['label']}", f"cmd: {s['cmd']}\nrc: {s['rc']}\nt0: {s['t0']}  t1: {s['t1']}\n--- stdout\n{s['out']}\n--- stderr\n{s['err']}")
        raw = "\n".join(s["out"] + s["err"] for s in self.steps)
        leaked = self.token in raw or self._token_in_files()
        v["token_ausente_de_salidas"] = not leaked
        for k, x in v.items():
            if x is not None: run.value(k, x, "automático desde dns_switch")
        res = run.finish()
        leaked = leaked or self._token_in_files()      # también tras escribir resultado y manifiesto
        print(f"veredicto T2: {res['veredicto']} · evidencia: {run.dir}")
        if leaked: print("¡EL TOKEN APARECE EN LA EVIDENCIA! No comparta el expediente.", file=sys.stderr); return 1
        return 0 if res["veredicto"] == "PASS" else 1

    def _token_in_files(self):
        return any(self.token in p.read_text(errors="ignore") for p in Path(self.run.dir).rglob("*") if p.is_file())


def main(argv=None):
    ap = argparse.ArgumentParser(); ap.add_argument("--autorizo"); ap.add_argument("--config", default="work/dns-switch/config-prueba.json"); ap.add_argument("--token-file", default="work/dns-switch/token")
    ap.add_argument("--domain", default="nexoeventos-test"); ap.add_argument("--state-dir"); ap.add_argument("--evidence-root", default="work/evidencias"); ap.add_argument("--api-base", default="")
    ap.add_argument("--propagation-timeout", type=float, default=180.0); ap.add_argument("--poll-interval", type=float, default=5.0)   # 180 s = 3 × TTL asumido (criterio de T2)
    a = ap.parse_args(argv); r = Runner(a)
    try:
        if a.autorizo != FRASE:
            return r.plan()
        return r.execute()
    except Abort as e:
        print("ABORTA:", e, file=sys.stderr); return 2
    except DS.Refused as e:
        print("RECHAZADO:", e, file=sys.stderr); return 2


if __name__ == "__main__":
    sys.exit(main())
