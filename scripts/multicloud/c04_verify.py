#!/usr/bin/env python3
"""C-04 — verificación de SOLO LECTURA de los respaldos que backup_cycle.py subió a OCI (no sube, no borra, no crea PAR). Reutiliza el lector y las
comprobaciones de failover/oci_source.py (no las reimplementa): para cada ciclo posterior a --since comprueba que el manifiesto es válido, que su FIRMA se
verifica con la clave PÚBLICA fijada, que el objeto cifrado existe con el tamaño y el SHA-256 del manifiesto y que el nombre es nuevo (no estaba en la lista
previa --before-list: nada se sobrescribió). Calcula los intervalos entre ciclos y el RPO OBSERVADO (el mayor hueco entre manifiestos consecutivos).
El RPO observado de unos pocos ciclos es una MEDICIÓN, no un RPO garantizado. La salida (JSON) no contiene secretos ni URL de PAR.
Uso: c04_verify.py --namespace NS --bucket B --profile P --signer-pub pub.pem --since 2026-11-18T23:00:00Z --before-list antes.txt --expect 3 --out c04.json
(--before-list: nombres de objetos del bucket ANTES de la prueba, uno por línea; se genera con `oci os object list` o con --list-only)."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
for sub in (HERE / "failover", HERE):
    sys.path.insert(0, str(sub))
import oci_source as oc  # noqa: E402


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_cycles(reader, signer_pub, *, since: datetime, before: set[str], expect: int, env: str | None = None, max_object_bytes: int = 8 << 30, expect_cert_sha256: str | None = None) -> dict:
    report: dict = {"ok": False, "esperados": expect, "ciclos": [], "omitidos": [], "intervalos_min": [], "rpo_observado_max_min": None, "advertencias": []}
    try:
        stems = reader.list_stems()
    except oc.FetchError as e:
        report["error"] = f"no se pudo listar el bucket: {e}"
        return report
    with tempfile.TemporaryDirectory(prefix="c04-") as td:
        work = Path(td)
        for stem in sorted(stems):
            try:
                mb = reader.get(stem + oc.MANIFEST_SUFFIX, 65536)
                m = json.loads(mb)
            except (oc.FetchError, ValueError, UnicodeDecodeError):
                report["omitidos"].append({"stem": stem, "motivo": "manifiesto ilegible"})
                continue
            if not isinstance(m, dict) or not isinstance(m.get("created_utc"), str):
                report["omitidos"].append({"stem": stem, "motivo": "manifiesto sin created_utc"})
                continue
            try:
                created = oc._parse_utc(m["created_utc"])
            except (ValueError, TypeError):
                report["omitidos"].append({"stem": stem, "motivo": "created_utc inválido"})
                continue
            if created < since:
                continue  # respaldo anterior a la prueba: no es un ciclo de C-04
            ciclo = {"stem": stem, "created_utc": m["created_utc"], "bytes": m.get("oci_cms_bytes"), "nombre_nuevo": stem + oc.MANIFEST_SUFFIX not in before and
                     (m.get("object_name") not in before)}
            why = oc._validate_manifest(m, stem, max_object_bytes)
            ciclo["manifiesto_valido"] = why is None
            if why:
                ciclo["motivo"] = why
            ciclo["entorno_ok"] = env is None or m.get("env") == env
            try:
                sig = reader.get(stem + oc.SIG_SUFFIX, 4096)
                ciclo["firma_ok"] = bool(oc.verify_signature(signer_pub, mb, sig, work))
            except oc.FetchError:
                ciclo["firma_ok"] = False
            ciclo["objeto_ok"] = False
            if why is None:
                part = work / (stem + ".part")
                try:
                    reader.get(Path(m["object_name"]).name, m["oci_cms_bytes"], sink=part, expected_size=m["oci_cms_bytes"])
                    ciclo["objeto_ok"] = _sha256(part) == m["oci_cms_sha256"]
                except oc.FetchError:
                    pass
                finally:
                    part.unlink(missing_ok=True)
            if expect_cert_sha256:  # identidad del certificado destinatario: un manifiesto que declare otra huella NO es admisible; sin dato = respaldo anterior a este campo (se advierte)
                got = str(m.get("recipient_cert_sha256") or "").replace(":", "").lower()
                ciclo["certificado"] = "sin_dato" if not got else ("ok" if got == expect_cert_sha256.replace(":", "").lower() else "distinto")
            ciclo["admisible"] = all(ciclo[k] for k in ("manifiesto_valido", "entorno_ok", "firma_ok", "objeto_ok", "nombre_nuevo")) and ciclo.get("certificado") != "distinto"
            report["ciclos"].append(ciclo)
    cycles = sorted(report["ciclos"], key=lambda c: c["created_utc"])
    times = [oc._parse_utc(c["created_utc"]) for c in cycles]
    report["intervalos_min"] = [round((b - a).total_seconds() / 60, 2) for a, b in zip(times, times[1:])]
    if report["intervalos_min"]:
        report["rpo_observado_max_min"] = max(report["intervalos_min"])
        report["rpo_observado_nota"] = "MEDICIÓN en %d ciclos (mayor hueco entre manifiestos); no es un RPO garantizado" % len(cycles)
    if len({c["stem"] for c in cycles}) != len(cycles):
        report["advertencias"].append("nombres de ciclo repetidos")
    if len(cycles) < expect:
        report["advertencias"].append(f"se esperaban {expect} ciclos y hay {len(cycles)}")
    if any(c.get("certificado") == "sin_dato" for c in cycles):
        report["advertencias"].append("manifiesto(s) sin recipient_cert_sha256 (anteriores a la fijación de identidad del certificado): no se pudo comprobar su destinatario")
    if report["omitidos"]:
        report["advertencias"].append(f"{len(report['omitidos'])} manifiesto(s) omitido(s): " + "; ".join(sorted({o['motivo'] for o in report['omitidos']})))
    report["ok"] = len(cycles) >= expect and all(c["admisible"] for c in cycles)
    return report


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--namespace", required=True)
    ap.add_argument("--bucket", required=True)
    ap.add_argument("--profile", required=True)
    ap.add_argument("--prefix", default="backups/")
    ap.add_argument("--signer-pub", required=True)
    ap.add_argument("--since", required=True, help="inicio de la prueba (UTC, ISO 8601)")
    ap.add_argument("--before-list", required=True, help="archivo con los nombres de objeto del bucket ANTES de la prueba")
    ap.add_argument("--expect", type=int, default=3)
    ap.add_argument("--env", default=None)
    ap.add_argument("--expect-cert-sha256", default=None, help="huella SHA-256 del certificado destinatario que deben declarar los manifiestos")
    ap.add_argument("--out", default=None)
    a = ap.parse_args(argv)
    before = {l.strip() for l in Path(a.before_list).read_text().splitlines() if l.strip()}
    reader = oc.OciCliReader(a.namespace, a.bucket, a.profile, prefix=a.prefix)
    rep = verify_cycles(reader, a.signer_pub, since=oc._parse_utc(a.since), before=before, expect=a.expect, env=a.env, expect_cert_sha256=a.expect_cert_sha256)
    text = json.dumps(rep, indent=1, ensure_ascii=False)
    if a.out:
        Path(a.out).write_text(text + "\n")
    print(text)
    return 0 if rep["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
