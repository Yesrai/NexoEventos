"""Mundo SIMULADO para probar el orquestador (B-13): dos sitios, un almacén de lease, sondas, DNS y relojes con deriva. Sin red ni nubes. Reutiliza el lease REAL (B-10)."""
from __future__ import annotations

import os
import random
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[2] / "backend"))

from app.failover.lease import LeaseClient, LeaseConfig, init_lease  # noqa: E402
from app.failover.store import ConditionalStore, InMemoryStore, StoreUnavailable  # noqa: E402
from orchestrator import Adapters, Config, Orchestrator, State  # noqa: E402

TTL, MARGIN, RHO = 15.0, 5.0, 0.05
SCENARIOS = ("primary_dead", "primary_alive_probers_blind", "primary_store_partitioned", "flapping", "ambiguous_probes", "bad_backup", "old_gate_off", "healthy")


class Link(ConditionalStore):
    verified = True

    def __init__(self, store, partitioned):
        self.s, self.part = store, partitioned

    def _g(self, fn):
        if self.part():
            raise StoreUnavailable("partición")
        return fn()
    def read(self): return self._g(self.s.read)
    def create(self, d): return self._g(lambda: self.s.create(d))
    def replace(self, e, d): return self._g(lambda: self.s.replace(e, d))


class World:
    def __init__(self, seed: int, scenario: str):
        self.rng = random.Random(seed); self.scenario = scenario
        self.t = 0.0; self.violations = 0; self.standby_wrote = False; self.dns_violation = False
        self.dns = "primary"; self.dns_applied = 0; self.restore_calls = 0; self.enable_calls = 0; self.acquire_ok_calls = 0
        self.primary_alive = True; self.primary_store_part = False; self.standby_store_part = False
        self.probers_blind = [False, False, False]; self.standby_enabled = False; self.primary_gate_enforced = True; self.bad_backup = False; self.standby_unhealthy = []
        self.store = InMemoryStore(); self.store.verified = True; init_lease(self.store)
        cfg = LeaseConfig(ttl_s=TTL, margin_s=MARGIN)
        self.rp, self.rs = 1 + RHO, 1 - RHO; self.op, self.os = self.rng.uniform(-1e5, 1e5), self.rng.uniform(-1e5, 1e5)
        self.primary = LeaseClient(Link(self.store, lambda: self.primary_store_part), cfg, "primario", mono=lambda: self.rp * self.t + self.op)
        self.standby = LeaseClient(Link(self.store, lambda: self.standby_store_part), cfg, "standby", mono=lambda: self.rs * self.t + self.os)
        assert self.primary.acquire().ok
        self.last_p = self.last_s = 0.0
        self.revive_at = None; self.events: list[tuple[float, callable]] = []
        self._setup(scenario)

    def _setup(self, sc):
        if sc == "primary_dead": self.events.append((3.0, lambda: setattr(self, "primary_alive", False)))
        elif sc == "primary_alive_probers_blind": self.probers_blind = [True, True, True]
        elif sc == "primary_store_partitioned": self.events.append((3.0, lambda: setattr(self, "primary_store_part", True))); self.events.append((70.0, lambda: setattr(self, "primary_store_part", False)))
        elif sc == "flapping":
            self.events.append((3.0, lambda: setattr(self, "primary_alive", False))); self.events.append((self.rng.uniform(12.0, 40.0), lambda: setattr(self, "primary_alive", True)))
        elif sc == "ambiguous_probes": self.probers_blind = [True, False, False]          # una sonda no ve al primario, que está SANO
        elif sc == "bad_backup": self.bad_backup = True; self.events.append((3.0, lambda: setattr(self, "primary_alive", False)))
        elif sc == "old_gate_off":
            # El primario sirve y escribe SIN compuerta (despliegue incorrecto) y pierde el almacén; las sondas no lo ven: el orquestador promovería y debe DETECTAR el doble escritor.
            self.primary_gate_enforced = False; self.probers_blind = [True, True, True]; self.events.append((3.0, lambda: setattr(self, "primary_store_part", True)))
        elif sc == "healthy": pass
        else: raise ValueError(sc)
        self.events.sort(key=lambda e: e[0])

    # --- modelo de escritura
    def primary_accepts(self) -> bool:
        return self.primary_alive and (self.primary.is_valid() or not self.primary_gate_enforced)

    def standby_accepts(self) -> bool:
        return self.standby_enabled and self.standby.is_valid()

    def _check(self):
        a, b = self.primary_accepts(), self.standby_accepts()
        if b: self.standby_wrote = True
        if a and b: self.violations += 1

    def advance(self, dt: float):
        steps = max(int(round(dt / 0.25)), 1)
        for _ in range(steps):
            self.t += dt / steps
            while self.events and self.events[0][0] <= self.t:
                self.events.pop(0)[1]()
            if self.primary_alive and self.t - self.last_p >= self.primary.config.renew_interval_s:
                self.last_p = self.t
                if self.primary._etag is not None and not self.primary._lost: self.primary.renew()
                else: self.primary.acquire()                          # el primario reiniciado intenta recuperar su lease (no puede si otro lo tiene)
            if self.standby._etag is not None and not self.standby._lost and self.t - self.last_s >= self.standby.config.renew_interval_s:
                self.last_s = self.t; self.standby.renew()             # guardián del standby (solo mientras retiene el lease)
            self._check()


class SimAdapters(Adapters):
    def __init__(self, w: World): self.w = w
    def precheck(self): return {"almacen_verificado": True, "dns_en_lista_blanca": True, "standby_listo": True}
    def probe_all(self):
        w = self.w
        return [False if w.probers_blind[i] else bool(w.primary_accepts()) for i in range(3)]       # «sano» = puede ESCRIBIR (salud + compuerta)
    def restore_latest(self):
        self.w.restore_calls += 1
        return {"fingerprint_ok": not self.w.bad_backup, "backup_age_s": 120.0, "backup": "sim-backup"}
    def lease_acquire(self):
        r = self.w.standby.acquire()
        if r.ok: self.w.acquire_ok_calls += 1
        return (r.ok, r.reason, self.w.standby.epoch if r.ok else None, r.wait_s)
    def lease_release(self):
        self.w.standby.release(); self.w.standby_enabled = False
    def enable_standby(self, epoch): self.w.enable_calls += 1; self.w.standby_enabled = True; self.w._check()
    def standby_status(self): return {"holds_lease": self.w.standby.is_valid(), "epoch": self.w.standby.epoch}
    def dns_plan(self): return {"destino": "standby"}
    def dns_apply(self):
        w = self.w
        if not (w.standby_enabled and w.standby.is_valid()): w.dns_violation = True        # I2: el DNS cambió sin escritor listo
        w._check()
        if w.dns != "standby":                                  # idempotente como dns_switch.py («Sin cambios» si ya apunta al destino): solo cuenta el cambio efectivo
            w.dns, w.dns_applied = "standby", w.dns_applied + 1
        return {"destino": "standby"}
    def probe_new_endpoint(self): return self.w.dns == "standby" or True
    def synthetic_write_ok(self): self.w._check(); return self.w.standby_accepts()
    def old_can_write(self): return self.w.primary_accepts() if self.w.primary_alive else None
    def primary_gate_attested(self): return self.w.primary_gate_enforced
    def standby_readiness(self): return {k: k not in self.w.standby_unhealthy for k in ("livez", "ready", "api")}
    def now(self): return self.w.t
    def sleep(self, s): self.w.advance(s)


def make(scenario, seed, state_path, run_id, start_t=10.0, dry_run=False, cfg: Config | None = None):
    w = World(seed, scenario); w.advance(start_t)
    ad = SimAdapters(w); cfg = cfg or Config()
    return w, ad, cfg


def run_scenario(scenario, seed, state_path, run_id, dry_run=False, cancel_at_stage=None) -> dict:
    w, ad, cfg = make(scenario, seed, state_path, run_id)
    state = State(state_path, run_id)
    cancel = (lambda: False)
    if cancel_at_stage:
        cancel = lambda: all(state.done(s) for s in cancel_at_stage[0]) if isinstance(cancel_at_stage, tuple) else False
    o = Orchestrator(ad, cfg, state, cancel_check=cancel, dry_run=dry_run)
    res = o.run()
    w.advance(5)
    return {"escenario": scenario, "outcome": res["outcome"], "safe_state": res["safe_state"], "abort_reason": res.get("abort_reason"), "violations": w.violations,
            "standby_wrote": w.standby_wrote, "dns": w.dns, "dns_applied": w.dns_applied, "dns_violation": w.dns_violation, "epoch": res.get("epoch"), "timeline": res["timeline"], **({"alerts": res["alerts"]} if res.get("alerts") else {})}
