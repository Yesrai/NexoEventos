#!/usr/bin/env python3
"""Registro de usuarios ficticios con diagnóstico: reintenta ante 5xx/cortes (como haría un cliente) y CONSERVA cada respuesta no exitosa como evidencia,
en lugar de abortar con un assert sin información."""
from pathlib import Path

p = Path(__file__).with_name("repl_test.py")
s = p.read_text()
if "def new_user(" not in s:
    helper = '''
def new_user(tag: str, addr=None):
    """Alta + login de un usuario ficticio. Las respuestas no exitosas se registran en DATA['incidencias_de_registro']; si no se logra tras 8 intentos, falla con la última respuesta."""
    u = fl.User(tag, addr=addr) if addr else fl.User(tag)
    last = None
    for attempt in range(8):
        try:
            st, js, srv = u._do("POST", "/api/auth/register", {"email": u.email, "display_name": "Lab ficticio", "password": fl.PWD}, timeout=10)
            if st == 201:
                st2, js2, _ = u._do("POST", "/api/auth/login", {"email": u.email, "password": fl.PWD}, timeout=10)
                if st2 == 200:
                    return u
                last = ("login", st2, js2)
            else:
                last = ("registro", st, js)
        except Exception as e:  # noqa: BLE001 - se registra
            last = ("excepcion", type(e).__name__, str(e)[:120])
        DATA.setdefault("incidencias_de_registro", []).append({"usuario": tag, "intento": attempt + 1, "respuesta": str(last)[:300], "t": round(time.time(), 2)})
        time.sleep(0.7)
    raise RuntimeError(f"no se pudo registrar al usuario ficticio {tag}: {last}")

'''
    marker = "def check(name, ok, detail=\"\"):"
    s = s.replace(marker, helper.lstrip("\n") + "\n" + marker, 1)
    s = s.replace('users = [fl.User(f"c{i}").register_login() for i in range(8)]', 'users = [new_user(f"c{i}") for i in range(8)]')
    s = s.replace('u = fl.User("cc", addr=("127.0.0.1", 18090)).register_login()', 'u = new_user("cc", addr=("127.0.0.1", 18090))')
    s = s.replace('uu = fl.User("d4").register_login()', 'uu = new_user("d4")')
    p.write_text(s)
print("ok")
