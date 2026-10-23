#!/usr/bin/env python3
"""En la VM de contingencia (como root, con el entorno de la aplicación cargado): actualiza EXCLUSIVAMENTE el password_hash de dos cuentas de demostración de la copia desechable.
Recibe por stdin un JSON {correo: hash_argon2}; nunca imprime hashes ni contraseñas. Falla (sin confirmar) si hay filas distintas de 2 o si cambian otras cuentas."""
import json, os, sys
import psycopg

ALLOWED = {"operador.demo@example.com": "operator", "smoke-1791073267-26124@example.com": "client"}
data = json.load(sys.stdin)
if set(data) != set(ALLOWED) or not all(isinstance(h, str) and h.startswith("$argon2") for h in data.values()):
    sys.exit("Entrada inválida: se esperan exactamente las dos cuentas autorizadas con hashes Argon2")
env = dict(l.rstrip("\n").split("=", 1) for l in open("/run/nexoeventos/backend.env") if "=" in l and not l.startswith("#"))   # se lee solo DATABASE_URL (no se imprime)
url = env["DATABASE_URL"].replace("postgresql+psycopg://", "postgresql://")
OTHERS = "select count(*), md5(coalesce(string_agg(password_hash, ',' order by id::text), '')) from users where email <> all(%s)"
with psycopg.connect(url) as conn, conn.cursor() as cur:
    cur.execute(OTHERS, (list(ALLOWED),)); before = cur.fetchone()
    for email, h in data.items():
        cur.execute("update users set password_hash=%s where email=%s and role=%s and is_active", (h, email, ALLOWED[email]))
        if cur.rowcount != 1:
            raise SystemExit(f"Se esperaba 1 fila para la cuenta autorizada ({ALLOWED[email]}); no se confirma el cambio")
    cur.execute(OTHERS, (list(ALLOWED),)); after = cur.fetchone()
    if before != after:
        raise SystemExit("Cambiaron otras cuentas; no se confirma")
print(json.dumps({"filas_actualizadas": 2, "otras_cuentas": before[0], "hash_de_hashes_de_otras_cuentas_igual": before == after}))
