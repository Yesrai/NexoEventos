#!/usr/bin/env python3
"""Actualiza SOLO la descripción de los eventos demo (ids del catálogo semilla) con el texto comercial vigente.

No toca fechas, precios, capacidad, inventario, reservas ni entradas. Idempotente.
Uso: python scripts/update-demo-descriptions.py [--database-url postgresql+psycopg:///nexoeventos] [--dry-run]
"""
from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path

from sqlalchemy import create_engine, text

spec = importlib.util.spec_from_file_location("seed_demo_catalog", Path(__file__).with_name("seed-demo-catalog.py"))
seed = importlib.util.module_from_spec(spec)
spec.loader.exec_module(seed)

parser = argparse.ArgumentParser()
parser.add_argument("--database-url", default="postgresql+psycopg:///nexoeventos")
parser.add_argument("--dry-run", action="store_true")
args = parser.parse_args()

engine = create_engine(args.database_url)
changed = 0
with engine.begin() as connection:
    for event in seed.EVENTS:
        event_id, description = event[0], event[7]
        current = connection.execute(text("SELECT description FROM events WHERE id = :id AND is_demo"), {"id": event_id}).scalar()
        if current is None or current == description:
            continue
        changed += 1
        if not args.dry_run:
            connection.execute(text("UPDATE events SET description = :d WHERE id = :id AND is_demo"), {"d": description, "id": event_id})
print(f"{'Cambiarían' if args.dry_run else 'Actualizados'}: {changed} eventos (solo descripción)")
