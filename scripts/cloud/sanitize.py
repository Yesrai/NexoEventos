#!/usr/bin/env python3
"""Sanitiza JSON/texto de AWS antes de usarlo como evidencia.

Enmascara IDs de cuenta, ARN, IDs de recursos, IPv4 públicas, endpoints RDS,
nombres de bucket con cuenta y claves de valor sensible. Conserva CIDR privados
de diseño (10.x) porque forman parte de la arquitectura documentada.
Uso: sanitize.py < entrada > salida
"""
import ipaddress
import json
import re
import sys

SENSITIVE_KEYS = re.compile(r"(?i)(password|secret|token|cookie|authorization|credential|privatekey|accesskey)")
INLINE_SENSITIVE = re.compile(r'(?i)("[^"]*(?:password|secret|token|cookie|authorization|credential|privatekey|accesskey)[^"]*"\s*:\s*)"[^"]*"')
RULES = [
    (re.compile(r"arn:aws[a-z-]*:[a-z0-9-]*:[a-z0-9-]*:\d{12}:[^\s\"]+"), "arn:aws:…(oculto)"),
    (re.compile(r"\b[a-z0-9-]+\.[a-z0-9]+\.[a-z0-9-]+\.rds\.amazonaws\.com\b"), "<endpoint-rds-oculto>"),
    (re.compile(r"\b(i|vpc|subnet|sg|sgr|rtb|rtbassoc|igw|eni|acl|vol|snap|ami|r|dopt|eipalloc)-([0-9a-f]{8,17})\b"),
     lambda m: f"{m.group(1)}-…{m.group(2)[-4:]}"),
    (re.compile(r"(?<![\d.])\d{12}(?![\d.])"), "<cuenta>"),
    (re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"), None),  # IPv4: tratamiento especial
]


def mask_ipv4(match: re.Match) -> str:
    text = match.group(0)
    try:
        ip = ipaddress.ip_address(text)
    except ValueError:
        return text
    if ip.is_private or ip.is_unspecified or ip.is_loopback or text.startswith("169.254."):
        return text
    parts = text.split(".")
    return f"{parts[0]}.{parts[1]}.x.x"


def sanitize_string(value: str) -> str:
    line = INLINE_SENSITIVE.sub(r'\1"<oculto>"', value)
    for pattern, repl in RULES:
        line = pattern.sub(mask_ipv4 if repl is None else repl, line)
    return line


def sanitize_json(value, key: str = ""):
    if key and SENSITIVE_KEYS.search(key):
        return "<oculto>"
    if isinstance(value, dict):
        return {k: sanitize_json(v, str(k)) for k, v in value.items()}
    if isinstance(value, list):
        return [sanitize_json(item) for item in value]
    if isinstance(value, str):
        return sanitize_string(value)
    return value


def sanitize(text: str) -> str:
    # AWS CLI produce JSON para las evidencias. Parsearlo primero evita dejar JSON
    # inválido cuando una clave sensible contiene un objeto o una lista anidados.
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        out_lines = []
        for line in text.splitlines():
            key = line.split(":", 1)[0]
            if SENSITIVE_KEYS.search(key) and ":" in line:
                out_lines.append(f"{key}: <oculto>")
            else:
                out_lines.append(sanitize_string(line))
        return "\n".join(out_lines) + ("\n" if text.endswith("\n") else "")
    return json.dumps(sanitize_json(parsed), indent=2, ensure_ascii=False) + "\n"


if __name__ == "__main__":
    sys.stdout.write(sanitize(sys.stdin.read()))
