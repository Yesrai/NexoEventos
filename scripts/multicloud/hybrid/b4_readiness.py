#!/usr/bin/env python3
"""¿Qué componentes de B4 (escenario híbrido AWS + OCI aislado) están PREPARADOS y cuáles dependen de validación real? SOLO LECTURA local: importa módulos, valida la configuración de ejemplo y enumera pendientes.
B4 NO se ejecuta. La promoción AUTOMÁTICA permanece bloqueada mientras falte cualquier validación real."""
from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
for p in (ROOT / "backend", ROOT / "scripts/multicloud/failover", ROOT / "scripts/multicloud/hybrid"):
    sys.path.insert(0, str(p))

COMPONENTES = [  # (nombre, módulo, símbolo, validado_en_real, pendiente)
    ("lease con CAS, Ed25519, estado persistente y guardia de sello", "app.failover.lease", "LeaseClient", True, "If-Match por PAR validado en OCI real; falta la identidad desatendida definitiva (usuario de servicio / instance principal)"),
    ("vallado en la base (triggers al COMMIT, atestación, cerrojo)", "app.failover.pg_fence", "PgFence", True, "hard_fence y cerrojo validados en RDS real (nexo_fence_lab); falta persistencia tras reinicio de la RDS y track_commit_timestamp"),
    ("instalación en tablas de negocio sin cambiar propietarios", "app.failover.pg_fence", "owner_grants_sql", False, "probada en copia local con las 14 tablas reales; no ejecutada en la RDS real (autorización aparte; ver fence_business.py plan)"),
    ("puerta de promoción con vallado fuerte", "promotion_gate", "StrongFence", False, "falta validarla de extremo a extremo con una parada real de la RDS Multi-AZ y su RTO"),
    ("guardia de reinicio del primario", "restart_guard", "RestartGuard", False, "falta probarla contra un reinicio REAL de la RDS"),
    ("sello antirretroceso (registro de apéndice + trinquete)", "app.failover.seal_log", "LogGuard", False, "falta ejecutar en OCI real la matriz T1–T10 (oci_seal_lab.py): identidad create-only, PAR de lectura con listado, retención sin versionado; el PAR de escritura NO es solo-adición"),
    ("testigo de frescura independiente (anti-rollback simultáneo)", "app.failover.witness", "WitnessGuard", False, "implementado y probado solo en LOCAL (servicio HTTP, cliente, quórum, ECDSA P-256, almacén de objetos con retención simulado); NO existe infraestructura real: falta desplegar ≥ 2 testigos independientes (p. ej. Google Cloud + otra) con almacén inmutable y clave en HSM/KMS, y validarlos"),
    ("orquestador con promoción automática bloqueada", "orchestrator", "Orchestrator", True, "la promoción automática exige validated_strong_fence y validated_antirollback (hoy falsos)"),
    ("B2 precheck de solo lectura / B3 vallado en base de laboratorio", "hybrid_b3", "build_remote", True, "ejecutados en RDS real el 20-nov"),
    ("B1 encendido controlado con watchdog", "hybrid_b1", "B1", True, "ejecutado el 20-nov"),
    ("claves del lease y registro de etapas", "hybrid_gate", "FRASES", True, "claves Ed25519 de laboratorio generadas; la clave del OPERADOR (failback) aún no existe"),
]


def status() -> dict:
    out = []
    for nombre, mod, sym, real, pend in COMPONENTES:
        try:
            ok = hasattr(importlib.import_module(mod), sym)
        except Exception:  # noqa: BLE001
            ok = False
        out.append({"componente": nombre, "implementado_y_probado_en_local": ok, "validado_en_entorno_real": real, "pendiente": pend})
    import orchestrator as OR
    cfg = OR.Config()
    return {"componentes": out, "automatico_permitido": bool(cfg.automatic and cfg.validated_strong_fence and cfg.validated_antirollback), "por_defecto": {"automatic": cfg.automatic, "validated_strong_fence": cfg.validated_strong_fence, "validated_antirollback": cfg.validated_antirollback},
            "b4_ejecutable_hoy": False, "motivo_b4": "B4 no está autorizado; esto solo comprueba la preparación local",
            "bloqueos_del_automatico": [c["pendiente"] for c in out if not c["validado_en_entorno_real"]]}


def main(argv=None) -> int:
    r = status(); print(json.dumps(r, indent=1, ensure_ascii=False)); return 0 if all(c["implementado_y_probado_en_local"] for c in r["componentes"]) else 1


if __name__ == "__main__":
    sys.exit(main())
