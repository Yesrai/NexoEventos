#!/usr/bin/env python3
"""Valida, SOLO con archivos locales (sin AWS), que los resultados de los experimentos de caos estén completos y que las cifras citadas se
reproduzcan a partir de los datos crudos. No ejecuta ni simula nada: lee `docs/evidencias/`.
Uso: python3 scripts/cloud/validate-chaos-result.py            (valida los tres experimentos reales conservados)
Cada validador devuelve {"estado": "completo"|"incompleto", "metricas": {...}, "advertencias": [...]}."""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EV = ROOT / "docs/evidencias"


def _ts(value: str) -> float:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()


def split_availability(requests: list[dict]) -> dict:
    """Separa la disponibilidad del TRÁFICO FUNCIONAL (`/api/…`) de la de los endpoints de salud (`/healthz`, `/livez`, `/health`, `/ready`).
    Mezclarlas falsea la medición: el ALB puede enviar todo el tráfico funcional a la instancia sana mientras los sondeos de salud caen en la afectada."""
    def pct(items: list[dict]) -> float | None:
        return round(100 * sum(1 for r in items if r["status"] == 200) / len(items), 1) if items else None

    health_paths = ("/healthz", "/livez", "/health", "/ready")
    functional = [r for r in requests if r["path"].startswith("/api/")]
    health = [r for r in requests if r["path"] in health_paths]
    return {"availability_api_pct": pct(functional), "availability_health_pct": pct(health), "requests_api": len(functional), "requests_health": len(health)}


def validate_api_failure(directory: Path) -> dict:
    """Caída de la API en una de dos instancias (resultado.json + solicitudes.json)."""
    warnings: list[str] = []
    result_file, requests_file = directory / "resultado.json", directory / "solicitudes.json"
    if not result_file.exists() or not requests_file.exists():
        return {"estado": "incompleto", "metricas": {}, "advertencias": [f"faltan archivos: {[f.name for f in (result_file, requests_file) if not f.exists()]}"]}
    result = json.loads(result_file.read_text())
    requests = json.loads(requests_file.read_text())
    errors = [r for r in requests if r["status"] != 200]
    paths = sorted({r["path"] for r in requests})
    error_paths = sorted({r["path"] for r in errors})
    declared = result["client"]
    if declared["requests"] != len(requests) or declared["errors"] != len(errors):
        warnings.append("el resumen del cliente no coincide con las solicitudes crudas")
    if errors and len(error_paths) < len(paths):
        warnings.append(f"los errores están solo en {error_paths} de {paths}: la disponibilidad global NO representa la de la API")
    for key in ("detection_after_stop_s", "recovery_after_restore_s"):
        if result["events"].get(key) is None:
            warnings.append(f"falta {key}")
    metrics = {
        "solicitudes": len(requests), "errores": len(errors), "estados_error": sorted({r["status"] for r in errors}), "rutas_con_error": error_paths,
        "deteccion_s": result["events"].get("detection_after_stop_s"), "recuperacion_s": result["events"].get("recovery_after_restore_s"),
        "disponibilidad_global_pct": round(100 * (len(requests) - len(errors)) / max(1, len(requests)), 1),
        **{k: v for k, v in split_availability(requests).items() if k.startswith("availability")},
    }
    return {"estado": "completo" if not any(w.startswith("falta") or "no coincide" in w for w in warnings) else "incompleto", "metricas": metrics, "advertencias": warnings}


def validate_autohealing(directory: Path) -> dict:
    """Repetición con reemplazo del ASG: debe haber resultado.json; si no, solo hay datos agregados del ALB."""
    warnings: list[str] = []
    if not (directory / "resultado.json").exists():
        warnings.append("no existe resultado.json (el script falló antes de guardarlo): sin disponibilidad de la API ni tiempos de detección/recuperación")
    alb_file = directory / "cloudwatch-alb.json"
    metrics: dict = {}
    if alb_file.exists():
        alb = json.loads(alb_file.read_text())
        metrics = {"respuestas_5xx_destino": sum(alb.get("target_5xx", {}).values()), "respuestas_5xx_elb": sum(alb.get("elb_5xx", {}).values())}
    else:
        warnings.append("falta cloudwatch-alb.json")
    return {"estado": "completo" if not warnings else "incompleto", "metricas": metrics, "advertencias": warnings}


def validate_rds_failover(directory: Path) -> dict:
    """Failover Multi-AZ de RDS: recalcula las interrupciones a partir de las muestras crudas."""
    warnings: list[str] = []
    result = json.loads((directory / "resultado.json").read_text())
    samples = json.loads((directory / "healthz-1s.json").read_text())
    first_bad = next((i for i, s in enumerate(samples) if s["code"] != "200"), None)
    if first_bad is None:
        return {"estado": "incompleto", "metricas": {}, "advertencias": ["no hay muestras fallidas de /healthz"]}
    recovered = next((s for s in samples[first_bad:] if s["code"] == "200"), None)
    healthz_s = round(_ts(recovered["t"]) - _ts(samples[first_bad]["t"]), 1) if recovered else None
    probe = dict(item.split("=", 1) for item in result["sonda_postgres_ec2"].split() if "=" in item)
    postgres_s = round(float(probe["primer_ok_despues"]) - float(probe["primer_fallo"]), 1)
    later_bad = [s["t"] for s in samples if s["code"] != "200" and recovered and _ts(s["t"]) > _ts(recovered["t"])]
    if later_bad:
        warnings.append(f"{len(later_bad)} fallos aislados posteriores sin explicar (primero: {later_bad[0]})")
    if not result.get("huella_igual"):
        warnings.append("la huella de datos antes/después no es idéntica")
    events = " ".join(result.get("eventos_rds", []))
    if "failover completed" not in events:
        warnings.append("no consta el evento 'failover completed' de RDS")
    metrics = {"interrupcion_postgres_s": postgres_s, "interrupcion_healthz_s": healthz_s, "muestras_healthz": len(samples), "huella_igual": result.get("huella_igual")}
    return {"estado": "completo" if not any("huella" in w or "failover completed" in w for w in warnings) else "incompleto", "metricas": metrics, "advertencias": warnings}


def validate_oci_recovery(directory: Path) -> dict:
    """Recuperación manual de la aplicación en OCI: recalcula 14/14, la huella y los 32 min 42 s; avisa de fallos y reanudaciones registrados."""
    warnings: list[str] = []
    smoke = json.loads((directory / "smoke.json").read_text())
    passed = sum(1 for r in smoke["resultados"] if r["ok"])
    if passed != len(smoke["resultados"]) or not smoke.get("todo_ok"):
        warnings.append("hay pruebas de humo fallidas")
    fingerprint = [l for l in (directory / "huella-restaurada.txt").read_text().splitlines() if l.strip()]
    ok_checks = sum(1 for l in fingerprint if l.startswith("OK"))
    values = sum(1 for l in fingerprint if "=" in l)
    delta = [l for l in (directory / "huella-delta.txt").read_text().splitlines() if l.startswith(("<", ">"))]
    if any("access_logs" not in l for l in delta):
        warnings.append("la huella cambió en algo distinto de access_logs")
    t0 = next(l.split()[0] for l in (directory / "tiempos-aprovisionamiento.txt").read_text().splitlines() if "T0_apply" in l)
    total_s = round(_ts(smoke["ejecutado_utc"]) - _ts(t0))
    orchestrator = (directory / "tiempos-orquestador.txt").read_text().splitlines()
    failures = [l for l in orchestrator if "FALLO" in l]
    resumes = [l for l in orchestrator if "REANUDACI" in l]
    if failures or resumes:
        warnings.append(f"el intento incluye {len(failures)} fallo(s) y {len(resumes)} reanudación(es) registrados: no es una ejecución limpia de principio a fin")
    metrics = {"pruebas_humo": f"{passed}/{len(smoke['resultados'])}", "huella_valores": values, "huella_verificaciones_ok": ok_checks,
               "huella_total_lineas": values + ok_checks, "duracion_desde_apply": f"{total_s // 60} min {total_s % 60} s"}
    return {"estado": "completo" if not any("fallidas" in w or "cambió" in w for w in warnings) else "incompleto", "metricas": metrics, "advertencias": warnings}


def main() -> int:
    report = {
        "caida_api_22oct": validate_api_failure(EV / "tolerancia-fallos-v2-20261022"),
        "autohealing_22oct": validate_autohealing(EV / "tolerancia-fallos-v2-20261022-b"),
        "failover_rds_23oct": validate_rds_failover(EV / "multicloud/aws/20261023-rds-multiaz/failover"),
        "recuperacion_oci_23oct": validate_oci_recovery(EV / "multicloud/oci/20261023-recuperacion-aplicacion"),
    }
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
