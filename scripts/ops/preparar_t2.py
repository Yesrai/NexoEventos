#!/usr/bin/env python3
"""Asistente para preparar T2 EN TU TERMINAL (el token y las IP NO pasan por el chat). Crea work/dns-switch/{config-prueba.json,token} con permisos 0600/0700.
  1) IP «a» = la IP con la que el subdominio responde HOY (consulta DNS de solo lectura a 1.1.1.1/8.8.8.8/9.9.9.9; deben coincidir). 2) IP «b» = una IP PÚBLICA distinta que escribes tú
  (debe ser IPv4 global: las IP de documentación y las privadas se rechazan; recomendado: la IP pública estática de tu VM de Azure, que es tuya y no recibe tráfico de T2).
  3) Token de DuckDNS: se pide sin eco. No se imprime nunca. No hace ningún cambio en DuckDNS."""
import getpass, json, os, re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "multicloud"))
import dns_switch as DS  # noqa: E402


def main():
    dom = (sys.argv[1] if len(sys.argv) > 1 else "nexoeventos-test")
    if dom in ("nexoeventos-demo",) or not dom.startswith("nexoeventos-test") or not DS.DOMAIN_RE.match(dom):
        print("El subdominio de pruebas debe llamarse nexoeventos-test…; nunca el de producción."); return 2
    d = ROOT / "work" / "dns-switch"; d.mkdir(parents=True, exist_ok=True); os.chmod(d, 0o700)
    seen = {}
    for srv in DS.DEFAULT_RESOLVERS:
        try: seen[srv] = tuple(sorted(DS.udp_resolver(f"{dom}.duckdns.org", srv)[0]))
        except Exception: seen[srv] = ()
    ans = {v for v in seen.values() if v}
    if len(ans) != 1 or not list(ans)[0]:
        print(f"{dom}.duckdns.org no responde de forma coherente en los 3 resolvedores. Crea el subdominio en DuckDNS apuntando a una IP tuya y espera ~1 min."); return 2
    a_ip = DS.validate_public_ipv4(list(ans)[0][0])
    b_ip = DS.validate_public_ipv4(input("IP pública «b» (distinta de «a»; p. ej. la IP estática de tu VM de Azure): ").strip())
    if b_ip == a_ip: print("«b» debe ser distinta de «a»."); return 2
    tok = getpass.getpass("Token de DuckDNS (no se muestra): ").strip()
    if not re.fullmatch(r"[A-Za-z0-9-]{8,64}", tok): print("Token con formato inválido."); return 2
    cfg = {"allowed_domains": [dom], "allowed_targets": {"a": a_ip, "b": b_ip}, "assumed_ttl_s": 60, "min_interval_s": 300, "resolvers": list(DS.DEFAULT_RESOLVERS), "state_dir": "work/dns-switch"}
    for name, content in (("config-prueba.json", json.dumps(cfg, indent=1)), ("token", tok)):
        fd = os.open(d / name, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as fh: fh.write(content)
    print(f"Listo: {d}/config-prueba.json y {d}/token (0600). El dominio parte de «a» y T2 lo llevará a «b» y de vuelta. Siguiente: backend/.venv/bin/python scripts/ops/ejecutar_t2.py (modo plan, solo lectura).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
