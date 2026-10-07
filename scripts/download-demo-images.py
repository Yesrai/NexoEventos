#!/usr/bin/env python3
"""Download pinned Wikimedia Commons thumbnails and record their licenses."""
from __future__ import annotations

import html
import json
import re
import ssl
import urllib.parse
import urllib.request
from pathlib import Path

import certifi

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "frontend" / "public" / "events"
ATTRIBUTIONS = ROOT / "docs" / "atribuciones-imagenes.md"
API = "https://commons.wikimedia.org/w/api.php"
TLS = ssl.create_default_context(cafile=certifi.where())
FILES = [
    ("concert-live", "File:Musicians perform on stage during live concert.jpg"),
    ("concert-stage", "File:Heritage Live concert crowd and stage at Sandringham 2023 - geograph.org.uk - 7586057.jpg"),
    ("concert-energy", "File:Stage diving.jpg"),
    ("dance-stage", "File:783 3 (+ 3) dancers performing on stage V-P.jpg"),
    ("open-theater", "File:Kreta (GR), Rethymno, Fortezza, Theater -- 2023 -- 8243.jpg"),
    ("theater-performance", "File:LEFTOVER- Theater Performance from Garage Theater Company 33.jpg"),
    ("standup-stage", "File:FSS hosts stand-up comic 210826-F-JW594-2053.jpg"),
    ("standup-microphone", "File:Standup Shot Template.jpg"),
    ("standup-room", "File:Davidsidmancomedyphoto.jpg"),
    ("pottery-hands", "File:Bolesławiec pottery workshop at Wikimania 2024 04.jpg"),
    ("pottery-table", "File:Bolesławiec pottery workshop at Wikimania 2024 05.jpg"),
    ("pottery-detail", "File:Bolesławiec pottery workshop at Wikimania 2024 06.jpg"),
    ("food-cheese", "File:Cheese - food fair london.jpg"),
    ("food-fair", "File:Food at a folk art fair on Rynek Główny in Kraków 02.jpg"),
    ("food-organic", "File:Tomato varieties at Porto Alegre organic food fair - Brazil.jpg"),
    ("food-local-fair", "File:DFC 3508 A bustling night market food stall displaying bowls of fresh vegetables herbs and colorful produce while a vendor prepares dishes behind the counter.jpg"),
    ("running-field", "File:7° B.Est cross country - 2018.jpg"),
    ("running-race", "File:A high school cross country runner runs during a race at a meet in North Carolina 01.jpg"),
    ("running-road", "File:September 2002, Running race in Rennes.jpg"),
    ("conference-speaker", "File:Person speaking at the conference.jpg"),
    ("festival-stage", "File:Live music performance at a summer festival with energetic crowd and talented musicians on stage.jpg"),
    ("art-exhibition", "File:Exhibition of Alfrid Shaimardanov (2021-05-15) 01.jpg"),
    ("networking-professionals", "File:British Asian professionals at a networking event in the City of London.jpg"),
    ("cooking-workshop", "File:Cooking workshop at Nina community centre, Herzliya.jpg"),
    ("children-workshop", "File:EduWiki Workshop \"Children and Wikis\" October 2025 03.jpg"),
    ("cinema-room", "File:Landmark's Atlantic Plumbing Cinema screening room.jpg"),
    ("technology-exhibition", "File:15th Iran Media Technology Exhibition & Conference (02).jpg"),
    ("culture-museum", "File:SZ Shenzhen Futian Shennan Middle Road Shenzhen Museum Ancient Art Museum 深圳博物馆陶瓷器展 exhibition of Chinaware Culture March 2025 R12S 802.jpg"),
]


def plain(value: str | None) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", html.unescape(value or ""))).strip()


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    rows = [
        "# Atribuciones de imágenes del catálogo demo",
        "",
        "Las fotografías son ilustrativas y no representan eventos reales anunciados por NexoEventos. Se descargan desde Wikimedia Commons a un ancho máximo de 1200 px.",
        "",
        "| Archivo local | Fuente | Autor/crédito | Licencia |",
        "|---|---|---|---|",
    ]
    params = urllib.parse.urlencode({
        "action": "query", "titles": "|".join(title for _, title in FILES), "prop": "imageinfo",
        "iiprop": "url|extmetadata", "iiurlwidth": "1200", "format": "json", "formatversion": "2",
    })
    request = urllib.request.Request(f"{API}?{params}", headers={"User-Agent": "NexoEventosAcademicDemo/1.0 (academic project)"})
    with urllib.request.urlopen(request, timeout=30, context=TLS) as response:
        pages = {page["title"]: page for page in json.load(response)["query"]["pages"]}
    for slug, title in FILES:
        page = pages[title]
        info = page["imageinfo"][0]
        metadata = info.get("extmetadata", {})
        image_url = info.get("thumburl") or info["url"]
        destination = OUTPUT / f"{slug}.jpg"
        if not destination.exists():
            download = urllib.request.Request(image_url, headers={"User-Agent": "NexoEventosAcademicDemo/1.0 (academic project)"})
            with urllib.request.urlopen(download, timeout=60, context=TLS) as response:
                destination.write_bytes(response.read())
        destination.chmod(0o644)
        source = info["descriptionurl"]
        artist = plain(metadata.get("Artist", {}).get("value")) or "Consultar la ficha de Commons"
        license_name = plain(metadata.get("LicenseShortName", {}).get("value")) or "Consultar la ficha de Commons"
        rows.append(f"| `frontend/public/events/{destination.name}` | [{title.removeprefix('File:')}]({source}) | {artist.replace('|', '/')} | {license_name.replace('|', '/')} |")
    ATTRIBUTIONS.write_text("\n".join(rows) + "\n", encoding="utf-8")
    print(f"Imágenes descargadas: {len(FILES)}; atribuciones: {ATTRIBUTIONS}")


if __name__ == "__main__":
    main()
