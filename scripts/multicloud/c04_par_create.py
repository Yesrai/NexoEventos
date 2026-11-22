#!/usr/bin/env python3
"""C-04: crea (o revoca) el PAR de ESCRITURA de OCI para el prefijo exclusivo de la prueba. Lo ejecuta SOLO la propietaria, desde su Mac, con su perfil DEFAULT.
Garantías (comprobadas en scripts/multicloud/tests/test_c04_par_create.py con una CLI y un portapapeles falsos):
  - la URL del PAR (secreto) vive solo en la memoria del proceso y en el PORTAPAPELES: nunca se imprime, no se escribe en archivos ni en argumentos de otros procesos
    (se entrega a `pbcopy` por la entrada estándar); la salida muestra solo metadatos (nombre, tipo, prefijo, caducidad, longitud);
  - región y perfil explícitos (sa-saopaulo-1, DEFAULT); tipo AnyObjectWrite (solo escritura, sin lectura ni listado); objeto = prefijo exclusivo; vida ≤ 100 min;
  - antes de crear: el bucket existe y es privado, no hay otro PAR y no es demasiado tarde (--not-after, margen de 120 min del laboratorio);
  - el formato de `access-uri` NO se supone: se valida (/p/…/o/<prefijo>, sin consulta) y se compone con el anfitrión de Object Storage de la región; si algo no cuadra, el PAR
    recién creado se REVOCA de inmediato;
  - `--revoke` borra el/los PAR con ese nombre (cierre de la ventana).
Uso:  python3 scripts/multicloud/c04_par_create.py [--not-after 2026-11-19T05:13:00Z]      |      python3 scripts/multicloud/c04_par_create.py --revoke"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import urllib.parse
from datetime import datetime, timedelta, timezone

PROFILE, REGION, BUCKET = "DEFAULT", "sa-saopaulo-1", "nexoeventos-recovery"
PREFIX, NAME, MINUTES = "backups/c04-20261119/", "c04-escritura-20261119", 100
HOST = f"https://objectstorage.{REGION}.oraclecloud.com"
TOKEN_RE = re.compile(r"^[A-Za-z0-9_\-=.~%+]{20,300}$")  # token opaco de OCI (base64url y similares); se valida forma y longitud, nunca se imprime
NS_RE = re.compile(r"^[A-Za-z0-9_\-]{1,100}$")


def _host_ok(host: str, ns: str) -> bool:
    """Anfitriones de Object Storage de la región autorizada: el regional y el dedicado por namespace (…oci.customer-oci.com). Cualquier otro se rechaza."""
    return host == f"objectstorage.{REGION}.oraclecloud.com" or host == f"{ns}.objectstorage.{REGION}.oci.customer-oci.com"


def parse_access_uri(value: str, ns: str) -> dict:
    """Descompone el access-uri (relativo `/p/…` o absoluto `https://…`) en componentes y devuelve booleanos de cada comprobación + la URL canónica si TODO cuadra.
    Admite el prefijo con `/` o codificado (`%2F`) y sin `/` final, pero exige token plausible, `/n/<namespace real>`, `/b/<bucket exacto>`, `/o/<prefijo exacto>` y, si es
    absoluto, https y un anfitrión de la región autorizada. Sin consulta, fragmento ni credenciales. La salida de diagnóstico son solo booleanos y la longitud del token."""
    r = {"relativo": False, "absoluto_https": False, "host_ok": None, "claves_p_n_b_o": False, "token_forma_ok": False, "token_longitud": 0, "ns_ok": False, "bucket_ok": False,
         "prefijo_ok": False, "prefijo_con_percent": False, "sin_consulta_ni_fragmento": False, "sin_credenciales": False, "canonica": None,
         # Sufijo tras `/o/` (solo estructura): permite distinguir «la ruta termina en /o/» de «contiene el prefijo» sin imprimir valores.
         "sufijo_longitud": 0, "sufijo_vacio": False, "sufijo_barra_inicial": False, "sufijo_barra_final": False, "sufijo_igual_prefijo": False,
         "sufijo_prefijo_parcial": False, "forma": None}
    if not isinstance(value, str) or not value or any(c.isspace() for c in value):
        return r
    u = urllib.parse.urlsplit(value)
    r["sin_consulta_ni_fragmento"] = not u.query and not u.fragment and "?" not in value and "#" not in value
    r["sin_credenciales"] = u.username is None and u.password is None
    if u.scheme:
        r["absoluto_https"] = u.scheme == "https"
        r["host_ok"] = bool(u.hostname) and _host_ok(u.hostname, ns) and u.port is None
    else:
        r["relativo"] = value.startswith("/") and not value.startswith("//")
    path = u.path
    seg = path.split("/")  # ['', 'p', token, 'n', ns, 'b', bucket, 'o', *prefijo]
    if len(seg) >= 9 and seg[0] == "" and (seg[1], seg[3], seg[5], seg[7]) == ("p", "n", "b", "o"):
        r["claves_p_n_b_o"] = True
        r["token_longitud"] = len(seg[2])
        r["token_forma_ok"] = bool(TOKEN_RE.match(seg[2])) and ".." not in seg[2]
        r["ns_ok"] = bool(NS_RE.match(seg[4])) and urllib.parse.unquote(seg[4]) == ns
        r["bucket_ok"] = urllib.parse.unquote(seg[6]) == BUCKET
        rest = "/".join(seg[8:])
        r["prefijo_con_percent"] = "%" in rest
        decoded = urllib.parse.unquote(rest)
        r["sufijo_longitud"] = len(decoded)
        r["sufijo_vacio"] = decoded == ""
        r["sufijo_barra_inicial"] = decoded.startswith("/")
        r["sufijo_barra_final"] = decoded.endswith("/")
        r["sufijo_igual_prefijo"] = decoded.rstrip("/") == PREFIX.rstrip("/")
        r["sufijo_prefijo_parcial"] = bool(decoded) and not r["sufijo_igual_prefijo"] and PREFIX.startswith(decoded)
        limpio = "//" not in decoded and ".." not in decoded
        # Dos formas aceptadas y NINGUNA otra:
        #  «igual»: la ruta ya trae el prefijo exacto (se normaliza solo `%2F`→`/` y la barra final).
        #  «vacio»: la ruta termina en `/o/` (el prefijo lo impone el servidor sobre el nombre del objeto, no va en la ruta). Se acepta porque la documentación de OCI dice que un PAR
        #  con prefijo permite PUT sobre nombres que EMPIECEN por el prefijo; el cliente concatena `PREFIX` + nombre. Que el servidor lo acepte lo prueba la sonda, no este análisis.
        r["forma"] = "igual" if (r["sufijo_igual_prefijo"] and limpio) else ("vacio" if r["sufijo_vacio"] else None)
        r["prefijo_ok"] = r["forma"] is not None
    scheme_ok = (r["relativo"] or (r["absoluto_https"] and r["host_ok"]))
    if scheme_ok and all(r[k] for k in ("claves_p_n_b_o", "token_forma_ok", "ns_ok", "bucket_ok", "prefijo_ok", "sin_consulta_ni_fragmento", "sin_credenciales")):
        # URL canónica: anfitrión regional + componentes validados, con el prefijo en barras normales y `/` final (backup_cycle concatena el nombre del objeto)
        r["canonica"] = f"{HOST}/p/{seg[2]}/n/{ns}/b/{BUCKET}/o/{PREFIX}"
    return r


def structure_report(r: dict) -> str:
    """Resumen NO sensible (solo booleanos y la longitud del token) de por qué se rechazó un access-uri."""
    keys = ("relativo", "absoluto_https", "host_ok", "claves_p_n_b_o", "token_forma_ok", "token_longitud", "ns_ok", "bucket_ok", "prefijo_ok", "prefijo_con_percent", "sufijo_longitud", "sufijo_vacio", "sufijo_barra_inicial", "sufijo_barra_final", "sufijo_igual_prefijo", "sufijo_prefijo_parcial", "forma", "sin_consulta_ni_fragmento", "sin_credenciales")
    return ", ".join(f"{k}={r[k]}" for k in keys)


class Abort(Exception):
    pass


def oci(args: list[str], *, check: bool = True) -> dict | list | None:
    cmd = ["oci", *args, "--profile", PROFILE, "--region", REGION]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=120, stdin=subprocess.DEVNULL, env={**__import__("os").environ, "SUPPRESS_LABEL_WARNING": "True"})
    if r.returncode != 0:
        if check:
            raise Abort("la CLI de OCI falló (código %d); no se muestra su salida por seguridad." % r.returncode)
        return None
    out = r.stdout.strip()
    return json.loads(out) if out else None


def namespace() -> str:
    cmd = ["oci", "os", "ns", "get", "--profile", PROFILE, "--region", REGION]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL, env={**__import__("os").environ, "SUPPRESS_LABEL_WARNING": "True"})
    if r.returncode != 0:
        raise Abort("no se pudo obtener el namespace (¿sesión OCI?).")
    return json.loads(r.stdout)["data"]


def copy_to_clipboard(text: str) -> None:
    subprocess.run(["pbcopy"], input=text.encode(), check=True, timeout=10)


def revoke_by_name(ns: str) -> int:
    """Borra los PAR con el nombre de C-04 (sin lanzar errores). Devuelve cuántos intentó borrar."""
    items = ((oci(["os", "preauth-request", "list", "--bucket-name", BUCKET, "--namespace-name", ns, "--all"], check=False) or {}).get("data")) or []
    mine = [i for i in items if i.get("name") == NAME and i.get("id")]
    for i in mine:
        oci(["os", "preauth-request", "delete", "--bucket-name", BUCKET, "--namespace-name", ns, "--par-id", i["id"], "--force"], check=False)
    return len(mine)


def create(not_after: datetime, now: datetime | None = None) -> None:
    now = now or datetime.now(timezone.utc)
    if now > not_after:
        raise Abort(f"demasiado tarde ({now:%H:%M} UTC > {not_after:%H:%M} UTC): no queda margen de 120 min del laboratorio; no se crea el PAR.")
    ns = namespace()
    b = oci(["os", "bucket", "get", "--bucket-name", BUCKET, "--namespace-name", ns])["data"]
    if b.get("public-access-type") != "NoPublicAccess":
        raise Abort("el bucket no es privado: no se continúa.")
    existing = oci(["os", "preauth-request", "list", "--bucket-name", BUCKET, "--namespace-name", ns, "--all"]) or {}
    if existing.get("data"):
        raise Abort("ya existe al menos un PAR en el bucket: no se crea otro (revisar o usar --revoke).")
    expires = (now + timedelta(minutes=MINUTES)).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        resp = oci(["os", "preauth-request", "create", "--bucket-name", BUCKET, "--namespace-name", ns, "--name", NAME, "--access-type", "AnyObjectWrite",
                    "--object-name", PREFIX, "--time-expires", expires])
        d = resp["data"]
    except (Abort, KeyError, TypeError, ValueError):
        if revoke_by_name(ns):  # la creación pudo completarse aunque la respuesta falló: no se deja ningún PAR huérfano
            raise Abort("la respuesta de la creación no se pudo interpretar. El PAR (si llegó a crearse) fue REVOCADO.")
        raise Abort("no se pudo crear el PAR (no quedó ninguno en el bucket).")
    par_id = d.get("id")

    def revoke_and_abort(why: str):
        if par_id:
            oci(["os", "preauth-request", "delete", "--bucket-name", BUCKET, "--namespace-name", ns, "--par-id", par_id, "--force"], check=False)
        raise Abort(why + " El PAR recién creado fue REVOCADO.")

    try:
        _finish(d, ns, revoke_and_abort)
    except Abort:
        raise
    except Exception as exc:  # noqa: BLE001 — ante cualquier error inesperado tras crear el PAR, se revoca (el mensaje no incluye datos de la respuesta)
        revoke_and_abort(f"error inesperado ({type(exc).__name__}).")


def _finish(d: dict, ns: str, revoke_and_abort) -> None:
    if d.get("access-type") != "AnyObjectWrite" or d.get("object-name") != PREFIX:
        revoke_and_abort("el PAR creado no tiene el tipo/prefijo esperados.")
    parsed = parse_access_uri(d.get("access-uri") or "", ns)
    if not parsed["canonica"]:  # segunda fuente: full-path de la API (por si el access-uri viene en otra forma)
        alt = parse_access_uri(d.get("full-path") or "", ns)
        if alt["canonica"]:
            parsed = alt
    if not parsed["canonica"]:
        print("Diagnóstico estructural (sin valores):", structure_report(parse_access_uri(d.get("access-uri") or "", ns)), file=sys.stderr)
        revoke_and_abort("el formato de access-uri no es el esperado.")
    url = parsed["canonica"]
    try:
        copy_to_clipboard(url)
    except (OSError, subprocess.SubprocessError):
        revoke_and_abort("no se pudo copiar al portapapeles.")
    full = d.get("full-path") or ""
    print("PAR creado (la URL NO se muestra):")
    print(f"  forma del access-uri: {parsed['forma']} ({'ruta terminada en /o/: se anexó el prefijo al construir la URL de trabajo' if parsed['forma'] == 'vacio' else 'la ruta ya traía el prefijo exacto'})")
    print(f"  nombre: {d.get('name')} | tipo: {d.get('access-type')} | prefijo: {d.get('object-name')}")
    print(f"  creado: {d.get('time-created')} | caduca: {d.get('time-expires')}")
    print(f"  URL en el portapapeles: {len(url)} caracteres (anfitrión {HOST.split('//')[1]}). ¿`full-path` de la API incluye el anfitrión? {'sí' if full.startswith('https://') else 'no'}")
    print("Ahora: pégala en la sesión SSM con `read -rs`, y vacía el portapapeles:  pbcopy < /dev/null")


def revoke() -> None:
    ns = namespace()
    items = (oci(["os", "preauth-request", "list", "--bucket-name", BUCKET, "--namespace-name", ns, "--all"]) or {}).get("data") or []
    mine = [i for i in items if i.get("name") == NAME]
    if not mine:
        print("No hay PAR con ese nombre (ya revocado o nunca creado).")
        return
    for i in mine:
        oci(["os", "preauth-request", "delete", "--bucket-name", BUCKET, "--namespace-name", ns, "--par-id", i["id"], "--force"])
    left = (oci(["os", "preauth-request", "list", "--bucket-name", BUCKET, "--namespace-name", ns, "--all"]) or {}).get("data") or []
    print(f"PAR revocado(s): {len(mine)}. Quedan {len(left)} PAR en el bucket.")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--revoke", action="store_true")
    ap.add_argument("--not-after", default="2026-11-19T05:13:00Z", help="no crear el PAR después de esta hora UTC (margen de 120 min del laboratorio)")
    a = ap.parse_args(argv)
    try:
        if a.revoke:
            revoke()
        else:
            create(datetime.fromisoformat(a.not_after.replace("Z", "+00:00")))
    except Abort as e:
        print("ABORTA:", e, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
