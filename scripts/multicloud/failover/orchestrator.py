#!/usr/bin/env python3
"""B-13 · Orquestador LOCAL de failover con etapas explícitas, verificaciones, idempotencia y cancelación segura.

NO ejecuta ninguna operación en la nube: todo pasa por un objeto `Adapters` y la única implementación que existe es la SIMULADA (sim.py). Con adaptadores sin configurar,
cada operación lanza NotAuthorized (falla cerrada). Modo por defecto de la CLI: `plan` (solo describe). Ejecutar de verdad exigiría además NEXO_ALLOW_FAILOVER_EXECUTE=YES,
una frase de confirmación exacta y adaptadores reales que AÚN NO EXISTEN (requieren autorización cloud, informe 19).

Etapas (cada una con precondición, acción idempotente y postcondición):
  PRECHECK → DECIDE → PREPARE_STANDBY → FENCE_AND_ACQUIRE → FENCE_CHECK → HEALTH_GATE → ENABLE_STANDBY → SWITCH_DNS → VERIFY
Invariantes de seguridad que se prueban en simulación (tests/test_failover_orchestrator.py):
  I1 nunca hay dos escritores a la vez (la tomadura del lease ES el vallado: el titular anterior caduca por su propio reloj antes de que se pueda tomar);
  I2 el DNS solo cambia después de: datos verificados + lease adquirido + standby confirmado;
  I3 ante datos ambiguos (sondas discrepantes, huella distinta, estado desconocido) NO se promueve;
  I4 cancelar en cualquier frontera deja ≤ 1 escritor; tras la promoción NO se revierte solo (failback manual con vallado: decisión humana);
  I5 repetir la misma ejecución no repite efectos (idempotencia); una ejecución ABORTADA no se reanuda con el mismo run_id;
  I6 (FENCE_CHECK, ANTES de habilitar el standby) el primario con estado DESCONOCIDO que podría seguir escribiendo bloquea la promoción y alerta: solo se promueve si se
     confirma que NO puede escribir, o si es inalcanzable pero hay evidencia (atestación) de que su compuerta de escritura está activa (WRITE_GATE_MODE=enforce, auto-vallado por lease);
  I7 (HEALTH_GATE, ANTES de habilitar escrituras y del DNS) el standby, ya con los datos restaurados y con su compuerta CERRADA, debe estar listo: /livez, /ready y una lectura de la API; si no,
     se libera el lease y no se habilita ningún escritor (el registro de promoción vuelve a NONE: aborto limpio);
  I8 el orden de activación es SIEMPRE: datos restaurados y verificados → lease → vallado del primario con evidencia → salud del standby → habilitar escrituras → DNS → verificación;
  I10 (ENABLE_STANDBY) con sello exigido, el sello persistente de promoción se escribe ANTES de habilitar escrituras; si no se puede escribir, no se promueve;
  I11 (PRECHECK) la promoción AUTOMÁTICA exige vallado fuerte y sello antirretroceso exigidos Y validados en entorno real; si no, se bloquea y alerta (failback siempre manual);
  I9 (DECIDE) un incidente clasificado como NO promovible (sano, transitorio, ambiguo, sondeador aislado) no se promueve; la clasificación y la evidencia quedan en el estado de la ejecución (panel Operación).
LIMITACIÓN: esto valida la LÓGICA con relojes y fallos simulados; no demuestra nada sobre AWS, OCI, RDS ni la red real.
"""
from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

STAGES = ["PRECHECK", "DECIDE", "PREPARE_STANDBY", "FENCE_AND_ACQUIRE", "FENCE_CHECK", "HEALTH_GATE", "ENABLE_STANDBY", "SWITCH_DNS", "VERIFY"]
READINESS_CHECKS = ("livez", "ready", "api")


class NotAuthorized(Exception):
    """Operación sin adaptador real configurado o sin autorización."""


class Abort(Exception):
    def __init__(self, reason: str, safe_state: str):
        super().__init__(reason); self.reason, self.safe_state = reason, safe_state


class Cancelled(Exception):
    pass


@dataclass
class Config:
    quorum: int = 2                         # sondas que deben fallar
    rounds: int = 3                         # rondas consecutivas
    round_interval_s: float = 5.0
    acquire_timeout_s: float = 60.0         # debe superar ttl + margen del lease
    poll_s: float = 1.0
    max_backup_age_s: float = 3600.0        # RPO máximo aceptado
    execute: bool = False
    # PROMOCIÓN AUTOMÁTICA (sin una persona al mando): SOLO con vallado fuerte exigido Y validado en RDS real, sello antirretroceso exigido Y validado (WORM real en OCI + trinquete), y failback manual.
    # Con automatic=False (por defecto) la promoción la dispara una persona; las demás protecciones (vallado fuerte, sello) se aplican igual si el adaptador las exige.
    automatic: bool = False
    validated_strong_fence: bool = False    # el vallado fuerte se demostró en la RDS REAL (pg_signal_backend, parada Multi-AZ, reinicio…)
    validated_antirollback: bool = False    # el sello antirretroceso se demostró con retención WORM REAL en OCI


class Adapters:
    """Contrato con el mundo exterior. La base lanza NotAuthorized: no hay nube por defecto."""
    def _no(self, name): raise NotAuthorized(f"adaptador «{name}» no configurado (requiere autorización cloud)")
    def precheck(self) -> dict: self._no("precheck")
    def probe_all(self) -> list: self._no("probe_all")                 # lista de True/False/None (None = desconocido)
    def restore_latest(self) -> dict: self._no("restore_latest")       # {"fingerprint_ok": bool, "backup_age_s": float, "backup": str}
    def lease_acquire(self) -> tuple: self._no("lease_acquire")        # (ok, razón, época|None, espera_s)
    def lease_release(self) -> None: self._no("lease_release")
    def enable_standby(self, epoch: int) -> None: self._no("enable_standby")
    def standby_status(self) -> dict: self._no("standby_status")       # {"holds_lease": bool, "epoch": int|None}
    def dns_plan(self) -> dict: self._no("dns_plan")
    def dns_apply(self) -> dict: self._no("dns_apply")                 # DEBE ser idempotente (dns_switch.py: «Sin cambios» si ya apunta al destino)
    def probe_new_endpoint(self) -> bool: self._no("probe_new_endpoint")
    def synthetic_write_ok(self) -> bool: self._no("synthetic_write_ok")
    def old_can_write(self): self._no("old_can_write")                 # True/False/None (inalcanzable)
    def primary_gate_attested(self): self._no("primary_gate_attested")  # True si hay EVIDENCIA vigente de que la compuerta del primario está en enforce (auto-vallado por lease); False/None = sin evidencia
    def standby_readiness(self) -> dict: self._no("standby_readiness")  # {"livez": bool, "ready": bool, "api": bool} del standby ANTES del DNS
    def incident(self):
        """Clasificación del incidente por señales INDEPENDIENTES (detector). None = sin detector (comportamiento anterior). Si existe: {"kind", "promotable", "reasons", "signals"}."""
        return None

    def fencing_assessment(self) -> dict:
        """Evaluación del vallado del primario: {"verdict": "FENCED"|"CAN_WRITE"|"UNKNOWN", "evidence": [{"kind","strength": "verified"|"inferred","detail"}]}. Por defecto se deriva de
        old_can_write()/primary_gate_attested(); los adaptadores completos la sustituyen por evidencia propia (estado de la instancia, compuerta, vallado de la BD)."""
        old = self.old_can_write()
        if old is True:
            return {"verdict": "CAN_WRITE", "evidence": [{"kind": "write_gate", "strength": "verified", "detail": "el primario acepta escrituras"}]}
        if old is False:
            return {"verdict": "FENCED", "evidence": [{"kind": "write_gate", "strength": "verified", "detail": "el primario informa que su compuerta está cerrada"}]}
        if self.primary_gate_attested() is True:
            return {"verdict": "FENCED", "evidence": [{"kind": "lease_expiry", "strength": "inferred", "detail": "primario inalcanzable con compuerta enforce atestiguada: sin lease no escribe"}]}
        return {"verdict": "UNKNOWN", "evidence": []}
    requires_seal = False
    def seal_primary(self, epoch: int) -> dict:
        """SELLO de promoción (persistente, en el almacén de OCI): impide que cualquier instancia de AWS recupere el lease tras un reinicio hasta el failback manual. {"sellado": bool}."""
        return {"sellado": False}
    def alert(self, severity: str, message: str) -> None: pass         # canal de alerta (el orquestador además lo anota en el estado de la ejecución, que lee el panel Operación)
    def now(self) -> float: return time.monotonic()
    def sleep(self, s: float) -> None: time.sleep(s)


class State:
    def __init__(self, path: str | os.PathLike, run_id: str):
        self.path, self.run_id = Path(path), run_id
        self.data = {"run_id": run_id, "stages": {}, "outcome": None, "safe_state": None, "epoch": None, "timeline": []}
        if self.path.exists():
            old = json.loads(self.path.read_text())
            if old.get("run_id") != run_id:
                raise ValueError("el archivo de estado pertenece a otro run_id")
            self.data = old

    def save(self):
        tmp = self.path.with_suffix(".tmp"); tmp.write_text(json.dumps(self.data, indent=1)); os.replace(tmp, self.path)

    def done(self, stage): return bool(self.data["stages"].get(stage, {}).get("done"))

    def mark(self, stage, result, t):
        self.data["stages"][stage] = {"done": True, "result": result}; self.data["timeline"].append([stage, round(t, 3)]); self.save()


class Orchestrator:
    def __init__(self, adapters: Adapters, cfg: Config, state: State, cancel_check=lambda: False, dry_run: bool = True):
        self.a, self.cfg, self.state, self.cancel, self.dry_run = adapters, cfg, state, cancel_check, dry_run
        self.t0 = adapters.now()

    # --- utilidades
    def _check_cancel(self):
        if self.cancel():
            raise Cancelled()

    def _wait(self, seconds: float):
        end = self.a.now() + seconds
        while self.a.now() < end:
            self._check_cancel()
            self.a.sleep(min(self.cfg.poll_s, max(end - self.a.now(), 0.01)))

    def _t(self): return self.a.now() - self.t0

    # --- etapas
    def stage_PRECHECK(self):
        if self.cfg.automatic:
            falta = [n for n, ok in (("vallado fuerte validado en RDS real", self.cfg.validated_strong_fence), ("sello antirretroceso validado con WORM real", self.cfg.validated_antirollback),
                                     ("adaptador con vallado fuerte exigido", bool(getattr(self.a, "require_strong_fence", False))), ("adaptador con sello exigido", bool(getattr(self.a, "requires_seal", False)))) if not ok]
            if falta:
                self._alert("critical", "promoción AUTOMÁTICA bloqueada: " + "; ".join(falta))
                raise Abort("promoción automática bloqueada (falta: " + "; ".join(falta) + "): solo se promueve con una persona al mando", "sin cambios")
        pc = self.a.precheck()
        bad = [k for k, v in pc.items() if not v]
        if bad:
            raise Abort(f"precondiciones incumplidas: {', '.join(bad)}", "sin cambios")
        return pc

    def stage_DECIDE(self):
        consecutive = 0
        for r in range(self.cfg.rounds):
            self._check_cancel()
            res = self.a.probe_all()
            if any(x is None for x in res):
                raise Abort("sondas con resultado desconocido: no se actúa", "sin cambios")
            failing = sum(1 for x in res if x is False)
            if failing >= self.cfg.quorum:
                consecutive += 1
            else:
                raise Abort(f"el primario responde para la mayoría de las sondas en la ronda {r + 1}: no se actúa", "sin cambios")
            if r < self.cfg.rounds - 1:
                self._wait(self.cfg.round_interval_s)
        inc = self.a.incident()
        if inc is not None:
            self.state.data["incident"] = {"kind": inc.get("kind"), "promotable": bool(inc.get("promotable")), "reasons": list(inc.get("reasons", []))[:6], "signals": dict(inc.get("signals", {}))}
            self.state.save()
            if not inc.get("promotable"):
                self._alert("warning" if inc.get("kind") in ("HEALTHY", "TRANSIENT") else "critical", f"incidente {inc.get('kind')} no promovible: " + "; ".join(map(str, inc.get("reasons", [])[:2])))
                raise Abort(f"incidente clasificado como {inc.get('kind')}: no es promovible ({'; '.join(map(str, inc.get('reasons', [])[:2]))})", "sin cambios")
        return {"rondas_fallidas": consecutive, **({"incidente": inc.get("kind")} if inc else {})}

    def stage_PREPARE_STANDBY(self):
        r = self.a.restore_latest()
        if not r.get("fingerprint_ok"):
            why = r.get("reason")  # solo informativo (motivo fijo y sin secretos del adaptador); no cambia ninguna condición
            raise Abort("la huella de los datos restaurados NO coincide: no se promueve" + (f" ({str(why)[:200]})" if why else ""), "sin cambios")
        if r.get("backup_age_s", 1e12) > self.cfg.max_backup_age_s:
            raise Abort("el respaldo supera la antigüedad máxima aceptada (RPO)", "sin cambios")
        return {"backup": r.get("backup"), "rpo_s": r.get("backup_age_s")}

    def stage_FENCE_AND_ACQUIRE(self):
        end = self.a.now() + self.cfg.acquire_timeout_s
        last = "?"
        while True:
            self._check_cancel()
            ok, reason, epoch, wait_s = self.a.lease_acquire()
            last = reason
            if ok:
                self.state.data["epoch"] = epoch; self.state.save()
                return {"epoch": epoch}
            if self.a.now() >= end:
                raise Abort(f"no se pudo adquirir el lease en {self.cfg.acquire_timeout_s:g} s ({last}): el titular sigue activo o el almacén no responde", "sin cambios de escritor")
            self._wait(min(max(wait_s, self.cfg.poll_s), max(end - self.a.now(), self.cfg.poll_s)))

    def _alert(self, severity: str, message: str):
        self.state.data.setdefault("alerts", []).append({"severity": severity, "message": message, "t": round(self._t(), 3)}); self.state.save()
        try:
            self.a.alert(severity, message)
        except Exception:  # noqa: BLE001 — una alerta que falla no puede impedir el aborto seguro
            pass

    def stage_FENCE_CHECK(self):
        """Antes de habilitar el standby: solo se promueve con EVIDENCIA de que el primario no puede seguir escribiendo. Si escribe (CAN_WRITE) o su estado es desconocido sin evidencia
        (UNKNOWN), se bloquea la promoción, se libera el lease y se alerta. La evidencia (tipo, fuerza verificada/inferida) queda en el estado para el panel."""
        fa = self.a.fencing_assessment()
        ev = [{"kind": str(e.get("kind"))[:24], "strength": e.get("strength"), "detail": str(e.get("detail"))[:120]} for e in fa.get("evidence", [])][:6]
        self.state.data["fencing"] = {"verdict": fa.get("verdict"), "evidence": ev, **({"classification": fa["classification"]} if fa.get("classification") else {})}; self.state.save()
        if fa.get("verdict") == "CAN_WRITE":
            self._alert("critical", "el primario SIGUE aceptando escrituras: promoción bloqueada")
            self.a.lease_release()
            raise Abort("el primario sigue aceptando escrituras (compuerta inactiva o sin vallar): se bloquea la promoción y se libera el lease", "sin escritor nuevo (lease liberado); el primario sigue escribiendo: intervención humana")
        if fa.get("verdict") != "FENCED":
            cls = fa.get("classification")
            self._alert("critical", "estado del primario desconocido sin evidencia de vallado: promoción bloqueada" + (f" (AWS: {cls}; modo seguro: nadie escribe hasta intervención humana)" if cls else ""))
            self.a.lease_release()
            raise Abort("estado del primario desconocido y sin evidencia de que no pueda escribir: podría seguir escribiendo; se bloquea la promoción y se libera el lease", "sin escritor nuevo (lease liberado): intervención humana")
        verified = any(e.get("strength") == "verified" for e in ev)
        if not verified:
            self._alert("warning", "vallado del primario solo INFERIDO (compuerta enforce atestiguada + lease caducado), sin evidencia directa")
        return {"vallado": "FENCED", "evidencia": [f"{e['kind']}:{e['strength']}" for e in ev]}

    def stage_HEALTH_GATE(self):
        """Antes de habilitar escrituras y del DNS: el standby (datos restaurados, compuerta CERRADA) debe responder /livez, /ready y la API; si no, se libera el lease y no se habilita ningún escritor."""
        h = self.a.standby_readiness() or {}
        bad = [k for k in READINESS_CHECKS if h.get(k) is not True]
        if bad:
            self._alert("warning", "el standby no está listo (" + ", ".join(bad) + "): no se habilitan escrituras ni se cambia el DNS")
            self.a.lease_release()
            raise Abort("el standby no pasó las comprobaciones de salud previas a la activación (" + ", ".join(bad) + "): no se habilitan escrituras ni se cambia el DNS", "sin escritor (indisponible): lease liberado")
        return {k: True for k in READINESS_CHECKS}

    def stage_ENABLE_STANDBY(self):
        for need in ("PREPARE_STANDBY", "FENCE_AND_ACQUIRE", "FENCE_CHECK", "HEALTH_GATE"):      # I8: escrituras solo tras datos + lease + vallado + salud
            if not self.state.done(need):
                raise Abort(f"precondición para habilitar escrituras incumplida ({need})", "sin escritor")
        epoch = self.state.data["epoch"]
        if epoch is None:
            raise Abort("no hay época de lease: no se habilita el standby", "sin escritor")
        if getattr(self.a, "requires_seal", False):                                       # I10: SIN sello persistente no se habilitan escrituras (una RDS que reinicia sola podría devolver la autoridad a AWS)
            try:
                sr = self.a.seal_primary(epoch)
            except Exception:  # noqa: BLE001
                sr = None
            if not (isinstance(sr, dict) and sr.get("sellado") is True):
                self._alert("critical", "no se pudo SELLAR el primario (protección persistente contra su regreso): no se habilitan escrituras")
                self.a.lease_release()
                raise Abort("no se pudo escribir el sello de promoción: sin él el primario podría recuperar autoridad tras un reinicio; no se habilitan escrituras", "sin escritor (lease liberado): intervención humana")
            self.state.data["sello"] = {"sellado": True, "epoca": epoch}; self.state.save()
        self.a.enable_standby(epoch)
        st = self.a.standby_status()
        if not (st.get("holds_lease") and st.get("epoch") == epoch):
            self.a.lease_release()
            raise Abort("el standby no confirmó el lease: se libera y no se continúa", "sin escritor (indisponible)")
        return st

    def stage_SWITCH_DNS(self):
        # Invariante I2: DNS solo tras datos verificados + lease + standby confirmado.
        for need in ("PREPARE_STANDBY", "FENCE_AND_ACQUIRE", "FENCE_CHECK", "ENABLE_STANDBY", "HEALTH_GATE"):
            if not self.state.done(need):
                raise Abort(f"precondición de DNS incumplida ({need})", "sin cambios de DNS")
        if self.dry_run:
            return {"plan": self.a.dns_plan(), "aplicado": False}
        return {"aplicado": True, **self.a.dns_apply()}

    def stage_VERIFY(self):
        ok_new = (self.a.probe_new_endpoint() if not self.dry_run else all((self.a.standby_readiness() or {}).get(k) is True for k in READINESS_CHECKS)); ok_w = self.a.synthetic_write_ok(); old = self.a.old_can_write()
        if old is True:
            self.a.lease_release()
            raise Abort("CRÍTICO: el sitio anterior SIGUE aceptando escrituras (su compuerta no está activa): se libera el lease nuevo y se exige intervención humana", "DOBLE ESCRITOR DETECTADO")
        if not (ok_new and ok_w):
            raise Abort("el nuevo sitio no responde o no escribe", "revisión humana (el lease nuevo sigue vigente)")
        return {"endpoint": ok_new, "escritura_sintetica": ok_w, "anterior_puede_escribir": old, "rto_s": round(self._t(), 3)}

    def before_stage(self, name): pass
    def after_stage(self, name, result): pass

    # --- ejecución
    def _safe_state_on_cancel(self) -> str:
        st = self.state
        if st.done("SWITCH_DNS") or st.done("ENABLE_STANDBY"):
            return "NO se revierte automáticamente: el nuevo escritor ya está activo; decisión humana (failback con vallado)"
        if st.done("FENCE_AND_ACQUIRE"):
            try: self.a.lease_release()
            except Exception: pass
            return "sin escritor (indisponible): lease liberado antes de habilitar el standby"
        return "sin cambios"

    def run(self) -> dict:
        d = self.state.data
        if d["outcome"] == "ABORTED":
            raise Abort("esta ejecución ya fue ABORTADA: usa otro run_id tras revisar la causa", d["safe_state"] or "?")
        if d["outcome"] == "DONE":
            return d                                                    # idempotente: no repite efectos
        try:
            for name in STAGES:
                self._check_cancel()
                if self.state.done(name):
                    continue
                self.before_stage(name)
                result = getattr(self, f"stage_{name}")()
                self.after_stage(name, result)                         # ganchos para inyectar caídas en pruebas (antes de persistir el avance)
                self.state.mark(name, result, self._t())
            d["outcome"], d["safe_state"] = "DONE", "nuevo escritor activo y verificado"
        except Abort as e:
            d["outcome"], d["safe_state"], d["abort_reason"] = "ABORTED", e.safe_state, e.reason
        except Cancelled:
            d["outcome"], d["safe_state"] = "CANCELLED", self._safe_state_on_cancel()
        # cualquier otra excepción: la ejecución queda abierta (sin outcome) y se puede reanudar con el mismo run_id
        self.state.save()
        return d


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Orquestador local de failover (simulación; sin operaciones cloud).")
    ap.add_argument("cmd", choices=["plan", "simulate", "run", "preflight"])
    ap.add_argument("--config", help="preflight: archivo JSON de configuración del despliegue real (solo se VALIDA; no se abre ninguna conexión)")
    ap.add_argument("--scenario", default="primary_dead"); ap.add_argument("--seed", type=int, default=1); ap.add_argument("--state-dir", default="work/failover-sim")
    ap.add_argument("--run-id", default="demo"); ap.add_argument("--confirm")
    a = ap.parse_args(argv)
    if a.cmd == "plan":
        print("Etapas:", " → ".join(STAGES)); print("Sin operaciones cloud. `simulate` ejecuta el escenario simulado; `run` exige adaptadores reales (no existen todavía).")
        return 0
    if a.cmd == "preflight":
        sys.path.insert(0, os.path.dirname(__file__))
        import failover_config as FC
        try:
            rep = FC.validate(FC.load(a.config))
        except (OSError, ValueError, TypeError):
            print("No se pudo leer la configuración.", file=sys.stderr); return 2
        print(json.dumps(rep, indent=1, ensure_ascii=False)); return 0 if rep["ok"] else 1
    if a.cmd == "run":
        if os.environ.get("NEXO_ALLOW_FAILOVER_EXECUTE") != "YES" or a.confirm != "EJECUTAR FAILOVER REAL":
            print("RECHAZADO: falta NEXO_ALLOW_FAILOVER_EXECUTE=YES y --confirm \"EJECUTAR FAILOVER REAL\".", file=sys.stderr); return 2
        print("RECHAZADO: no hay adaptadores reales configurados (falla cerrada). Pendiente de autorización cloud.", file=sys.stderr); return 2
    sys.path.insert(0, os.path.dirname(__file__))
    import sim
    out = sim.run_scenario(a.scenario, a.seed, Path(a.state_dir) / f"{a.run_id}.json", a.run_id)
    print(json.dumps(out, indent=1, ensure_ascii=False)); return 0 if out["violations"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
