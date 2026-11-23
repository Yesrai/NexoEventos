#!/usr/bin/env python3
"""Selector y verificador del último respaldo restaurable para el failover (B-13 ↔ B-14 ↔ S-01).

Problema que resuelve: el orquestador (`orchestrator.py`) necesita `restore_latest()` -> {fingerprint_ok, backup_age_s, backup}, pero solo existía la versión
simulada. Aquí está la lógica REAL y local (sin nube) que, dado un directorio con los objetos descargados del bucket (cifrado + manifiesto que sube
`backup_cycle.py`), decide qué respaldo usar y lo verifica de extremo a extremo:
  1. lee todos los `*.manifest.json` (los ilegibles o sin campos obligatorios se descartan con motivo);
  2. de cada uno exige que el objeto exista y que SHA-256 y tamaño coincidan (un objeto truncado o alterado se descarta y se recurre al anterior);
  3. elige el más reciente válido (por `created_utc` = inicio de la captura de datos; la antigüedad que se informa es el RPO real de ese respaldo);
  4. exige huella de datos en el manifiesto (`fingerprint_before/after`): sin huella NO es verificable y `fingerprint_ok` es False (falla cerrada);
  5. ejecuta restore-drill.sh (descifra con la clave —posiblemente protegida con contraseña, solo por `--passin env:/file:/fd:`—, comprueba el SHA-256 del volcado
     en claro, restaura en una base aislada y compara la huella con tolerancia a escrituras durante el volcado).
No decide si se promueve: eso lo hacen las etapas del orquestador (antigüedad máxima, huella). Nada de esto prueba AWS ni OCI: la descarga real de los objetos
(PAR de lectura / credencial de OCI) es un adaptador aparte que requiere autorización cloud.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
RESTORE_DRILL = ROOT / "scripts/multicloud/restore-drill.sh"
REQUIRED = ("name", "object_name", "created_utc", "oci_cms_sha256", "oci_cms_bytes", "plaintext_dump_sha256")


def _t(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def scan(directory: Path, env: str | None = None) -> tuple[list[dict], list[dict]]:
    """Devuelve (candidatos válidos ordenados del más nuevo al más viejo, descartados con motivo)."""
    good, skipped = [], []
    for mp in sorted(directory.glob("*.manifest.json")):
        try:
            m = json.loads(mp.read_text())
            missing = [k for k in REQUIRED if k not in m]
            if missing:
                raise ValueError("faltan campos: " + ", ".join(missing))
            created = _t(m["created_utc"])
            obj = directory / Path(m["object_name"]).name  # solo el nombre: el manifiesto no puede apuntar fuera del directorio
        except (ValueError, OSError, TypeError):
            skipped.append({"manifest": mp.name, "reason": "manifiesto ilegible o incompleto"}); continue
        if env is not None and m.get("env") != env:
            skipped.append({"manifest": mp.name, "reason": f"entorno distinto ({m.get('env')})"}); continue
        if not obj.is_file():
            skipped.append({"manifest": mp.name, "reason": "falta el objeto cifrado"}); continue
        if obj.stat().st_size != m["oci_cms_bytes"] or _sha256(obj) != m["oci_cms_sha256"]:
            skipped.append({"manifest": mp.name, "reason": "el objeto no coincide con el manifiesto (SHA-256/tamaño)"}); continue
        good.append({"manifest": m, "manifest_path": mp, "object_path": obj, "created": created})
    good.sort(key=lambda c: c["created"], reverse=True)
    return good, skipped


def restore_latest(directory, key, passin: str = "", env: str | None = None, now: datetime | None = None, mode: str = "local",
                   restore_env: dict | None = None, timeout: int = 900) -> dict:
    """Implementación real (local) del adaptador `restore_latest` del orquestador. Nunca lanza por datos malos: devuelve fingerprint_ok=False con el motivo."""
    now = now or datetime.now(timezone.utc)
    good, skipped = scan(Path(directory), env)
    out = {"fingerprint_ok": False, "backup_age_s": 1e12, "backup": None, "skipped": skipped, "reason": None}
    if not good:
        out["reason"] = "no hay ningún respaldo válido (manifiesto + objeto íntegros)"
        return out
    c = good[0]
    m = c["manifest"]
    out["backup"] = m["name"]
    out["backup_age_s"] = max((now - c["created"]).total_seconds(), 0.0)
    fb, fa = m.get("fingerprint_before"), m.get("fingerprint_after")
    if not fb or not fa:
        out["reason"] = "el manifiesto no trae huella de datos: el respaldo no es verificable (falla cerrada)"
        return out
    with tempfile.TemporaryDirectory() as td:
        base = Path(td) / "baseline.json"
        base.write_text(json.dumps({"baselines": {m["name"]: {"fingerprint": fb, "fingerprint_after": fa}}}))
        cmd = [str(RESTORE_DRILL), "--manifest", str(c["manifest_path"]), "--cms", str(c["object_path"]), "--key", str(key), "--baseline", str(base),
               "--baseline-key", m["name"], "--mode", mode] + (["--passin", passin] if passin else [])
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=timeout, env=restore_env)
        except subprocess.TimeoutExpired:
            out["reason"] = "la restauración excedió el tiempo máximo"
            return out
    out["fingerprint_ok"] = r.returncode == 0 and "huella idéntica" in r.stdout
    if not out["fingerprint_ok"]:
        # restore-drill.sh imprime motivos fijos y sin secretos (FALLÓ: ...); se conserva solo esa línea.
        line = next((l for l in r.stderr.splitlines() if l.startswith("FALLÓ")), "la restauración falló")
        out["reason"] = line[:300]
    return out


if __name__ == "__main__":
    import argparse
    import sys
    ap = argparse.ArgumentParser(description="Selecciona y verifica el último respaldo restaurable (solo local).")
    ap.add_argument("directory"); ap.add_argument("--key", required=True); ap.add_argument("--passin", default=""); ap.add_argument("--env"); ap.add_argument("--mode", default="docker")
    a = ap.parse_args()
    res = restore_latest(a.directory, a.key, a.passin, a.env, mode=a.mode)
    print(json.dumps(res, indent=1, ensure_ascii=False))
    sys.exit(0 if res["fingerprint_ok"] else 1)
