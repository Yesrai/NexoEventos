"""PROVEEDORES REALES (G1) para `real_factory.build_adapters`: cada función devuelve un `provider(cfg) -> objeto` que construye el extremo REAL (lease por PAR, ledger en disco, lector de OCI, estado de AWS
de solo lectura, atestación de la base, vallado fuerte, sello, autoprueba del almacén, DNS) a partir de la configuración validada y de las RUTAS de secretos que se entregan aparte (`paths`).

Garantías de diseño:
  * CONSTRUIR no abre conexiones ni cambia nada: la red solo se toca al USAR el objeto (lease.acquire, sonda, etc.). Los secretos (URL de los PAR, claves, tokens) se leen de archivos 0600 y nunca se imprimen.
  * Nada aquí habilita el modo real: `real_factory.REAL_WIRING_ENABLED` sigue en False y el centro de operaciones tiene su propia barrera (`REAL_EXECUTION_WIRED`). Estos proveedores se prueban en LOCAL con
    extremos simulados (tests/test_real_providers.py).
  * El apagado de la RDS solo se cablea si `primary.strong_fence.allow_stop_rds` es true; el cambio de DNS lo decide la fábrica (`dns.mode == apply` y NEXO_ALLOW_DNS_CHANGE=YES), no este módulo.
`paths` (todas absolutas, archivos 0600): own_private_key_file (Ed25519 de ESTE nodo, 32 bytes en hex), peer_public_files {holder: archivo con la pública en hex}, lease_state_path, state_dir,
selftest_par_url_file (PAR de PREFIJO para la autoprueba), attestation_par_url_file (PAR de un objeto: atestación del vallado en la base), seal_log_par_url_file (+ seal_log_prefix), ledger_path (opcional)."""
from __future__ import annotations

import stat
import sys
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[2] / "backend"))

from fenced_db import PromotionLedger  # noqa: E402

from app.failover import store as st  # noqa: E402
from app.failover.lease import Ed25519Auth, LeaseClient, LeaseConfig  # noqa: E402


class ProviderError(Exception):
    pass


def _secret_file(p, what: str) -> str:
    q = Path(str(p))
    if not q.is_absolute():
        raise ProviderError(f"{what}: la ruta debe ser absoluta")
    try:
        mode = q.stat().st_mode
    except OSError:
        raise ProviderError(f"{what}: archivo inexistente") from None
    if mode & (stat.S_IRWXG | stat.S_IRWXO):
        raise ProviderError(f"{what}: el archivo debe tener permisos 0600")
    return q.read_text().strip()


def _hex32(s: str, what: str) -> bytes:
    try:
        b = bytes.fromhex(s)
    except ValueError:
        raise ProviderError(f"{what}: no es hexadecimal") from None
    if len(b) != 32:
        raise ProviderError(f"{what}: debe ser de 32 bytes")
    return b


def _need(paths: dict, key: str):
    if not paths.get(key):
        raise ProviderError(f"falta paths.{key}")
    return paths[key]


class RealClock:
    """Reloj MONÓTONO real con la interfaz del orquestador: `advance(dt)` espera de verdad y avisa a los oyentes (guardián del lease) con el tiempo nuevo."""
    def __init__(self, mono=time.monotonic, sleep=time.sleep):
        self._mono, self._sleep, self._lock, self.listeners = mono, sleep, threading.Lock(), []

    def now(self) -> float:
        return self._mono()

    def advance(self, dt: float) -> None:
        if dt > 0:
            self._sleep(dt)
        t = self._mono()
        for l in list(self.listeners):
            l(t)


def clock_provider(*, mono=time.monotonic, sleep=time.sleep):
    return lambda cfg: RealClock(mono, sleep)


def lease_store_provider(paths: dict, *, allow_http_localhost=False, **kw):
    """Almacén del lease por PAR (If-Match / If-None-Match). La autoprueba la hace `store_verifier_provider`, no el constructor."""
    def build(cfg):
        return st.ParHttpStore(cfg["lease"]["par_url_file"], allow_http_localhost=allow_http_localhost, **kw)
    return build


def lease_provider(paths: dict, *, allow_http_localhost=False, holder="oci-standby", ttl_s=15.0, margin_s=5.0, mono=time.monotonic, epoch_reporter=None, head_provider=None, acquire_guard=None, **store_kw):
    def build(cfg):
        if (cfg.get("lease") or {}).get("auth") != "ed25519":
            raise ProviderError("lease.auth: el proveedor real solo admite ed25519 (sin secretos compartidos)")
        priv = _hex32(_secret_file(_need(paths, "own_private_key_file"), "clave privada del nodo"), "clave privada del nodo")
        peers = {h: _hex32(Path(str(f)).read_text().strip(), f"pública de {h}") for h, f in (paths.get("peer_public_files") or {}).items()}      # las públicas no son secretas
        if not peers:
            raise ProviderError("falta paths.peer_public_files (las públicas de los demás titulares)")
        store = lease_store_provider(paths, allow_http_localhost=allow_http_localhost, **store_kw)(cfg)
        return LeaseClient(store, LeaseConfig(ttl_s=ttl_s, margin_s=margin_s), holder_id=holder, mono=mono, authenticator=Ed25519Auth(holder, priv, peers),
                           state_path=str(_need(paths, "lease_state_path")), epoch_reporter=epoch_reporter, head_provider=head_provider, acquire_guard=acquire_guard)
    return build


def store_verifier_provider(paths: dict, *, allow_http_localhost=False, **store_kw):
    """Devuelve `verifier() -> bool`: ejecuta la autoprueba de semántica condicional contra objetos de prueba EXCLUSIVOS (no toca el objeto del lease). Exige un PAR de PREFIJO propio
    (`paths.selftest_par_url_file`, URL que acaba en «/»): el PAR del lease es de UN solo objeto y no permite crear los de prueba."""
    def build(cfg):
        import uuid
        par = _need(paths, "selftest_par_url_file")
        def verify() -> bool:
            rep = st.verify_store_semantics(lambda: st.ParHttpStore(par, object_name=f"writer-lease.json.selftest-{uuid.uuid4().hex[:8]}", allow_http_localhost=allow_http_localhost, **store_kw))
            return bool(rep) and all(rep.values())
        return verify
    return build


def ledger_provider(paths: dict):
    def build(cfg):
        p = paths.get("ledger_path") or (Path(_need(paths, "state_dir")) / "ledger.json")
        return PromotionLedger(p)
    return build


def oci_reader_provider(paths: dict | None = None, *, allow_http_localhost=False, **kw):
    """Lector del bucket de recuperación. Con `oci_reader_par_url_file` en `paths` usa un PAR de LECTURA (https, host oraclecloud.com); si no, la CLI de OCI con el perfil de la configuración."""
    def build(cfg):
        import oci_source as oc
        r = cfg["recovery"]
        par = (paths or {}).get("oci_reader_par_url_file")
        if par:
            return oc.ParHttpReader(par, prefix=r.get("object_prefix", ""), allow_http_localhost=allow_http_localhost, **kw)
        return oc.OciCliReader(namespace=(paths or {}).get("oci_namespace", ""), bucket=r["bucket"], profile=r["oci_profile"], prefix=r.get("object_prefix", ""), **kw)
    return build


def aws_state_provider(*, run=None, profile=None, region=None):
    """Estado de EC2/RDS del primario, SOLO LECTURA (describe-*). Cualquier error ⇒ desconocido (nunca «parado»). Devuelve el callable `read()`."""
    def build(cfg):
        import evidence as ev
        a = ((cfg.get("primary") or {}).get("aws")) or {}
        return ev.AwsState(instance_tag=a.get("instance_tag", "nexoeventos-academy-app"), db_id=a.get("db_id", "nexoeventos-academy-postgres"), run=run, profile=profile, region=region).read
    return build


def db_attestation_provider(paths: dict, *, allow_http_localhost=False, wall=time.time, **store_kw):
    """Lee la atestación (publicada por el guardián del primario) del vallado en la BASE: `() -> bool` según `primary.attestation_max_age_s`. Vencida, ausente o ilegible ⇒ False."""
    def build(cfg):
        from app.failover.pg_fence import FenceAttestation
        maxage = float((cfg.get("primary") or {}).get("attestation_max_age_s", 30))
        fa = FenceAttestation(st.ParHttpStore(_need(paths, "attestation_par_url_file"), allow_http_localhost=allow_http_localhost, **store_kw), wall=wall)
        return lambda: bool(fa.read(max_age_s=maxage).get("ok"))
    return build


def strong_fence_provider(paths: dict | None = None, *, aws_read=None, hard_fence=None, stop_rds=None, **kw):
    """Vallado fuerte. `stop_rds` solo se entrega a StrongFence si la configuración permite parar la RDS (`allow_stop_rds`); si no, jamás se podrá ordenar."""
    def build(cfg):
        import promotion_gate as pgate
        sf = ((cfg.get("primary") or {}).get("strong_fence")) or {}
        allow = bool(sf.get("allow_stop_rds"))
        if allow and stop_rds is None:
            raise ProviderError("allow_stop_rds=true pero no se entregó el ejecutor de parada de la RDS")
        return pgate.StrongFence(hard_fence=hard_fence, aws_read=aws_read or aws_state_provider()(cfg), stop_rds=(stop_rds if allow else None), allow_stop_rds=allow, max_age_s=float(sf.get("max_age_s", 60.0)), **kw)
    return build


def sealer_provider(paths: dict, *, oci_auth, witness_report=None, ratchet=None, log=None, allow_http_localhost=False, **kw):
    """Sellador de la promoción: añade la entrada «sealed» al registro de apéndice. `log` es el almacén de escritura (OciSdkLogStore con identidad sin OVERWRITE/DELETE); sin él se usa el PAR de prefijo
    indicado (solo válido si permite crear). Con `primary.freshness_witness.require` el informe al testigo es OBLIGATORIO: sin `witness_report` NO se construye."""
    def build(cfg):
        from app.failover import seal_log
        fw = ((cfg.get("primary") or {}).get("freshness_witness")) or {}
        if fw.get("require") and witness_report is None:
            raise ProviderError("freshness_witness.require=true: falta witness_report (la promoción no se completa sin que el testigo registre la cabeza)")
        lg = log or seal_log.ParLogStore(_need(paths, "seal_log_par_url_file"), allow_create=True, prefix=paths.get("seal_log_prefix"), allow_http_localhost=allow_http_localhost, **kw)
        return seal_log.make_sealer(lg, oci_auth, ratchet=ratchet, witness_report=witness_report)
    return build


def standby_provider(paths: dict, *, fence, app_exec, lease_obj=None):
    """Standby sobre el PostgreSQL de la VM de OCI (PgStandby): permiso de promoción + lease válido + época vigente EN LA BASE. `fence` y `app_exec` los entrega quien conoce las credenciales."""
    def build(cfg):
        import pg_standby
        if lease_obj is None:
            raise ProviderError("standby: falta el lease (lease_obj) con el que comparte autoridad")
        return pg_standby.PgStandby(lease_obj, fence, Path(_need(paths, "state_dir")) / "promote.permit", app_exec)
    return build


def dns_runtime_provider():
    """Resolvedor UDP/53 y abridor HTTPS verificado hacia DuckDNS (dns_switch). No cambia nada por sí mismo: el permiso de cambio lo decide la fábrica."""
    def build(cfg):
        import dns_switch as dsw
        return {"resolver": dsw.udp_resolver, "opener": dsw._default_urlopen}
    return build


def build_real_providers(paths: dict, *, oci_auth, witness_report, fence, app_exec, allow_http_localhost=False, aws_run=None, aws_profile=None, aws_region=None, stop_rds=None, hard_fence=None, ratchet=None, seal_log=None) -> dict:
    """Conjunto COMPLETO para `build_adapters(..., providers=...)`. El `standby` comparte el lease con el adaptador: se crea una vez y se reutiliza."""
    cache: dict = {}
    def lease_once(cfg):
        if "lease" not in cache:
            cache["lease"] = lease_provider(paths, allow_http_localhost=allow_http_localhost)(cfg)
        return cache["lease"]
    return {
        "clock": clock_provider(), "lease": lease_once,
        "standby": lambda cfg: standby_provider(paths, fence=fence, app_exec=app_exec, lease_obj=lease_once(cfg))(cfg),
        "ledger": ledger_provider(paths), "oci_reader": oci_reader_provider(paths, allow_http_localhost=allow_http_localhost),
        "dns_runtime": dns_runtime_provider(), "aws_state": aws_state_provider(run=aws_run, profile=aws_profile, region=aws_region),
        "db_attestation": db_attestation_provider(paths, allow_http_localhost=allow_http_localhost),
        "strong_fence": strong_fence_provider(paths, aws_read=None, hard_fence=hard_fence, stop_rds=stop_rds),
        "sealer": sealer_provider(paths, oci_auth=oci_auth, witness_report=witness_report, ratchet=ratchet, log=seal_log, allow_http_localhost=allow_http_localhost),
        "store_verifier": store_verifier_provider(paths, allow_http_localhost=allow_http_localhost),
    }
