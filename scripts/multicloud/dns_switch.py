#!/usr/bin/env python3
"""B-12 · Cambio de DNS (DuckDNS) PREPARADO, no ejecutado por defecto. Solo biblioteca estándar.

Subcomandos:  plan (solo informa)  ·  apply (cambia)  ·  rollback (vuelve a la IP anterior)  ·  verify (espera la propagación).
`plan` y `verify` NO modifican nada. `apply`/`rollback` solo modifican con TODAS estas condiciones a la vez:
  1) NEXO_ALLOW_DNS_CHANGE=YES en el entorno; 2) --confirm con la frase EXACTA («CAMBIAR DNS <dominio> A <ip>» / «REVERTIR DNS <dominio> A <ip>»);
  3) el dominio y el DESTINO figuran en la lista blanca del archivo de configuración (no se admiten IP escritas a mano); 4) la IP es pública, IPv4 y válida;
  5) pasó el intervalo mínimo desde el último cambio (salvo --force-interval, y nunca en apply sin motivo); 6) nadie más está cambiando (bloqueo de archivo).
El token de DuckDNS se lee de DUCKDNS_TOKEN o de --token-file (permisos 0600); nunca se imprime, no va en el estado ni en el registro de auditoría.
Antes de cambiar se guarda la IP anterior (estado) para poder revertir. Tras cambiar se espera la propagación consultando varios resolvedores (UDP/53, solo lectura).
Códigos de salida: 0 correcto · 1 propagación incompleta · 2 parámetros/configuración/seguridad · 3 intervalo mínimo · 4 el proveedor rechazó o falló (el estado no cambia) · 5 bloqueado por otro cambio.
"""
from __future__ import annotations

import argparse
import fcntl
import ipaddress
import json
import os
import re
import socket
import struct
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_RESOLVERS = ("1.1.1.1", "8.8.8.8", "9.9.9.9")
DOMAIN_RE = re.compile(r"^[a-z0-9-]{1,63}$")
API_BASE = "https://www.duckdns.org"


class Refused(Exception):
    def __init__(self, msg, code=2):
        super().__init__(msg); self.code = code


# ---------------------------------------------------------------- validación
def validate_public_ipv4(text: str) -> str:
    if not isinstance(text, str) or text != text.strip():
        raise Refused(f"IP inválida: «{text!r}»")
    try:
        ip = ipaddress.IPv4Address(text)
    except ValueError:
        raise Refused(f"IP inválida (se exige IPv4 con formato estricto): «{text}»")
    if not ip.is_global or ip.is_multicast or ip.is_loopback or ip.is_link_local or ip.is_private or ip.is_reserved or ip.is_unspecified:
        raise Refused(f"IP no pública o reservada: {ip}")
    return str(ip)


def load_config(path: str) -> dict:
    try:
        cfg = json.loads(Path(path).read_text())
    except (OSError, ValueError) as e:
        raise Refused(f"no se pudo leer la configuración: {type(e).__name__}")
    doms = cfg.get("allowed_domains")
    tg = cfg.get("allowed_targets")
    if not isinstance(doms, list) or not doms or not all(isinstance(d, str) and DOMAIN_RE.match(d) for d in doms):
        raise Refused("configuración: allowed_domains debe ser una lista de subdominios de DuckDNS válidos")
    if not isinstance(tg, dict) or not tg:
        raise Refused("configuración: allowed_targets debe mapear etiqueta → IP pública")
    cfg["allowed_targets"] = {k: validate_public_ipv4(v) for k, v in tg.items()}      # una IP inválida en la lista blanca se detecta ANTES de usarla
    cfg.setdefault("assumed_ttl_s", 60); cfg.setdefault("min_interval_s", 300); cfg.setdefault("resolvers", list(DEFAULT_RESOLVERS))
    cfg.setdefault("state_dir", "work/dns-switch")
    return cfg


# ---------------------------------------------------------------- DNS (consulta A, solo lectura)
def build_query(name: str, qid: int = 0x1234) -> bytes:
    hdr = struct.pack(">HHHHHH", qid, 0x0100, 1, 0, 0, 0)
    q = b"".join(bytes([len(p)]) + p.encode() for p in name.rstrip(".").split(".")) + b"\x00"
    return hdr + q + struct.pack(">HH", 1, 1)


def _skip_name(data, off):
    while True:
        if off >= len(data): raise ValueError("paquete truncado")
        l = data[off]
        if l == 0: return off + 1
        if l & 0xC0 == 0xC0: return off + 2
        off += 1 + l


def parse_response(data: bytes, qid: int = 0x1234) -> tuple[list[str], int | None]:
    if len(data) < 12: raise ValueError("respuesta demasiado corta")
    rid, flags, qd, an, _, _ = struct.unpack(">HHHHHH", data[:12])
    if rid != qid: raise ValueError("id de consulta distinto")
    if flags & 0x000F: raise ValueError(f"código de error DNS {flags & 0xF}")
    off = 12
    for _ in range(qd): off = _skip_name(data, off) + 4
    ips, ttls = [], []
    for _ in range(an):
        off = _skip_name(data, off)
        if off + 10 > len(data): raise ValueError("registro truncado")
        rtype, _, ttl, rdlen = struct.unpack(">HHIH", data[off:off + 10]); off += 10
        if off + rdlen > len(data): raise ValueError("rdata truncado")
        if rtype == 1 and rdlen == 4:
            ips.append(socket.inet_ntoa(data[off:off + 4])); ttls.append(ttl)
        off += rdlen
    return ips, (min(ttls) if ttls else None)


def udp_resolver(name: str, server: str, timeout: float = 3.0) -> tuple[list[str], int | None]:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.settimeout(timeout)
    try:
        s.sendto(build_query(name), (server, 53)); data, _ = s.recvfrom(2048)
        return parse_response(data)
    finally:
        s.close()


# ---------------------------------------------------------------- estado y auditoría
class State:
    def __init__(self, directory: str, domain: str):
        self.dir = Path(directory); self.dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = self.dir / f"{domain}.json"; self.audit = self.dir / f"{domain}.audit.jsonl"; self.lock_path = self.dir / f"{domain}.lock"
        self._fd = None

    def lock(self):
        self._fd = os.open(self.lock_path, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(self._fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(self._fd); self._fd = None
            raise Refused("otro cambio de DNS está en curso (bloqueo)", 5)

    def unlock(self):
        if self._fd is not None:
            os.close(self._fd); self._fd = None

    def load(self) -> dict:
        try:
            return json.loads(self.path.read_text())
        except (OSError, ValueError):
            return {}

    def save(self, data: dict):
        tmp = self.path.with_suffix(".tmp"); tmp.write_text(json.dumps(data, indent=1)); os.chmod(tmp, 0o600); os.replace(tmp, self.path)

    def log(self, **entry):
        entry["utc"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with open(self.audit, "a") as f: f.write(json.dumps(entry, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------- proveedor
def read_token(args) -> str:
    if args.token_file:
        p = Path(args.token_file)
        if not p.is_file() or (p.stat().st_mode & 0o077):
            raise Refused("el archivo del token debe existir con permisos 0600")
        tok = p.read_text().strip()
    else:
        tok = os.environ.get("DUCKDNS_TOKEN", "").strip()
    if not re.fullmatch(r"[A-Za-z0-9-]{8,64}", tok or ""):
        raise Refused("falta un token de DuckDNS válido (DUCKDNS_TOKEN o --token-file)")
    return tok


def duckdns_update(domain: str, ip: str, token: str, api_base: str, opener=None, timeout=10) -> None:
    url = f"{api_base}/update?" + urllib.parse.urlencode({"domains": domain, "token": token, "ip": ip, "verbose": "true"})
    try:
        with (opener or urllib.request.urlopen)(url, timeout=timeout) as r:
            body = r.read(200).decode("utf-8", "replace")
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise Refused(f"DuckDNS no respondió ({type(e).__name__}); el estado NO cambió", 4)
    first = body.strip().splitlines()[0] if body.strip() else ""
    if first != "OK":
        raise Refused("DuckDNS rechazó la actualización (KO); el estado NO cambió", 4)


# ---------------------------------------------------------------- operaciones
def current_ip(domain, cfg, resolver):
    seen = {}
    for srv in cfg["resolvers"]:
        try:
            ips, ttl = resolver(f"{domain}.duckdns.org", srv)
            seen[srv] = (sorted(ips), ttl)
        except Exception as e:
            seen[srv] = ([], None)
    answers = {tuple(v[0]) for v in seen.values() if v[0]}
    return (list(answers.pop())[0] if len(answers) == 1 and list(answers)[0] else None), seen


def wait_propagation(domain, cfg, resolver, expect, timeout_s, interval_s, sleep=time.sleep, clock=time.monotonic):
    t0 = clock(); stale = {}
    while True:
        stale, ttl_seen = {}, []
        for srv in cfg["resolvers"]:
            try:
                ips, ttl = resolver(f"{domain}.duckdns.org", srv)
            except Exception:
                ips, ttl = [], None
            if ttl is not None: ttl_seen.append(ttl)
            if expect not in ips: stale[srv] = ips
        if not stale:
            return True, clock() - t0, stale, max(ttl_seen or [0])
        if clock() - t0 >= timeout_s:
            return False, clock() - t0, stale, max(ttl_seen or [0])
        sleep(interval_s)


def expected_phrase(action: str, domain: str, ip: str) -> str:
    return f"{'CAMBIAR' if action == 'apply' else 'REVERTIR'} DNS {domain} A {ip}"


def run(args, resolver, opener, sleep, clock, out) -> int:
    cfg = load_config(args.config)
    domain = args.domain
    if not DOMAIN_RE.match(domain or ""):
        raise Refused("dominio inválido")
    if domain not in cfg["allowed_domains"]:
        raise Refused(f"el dominio «{domain}» no está en la lista blanca")
    st = State(args.state_dir or cfg["state_dir"], domain); state = st.load()
    ttl_assumed = cfg["assumed_ttl_s"]
    if args.cmd == "verify":
        ip = validate_public_ipv4(args.expect_ip)
        ok, took, stale, ttl = wait_propagation(domain, cfg, resolver, ip, args.timeout, args.interval, sleep, clock)
        print(f"{'OK' if ok else 'INCOMPLETO'}: propagación de {domain}.duckdns.org → {ip} en {took:.1f} s (TTL observado {ttl} s, supuesto {ttl_assumed} s)" + ("" if ok else f"; resolvedores sin actualizar: {sorted(stale)}"), file=out)
        return 0 if ok else 1
    # destino
    if args.cmd == "rollback":
        prev = state.get("previous_ip")
        if not prev: raise Refused("no hay IP anterior registrada: no se puede revertir")
        target_ip, target_label = validate_public_ipv4(prev), "anterior"
    else:
        if args.target not in cfg["allowed_targets"]:
            raise Refused(f"destino «{args.target}» no está en la lista blanca (permitidos: {', '.join(sorted(cfg['allowed_targets']))})")
        target_ip, target_label = cfg["allowed_targets"][args.target], args.target
    if args.cmd in ("apply", "rollback") and os.environ.get("NEXO_ALLOW_DNS_CHANGE") != "YES":
        raise Refused("falta NEXO_ALLOW_DNS_CHANGE=YES (protección contra cambios accidentales; se comprueba ANTES de cualquier consulta de red)")
    cur, seen = current_ip(domain, cfg, resolver)
    print(f"Dominio: {domain}.duckdns.org · IP actual (resolvedores): {cur or 'indeterminada/discrepante'} · destino «{target_label}»: {target_ip}", file=out)
    print(f"TTL supuesto: {ttl_assumed} s → los clientes pueden tardar hasta ese tiempo en ver el cambio (parte del RTO).", file=out)
    if args.cmd == "plan":
        print("PLAN (no se cambió nada). Para ejecutar: NEXO_ALLOW_DNS_CHANGE=YES … apply --confirm \"" + expected_phrase('apply', domain, target_ip) + "\"", file=out)
        return 0
    # apply / rollback: todas las salvaguardas
    if os.environ.get("NEXO_ALLOW_DNS_CHANGE") != "YES":
        raise Refused("falta NEXO_ALLOW_DNS_CHANGE=YES (protección contra cambios accidentales)")
    want = expected_phrase(args.cmd, domain, target_ip)
    if args.confirm != want:
        raise Refused(f"confirmación incorrecta: se exige exactamente «{want}»")
    if cur == target_ip and args.cmd == "apply":
        print("Sin cambios: el dominio ya apunta a ese destino.", file=out); return 0
    last = state.get("last_change_epoch")
    if args.cmd == "apply" and last and not args.force_interval and (time.time() - last) < cfg["min_interval_s"]:
        raise Refused(f"intervalo mínimo no cumplido ({cfg['min_interval_s']} s desde el último cambio)", 3)
    token = read_token(args)
    st.lock()
    try:
        state = st.load()                                    # relectura bajo bloqueo
        previous = cur or state.get("current_ip_set")
        if args.cmd == "apply" and not previous:
            raise Refused("no se pudo determinar la IP actual: indica --previous-ip para poder revertir")
        duckdns_update(domain, target_ip, token, args.api_base, opener)
        new = dict(state)
        if args.cmd == "apply":
            new.update(previous_ip=previous or args.previous_ip, current_ip_set=target_ip, last_change_epoch=time.time())
        else:
            new.update(current_ip_set=target_ip, last_change_epoch=time.time(), previous_ip=None)
        st.save(new); st.log(action=args.cmd, domain=domain, from_ip=previous, to_ip=target_ip, label=target_label)
    finally:
        st.unlock()
    ok, took, stale, ttl = wait_propagation(domain, cfg, resolver, target_ip, args.timeout, args.interval, sleep, clock)
    print(f"{'OK' if ok else 'INCOMPLETO'}: {args.cmd} → {target_ip}; propagación en {took:.1f} s" + ("" if ok else f"; sin actualizar: {sorted(stale)}"), file=out)
    return 0 if ok else 1


def main(argv=None, resolver=udp_resolver, opener=None, sleep=time.sleep, clock=time.monotonic, out=sys.stdout) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("cmd", choices=["plan", "apply", "rollback", "verify"])
    ap.add_argument("--config", required=True); ap.add_argument("--domain", required=True)
    ap.add_argument("--target"); ap.add_argument("--confirm"); ap.add_argument("--expect-ip"); ap.add_argument("--previous-ip")
    ap.add_argument("--token-file"); ap.add_argument("--state-dir")
    ap.add_argument("--timeout", type=float, default=180); ap.add_argument("--interval", type=float, default=5)
    ap.add_argument("--force-interval", action="store_true"); ap.add_argument("--api-base", default=API_BASE)
    a = ap.parse_args(argv)
    try:
        if a.api_base != API_BASE and os.environ.get("NEXO_DNS_TEST") != "1":
            raise Refused("--api-base solo se admite en pruebas (NEXO_DNS_TEST=1): el proveedor es siempre https://www.duckdns.org")
        if a.previous_ip: a.previous_ip = validate_public_ipv4(a.previous_ip)
        return run(a, resolver, opener, sleep, clock, out)
    except Refused as e:
        print(f"RECHAZADO: {e}", file=sys.stderr); return e.code


if __name__ == "__main__":
    sys.exit(main())
