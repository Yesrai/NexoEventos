"""Activación controlada del standby y composición de TODOS los adaptadores del orquestador (B-13), para un entorno LOCAL de pruebas.

`FullRecoveryAdapters` implementa el contrato completo de `orchestrator.Adapters` conectando: sondas (adapters_probes), lectura/verificación del respaldo en OCI (oci_source),
lease real (backend/app/failover/lease.py), servicio standby con vallado de datos (fenced_db), registro de promoción y cambio de DNS (adapters_dns / dns_switch.py).
NO ejecuta nada en la nube: los extremos (HTTP, DNS, OCI) los pone quien lo construye; en las pruebas son servidores falsos en 127.0.0.1.

Escritura del standby = TRES condiciones independientes, ninguna es solo una bandera local:
  1. permiso de promoción (archivo creado con O_EXCL por enable_standby, DESPUÉS de verificar el respaldo y de adquirir el lease);
  2. lease VÁLIDO: plazo calculado con el reloj monótono desde la última renovación CONFIRMADA por el almacén condicional (caduca solo si no renueva);
  3. época vigente en la propia base de datos (fenced_db): un token de época vieja se rechaza dentro de la transacción aunque 1 y 2 estén mal (defensa en profundidad).
Garantías de orden (probadas): no hay lease sin respaldo verificado; no hay habilitación sin lease de la época correcta; el DNS solo tras standby confirmado (orquestador, I2);
tras un DNS incierto o rechazado el registro de promoción queda bloqueado y NINGUNA ejecución automática vuelve a promover.
LÍMITE: esto NO es un vallado del primario. El primario solo queda impedido por su AUTO-vallado (lease que caduca por su reloj + compuerta activa); si su proceso está congelado y su
compuerta no está en `enforce`, nada de lo de aquí lo detiene. Ver fenced_db.py.
"""
from __future__ import annotations

import json
import os
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[2] / "backend"))

import adapters_probes as ap  # noqa: E402
import oci_source as oc  # noqa: E402
from adapters_dns import DnsSwitchAdapter  # noqa: E402
from fenced_db import FencedDatabase, FencedOut, LedgerError, PromotionLedger  # noqa: E402
from orchestrator import Abort, Adapters, Config, Orchestrator, State  # noqa: E402

from app.failover.lease import LeaseClient  # noqa: E402


class SimClock:
    """Reloj simulado compartible entre hilos (monótono: solo avanza)."""
    def __init__(self, t: float = 0.0):
        self.t, self._lock, self.listeners = t, threading.Lock(), []

    def now(self) -> float:
        return self.t

    def advance(self, dt: float) -> None:
        with self._lock:
            self.t += dt
            t = self.t
        for l in list(self.listeners):        # «procesos» en segundo plano (renovación del lease, monitores): corren aunque el hilo que avanza el tiempo sea otro
            l(t)


class StandbyService:
    """El standby local: lease + base con vallado + permiso de promoción. `write()` exige las tres condiciones."""

    def __init__(self, lease: LeaseClient, db: FencedDatabase, promote_file, name: str = "standby"):
        self.lease, self.db, self.promote_file, self.name = lease, db, Path(promote_file), name

    def promote_permitted(self) -> bool:
        return self.promote_file.exists()

    def writes_permitted(self) -> bool:
        return self.promote_permitted() and self.lease.is_valid()

    def holds_lease_object(self) -> bool:
        return self.lease._etag is not None and not self.lease._lost

    def keeper_step(self) -> None:
        if self.holds_lease_object():
            self.lease.renew()

    def enable(self, epoch: int) -> None:
        if not self.lease.is_valid() or self.lease.epoch != epoch:
            raise FencedOut("el lease no es válido o no es de la época indicada: no se habilita")
        self.db.raise_fence(epoch)                              # 1.º el vallado de DATOS (los escritores de épocas anteriores quedan rechazados)
        fd = os.open(self.promote_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)   # 2.º el permiso; no se sobrescribe
        with os.fdopen(fd, "w") as f:
            f.write(str(epoch))

    def disable(self) -> None:
        self.promote_file.unlink(missing_ok=True)

    def write(self, payload: str) -> int:
        if not self.writes_permitted():
            raise FencedOut("el standby no tiene permiso de promoción y lease válido a la vez")
        return self.db.write(self.lease.epoch, self.name, payload, still_valid=self.lease.is_valid)

    def status(self) -> dict:
        return {"mode": "enforce", "role": "standby", "holds_lease": self.lease.is_valid(), "epoch": self.lease.epoch, "promote_permitted": self.promote_permitted(),
                "fence_epoch": self.db.epoch()}


class FullRecoveryAdapters(Adapters):
    def __init__(self, *, run_id: str, clock: SimClock, lease: LeaseClient, standby: StandbyService, ledger: PromotionLedger, probes: ap.ProbeSet, dns: DnsSwitchAdapter,
                 oci_reader, oci_key, oci_passin: str = "", signer_pub=None, backup_env: str | None = None, restore_mode: str = "local", restore_env: dict | None = None,
                 wall_now=lambda: datetime.now(timezone.utc), max_backup_age_s: float = 3600.0, standby_health: ap.HttpProbe | None = None,
                 primary_gate_url: str | None = None, standby_gate_url: str | None = None, min_probes: int = 3, allow_http_localhost: bool = False,
                 tick_hooks=(), step_s: float = 0.25, store_verifier=None, primary_db_fence=None, require_primary_db_fence: bool = False,
                 external_writers_check=None, allow_partial_visibility: bool = False, primary_gate_attested=None, standby_readiness_probes: dict | None = None, aws_state=None, detector=None, restore_cert_sha256: str | None = None, db_attestation=None, strong_fence=None, require_strong_fence: bool = False, sealer=None, require_seal: bool = False):
        self.sealer, self.requires_seal = sealer, require_seal
        self.strong_fence, self.require_strong_fence, self.strong_result = strong_fence, require_strong_fence, None
        self.run_id, self.clock, self.lease, self.standby, self.ledger, self.probes, self.dns = run_id, clock, lease, standby, ledger, probes, dns
        self.oci = dict(reader=oci_reader, key=oci_key, passin=oci_passin, signer_pub=signer_pub, env=backup_env, mode=restore_mode, restore_env=restore_env)
        self.wall_now, self.max_backup_age_s, self.standby_health = wall_now, max_backup_age_s, standby_health
        self.primary_gate_url, self.standby_gate_url, self.min_probes, self.allow_http_localhost = primary_gate_url, standby_gate_url, min_probes, allow_http_localhost
        self.tick_hooks, self.step_s = list(tick_hooks), step_s
        # El almacén del lease debe PASAR la autoprueba de If-Match / If-None-Match (store_verifier -> bool) en el precheck y otra vez antes de tomar el lease en esta ejecución.
        # Sin verificador se exige al menos que el almacén venga marcado `verified`. Vallado externo de la base del primario (opcional): callable -> dict; con
        # require_primary_db_fence=True su fallo impide habilitar el standby; por defecto solo se registra (el primario puede estar inalcanzable: entonces solo queda el auto-vallado).
        self.store_verifier, self.primary_db_fence, self.require_primary_db_fence = store_verifier, primary_db_fence, require_primary_db_fence
        # Detector de escritores externos (app.failover.external_writers): callable -> dict {"bloquea": bool, "visibilidad": "completa"|"parcial"}. Si se entrega, entra al precheck
        # como `sin_escritores_externos` (falla cerrado: un hallazgo que bloquea, visibilidad parcial —salvo permiso expreso— o cualquier error lo incumplen). Sin él, el precheck no cambia.
        self.external_writers_check, self.allow_partial_visibility = external_writers_check, allow_partial_visibility
        # Evidencia (callable -> True/False/None, o un bool) de que la compuerta del primario está en enforce: si el primario es inalcanzable, sin ella NO se promueve (podría seguir escribiendo).
        # Sondas de preparación del standby ANTES del DNS: {"livez": HttpProbe, "ready": HttpProbe, "api": HttpProbe}; sin ellas la preparación no se puede confirmar (falla cerrado).
        self._gate_attested, self.standby_readiness_probes = primary_gate_attested, dict(standby_readiness_probes or {})
        # Evidencia adicional de vallado (estado de AWS en solo lectura), detector de incidentes y huella del certificado destinatario (C-04) que debe declarar el respaldo.
        self.aws_state, self.detector, self.restore_cert_sha256, self.db_attestation = aws_state, detector, restore_cert_sha256, db_attestation
        self.alerts: list[tuple[str, str]] = []
        self.fence_result: dict | None = None
        self._store_checked = False
        self.verified_backup: tuple | None = None
        self._began = False
        self._last_renew = clock.now()
        self.calls: dict[str, int] = {}
        clock.listeners.append(self._on_tick)
        # el cambio de DNS actualiza el registro de promoción (los callbacks los llama dns_apply)
        dns.on_applied = lambda changed: self._ledger(PromotionLedger.PROMOTED)
        dns.on_uncertain = lambda why: self._ledger(PromotionLedger.UNCERTAIN_DNS)
        dns.on_rejected = lambda: self._ledger(PromotionLedger.DNS_REJECTED)

    # ---------------------------------------------------------------- reloj (bucle de eventos local: renueva el lease del standby mientras el orquestador espera)
    def now(self) -> float:
        return self.clock.now()

    def sleep(self, s: float) -> None:
        end = self.clock.now() + s
        while self.clock.now() < end - 1e-9:
            self.clock.advance(min(self.step_s, end - self.clock.now()))

    def _on_tick(self, t: float) -> None:
        """Guardián del standby (como el hilo de la compuerta real): renueva el lease mientras lo retiene, independientemente de qué hilo avance el reloj."""
        if self.standby.holds_lease_object() and t - self._last_renew >= self.lease.config.renew_interval_s:
            self._last_renew = t
            self.standby.keeper_step()
        for h in self.tick_hooks:
            h(t)

    # ---------------------------------------------------------------- registro
    def _count(self, name):
        self.calls[name] = self.calls.get(name, 0) + 1

    def _ledger(self, state):
        try:
            self.ledger.advance(self.run_id, state, self.lease.epoch if state == PromotionLedger.WRITER_ENABLED else None)
        except LedgerError:
            pass

    def _verify_store(self) -> bool:
        """Repite la autoprueba de semántica condicional (si hay verificador) y fija `verified` en el almacén: un servicio que deja de respetar las condiciones se rechaza."""
        if self.store_verifier is None:
            return bool(getattr(self.lease.store, "verified", False))
        try:
            ok = bool(self.store_verifier())
        except Exception:  # noqa: BLE001
            ok = False
        self.lease.store.verified = ok
        return ok

    # ---------------------------------------------------------------- contrato del orquestador
    def precheck(self) -> dict:
        def safe(fn):
            try:
                return bool(fn())
            except Exception:  # noqa: BLE001 — cualquier error de una comprobación es «no cumplida» (falla cerrado)
                return False
        def store_ok():
            if not self._verify_store():
                return False
            self.lease.store.read()
            return True
        def standby_idle():
            if self.standby.promote_permitted() or self.standby.writes_permitted():
                return False
            if self.standby_gate_url:                                    # además, lo que el propio standby declara por HTTP: debe estar vallado (sin lease)
                return ap.gate_status(self.standby_gate_url, allow_http_localhost=self.allow_http_localhost) == "vallado"
            return not self.lease.is_valid()
        def rpo_reachable():
            return ap.peek_backup_meets_rpo(self.oci["reader"], now=self.wall_now(), max_age_s=self.max_backup_age_s, signer_pub=self.oci["signer_pub"], env=self.oci["env"])["ok"]
        def restore_possible():
            k = Path(self.oci["key"])
            drill = HERE.parent / "restore-drill.sh"
            pin = self.oci["passin"]
            var_ok = (not pin.startswith("env:")) or pin[4:] in (self.oci["restore_env"] or os.environ)
            return k.is_file() and os.access(drill, os.X_OK) and var_ok and bool(self.oci["signer_pub"])
        def no_external_writers():
            rep = self.external_writers_check()
            return rep.get("bloquea") is False and (rep.get("visibilidad") == "completa" or self.allow_partial_visibility)
        extra = {"sin_escritores_externos": safe(no_external_writers)} if self.external_writers_check is not None else {}
        return {
            **extra,
            "almacen_verificado": safe(store_ok),
            "dns_en_lista_blanca": safe(self.dns.validate),
            "sondas_configuradas": safe(lambda: len(self.probes.probes) >= self.min_probes),
            "standby_responde": safe(lambda: self.standby_health is not None and self.standby_health.run() is True),
            "standby_no_habilitado_para_escribir": safe(standby_idle),
            "rpo_alcanzable": safe(rpo_reachable),
            "restauracion_posible": safe(restore_possible),
            "sin_promocion_previa": safe(lambda: self.ledger.state() == PromotionLedger.NONE),
        }

    def probe_all(self) -> list:
        self._count("probe_all")
        return self.probes.probe_all()

    def restore_latest(self) -> dict:
        self._count("restore_latest")
        r = oc.restore_latest_from_oci(self.oci["reader"], self.oci["key"], self.oci["passin"], now=self.wall_now(), env=self.oci["env"], max_age_s=self.max_backup_age_s,
                                       signer_pub=self.oci["signer_pub"], mode=self.oci["mode"], restore_env=self.oci["restore_env"],
                                       expect_cert_sha256=self.restore_cert_sha256)
        ok = bool(r.get("fingerprint_ok")) and r.get("backup_age_s", 1e12) <= self.max_backup_age_s
        self.verified_backup = (r.get("backup"), r.get("backup_age_s")) if ok else None
        return r

    def lease_acquire(self) -> tuple:
        self._count("lease_acquire")
        if self.verified_backup is None:                                   # defensa en profundidad: sin respaldo verificado ni siquiera se intenta tomar el lease
            return (False, "respaldo no verificado: no se toma el lease", None, 0.0)
        if not self._store_checked:
            if not self._verify_store():
                return (False, "el almacén del lease no pasó la autoprueba de condiciones: no se toma el lease", None, 1.0)
            self._store_checked = True
        if not self._began:
            try:
                if not self.ledger.begin(self.run_id):
                    return (False, "otra promoción está en curso o ya ocurrió (registro de promoción)", None, 1.0)
            except LedgerError:
                return (False, "registro de promoción ilegible", None, 1.0)
            self._began = True
        r = self.lease.acquire()
        if r.ok:
            self._last_renew = self.clock.now()
            return (True, r.reason, self.lease.epoch, 0.0)
        return (False, r.reason, None, r.wait_s)

    def lease_release(self) -> None:
        self._count("lease_release")
        was_enabled = self.standby.promote_permitted()
        self.standby.disable()
        try:
            self.lease.release()
        finally:
            if self._began and not was_enabled:
                self._ledger(PromotionLedger.NONE)                        # aborto limpio: aún no había escritor

    def enable_standby(self, epoch: int) -> None:
        self._count("enable_standby")
        if self.verified_backup is None:
            raise Abort("no se habilita el standby: el respaldo no está verificado", "sin escritor")
        if not self.lease.is_valid() or self.lease.epoch != epoch:
            raise Abort("no se habilita el standby: el lease no es válido o es de otra época", "sin escritor")
        if self.ledger.read().get("run_id") != self.run_id or self.ledger.state() != PromotionLedger.IN_PROGRESS:
            raise Abort("no se habilita el standby: el registro de promoción no pertenece a esta ejecución", "sin escritor")
        if self.primary_db_fence is not None:             # vallado EXTERNO de la base del primario (lo hace cumplir el servidor); complementa al lease
            try:
                self.fence_result = {"confirmado": True, **(self.primary_db_fence() or {})}
            except Exception as e:  # noqa: BLE001
                self.fence_result = {"confirmado": False, "error": type(e).__name__}
            if not self.fence_result["confirmado"] and self.require_primary_db_fence:
                raise Abort("no se pudo vallar la base del primario y el vallado es obligatorio: no se habilita el standby", "sin escritor")
        try:
            self.standby.enable(epoch)
        except (FencedOut, FileExistsError, OSError) as e:
            self.standby.disable()
            raise Abort(f"no se pudo habilitar el standby ({type(e).__name__})", "sin escritor")
        self._ledger(PromotionLedger.WRITER_ENABLED)

    def standby_status(self) -> dict:
        s = self.standby.status()
        return {"holds_lease": s["holds_lease"], "epoch": s["epoch"], "writes_permitted": self.standby.writes_permitted(), "fence_epoch": s["fence_epoch"],
                "primary_db_fence": (self.fence_result or {}).get("confirmado")}

    def dns_plan(self) -> dict:
        return self.dns.dns_plan()

    def dns_apply(self) -> dict:
        self._count("dns_apply")
        return self.dns.dns_apply()

    def probe_new_endpoint(self) -> bool:
        return bool(self.dns.verify_points_to_target() and self.standby_health is not None and self.standby_health.run() is True)

    def synthetic_write_ok(self) -> bool:
        try:
            self.standby.write(f"synthetic:{self.run_id}")
            return True
        except (FencedOut, OSError, Exception):  # noqa: BLE001
            return False

    def old_can_write(self):
        if not self.primary_gate_url:
            return None
        r = ap.gate_status(self.primary_gate_url, allow_http_localhost=self.allow_http_localhost)
        return {"escribe": True, "vallado": False}.get(r)

    def incident(self):
        return self.detector.observe() if self.detector is not None else None

    def fencing_assessment(self) -> dict:
        """Evidencia de que el primario no puede escribir (evidence.assess_fencing): compuerta, estado de la EC2 en AWS (solo lectura), vallado de la BD y, si el primario es inalcanzable, lease tomado + atestación."""
        from evidence import assess_fencing
        gate = ap.gate_status(self.primary_gate_url, allow_http_localhost=self.allow_http_localhost) if self.primary_gate_url else None
        try:
            aws = self.aws_state() if callable(self.aws_state) else (self.aws_state.read() if self.aws_state is not None else None)
        except Exception:  # noqa: BLE001
            aws = None
        if self.fence_result is None and self.primary_db_fence is not None:   # el vallado de la base del primario se intenta ANTES de decidir (idempotente; enable_standby lo repite)
            try:
                self.fence_result = {"confirmado": True, **(self.primary_db_fence() or {})}
            except Exception as e:  # noqa: BLE001
                self.fence_result = {"confirmado": False, "error": type(e).__name__}
        dbf = (self.fence_result or {}).get("confirmado") if self.fence_result else None
        try:
            att = self.db_attestation() if callable(self.db_attestation) else self.db_attestation
        except Exception:  # noqa: BLE001
            att = None
        strong = None
        if getattr(self, "require_strong_fence", False):
            sf = getattr(self, "strong_fence", None)
            strong = sf.establish() if sf is not None else {"strong": False, "classification": "UNREACHABLE", "insufficient": ["puerta de promoción fuerte no configurada"]}
            self.strong_result = strong
        return assess_fencing(gate=gate, aws=aws, db_fence=dbf, gate_attested=self.primary_gate_attested(), lease_held=self.lease.is_valid(),
                              db_attested=bool(isinstance(att, dict) and att.get("ok") is True), strong=strong, require_strong=bool(getattr(self, "require_strong_fence", False)))

    def seal_primary(self, epoch: int) -> dict:
        if self.sealer is None:
            return {"sellado": False}
        self.sealer(epoch)
        return {"sellado": True}

    def primary_gate_attested(self):
        v = self._gate_attested() if callable(self._gate_attested) else self._gate_attested
        return v if isinstance(v, bool) else None

    def standby_readiness(self) -> dict:
        out = {}
        for k in ("livez", "ready", "api"):
            p = self.standby_readiness_probes.get(k)
            try:
                out[k] = bool(p is not None and p.run() is True)
            except Exception:  # noqa: BLE001 — cualquier error de sonda = no listo
                out[k] = False
        return out

    def alert(self, severity: str, message: str) -> None:
        self.alerts.append((severity, message))

    # ---------------------------------------------------------------- conclusión de una ejecución
    def finalize(self, result: dict) -> None:
        """Concilia el registro tras la ejecución: un aborto sin escritor habilitado devuelve el registro a NONE (otra ejecución puede intentarlo);
        cualquier estado con escritor habilitado queda bloqueado hasta que una PERSONA lo libere (PromotionLedger.clear)."""
        if result.get("outcome") == "ABORTED" and self._began and self.ledger.state() == PromotionLedger.IN_PROGRESS:
            self.standby.disable()                            # aborto sin escritor habilitado: no se deja un lease retenido por una ejecución abortada
            try:
                self.lease.release()
            except Exception:  # noqa: BLE001
                pass
            self._ledger(PromotionLedger.NONE)


def write_last_run(status_dir, result: dict, origen: str, modo: str = "FAILOVER_AUTOMATICO") -> None:
    """Escribe `last-run.json` (0600, reemplazo atómico) para el panel de operación: solo campos permitidos, sin secretos. `origen`: local | simulado | cloud_verificado."""
    if origen not in ("local", "simulado", "cloud_verificado"):
        raise ValueError("origen inválido")
    d = Path(status_dir); d.mkdir(parents=True, exist_ok=True, mode=0o700)
    data = {"outcome": result.get("outcome"), "safe_state": str(result.get("safe_state") or "")[:160], "abort_reason": str(result.get("abort_reason") or "")[:200], "origen": origen,
            "timeline": [[t[0], t[1]] for t in result.get("timeline", []) if isinstance(t, list) and len(t) == 2], "epoch": result.get("epoch"),
            "modo": modo if modo in ("RECUPERACION_DESDE_RESPALDO", "STANDBY_PREPARADO", "FAILOVER_AUTOMATICO", "FAILBACK") else "FAILOVER_AUTOMATICO",
            "incident": ({"kind": str((result.get("incident") or {}).get("kind"))[:24], "promotable": bool((result.get("incident") or {}).get("promotable")),
                          "reasons": [str(x)[:140] for x in ((result.get("incident") or {}).get("reasons") or [])[:3]],
                          "signals": {str(k)[:16]: (v if isinstance(v, (bool, str)) or v is None else str(v))[:24] if isinstance(v, str) else v for k, v in ((result.get("incident") or {}).get("signals") or {}).items()}}
                         if result.get("incident") else None),
            "fencing": ({"verdict": str((result.get("fencing") or {}).get("verdict"))[:12],
                         "evidence": [{"kind": str(e.get("kind"))[:24], "strength": str(e.get("strength"))[:10], "detail": str(e.get("detail"))[:120]} for e in ((result.get("fencing") or {}).get("evidence") or [])[:6]]}
                        if result.get("fencing") else None),
            "alerts": [{"severity": str(a.get("severity"))[:12], "message": str(a.get("message"))[:160]} for a in (result.get("alerts") or [])[:5] if isinstance(a, dict)]}
    tmp = d / "last-run.json.tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(data, f)
    os.replace(tmp, d / "last-run.json")


def run_failover(adapters: FullRecoveryAdapters, cfg: Config, state: State, dry_run: bool = False, status_dir=None, origen: str = "simulado") -> dict:
    """Ejecuta el orquestador existente (máquina de estados intacta) con los adaptadores completos y concilia el registro al terminar. Con `status_dir` deja `last-run.json` para el panel."""
    res = Orchestrator(adapters, cfg, state, dry_run=dry_run).run()
    adapters.finalize(res)
    if status_dir is not None:
        write_last_run(status_dir, res, origen)
    return res
