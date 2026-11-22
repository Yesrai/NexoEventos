"""CLI local del centro de operaciones (sin red, sin nube).
  init-identities --dir D          genera 3 identidades (viewer, requester, approver); imprime cada token UNA vez en el terminal y guarda solo los hashes (0600)
  check TIPO                       muestra las barreras de ejecución de un tipo (exit 0 solo si todas pasan Y hay adaptadores cableados, hoy nunca)
  record-evidence ETAPA --report F --result PASS|FAIL   registra evidencia T1–T4 (SHA-256 del informe) y la audita
  kill-switch on|off               crea/retira el interruptor de emergencia
  verify-audit                     verifica la cadena de auditoría
  evidence-start|-event|-mark|-value|-attach|-finish|-verify   recolector de evidencias T1–T8 (ver evidence.py; veredicto PASS/FAIL/PARCIAL)
  execute ID                       SIEMPRE se niega: no hay ejecución cableada (requiere cambio de código y autorización específica)"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import barriers as B, evidence as E, evidence_t1 as T1, identities as I
from .audit import AuditLog
from .recovery import RecoveryStore, TIPOS
from .settings import Settings


def main(argv=None, env=None, out=sys.stdout):
    ap = argparse.ArgumentParser(prog="ops_center"); sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("init-identities"); p.add_argument("--dir", required=True)
    p = sub.add_parser("check"); p.add_argument("tipo", choices=sorted(TIPOS))
    p = sub.add_parser("record-evidence"); p.add_argument("etapa", choices=sorted(B.EVIDENCE_NAMES)); p.add_argument("--report", required=True); p.add_argument("--result", choices=("PASS", "FAIL"), required=True)
    p = sub.add_parser("kill-switch"); p.add_argument("state", choices=("on", "off"))
    sub.add_parser("verify-audit")
    p = sub.add_parser("collect"); p.add_argument("--targets", required=True); p.add_argument("--loop", action="store_true"); p.add_argument("--interval", type=int, default=60)
    p = sub.add_parser("evidence-start"); p.add_argument("etapa", choices=sorted(B.EVIDENCE_NAMES) + ["T5", "T6", "T7", "T8"]); p.add_argument("--root", required=True)
    q1 = sub.add_parser("evidence-t1"); q1.add_argument("run"); q1.add_argument("--probe", required=True)
    for name in ("event", "mark", "value", "attach", "finish", "verify"):
        q = sub.add_parser("evidence-" + name); q.add_argument("run")
        if name in ("event", "mark"): q.add_argument("name")
        if name == "value": q.add_argument("criterio"); q.add_argument("valor"); q.add_argument("--nota", default="")
        if name == "attach": q.add_argument("file"); q.add_argument("--redacted", action="store_true")
    p = sub.add_parser("execute"); p.add_argument("id")
    a = ap.parse_args(argv)
    s = Settings.from_env(env)
    if a.cmd == "init-identities":
        d = Path(a.dir); d.mkdir(parents=True, exist_ok=True); f = d / "identities.json"
        if f.exists():
            print("ya existe identities.json: no se sobrescribe", file=out); return 2
        ids, toks = [], {}
        for ident, role in (("ti-lectura", "viewer"), ("ti-solicitante", "requester"), ("propietaria-aprobador", "approver")):
            t = I.new_token(); toks[ident] = t; ids.append({"id": ident, "role": role, "token_sha256": I.hash_token(t)})
        fd = os.open(f, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "w") as fh: json.dump({"identities": ids}, fh, indent=1)
        print("Tokens (se muestran UNA vez; guárdelos en el gestor de contraseñas, nunca en el repositorio):", file=out)
        for k, v in toks.items(): print(f"  {k}: {v}", file=out)
        return 0
    if a.cmd.startswith("evidence-"):
        try:
            if a.cmd == "evidence-start":
                tpl = json.loads((Path(__file__).parent / "criterios" / f"{a.etapa}.json").read_text())
                r = E.EvidenceRun.start(a.root, a.etapa, tpl["title"], tpl["criteria"]); print(r.dir, file=out); return 0
            if a.cmd == "evidence-t1":
                vals = T1.apply(E.EvidenceRun.open(a.run), a.probe); print(f"{len(vals)} valores registrados automáticamente", file=out); return 0
            if a.cmd == "evidence-verify":
                v = E.verify_manifest(a.run); print(json.dumps(v), file=out); return 0 if v["ok"] else 1
            r = E.EvidenceRun.open(a.run)
            if a.cmd == "evidence-event": r.event(a.name)
            elif a.cmd == "evidence-mark": print(r.mark(a.name), file=out)
            elif a.cmd == "evidence-value":
                v = a.valor.lower() in ("true", "false") and a.valor.lower() == "true" if a.valor.lower() in ("true", "false") else float(a.valor)
                r.value(a.criterio, v, a.nota)
            elif a.cmd == "evidence-attach": r.attach(a.file, redacted=a.redacted)
            elif a.cmd == "evidence-finish":
                res = r.finish(); print(res["veredicto"], file=out); return 0 if res["veredicto"] == "PASS" else 1
            return 0
        except (E.EvidenceError, ValueError, OSError) as exc:
            print(f"ERROR: {exc}", file=out); return 2
    audit = AuditLog(Path(s.state_dir) / "audit.jsonl")
    if a.cmd == "collect":
        from . import collector as C
        try:
            snap = C.run(s, a.targets, once=not a.loop, interval=a.interval)
        except (OSError, ValueError) as exc:
            print(f"ERROR: {exc}", file=out); return 2
        print(json.dumps({n: snap["clouds"][n]["estado"] for n in C.CLOUDS}), file=out); return 0
    if a.cmd == "verify-audit":
        v = audit.verify(); print(json.dumps(v), file=out); return 0 if v["ok"] else 1
    if a.cmd == "kill-switch":
        Path(s.state_dir).mkdir(parents=True, exist_ok=True)
        if a.state == "on": s.kill_switch.write_text(datetime.now(timezone.utc).isoformat())
        else: s.kill_switch.unlink(missing_ok=True)
        audit.append("local-cli", "kill_switch_" + a.state); print("interruptor " + a.state, file=out); return 0
    if a.cmd == "record-evidence":
        rp = Path(a.report)
        if not rp.is_file(): print("informe inexistente", file=out); return 2
        try:
            ver = json.loads(rp.read_text()).get("veredicto")
        except (ValueError, OSError, AttributeError):
            ver = None
        if ver is not None and ((a.result == "PASS") != (ver == "PASS")):
            print(f"RECHAZADO: el informe declara «{ver}»; solo un informe PASS puede registrarse como PASS (y un PASS no se registra como FAIL)", file=out); return 2
        if ver is None and a.result == "PASS":
            print("RECHAZADO: un PASS exige un informe del recolector de evidencias (resultado.json con veredicto)", file=out); return 2
        rec = {"etapa": a.etapa, "resultado": a.result, "at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "report_sha256": hashlib.sha256(rp.read_bytes()).hexdigest(), "informe": rp.name}
        Path(s.evidence_dir).mkdir(parents=True, exist_ok=True)
        fd = os.open(Path(s.evidence_dir) / f"{a.etapa}.json", os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "w") as fh: json.dump(rec, fh, indent=1)
        audit.append("local-cli", "evidencia_registrada", etapa=a.etapa, resultado=a.result, sha=rec["report_sha256"][:16]); print("evidencia registrada", file=out); return 0
    if a.cmd == "check":
        store = RecoveryStore(s.state_dir, audit, lambda r: {"ok": False, "barriers": []})
        res = B.summarize(B.barrier_list(s, audit, store=store, tipo=a.tipo, execution=True))
        for b in res["barriers"]: print(("PASA    " if b["ok"] else "BLOQUEA ") + b["id"] + " — " + b["detalle"], file=out)
        return 0 if res["ok"] else 1
    if a.cmd == "execute":
        audit.append("local-cli", "ejecucion_denegada", id=a.id)
        print("DENEGADO: la ejecución real no está cableada (REAL_EXECUTION_WIRED=False). Requiere cambio de código revisado y autorización específica.", file=out); return 3
    return 2


if __name__ == "__main__":
    sys.exit(main())
