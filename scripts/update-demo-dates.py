#!/usr/bin/env python3
"""Reprograma SOLO la fecha de eventos demo YA PASADOS y sin reservas ni entradas.

No toca precios, capacidad, inventario, zonas, asientos, reservas ni entradas, ni eventos futuros, ni eventos con ventas
(se informan como omitidos). Por defecto solo muestra el plan; escribe únicamente con --apply. Idempotente.
Uso: python scripts/update-demo-dates.py --database-url postgresql+psycopg://... [--apply]   (--dry-run es el valor por defecto)
"""
from __future__ import annotations

import argparse
import importlib.util
from datetime import date, timedelta
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

spec = importlib.util.spec_from_file_location("seed_demo_catalog", Path(__file__).with_name("seed-demo-catalog.py"))
seed = importlib.util.module_from_spec(spec)
spec.loader.exec_module(seed)

parser = argparse.ArgumentParser()
parser.add_argument("--database-url", default="postgresql+psycopg:///nexoeventos")
parser.add_argument("--apply", action="store_true")
parser.add_argument("--dry-run", action="store_true", help="valor por defecto; se acepta por claridad")
args = parser.parse_args()
apply = args.apply and not args.dry_run

url = make_url(args.database_url)
print(f"Destino: {url.host or 'socket local'}:{url.port or ''}/{url.database} · modo {'APLICAR' if apply else 'solo plan (dry-run)'}")
start = date.today() + timedelta(days=3)
engine = create_engine(args.database_url)
moved, skipped = [], []
with engine.begin() as connection:
    for event in seed.EVENTS:
        event_id, offset = event[0], event[3]
        row = connection.execute(text("""
            SELECT event_date,
                   (SELECT count(*) FROM reservations r WHERE r.event_id = e.id) +
                   (SELECT count(*) FROM tickets t WHERE t.event_id = e.id)
            FROM events e WHERE e.id = :id AND e.is_demo
        """), {"id": event_id}).one_or_none()
        if row is None or row[0] >= date.today():
            continue
        if row[1]:
            skipped.append(event_id)
            continue
        moved.append((event_id, row[0], start + timedelta(days=offset)))
        if apply:
            connection.execute(text("UPDATE events SET event_date = :d WHERE id = :id AND is_demo"), {"d": start + timedelta(days=offset), "id": event_id})
for event_id, old, new in moved:
    print(f"  evento {event_id}: {old} -> {new}")
print(f"{'Reprogramados' if apply else 'Se reprogramarían'}: {len(moved)} · omitidos por tener ventas: {len(skipped)} {skipped or ''}")
