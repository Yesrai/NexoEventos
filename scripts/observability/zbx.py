"""Cliente mínimo de la API JSON-RPC de Zabbix 7.0 (solo biblioteca estándar). Nunca imprime tokens ni contraseñas."""
from __future__ import annotations
import json
import ssl
import urllib.request


class Zabbix:
    def __init__(self, url: str, token: str | None = None, insecure_tls: bool = False):
        self.url = url.rstrip("/") + "/api_jsonrpc.php"
        self.token = token
        self.ctx = ssl._create_unverified_context() if insecure_tls else None   # certificado autofirmado de la demostración
        self._id = 0

    def call(self, method: str, params=None, auth: bool = True):
        self._id += 1
        headers = {"Content-Type": "application/json-rpc"}
        if auth and self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        body = json.dumps({"jsonrpc": "2.0", "method": method, "params": params if params is not None else {}, "id": self._id}).encode()
        with urllib.request.urlopen(urllib.request.Request(self.url, body, headers), timeout=60, context=self.ctx) as r:
            out = json.load(r)
        if "error" in out:
            e = out["error"]
            raise RuntimeError(f"Zabbix API {method}: {e.get('message')} {e.get('data')}")
        return out["result"]

    def login(self, user: str, password: str):
        self.token = self.call("user.login", {"username": user, "password": password}, auth=False)
        return self.token
