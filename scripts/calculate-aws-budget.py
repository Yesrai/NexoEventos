#!/usr/bin/env python3
"""Recalculate the V1 estimate without treating 730 hours as 30 days."""
from __future__ import annotations

import argparse
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo


RATES = {
    "ec2_hour": Decimal("0.0208"),
    "rds_hour": Decimal("0.018"),
    "ipv4_hour": Decimal("0.005"),
    "ebs_month": Decimal("1.600"),
    "rds_storage_month": Decimal("2.300"),
    "managed_secret_month": Decimal("0.400"),
    "s3_month": Decimal("0.023"),
    "log_storage_month": Decimal("0.006"),
    "alarm_month": Decimal("0.100"),
    "log_ingestion_month": Decimal("0.500"),
}


def parse_local(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=ZoneInfo("America/Lima"))


def money(value: Decimal) -> str:
    return f"{value.quantize(Decimal('0.001'))}"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--created-at", required=True, help="Fecha local ISO, por ejemplo 2026-10-05T09:00")
    parser.add_argument("--end-at", default="2026-11-26T23:59")
    parser.add_argument("--ec2-hours", type=Decimal, required=True)
    parser.add_argument("--rds-hours", type=Decimal, required=True)
    parser.add_argument("--ipv4-hours", type=Decimal, required=True)
    parser.add_argument("--margin", type=Decimal, default=Decimal("3.00"))
    args = parser.parse_args()

    created = parse_local(args.created_at)
    end = parse_local(args.end_at)
    elapsed_hours = Decimal(str((end - created).total_seconds() / 3600))
    if elapsed_hours <= 0 or min(args.ec2_hours, args.rds_hours, args.ipv4_hours) < 0:
        raise SystemExit("Fechas u horas inválidas.")
    if max(args.ec2_hours, args.rds_hours, args.ipv4_hours) > elapsed_hours:
        raise SystemExit("Las horas activas no pueden superar el periodo de persistencia.")

    months_30d = elapsed_hours / Decimal("720")
    runtime = (
        args.ec2_hours * RATES["ec2_hour"]
        + args.rds_hours * RATES["rds_hour"]
        + args.ipv4_hours * RATES["ipv4_hour"]
    )
    persistent_monthly = sum(
        RATES[key]
        for key in (
            "ebs_month", "rds_storage_month", "managed_secret_month", "s3_month",
            "log_storage_month", "alarm_month",
        )
    )
    persistent = persistent_monthly * months_30d
    variable = RATES["log_ingestion_month"] * months_30d
    subtotal = runtime + persistent + variable

    print(f"persistencia_horas={elapsed_hours.quantize(Decimal('0.001'))}")
    print(f"meses_de_720h={months_30d.quantize(Decimal('0.000001'))}")
    print(f"ejecucion_usd={money(runtime)}")
    print(f"almacenamiento_servicios_usd={money(persistent)}")
    print(f"consumo_variable_base_usd={money(variable)}")
    print(f"subtotal_usd={money(subtotal)}")
    print(f"margen_usd={money(args.margin)}")
    print(f"techo_planificado_usd={money(subtotal + args.margin)}")


if __name__ == "__main__":
    main()
