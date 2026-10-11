#!/usr/bin/env python3
"""Valida localmente el alcance y la minimización de logs de EV08."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    template_path = ROOT / "ansible/roles/nexoeventos_observability/templates/amazon-cloudwatch-agent.json.j2"
    rendered = template_path.read_text()
    replacements = {
        "{{ nexoeventos_cloudwatch_region }}": "us-east-1",
        "{{ nexoeventos_environment }}": "academy",
        "{{ nexoeventos_api_log }}": "/var/log/nexoeventos/api.log",
        "{{ nexoeventos_nginx_access_log }}": "/var/log/nginx/nexoeventos-access.log",
        "{{ nexoeventos_nginx_error_log }}": "/var/log/nginx/nexoeventos-error.log",
    }
    for source, target in replacements.items():
        rendered = rendered.replace(source, target)
    config = json.loads(rendered)
    assert "retention_in_days" not in rendered
    assert config["agent"] == {"debug": False, "region": "us-east-1", "run_as_user": "root"}
    entries = config["logs"]["logs_collected"]["files"]["collect_list"]
    assert {entry["file_path"] for entry in entries} == {
        "/var/log/nexoeventos/api.log",
        "/var/log/nginx/nexoeventos-access.log",
        "/var/log/nginx/nexoeventos-error.log",
    }
    assert all("initial_position" not in entry for entry in entries)
    assert len({(entry["log_group_name"], entry["log_stream_name"]) for entry in entries}) == 3

    nginx = (ROOT / "ansible/roles/nexoeventos/templates/nexoeventos-nginx.conf.j2").read_text()
    log_format = nginx.split("server {", 1)[0]
    assert "$uri" in log_format
    for forbidden in ("$request ", "$args", "$query_string", "$http_", "$cookie_", "$remote_addr"):
        assert forbidden not in log_format, f"dato sensible en log_format: {forbidden}"

    service = (ROOT / "ansible/roles/nexoeventos/templates/nexoeventos-api.service.j2").read_text()
    assert "--no-access-log" in service
    assert "StandardOutput=append:/var/log/nexoeventos/api.log" in service
    assert "StandardError=append:/var/log/nexoeventos/api.log" in service
    print("Configuración EV08 válida: tres fuentes reales, mínimo de datos y retención externa.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
