#!/usr/bin/env python3
"""Genera compose.yml incrustando parts/* (Docker Desktop no deja montar archivos de esta carpeta, así que van como configs en línea)."""
import re
from pathlib import Path
here = Path(__file__).parent
t = (here / "compose.tmpl.yml").read_text()
def sub(m):
    body = (here / m.group(1)).read_text()
    assert "$" not in body.replace("$$", ""), f"{m.group(1)} contiene $ (interpolación de Compose)"
    return "".join(("      " + l if l.strip() else "\n") for l in body.splitlines(True))
(here / "compose.yml").write_text(re.sub(r"^@@(.+?)@@$", sub, t, flags=re.M))
