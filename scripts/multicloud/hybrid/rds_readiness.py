#!/usr/bin/env python3
"""B2 · ¿Está esta Amazon RDS PostgreSQL lista para el vallado fuerte? SOLO LECTURA. `plan` imprime los comandos (AWS API de solo lectura + precheck de PostgreSQL, que se ejecuta dentro de una transacción que se
deshace); `evaluate` recibe sus salidas JSON y emite el veredicto SIN abrir ninguna conexión. Comprueba lo que el vallado fuerte necesita de verdad:
  · terminar sesiones de la aplicación (pg_signal_backend del administrador o de rds_superuser)  · compatibilidad de hard_fence  · track_commit_timestamp  · permisos del administrador (esquema, funciones SECURITY DEFINER,
    triggers diferidos, propiedad de las tablas)  · restricciones de Multi-AZ y de la parada (réplicas de lectura, estado, reinicio automático a los 7 días)  · max_prepared_transactions=0.
Uso: rds_readiness.py plan --db-id ID [--profile P --region R] | evaluate --aws-file F --params-file F --pg-file F"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PARAMS = ("track_commit_timestamp", "max_prepared_transactions", "rds.force_ssl", "synchronous_commit")


def plan(db_id: str, profile: str | None = None, region: str | None = None) -> list[str]:
    base = "aws" + (f" --profile {profile}" if profile else "") + (f" --region {region}" if region else "")
    return [f"{base} rds describe-db-instances --db-instance-identifier {db_id} --query 'DBInstances[0]' --output json   > aws.json      # estado, Multi-AZ, réplicas, grupo de parámetros, AutomaticRestartTime",
            f"{base} rds describe-db-parameters --db-parameter-group-name <grupo de aws.json> --query \"Parameters[?ParameterName=='track_commit_timestamp' || ParameterName=='max_prepared_transactions' || ParameterName=='rds.force_ssl' || ParameterName=='synchronous_commit']\" --output json   > params.json",
            "backend/.venv/bin/python scripts/multicloud/hybrid/fence_admin.py precheck --read-only --admin-dsn-file <archivo 0600 en la EC2> --app-role nexoeventos_app   > pg.json     # SOLO LECTURA: transacción READ ONLY, sin DDL de prueba",
            "backend/.venv/bin/python scripts/multicloud/hybrid/rds_readiness.py evaluate --aws-file aws.json --params-file params.json --pg-file pg.json"]


def evaluate(aws: dict, params: list[dict], pg: dict) -> dict:
    blockers, warnings, notes = [], [], []
    st = aws.get("DBInstanceStatus")
    if st != "available":
        blockers.append(f"la RDS está `{st}`: el precheck exige `available` (B1 la enciende)")
    if aws.get("Engine") != "postgres" or not str(aws.get("EngineVersion", "")).startswith("18"):
        blockers.append(f"motor/versión {aws.get('Engine')} {aws.get('EngineVersion')}: la prueba y el vallado se validaron con PostgreSQL 18")
    replicas = aws.get("ReadReplicaDBInstanceIdentifiers") or []
    stop_possible = not replicas and not aws.get("ReadReplicaSourceDBInstanceIdentifier")
    if replicas:
        warnings.append("la RDS tiene réplicas de lectura: RDS NO permite detenerla (la parada confirmada no sería posible; solo el vallado por la base)")
    if aws.get("MultiAZ"):
        notes.append("Multi-AZ: la parada (stop-db-instance) está permitida para PostgreSQL; la conmutación interna de AWS conserva el endpoint y el cerrojo (volumen replicado). Medir cuánto tarda en B-fases (RTO).")
        notes.append("Multi-AZ síncrono: un commit puede quedar esperando a la réplica; hard_fence debe terminar esa sesión y comprobar que desaparece (se prueba en B3 sobre nexo_fence_lab).")
    if aws.get("AutomaticRestartTime"):
        notes.append(f"reinicio automático previsto: {aws['AutomaticRestartTime']} (la guardia de reinicio y el sello existen por esto)")
    pmap = {p.get("ParameterName"): p for p in (params or [])}
    tct = (pmap.get("track_commit_timestamp") or {})
    tct_pg = pg.get("track_commit_timestamp")
    if (tct_pg or tct.get("ParameterValue")) != "on" and tct_pg != "on":
        warnings.append("track_commit_timestamp no está en `on`: late_commits() no puede enumerar huérfanos. Activarlo es un cambio del grupo de parámetros y exige REINICIO de la RDS (se pide aparte, no en B2)")
    mpt = pg.get("max_prepared_transactions", pmap.get("max_prepared_transactions", {}).get("ParameterValue"))
    if str(mpt) not in ("0", "None"):
        blockers.append(f"max_prepared_transactions={mpt}: un COMMIT PREPARED evita el trigger; debe ser 0")
    if pg.get("read_only"):
        blockers.extend(["PostgreSQL: " + b for b in (pg.get("blockers") or [])])
        notes.append("precheck PURO DE LECTURA: no mide si el administrador puede crear esquema/funciones SECURITY DEFINER/triggers/event triggers (exige DDL); se mide en B3 dentro de nexo_fence_lab")
    elif not pg.get("ok_to_install"):
        blockers.extend(["PostgreSQL: " + b for b in (pg.get("blockers") or ["precheck no apto"])])
    if pg.get("is_superuser") is False and not pg.get("member_rds_superuser"):
        blockers.append("el administrador no es superusuario ni miembro de rds_superuser")
    signal = bool(pg.get("can_signal_backends")); signal_rds = bool(pg.get("rds_superuser_can_signal"))
    if not signal:
        warnings.append("el administrador NO puede terminar sesiones de otros roles (pg_signal_backend): hard_fence imposible; solo valdría la parada confirmada de la RDS")
    notes.append(f"pg_signal_backend: administrador={signal}, rds_superuser={signal_rds}")
    if pg.get("admin_can_set_session_replication_role"):
        warnings.append("el administrador puede fijar session_replication_role (vía de escape de administración, ya conocida): el guardián la detecta pero no la impide")
    hard = signal and not blockers
    return {"ready_for_b3": not blockers, "hard_fence_possible": hard, "stop_confirmation_possible": stop_possible, "blockers": blockers, "warnings": warnings, "notes": notes,
            "strong_fence_available": bool(hard or stop_possible)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(); ap.add_argument("cmd", choices=["plan", "evaluate"]); ap.add_argument("--db-id", default="nexoeventos-academy-postgres"); ap.add_argument("--profile"); ap.add_argument("--region")
    ap.add_argument("--aws-file"); ap.add_argument("--params-file"); ap.add_argument("--pg-file"); a = ap.parse_args(argv)
    if a.cmd == "plan":
        print("\n".join(plan(a.db_id, a.profile, a.region))); return 0
    try:
        r = evaluate(json.loads(Path(a.aws_file).read_text()), json.loads(Path(a.params_file).read_text()), json.loads(Path(a.pg_file).read_text()))
    except (OSError, ValueError, TypeError):
        print("ERROR: archivos ilegibles", file=sys.stderr); return 2
    print(json.dumps(r, indent=1, ensure_ascii=False)); return 0 if r["ready_for_b3"] else 1


if __name__ == "__main__":
    sys.exit(main())
