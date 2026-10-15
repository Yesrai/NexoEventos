#!/usr/bin/env python3
"""Añade o reemplaza fotografías del catálogo demo desde Wikimedia Commons con licencia verificada.

- Solo acepta licencias CC BY, CC BY-SA, CC0 o dominio público (se lee del propio archivo en la API de Commons).
- Descarga una miniatura de 1600 px de ancho a frontend/public/events/<slug>.jpg.
- Conserva la atribución: agrega o reemplaza SOLO la fila de ese archivo en docs/atribuciones-imagenes.md.
- Con --apply-db asigna la imagen a los eventos indicados (solo events.image_path; nada más).
Uso: python scripts/add-demo-images.py [--apply-db] [--database-url postgresql+psycopg:///nexoeventos]
"""
from __future__ import annotations

import argparse
import html
import json
import re
import ssl
import time
import urllib.parse
import urllib.request
from pathlib import Path

import certifi

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "frontend" / "public" / "events"
ATTRIBUTIONS = ROOT / "docs" / "atribuciones-imagenes.md"
API = "https://commons.wikimedia.org/w/api.php"
TLS = ssl.create_default_context(cafile=certifi.where())
HEADERS = {"User-Agent": "NexoEventos-academic/1.0 (proyecto academico)"}
ALLOWED = ("CC BY", "CC0", "Public domain")
# slug local, archivo de Commons, eventos que lo usan
IMAGES = [
    ("concert-arena-lights", "File:Beach-Please-2022-crowd-stage-lights-night-performance.jpg", [1031]),
    ("stadium-match", "File:Crowd at Dora Stadium.jpg", [1030]),
    ("auditorium-seats", "File:Regent Hokitika Interior MRD 12.jpg", [1028]),
    ("kids-electronics", "File:Electronics experiments LPB Laos.jpg", [1024]),
    ("conference-panel", "File:Panelists answering questions during a Wikimania 2026 session. - Wikimania 2026 - Paris by @JJxFile 0017 09.jpg", [1019]),
]


def get(url: str) -> bytes:
    time.sleep(1.5)
    with urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS), context=TLS, timeout=60) as response:
        return response.read()


def clean(value: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", value))).strip()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply-db", action="store_true")
    parser.add_argument("--database-url", default="postgresql+psycopg:///nexoeventos")
    args = parser.parse_args()
    rows = ATTRIBUTIONS.read_text(encoding="utf-8").splitlines()
    for slug, title, event_ids in IMAGES:
        query = urllib.parse.urlencode({"action": "query", "format": "json", "titles": title, "prop": "imageinfo", "iiprop": "url|size|extmetadata", "iiurlwidth": "1600"})
        page = next(iter(json.loads(get(f"{API}?{query}"))["query"]["pages"].values()))
        info = page["imageinfo"][0]
        meta = info["extmetadata"]
        license_name = clean(meta.get("LicenseShortName", {}).get("value", ""))
        if not any(license_name.startswith(prefix) for prefix in ALLOWED):
            raise SystemExit(f"Licencia no permitida para {title}: {license_name!r}")
        author = clean(meta.get("Artist", {}).get("value", "")) or "Autor no indicado"
        (OUTPUT / f"{slug}.jpg").write_bytes(get(info["thumburl"]))
        link = "https://commons.wikimedia.org/wiki/" + urllib.parse.quote(title.replace(" ", "_"), safe=":/(),")
        row = f"| `frontend/public/events/{slug}.jpg` | [{title[5:]}]({link}) | {author} | {license_name}; miniatura de 1600 px |"
        rows = [line for line in rows if f"`frontend/public/events/{slug}.jpg`" not in line]
        rows.append(row)
        print(f"{slug}: {license_name} · {info['width']}x{info['height']} · {author[:40]}")
    ATTRIBUTIONS.write_text("\n".join(rows) + "\n", encoding="utf-8")
    if args.apply_db:
        from sqlalchemy import create_engine, text

        with create_engine(args.database_url).begin() as connection:
            for slug, _title, event_ids in IMAGES:
                for event_id in event_ids:
                    connection.execute(text("UPDATE events SET image_path = :p WHERE id = :id AND is_demo"), {"p": f"/events/{slug}.jpg", "id": event_id})
        print("image_path actualizado solo en los eventos indicados")


if __name__ == "__main__":
    main()
