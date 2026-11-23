"""FÁBRICA que conecta una configuración validada (`failover_config`) con `FullRecoveryAdapters`. Cierra la brecha G1: antes solo existían los adaptadores y la validación, no el paso entre ambos.

Diseño (sin red, sin nube, sin efectos):
  1. `build_adapters` EXIGE `failover_config.validate(cfg)` correcto: una configuración insegura nunca produce adaptadores (falla cerrado).
  2. Los argumentos DERIVABLES de la configuración se calculan en `derive_kwargs` (URL → sondas HTTPS, umbrales, banderas `require_*`, ruta de clave, huella del certificado…). Es una función pura.
  3. Lo que exige un extremo real (almacén del lease, servicio standby, registro de promoción, lector de OCI, estado de AWS, sello, vallado fuerte, atestación de la base, resolvedor/abridor de DNS)
     NO se fabrica aquí: lo entrega un PROVEEDOR inyectado. Si falta uno, se rechaza con el nombre del faltante.
  4. `mode="sim"` acepta proveedores simulados (pruebas). `mode="real"` está BLOQUEADO por `REAL_WIRING_ENABLED = False`: cablear los proveedores reales exige un cambio de código revisado, DESPUÉS
     de T1–T4 y con la autorización específica; el centro de operaciones (`REAL_EXECUTION_WIRED`) es una segunda barrera independiente.
`REAL_CONTRACT` documenta, proveedor por proveedor, qué debe construir la versión real y con qué permisos/conectividad (ver docs/operacion/auditoria-adaptadores-failover.md)."""
from __future__ import annotations

import os
import re
from pathlib import Path

import adapters_probes as ap
import failover_config as FC
from adapters_standby import FullRecoveryAdapters

REAL_WIRING_ENABLED = False

REQUIRED_PROVIDERS = ("clock", "lease", "standby", "ledger", "oci_reader", "dns_runtime", "aws_state", "db_attestation", "strong_fence", "sealer", "store_verifier")
OPTIONAL_PROVIDERS = ("primary_db_fence", "external_writers_check", "detector", "tick_hooks")

REAL_CONTRACT = {
    "clock": "reloj monótono real (no simulado) para el orquestador y el guardián del lease",
    "lease": "LeaseClient(ParHttpStore(lease.par_url_file), LeaseConfig(ttl, margen), holder='oci-standby', Ed25519Auth con la privada SOLO de este nodo y las públicas de los demás)",
    "standby": "StandbyService + fenced_db sobre el PostgreSQL de la VM de OCI (permiso de promoción, lease válido y época vigente EN LA BASE)",
    "ledger": "PromotionLedger en OPS_FAILOVER_DIR (archivo 0600; ledger.json que lee el centro de operaciones)",
    "oci_reader": "lector de Object Storage de OCI con perfil de LECTURA del bucket (inspect/read objects), recovery.object_prefix",
    "dns_runtime": "resolvedor (UDP/53: 1.1.1.1, 8.8.8.8, 9.9.9.9) y abridor HTTPS hacia DuckDNS; token en archivo 0600; NEXO_ALLOW_DNS_CHANGE=YES solo en el ejecutor humano",
    "aws_state": "solo lectura: ec2 describe-instances / rds describe-db-instances con las etiquetas de primary.aws; credenciales temporales del laboratorio",
    "db_attestation": "atestación ≤ primary.attestation_max_age_s de que la BASE del primario rechaza commits sin lease (vallado en la base)",
    "strong_fence": "promotion_gate: db_hard_fence y/o rds_stop_confirmed (rds:StopDBInstance solo si allow_stop_rds=true)",
    "sealer": "seal_log.make_sealer sobre el objeto de sello de OCI + testigo de frescura (primary.freshness_witness) con HttpWitnessClient(token_file, ca_file)",
    "store_verifier": "autoprueba If-Match/If-None-Match del almacén del lease (T1) antes de tomar el lease",
}


class WiringError(Exception):
    pass


class NotWired(WiringError):
    pass


def _g(d, *ks, default=None):
    for k in ks:
        if not isinstance(d, dict) or k not in d: return default
        d = d[k]
    return d


def derive_kwargs(cfg: dict, *, env=None, allow_http_localhost: bool = False, check_files: bool = True) -> dict:
    """Mapeo PURO configuración → argumentos de FullRecoveryAdapters que NO requieren un extremo real. No abre archivos ni conexiones."""
    env = os.environ if env is None else env
    p, s, r = cfg.get("primary") or {}, cfg.get("standby") or {}, cfg.get("recovery") or {}
    det = cfg.get("detector") or {}
    mk = lambda url, **kw: ap.HttpProbe(url, allow_http_localhost=allow_http_localhost, **kw)
    # G9: política TLS por extremo (certificado fijado y/o verify_as). El control (un tercer sitio) usa siempre las CA públicas.
    ptls = ap.TlsPolicy.from_config(p.get("tls"), check_files=check_files)
    stls = ap.TlsPolicy.from_config(s.get("tls"), check_files=check_files)
    probes = [mk(p["livez_url"], tls=ptls), mk(p["ready_url"], json_ok=lambda d: isinstance(d, dict), tls=ptls), mk(p["write_gate_url"], tls=ptls)]
    kw = dict(
        probes=ap.ProbeSet(probes, control=mk(p["control_url"])),
        min_probes=max(int(det.get("quorum", 2)), 2),
        standby_health=mk(s["api_url"], tls=stls),
        standby_readiness_probes={"livez": mk(s["livez_url"], tls=stls), "ready": mk(s["ready_url"], tls=stls), "api": mk(s["api_url"], tls=stls)},
        primary_tls=ptls, standby_tls=stls,
        primary_gate_url=p["write_gate_url"], standby_gate_url=s.get("write_gate_url") or s["livez_url"].rsplit("/", 1)[0] + "/write-gate",
        oci_key=Path(r["private_key_file"]) if r.get("private_key_file") else None,
        oci_passin="env:NEXO_RECOVERY_PASS" if r.get("key_provider") == "interactive_person" else "",
        signer_pub=Path(r["signer_pub"]), restore_cert_sha256=r["cert_sha256"], max_backup_age_s=float(r.get("max_backup_age_s", 3600)),
        require_primary_db_fence=(p.get("db_fence") == "require"), require_strong_fence=bool(_g(p, "strong_fence", "require")), require_seal=bool(_g(p, "seal", "require")),
        primary_gate_attested=bool(p.get("gate_attested")), allow_http_localhost=allow_http_localhost,
    )
    return kw


def build_adapters(cfg: dict, providers: dict, *, mode: str = "sim", run_id: str = "run-0", check_files: bool = True, env=None, allow_http_localhost: bool = False) -> FullRecoveryAdapters:
    if mode == "real" and not REAL_WIRING_ENABLED:
        raise NotWired("mode='real' está BLOQUEADO (REAL_WIRING_ENABLED=False): requiere un cambio de código revisado y la autorización específica de la propietaria")
    if mode not in ("sim", "real"):
        raise WiringError("mode debe ser 'sim' o 'real'")
    v = FC.validate(cfg, check_files=check_files)
    if not v["ok"]:
        raise WiringError("configuración NO válida; no se construyen adaptadores: " + "; ".join(str(e)[:110] for e in v["errors"][:4]) + (" …" if len(v["errors"]) > 4 else ""))
    if cfg.get("automatic") is True:
        raise WiringError("automatic=true no está soportado por esta fábrica: la conmutación es CONTROLADA (humano presente)")
    missing = [n for n in REQUIRED_PROVIDERS if n not in providers or not callable(providers[n])]
    if missing:
        raise WiringError("faltan proveedores: " + ", ".join(missing) + " (cada uno entrega un extremo real o simulado; ver REAL_CONTRACT)")
    kw = derive_kwargs(cfg, env=env, allow_http_localhost=allow_http_localhost, check_files=check_files)
    built = {n: providers[n](cfg) for n in REQUIRED_PROVIDERS}
    for n in OPTIONAL_PROVIDERS:
        if n in providers and callable(providers[n]): built[n] = providers[n](cfg)
    kw.update(run_id=run_id, clock=built.pop("clock"), lease=built.pop("lease"), standby=built.pop("standby"), ledger=built.pop("ledger"), oci_reader=built.pop("oci_reader"),
              aws_state=built.pop("aws_state"), db_attestation=built.pop("db_attestation"), strong_fence=built.pop("strong_fence"), sealer=built.pop("sealer"), store_verifier=built.pop("store_verifier"))
    dns = built.pop("dns_runtime"); d = cfg.get("dns") or {}
    for k in ("domain", "target", "config_path", "token_file", "state_dir"):
        if not d.get(k) or not isinstance(d[k], str):
            raise WiringError(f"dns.{k}: obligatorio para construir el adaptador de DNS")
    if re.fullmatch(r"nexoeventos-demo", d["domain"]):
        raise WiringError("dns.domain: el dominio de producción no se admite en la conmutación de pruebas")
    from adapters_dns import DnsSwitchAdapter
    kw["dns"] = DnsSwitchAdapter(config_path=d["config_path"], domain=d["domain"], target=d["target"], token_file=d["token_file"], state_dir=d["state_dir"], resolver=dns["resolver"], opener=dns["opener"],
                                 allow_change=(d.get("mode") == "apply" and (env or os.environ).get("NEXO_ALLOW_DNS_CHANGE") == "YES"))
    if "primary_db_fence" in built: kw["primary_db_fence"] = built.pop("primary_db_fence")
    if "external_writers_check" in built: kw["external_writers_check"] = built.pop("external_writers_check")
    if "detector" in built: kw["detector"] = built.pop("detector")
    if "tick_hooks" in built: kw["tick_hooks"] = built.pop("tick_hooks")
    return FullRecoveryAdapters(**kw)
