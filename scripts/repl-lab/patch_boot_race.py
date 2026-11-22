#!/usr/bin/env python3
"""Evita la carrera de arranque: PostgreSQL espera a que el witness esté sano y el arranque cerrado reintenta unos segundos antes de decidir 'falla cerrada'."""
from pathlib import Path

here = Path(__file__).parent
s = (here / "compose.tmpl.yml").read_text()
if "service_healthy" not in s:
    s = s.replace('  entrypoint: ["/bin/bash", "/lab-entry.sh"]   # arranque cerrado: ver parts/lab-entry.sh\n',
                  '  entrypoint: ["/bin/bash", "/lab-entry.sh"]   # arranque cerrado: ver parts/lab-entry.sh\n  depends_on:\n    witness: {condition: service_healthy}\n')
    s = s.replace('    volumes: ["witness-data:/data"]\n    ports: ["127.0.0.1:18100:8000"]',
                  '    volumes: ["witness-data:/data"]\n    healthcheck:\n      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen(\'http://127.0.0.1:8000/state\', timeout=2)"]\n      interval: 1s\n      timeout: 3s\n      retries: 30\n    ports: ["127.0.0.1:18100:8000"]')
    (here / "compose.tmpl.yml").write_text(s)

e = (here / "parts/lab-entry.sh").read_text()
if "for try in" not in e:
    old = "body=$$( (exec 3<>/dev/tcp/172.29.241.10/8000 && printf 'GET /state HTTP/1.0\\r\\n\\r\\n' >&3 && timeout 3 cat <&3) 2>/dev/null )\n"
    assert old in e
    new = ("for try in 1 2 3 4; do\n  " + old.rstrip("\n") + "\n  [ -n \"$$body\" ] && break\n  sleep 1\ndone\n")
    (here / "parts/lab-entry.sh").write_text(e.replace(old, new))
print("ok")
