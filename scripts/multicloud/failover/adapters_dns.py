"""Adaptador DNS del orquestador (B-12 ↔ B-13): envuelve `dns_switch.py` SIN modificarlo y traduce sus códigos de salida a las garantías del orquestador.

Contrato real de dns_switch.main(argv, resolver, opener, sleep, clock, out) -> código:
  0 correcto (cambió y propagó) · 1 el proveedor aceptó pero la propagación NO se confirmó · 2 rechazado (lista blanca, frase, NEXO_ALLOW_DNS_CHANGE, IP inválida)
  3 intervalo mínimo · 4 el proveedor falló (KO explícito o sin respuesta; «el estado NO cambió» solo es seguro en el caso KO) · 5 otro cambio en curso (bloqueo).
Política del adaptador (falla cerrado, sin segunda promoción):
  - plan: solo lee; clasifica el estado actual: ya_apunta_al_destino · requiere_cambio · indeterminado (resolvedores discrepantes o sin respuesta).
  - apply: indeterminado ⇒ NO cambia. Ya apunta ⇒ no hace nada (idempotente, sin operación duplicada). Sin autorización explícita (allow_change + NEXO_ALLOW_DNS_CHANGE=YES) ⇒ no cambia.
  - código 1, o código 4 sin respuesta del proveedor y sin evidencia en los resolvedores, o 5 ⇒ estado INCIERTO: se lanza Abort con safe_state que prohíbe repetir la promoción;
    el DNS puede haber cambiado o no, y el nuevo escritor YA está activo: decisión humana (el registro de promoción impide que otra ejecución automática promueva de nuevo).
  - código 4 con KO explícito ⇒ el DNS NO cambió con certeza; el nuevo escritor sigue activo (reintento manual).
  - un resolvedor/valor desconocido nunca se interpreta como «ya apunta al destino».
Todas las pruebas usan un API de DuckDNS y un resolvedor FALSOS; el adaptador nunca contacta al proveedor real salvo que se le pasen `opener`/`resolver` reales (no se hace aquí).
"""
from __future__ import annotations

import contextlib
import io
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import dns_switch as dsw  # noqa: E402
from orchestrator import Abort  # noqa: E402

SAFE_WRITER_ACTIVE_DNS_UNCERTAIN = "nuevo escritor activo; DNS INCIERTO: NO repetir la promoción; revisión humana (comprobar el DNS a mano antes de actuar)"
SAFE_WRITER_ACTIVE_DNS_UNCHANGED = "nuevo escritor activo; DNS SIN cambiar: el tráfico no llega al nuevo sitio; reintento manual del DNS (no promover de nuevo)"


class DnsSwitchAdapter:
    def __init__(self, *, config_path, domain: str, target: str, token_file, state_dir, resolver, opener, sleep=time.sleep, clock=time.monotonic,
                 timeout_s: float = 180.0, interval_s: float = 5.0, allow_change: bool = False, on_uncertain=None, on_rejected=None, on_applied=None):
        self.config_path, self.domain, self.target = str(config_path), domain, target
        self.token_file, self.state_dir = str(token_file), str(state_dir)
        self.resolver, self.opener, self.sleep, self.clock = resolver, opener, sleep, clock
        self.timeout_s, self.interval_s, self.allow_change = timeout_s, interval_s, allow_change
        self.on_uncertain, self.on_rejected, self.on_applied = on_uncertain, on_rejected, on_applied
        self.calls = {"plan": 0, "apply": 0}

    # ---------------------------------------------------------------- lectura / validación
    def _cfg_and_ip(self):
        try:
            cfg = dsw.load_config(self.config_path)
            if self.domain not in cfg["allowed_domains"]:
                raise dsw.Refused("dominio fuera de la lista blanca")
            if self.target not in cfg["allowed_targets"]:
                raise dsw.Refused("destino fuera de la lista blanca")
            return cfg, cfg["allowed_targets"][self.target]
        except dsw.Refused as e:
            raise ConfigInvalid(str(e))

    def validate(self) -> bool:
        """Para el precheck: configuración, lista blanca y token presentes y bien formados (sin imprimir nada)."""
        try:
            self._cfg_and_ip()
            p = Path(self.token_file)
            return p.is_file() and not (p.stat().st_mode & 0o077) and bool(p.read_text().strip())
        except (ConfigInvalid, OSError):
            return False

    def inspect(self) -> dict:
        cfg, ip = self._cfg_and_ip()
        cur, seen = dsw.current_ip(self.domain, cfg, self.resolver)
        answered = [s for s, v in seen.items() if v[0]]
        if cur is None:
            estado = "indeterminado"                     # discrepancia entre resolvedores o ninguno respondió
        elif cur == ip:
            estado = "ya_apunta_al_destino"
        else:
            estado = "requiere_cambio"
        return {"estado": estado, "ip_destino": ip, "ip_actual": cur, "resolvedores_con_respuesta": len(answered), "resolvedores": len(seen)}

    def dns_plan(self) -> dict:
        self.calls["plan"] += 1
        info = self.inspect()
        buf = io.StringIO()
        rc = dsw.main(["plan", "--config", self.config_path, "--domain", self.domain, "--target", self.target, "--state-dir", self.state_dir],
                      resolver=self.resolver, opener=self.opener, sleep=self.sleep, clock=self.clock, out=buf)
        if rc != 0:
            raise ConfigInvalid(f"dns_switch plan devolvió {rc}")
        return {"destino": self.target, "estado": info["estado"], "accion": {"ya_apunta_al_destino": "ninguna", "requiere_cambio": "cambiar", "indeterminado": "no cambiar (indeterminado)"}[info["estado"]]}

    def verify_points_to_target(self) -> bool:
        info = self.inspect()
        return info["estado"] == "ya_apunta_al_destino"

    # ---------------------------------------------------------------- cambio
    def _uncertain(self, why: str):
        if self.on_uncertain:
            self.on_uncertain(why)
        raise Abort(f"DNS en estado incierto ({why})", SAFE_WRITER_ACTIVE_DNS_UNCERTAIN)

    def dns_apply(self) -> dict:
        self.calls["apply"] += 1
        try:
            info = self.inspect()
        except ConfigInvalid as e:
            raise Abort(f"configuración DNS inválida ({e})", SAFE_WRITER_ACTIVE_DNS_UNCHANGED)
        if info["estado"] == "indeterminado":
            raise Abort("el DNS actual es indeterminado (resolvedores discrepantes o sin respuesta): no se cambia", SAFE_WRITER_ACTIVE_DNS_UNCHANGED)
        if info["estado"] == "ya_apunta_al_destino":
            if self.on_applied:
                self.on_applied(False)
            return {"cambio": False, "ya_apuntaba": True}                 # idempotente: ninguna operación duplicada
        if not self.allow_change or os.environ.get("NEXO_ALLOW_DNS_CHANGE") != "YES":
            raise Abort("cambio de DNS no autorizado (falta allow_change y/o NEXO_ALLOW_DNS_CHANGE=YES)", SAFE_WRITER_ACTIVE_DNS_UNCHANGED)
        phrase = dsw.expected_phrase("apply", self.domain, info["ip_destino"])
        out, err = io.StringIO(), io.StringIO()
        try:
            with contextlib.redirect_stderr(err):
                rc = dsw.main(["apply", "--config", self.config_path, "--domain", self.domain, "--target", self.target, "--confirm", phrase,
                               "--token-file", self.token_file, "--state-dir", self.state_dir, "--timeout", str(self.timeout_s), "--interval", str(self.interval_s)],
                              resolver=self.resolver, opener=self.opener, sleep=self.sleep, clock=self.clock, out=out)
        except Exception as e:  # noqa: BLE001 — un fallo inesperado a mitad de un apply es un estado incierto, no «sin cambios»
            self._uncertain(f"excepción inesperada {type(e).__name__}")
        msg = err.getvalue()
        if rc == 0:
            if self.verify_points_to_target():
                if self.on_applied:
                    self.on_applied(True)
                return {"cambio": True, "propagado": True}
            self._uncertain("dns_switch informó éxito pero los resolvedores no lo confirman")
        if rc == 1:
            self._uncertain("el proveedor aceptó el cambio pero la propagación no se confirmó")
        if rc == 4:
            if "rechazó" in msg:                                       # KO explícito del proveedor: seguro que no cambió
                if self.on_rejected:
                    self.on_rejected()
                raise Abort("el proveedor DNS rechazó la actualización (KO); el DNS no cambió", SAFE_WRITER_ACTIVE_DNS_UNCHANGED)
            try:                                                      # sin respuesta: puede haberse aplicado; se mira la evidencia
                if self.verify_points_to_target():
                    if self.on_applied:
                        self.on_applied(True)
                    return {"cambio": True, "propagado": True, "nota": "el proveedor no respondió pero los resolvedores muestran el destino"}
            except ConfigInvalid:
                pass
            self._uncertain("el proveedor no respondió y no hay evidencia de si aplicó el cambio")
        if rc == 5:
            self._uncertain("hay otro cambio de DNS en curso (bloqueo)")
        raise Abort(f"dns_switch rechazó el cambio (código {rc})", SAFE_WRITER_ACTIVE_DNS_UNCHANGED)


class ConfigInvalid(Exception):
    pass
