"""Configuración del failover AWS → OCI y su validación FALLA CERRADO. Solo valida y resume qué falta (no abre conexiones, no crea nada). Un archivo JSON describe el despliegue real; el
orquestador `run` sigue sin ejecutarse (requiere autorización cloud, NEXO_ALLOW_FAILOVER_EXECUTE=YES y la frase de confirmación). Aquí se garantiza que la configuración, de existir, sea SEGURA:
  · sondas: URL https (tres señales HTTP desde OCI + control) y estado de AWS por API (dos familias independientes);
  · vallado: la compuerta del primario ATESTIGUADA en enforce y el almacén del lease verificado (If-Match/If-None-Match); sin eso no se habilita ningún modo automático;
  · respaldo C-04: certificado destinatario fijado por SHA-256 (64 hex), clave pública de firma y clave privada FUERA del repositorio (ruta absoluta, permisos 0600);
  · DNS: modo `dry-run` por defecto; `apply` exige además la variable NEXO_ALLOW_DNS_CHANGE=YES;
  · vallado en la BASE del primario obligatorio (db_fence=require) con atestación vigente de ≤ 60 s; sin él no se acepta evidencia inferida;
  · la clave de descifrado: un failover AUTOMÁTICO exige una identidad de recuperación en Vault/KMS (key_provider), nunca una persona ni la clave personal C-04;
  · ningún secreto en línea (URL de PAR, tokens, contraseñas): solo rutas a archivos 0600.
"""
from __future__ import annotations

import json
import os
import re
import stat
from pathlib import Path
from urllib.parse import urlparse

SECRET_KEYS = re.compile(r"(password|passwd|secret|token|par_url|passphrase|api_key)$", re.I)
SHA = re.compile(r"^[0-9a-fA-F:]{64,95}$")


def _https(u) -> bool:
    p = urlparse(str(u or ""))
    return p.scheme == "https" and bool(p.hostname) and not p.username and not p.query and not p.fragment


def _walk_inline_secrets(d, path=""):
    if isinstance(d, dict):
        for k, v in d.items():
            if SECRET_KEYS.search(str(k)) and isinstance(v, str) and v and not str(k).endswith("_file"):
                yield f"{path}{k}"
            yield from _walk_inline_secrets(v, f"{path}{k}.")


def validate(cfg: dict, *, check_files: bool = True) -> dict:
    """Devuelve {"ok": bool, "errors": [...], "warnings": [...], "modo": "standby_preparado"|"failover_automatico"|"recuperacion_desde_respaldo"}."""
    errs: list[str] = []; warns: list[str] = []
    get = lambda *ks: _get(cfg, ks)
    for k in _walk_inline_secrets(cfg):
        errs.append(f"secreto en línea en «{k}»: use un archivo 0600 (…_file)")
    # sondas
    for key in ("primary.livez_url", "primary.ready_url", "primary.control_url", "primary.write_gate_url", "standby.livez_url", "standby.ready_url", "standby.api_url"):
        if not _https(get(*key.split("."))):
            errs.append(f"{key}: debe ser una URL https sin credenciales ni parámetros")
    aws = get("primary", "aws") or {}
    if not (aws.get("instance_tag") and aws.get("db_id")):
        errs.append("primary.aws: faltan instance_tag y db_id (estado de EC2/RDS por API, solo lectura): sin esa familia de señales una sola fuente no basta")
    # vallado en la base: sin él NO se acepta evidencia inferida (un primario aislado se promovería sin garantía de que su base rechace commits)
    if get("primary", "db_fence") != "require":
        errs.append("primary.db_fence debe ser «require»: sin vallado en la base del primario no hay garantía comprobable para promover ante un aislamiento")
    # VALLADO FUERTE (promotion_gate.py): sin él NO se promueve. Evidencia: base del primario vallada con fuerza (sesiones terminadas) o RDS `stopped` por el plano de control; nunca atestación, lease caducado, timeout o barrera HTTP.
    sf = get("primary", "strong_fence")
    if not isinstance(sf, dict) or sf.get("require") is not True:
        errs.append("primary.strong_fence.require debe ser true: la espera del lease no excluye un commit antiguo pendiente en un servidor de base congelado")
    else:
        if not isinstance(sf.get("max_age_s"), (int, float)) or not (1 <= sf["max_age_s"] <= 120):
            errs.append("primary.strong_fence.max_age_s: 1–120 s (la evidencia fuerte caduca)")
        if not set(sf.get("methods") or []) & {"db_hard_fence", "rds_stop_confirmed"} or not set(sf["methods"]) <= {"db_hard_fence", "rds_stop_confirmed"}:
            errs.append("primary.strong_fence.methods: db_hard_fence y/o rds_stop_confirmed (ningún otro método cuenta como prueba)")
        if not isinstance(sf.get("allow_stop_rds"), bool):
            errs.append("primary.strong_fence.allow_stop_rds: true/false explícito (¿puede ORDENAR la parada de la RDS? es una acción destructiva sobre el primario)")
        if cfg.get("automatic") is True and sf.get("validated_on_real_rds") is not True:
            errs.append("automatic=true exige primary.strong_fence.validated_on_real_rds=true: el vallado fuerte aún no está demostrado en una RDS real (pg_signal_backend, track_commit_timestamp, parada Multi-AZ)")
    # SELLO de promoción (seal.py): protección persistente contra el regreso del primario (reinicio de la RDS a los 7 días, Auto Scaling, guardián). Sin él NO hay promoción.
    sl = get("primary", "seal")
    if not isinstance(sl, dict) or sl.get("require") is not True:
        errs.append("primary.seal.require debe ser true: sin sello persistente un primario que reinicia solo podría recuperar la autoridad de escritura")
    elif not sl.get("operator_pubkey_file") or not sl.get("object"):
        errs.append("primary.seal: faltan object y operator_pubkey_file (clave pública del OPERADOR que firma el failback manual; su privada no está en ningún nodo)")
    elif cfg.get("automatic") is True and sl.get("antirollback_validated") is not True:
        errs.append("automatic=true exige primary.seal.antirollback_validated=true: registro de apéndice con retención (WORM) validado en OCI REAL + trinquete en la base (seal_log.py); un PAR de sobrescritura podría devolver un «unsealed» antiguo")
    # TESTIGO DE FRESCURA INDEPENDIENTE (witness.py): la referencia que no retrocede junto con el lease, el sello y la base. Sin ella un rollback simultáneo coherente y con firmas válidas se aceptaría en una instancia nueva.
    fw = get("primary", "freshness_witness")
    if not isinstance(fw, dict) or fw.get("require") is not True:
        errs.append("primary.freshness_witness.require debe ser true: sin una referencia de frescura independiente un rollback simultáneo del lease y del sello se acepta")
    else:
        if not fw.get("url_file") or not fw.get("pubkey_file"): errs.append("primary.freshness_witness: faltan url_file y pubkey_file (clave pública del testigo anclada en la configuración)")
        if not isinstance(fw.get("max_age_s"), (int, float)) or not (1 <= fw["max_age_s"] <= 120): errs.append("primary.freshness_witness.max_age_s: 1–120 s")
        w, k = fw.get("witnesses", 1), fw.get("quorum_k", 1)
        if not (isinstance(w, int) and isinstance(k, int) and 1 <= k <= w): errs.append("primary.freshness_witness: witnesses y quorum_k enteros con 1 ≤ quorum_k ≤ witnesses")
        elif cfg.get("automatic") is True and (w < 2 or k < 2): errs.append("automatic=true exige ≥ 2 testigos independientes y quorum_k ≥ 2 (un solo testigo restaurado a un prefijo válido retrocedería a un consumidor nuevo)")
        if cfg.get("automatic") is True and fw.get("independent_infrastructure_validated") is not True:
            errs.append("automatic=true exige primary.freshness_witness.independent_infrastructure_validated=true: el testigo debe vivir en infraestructura inmutable e independiente de AWS y OCI, y esa garantía aún no existe")
    if get("lease", "auth") not in ("ed25519", "hmac"):
        errs.append("lease.auth: ed25519 (recomendado) o hmac: el almacén del lease se puede sobrescribir sin If-Match")
    am = get("primary", "attestation_max_age_s")
    if not isinstance(am, (int, float)) or am <= 0 or am > 60:
        errs.append("primary.attestation_max_age_s: 1–60 s (una atestación caducada nunca es prueba suficiente)")
    # vallado y lease
    if get("primary", "gate_attested") is not True:
        errs.append("primary.gate_attested debe ser true: WRITE_GATE_MODE=enforce comprobado en el primario (sin eso, un primario inalcanzable bloquea la promoción)")
    if get("lease", "store") != "par-http" or not get("lease", "par_url_file"):
        errs.append("lease: store par-http con par_url_file (archivo 0600) y autoprueba obligatoria de condiciones")
    # respaldo C-04
    rec = get("recovery") or {}
    if not SHA.match(str(rec.get("cert_sha256") or "")):
        errs.append("recovery.cert_sha256: huella SHA-256 del certificado destinatario (obligatoria: no se restaura un respaldo cifrado para otro certificado)")
    for k in ("signer_pub", "object_prefix", "bucket", "oci_profile"):
        if not rec.get(k):
            errs.append(f"recovery.{k}: obligatorio")
    kp = rec.get("key_provider")
    if kp not in ("interactive_person", "oci_vault_secret", "oci_kms"):
        errs.append("recovery.key_provider: interactive_person | oci_vault_secret | oci_kms")
    if kp == "interactive_person":
        if cfg.get("automatic") is True:
            errs.append("recovery.key_provider=interactive_person: el descifrado depende de una PERSONA (su Mac/frase): no es compatible con failover automático")
        if not rec.get("private_key_file"):
            errs.append("recovery.private_key_file: obligatorio con key_provider=interactive_person")
    elif kp in ("oci_vault_secret", "oci_kms"):
        if not rec.get("key_ref") or "ocid1." not in str(rec.get("key_ref")) and not str(rec.get("key_ref", "")).startswith("<"):
            errs.append("recovery.key_ref: OCID del secreto/clave de la identidad de recuperación SEPARADA (no la clave personal C-04)")
        if rec.get("private_key_file"):
            errs.append("recovery.private_key_file no debe usarse con una identidad de recuperación en Vault/KMS (la clave no se copia al disco del standby)")
        warns.append(f"key_provider={kp}: aún NO implementado ni probado en la nube; hasta entonces el failover automático no puede ser operativo")
    if rec.get("private_key_file") and not os.path.isabs(str(rec["private_key_file"])):
        errs.append("recovery.private_key_file: ruta absoluta fuera del repositorio")
    if "/work/" in str(rec.get("private_key_file", "")) or "/Workspace/NexoEventos/" in str(rec.get("private_key_file", "")):
        errs.append("recovery.private_key_file: la clave no puede estar dentro del repositorio")
    if rec.get("max_backup_age_s") and float(rec["max_backup_age_s"]) > 24 * 3600:
        warns.append("recovery.max_backup_age_s > 24 h: RPO muy amplio")
    # DNS
    dns = get("dns") or {}
    if dns.get("mode", "dry-run") not in ("dry-run", "apply"):
        errs.append("dns.mode: dry-run o apply")
    if dns.get("mode") == "apply":
        warns.append("dns.mode=apply: el cambio real exige además NEXO_ALLOW_DNS_CHANGE=YES y confirmación")
    # incidente
    det = get("detector") or {}
    if int(det.get("rounds", 3)) < 3 or int(det.get("quorum", 2)) < 2:
        errs.append("detector: rounds >= 3 y quorum >= 2 (protección contra falsos positivos)")
    if check_files:
        for key in ("lease.par_url_file", "recovery.signer_pub", "recovery.private_key_file"):
            pth = get(*key.split("."))
            if pth:
                try:
                    st = os.stat(pth)
                    if key != "recovery.signer_pub" and stat.S_IMODE(st.st_mode) & 0o077:
                        errs.append(f"{key}: permisos {oct(stat.S_IMODE(st.st_mode))}; debe ser 0600")
                except OSError:
                    errs.append(f"{key}: no existe o no se puede leer")
    modo = "failover_automatico" if (not errs and cfg.get("automatic") is True) else ("standby_preparado" if not errs else "recuperacion_desde_respaldo")
    return {"ok": not errs, "errors": errs, "warnings": warns, "modo": modo}


def _get(d, keys):
    for k in keys:
        if not isinstance(d, dict):
            return None
        d = d.get(k)
    return d


def load(path) -> dict:
    return json.loads(Path(path).read_text())


EXAMPLE = {
    "automatic": False,
    "primary": {"livez_url": "https://app.example/livez", "ready_url": "https://app.example/ready", "control_url": "https://control.example/health", "write_gate_url": "https://app.example/write-gate",
                "aws": {"instance_tag": "nexoeventos-academy-app", "db_id": "nexoeventos-academy-postgres"}, "gate_attested": True, "db_fence": "require", "attestation_max_age_s": 30,
                "strong_fence": {"require": True, "max_age_s": 60, "methods": ["db_hard_fence", "rds_stop_confirmed"], "allow_stop_rds": False, "validated_on_real_rds": False},
                "freshness_witness": {"require": True, "url_file": "/etc/nexoeventos/failover/witness.url", "pubkey_file": "/etc/nexoeventos/failover/witness.pub", "max_age_s": 30, "witnesses": 1, "quorum_k": 1, "independent_infrastructure_validated": False},
                "seal": {"require": True, "object": "failover-seal.json", "operator_pubkey_file": "/etc/nexoeventos/failover/operator.pub"}},
    "standby": {"livez_url": "https://oci.example/livez", "ready_url": "https://oci.example/ready", "api_url": "https://oci.example/api/events"},
    "lease": {"store": "par-http", "par_url_file": "/etc/nexoeventos/failover/lease-par.url", "auth": "ed25519"},
    "recovery": {"bucket": "nexoeventos-recovery", "object_prefix": "backups/c04-20261119/", "oci_profile": "NEXOEVENTOS_UPLOADER", "cert_sha256": "5c6d387bbc29ef818e0c3267cf477b32a2b890fda31be2d7c3c3d6cd9d5c7bcf",
                 "signer_pub": "/etc/nexoeventos/failover/c04-backup-sign.pub", "key_provider": "interactive_person", "private_key_file": "/etc/nexoeventos/failover/recovery-private.protected.pem", "max_backup_age_s": 3600},
    "dns": {"mode": "dry-run"},
    "detector": {"rounds": 3, "quorum": 2},
}
