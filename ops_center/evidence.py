"""Recolector de evidencias de las pruebas Cloud (T1–T8). Escribe SOLO en un directorio local nuevo (0700); no llama a ninguna nube por sí mismo.
Guarda: timestamps UTC (ms) de cada evento, marcas con nombre (para RTO/RPO), muestras de salud, capturas de texto saneadas y archivos adjuntos con SHA-256, valores medidos por criterio,
y un veredicto HONESTO: PASS solo si TODOS los criterios están medidos y cumplidos; FAIL si alguno medido no se cumple; PARCIAL si falta medir alguno (nunca se promueve a PASS).
Las capturas de pantalla se adjuntan solo con `redacted=True` (el operador confirma que se ocultaron identificadores); si no, quedan marcadas «pendiente de redacción» y el veredicto no puede ser PASS."""
from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

_SECRET = re.compile(r"https?://\S+|\b\d{1,3}(?:\.\d{1,3}){3}\b|ocid1\.\S+|arn:aws:\S+|AKIA[0-9A-Z]{12,}|/p/[A-Za-z0-9_-]{6,}|-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----|(?i:bearer\s+\S+)|(?i:(?:token|password|secret)\s*[=:]\s*\S+)")
KINDS = ("max", "min", "bool")


def scrub(text: str, limit: int = 4000) -> str:
    return _SECRET.sub("[oculto]", str(text))[:limit]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc)


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""): h.update(chunk)
    return h.hexdigest()


class EvidenceError(Exception):
    pass


def _write(path: Path, data, mode=0o600):
    fd = os.open(path, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, mode)
    with os.fdopen(fd, "w") as f:
        f.write(data if isinstance(data, str) else json.dumps(data, ensure_ascii=False, indent=1))


class EvidenceRun:
    def __init__(self, dir_: Path, meta: dict):
        self.dir, self.meta = Path(dir_), meta
        self.marks: dict[str, str] = {k: v for k, v in meta.get("marks", {}).items()}

    # -------- ciclo de vida --------
    @classmethod
    def start(cls, root, stage: str, title: str, criteria: list[dict], clock=utc_now):
        if not re.fullmatch(r"T[1-8]", stage):
            raise EvidenceError("etapa inválida (T1–T8)")
        ids = set()
        for c in criteria:
            if c.get("kind") not in KINDS or not c.get("id") or c["id"] in ids or (c["kind"] != "bool" and not isinstance(c.get("threshold"), (int, float))):
                raise EvidenceError(f"criterio inválido: {c.get('id')}")
            ids.add(c["id"])
        if not criteria:
            raise EvidenceError("una prueba sin criterios de aceptación no se registra")
        now = clock()
        d = Path(root) / f"{stage}-{now.strftime('%Y%m%dT%H%M%SZ')}-{secrets.token_hex(2)}"
        d.mkdir(parents=True, mode=0o700); (d / "capturas").mkdir(mode=0o700)
        meta = {"stage": stage, "title": scrub(title, 200), "started_utc": iso(now), "criteria": criteria, "values": {}, "marks": {}, "attachments": []}
        r = cls(d, meta); r._save(); r.event("inicio", titulo=meta["title"]); return r

    @classmethod
    def open(cls, dir_):
        return cls(Path(dir_), json.loads((Path(dir_) / "meta.json").read_text()))

    def _save(self):
        self.meta["marks"] = self.marks; _write(self.dir / "meta.json", self.meta)

    def _check_open(self):
        if (self.dir / "resultado.json").exists():
            raise EvidenceError("la corrida ya está cerrada")

    # -------- registro --------
    def event(self, name: str, clock=utc_now, **data) -> dict:
        self._check_open()
        e = {"t_utc": iso(clock()), "evento": scrub(name, 80), "datos": {str(k)[:40]: scrub(v, 300) if isinstance(v, str) else v for k, v in data.items()}}
        with open(self.dir / "events.jsonl", "a") as f:
            f.write(json.dumps(e, ensure_ascii=False) + "\n"); f.flush(); os.fsync(f.fileno())
        os.chmod(self.dir / "events.jsonl", 0o600); return e

    def mark(self, name: str, clock=utc_now) -> str:
        if not re.fullmatch(r"[a-z0-9_]{2,40}", name):
            raise EvidenceError("nombre de marca inválido")
        if name in self.marks:
            raise EvidenceError("la marca ya existe (no se reescribe)")
        t = iso(clock()); self.marks[name] = t; self._save(); self.event("marca", nombre=name); return t

    def seconds_between(self, a: str, b: str):
        if a not in self.marks or b not in self.marks:
            return None
        return round((parse(self.marks[b]) - parse(self.marks[a])).total_seconds(), 3)

    def sample(self, target: str, ok, latency_ms=None, status=None, clock=utc_now):
        """Muestra de salud: ok True/False/None (None = desconocido; no cuenta como sano)."""
        with open(self.dir / "salud.jsonl", "a") as f:
            f.write(json.dumps({"t_utc": iso(clock()), "objetivo": scrub(target, 60), "ok": ok, "ms": latency_ms, "estado": status}) + "\n")
        os.chmod(self.dir / "salud.jsonl", 0o600)

    def probe_http(self, target: str, url: str, timeout=3.0):
        import ssl
        ctx = ssl.create_default_context()
        if not ctx.get_ca_certs():
            try:
                import certifi
                ctx = ssl.create_default_context(cafile=certifi.where())
            except ImportError:
                pass
        t0 = time.monotonic()
        try:
            with urllib.request.urlopen(url, timeout=timeout, context=ctx) as r: ok, st = 200 <= r.status < 300, r.status
        except urllib.error.HTTPError as e: ok, st = False, e.code
        except Exception: ok, st = False, None  # noqa: BLE001
        self.sample(target, ok, round((time.monotonic() - t0) * 1000, 1), st); return ok

    def availability(self, target: str):
        rows = [json.loads(l) for l in (self.dir / "salud.jsonl").read_text().splitlines()] if (self.dir / "salud.jsonl").exists() else []
        rows = [r for r in rows if r["objetivo"] == target]
        return None if not rows else round(100.0 * sum(1 for r in rows if r["ok"] is True) / len(rows), 2)

    def capture_text(self, name: str, text: str):
        self._check_open()
        if not re.fullmatch(r"[\w.-]{1,60}", name): raise EvidenceError("nombre de captura inválido")
        p = self.dir / "capturas" / f"{name}.txt"; _write(p, scrub(text, 100000))
        self.meta["attachments"].append({"archivo": p.name, "sha256": sha256_file(p), "tipo": "texto saneado", "redactado": True}); self._save(); self.event("captura_texto", nombre=name)

    def attach(self, path, redacted: bool = False):
        self._check_open(); src = Path(path)
        if not src.is_file() or src.stat().st_size > 50 * 1024 * 1024: raise EvidenceError("archivo inexistente o mayor de 50 MB")
        dst = self.dir / "capturas" / re.sub(r"[^\w.-]", "_", src.name)
        dst.write_bytes(src.read_bytes()); os.chmod(dst, 0o600)
        self.meta["attachments"].append({"archivo": dst.name, "sha256": sha256_file(dst), "tipo": "adjunto", "redactado": bool(redacted)}); self._save(); self.event("adjunto", nombre=dst.name, redactado=bool(redacted))

    def value(self, criterion_id: str, v, note: str = ""):
        self._check_open()
        c = next((c for c in self.meta["criteria"] if c["id"] == criterion_id), None)
        if not c: raise EvidenceError("criterio desconocido")
        if c["kind"] == "bool" and not isinstance(v, bool): raise EvidenceError("este criterio requiere true/false")
        if c["kind"] != "bool" and (isinstance(v, bool) or not isinstance(v, (int, float))): raise EvidenceError("este criterio requiere un número")
        self.meta["values"][criterion_id] = {"valor": v, "nota": scrub(note, 200), "t_utc": iso(utc_now())}; self._save(); self.event("valor", criterio=criterion_id, valor=v)

    # -------- cierre --------
    def finish(self) -> dict:
        self._check_open(); rows, pend_redact = [], [a["archivo"] for a in self.meta["attachments"] if not a["redactado"]]
        for c in self.meta["criteria"]:
            v = self.meta["values"].get(c["id"])
            if v is None: res = "SIN_MEDIR"
            elif c["kind"] == "bool": res = "CUMPLE" if v["valor"] is True else "NO_CUMPLE"
            elif c["kind"] == "max": res = "CUMPLE" if v["valor"] <= c["threshold"] else "NO_CUMPLE"
            else: res = "CUMPLE" if v["valor"] >= c["threshold"] else "NO_CUMPLE"
            rows.append({"id": c["id"], "descripcion": c.get("desc", ""), "regla": c["kind"] + (f" {c['threshold']}" if c["kind"] != "bool" else ""), "valor": (v or {}).get("valor"), "resultado": res})
        if any(r["resultado"] == "NO_CUMPLE" for r in rows): verdict = "FAIL"
        elif any(r["resultado"] == "SIN_MEDIR" for r in rows) or pend_redact: verdict = "PARCIAL"
        else: verdict = "PASS"
        end = utc_now()
        res = {"etapa": self.meta["stage"], "titulo": self.meta["title"], "inicio_utc": self.meta["started_utc"], "fin_utc": iso(end), "veredicto": verdict, "criterios": rows, "marcas": self.marks,
               "sin_redactar": pend_redact, "nota": "PASS exige todos los criterios medidos y cumplidos y todas las capturas redactadas; PARCIAL nunca es PASS"}
        self.event("fin", veredicto=verdict, clock=lambda: end)
        _write(self.dir / "resultado.json", res)
        md = [f"# {res['etapa']} — {res['titulo']}", f"Veredicto: **{verdict}** · {res['inicio_utc']} → {res['fin_utc']} (UTC)", "", "| Criterio | Regla | Valor | Resultado |", "|---|---|---|---|"]
        md += [f"| {r['id']} · {r['descripcion']} | {r['regla']} | {r['valor']} | {r['resultado']} |" for r in rows]
        if self.marks: md += ["", "Marcas (UTC): " + ", ".join(f"{k}={v}" for k, v in self.marks.items())]
        if pend_redact: md += ["", "Capturas sin redactar: " + ", ".join(pend_redact)]
        _write(self.dir / "resultado.md", "\n".join(md) + "\n")
        man = [f"{sha256_file(p)}  {p.relative_to(self.dir)}" for p in sorted(self.dir.rglob("*")) if p.is_file() and p.name != "MANIFIESTO.sha256"]
        _write(self.dir / "MANIFIESTO.sha256", "\n".join(man) + "\n"); return res


def verify_manifest(dir_) -> dict:
    d = Path(dir_); man = d / "MANIFIESTO.sha256"
    if not man.is_file(): return {"ok": False, "error": "sin manifiesto"}
    bad = []
    for line in man.read_text().splitlines():
        h, _, rel = line.partition("  ")
        p = d / rel
        if not p.is_file() or sha256_file(p) != h: bad.append(rel)
    return {"ok": not bad, "alterados": bad}
