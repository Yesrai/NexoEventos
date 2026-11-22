#!/usr/bin/env python3
"""Aplica a compose.tmpl.yml el arranque cerrado de PostgreSQL (parts/lab-entry.sh). Idempotente."""
from pathlib import Path

p = Path(__file__).with_name("compose.tmpl.yml")
s = p.read_text()
if "lab-entry.sh" not in s:
    s = s.replace("x-pg: &pg\n  image: postgres:18\n", 'x-pg: &pg\n  image: postgres:18\n  entrypoint: ["/bin/bash", "/lab-entry.sh"]   # arranque cerrado: ver parts/lab-entry.sh\n')
    s = s.replace("    - {source: db_init, target: /docker-entrypoint-initdb.d/10-roles.sql, mode: 0444}\n  environment:\n    POSTGRES_PASSWORD: lab-local-only-admin",
                  "    - {source: db_init, target: /docker-entrypoint-initdb.d/10-roles.sql, mode: 0444}\n    - {source: lab_entry, target: /lab-entry.sh, mode: 0444}\n  environment:\n    POSTGRES_PASSWORD: lab-local-only-admin")
    for n in ("aws", "oci"):
        s = s.replace(f"  pg-{n}:\n    <<: *pg\n", f"  pg-{n}:\n    <<: *pg\n    environment: {{POSTGRES_PASSWORD: lab-local-only-admin, NODE_NAME: pg-{n}}}\n")
    s = s.replace("  witness_py:\n    content: |", "  lab_entry:\n    content: |\n@@parts/lab-entry.sh@@\n  witness_py:\n    content: |")
    p.write_text(s)
print("ok")
