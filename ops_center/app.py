"""API del centro de operaciones (FastAPI). Autenticación por token Bearer (identidades propias, sin cookies ⇒ sin CSRF), sin CORS, cabeceras estrictas.
NINGÚN endpoint ejecuta nada: solo consulta, solicita, valida, aprueba/deniega y audita."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from . import barriers as B, identities as I, recovery as R, status as S
from .audit import AuditLog
from .settings import Settings

STATIC = Path(__file__).resolve().parent / "static"
HEADERS = {"Content-Security-Policy": "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'",
           "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer", "Cache-Control": "no-store", "X-Frame-Options": "DENY"}


class NewRequest(BaseModel):
    tipo: str = Field(max_length=48)
    reason: str = Field(max_length=500)
    idempotency_key: str | None = Field(default=None, max_length=64)


class Decision(BaseModel):
    comment: str = Field(default="", max_length=300)


def create_app(settings: Settings, authenticator: I.Authenticator | None = None, clock=lambda: datetime.now(timezone.utc)) -> FastAPI:
    app = FastAPI(title="NexoEventos · Centro de operaciones", docs_url=None, redoc_url=None, openapi_url=None)
    audit = AuditLog(Path(settings.state_dir) / "audit.jsonl")
    auth = authenticator or I.Authenticator(I.load(settings.identities_file))

    def validator(r):
        return B.summarize(B.barrier_list(settings, audit, tipo=r["tipo"], now=clock()))

    store = R.RecoveryStore(settings.state_dir, audit, validator, clock=clock)

    @app.middleware("http")
    async def sec_headers(request: Request, call_next):
        resp = await call_next(request)
        for k, v in HEADERS.items(): resp.headers[k] = v
        return resp

    def who(perm: str):
        def dep(request: Request):
            origin = request.client.host if request.client else "?"
            ident, err = auth.check(request.headers.get("authorization"), origin)
            if not ident:
                raise HTTPException(429 if err == "bloqueado" else 401, "No autenticado")
            if not I.can(ident["role"], perm):
                audit.append(ident["id"], "acceso_denegado", permiso=perm)
                raise HTTPException(403, "Permiso insuficiente")
            return ident
        return dep

    @app.exception_handler(R.RecoveryError)
    async def _re(_, exc: R.RecoveryError):
        return JSONResponse({"detail": str(exc)}, status_code=exc.code)

    @app.get("/healthz")
    def healthz():
        return {"ok": True}

    @app.get("/")
    def index():
        return FileResponse(STATIC / "index.html")

    @app.get("/panel.js")
    def js():
        return FileResponse(STATIC / "panel.js", media_type="application/javascript")

    @app.get("/panel.css")
    def css():
        return FileResponse(STATIC / "panel.css", media_type="text/css")

    @app.get("/api/ops/overview")
    def overview(_: dict = Depends(who("read"))):
        data = S.overview(settings, clock())
        data["barreras_failover"] = B.summarize(B.barrier_list(settings, audit, store=store, tipo="failover_aws_a_oci", now=clock(), execution=True))
        data["solicitudes_activas"] = len([r for r in store.list() if r["state"] in R.ACTIVOS])
        return data

    @app.get("/api/ops/barriers/{tipo}")
    def barriers(tipo: str, _: dict = Depends(who("read"))):
        if tipo not in R.TIPOS: raise HTTPException(404, "tipo desconocido")
        return B.summarize(B.barrier_list(settings, audit, store=store, tipo=tipo, now=clock(), execution=True))

    @app.get("/api/ops/recovery-requests")
    def listing(_: dict = Depends(who("read"))):
        return {"tipos": R.TIPOS, "solicitudes": store.list()}

    @app.post("/api/ops/recovery-requests", status_code=201)
    def create(body: NewRequest, ident: dict = Depends(who("request"))):
        return store.create(ident["id"], body.tipo, body.reason, body.idempotency_key)

    @app.get("/api/ops/recovery-requests/{rid}")
    def one(rid: str, _: dict = Depends(who("read"))):
        return store.get(rid)

    @app.post("/api/ops/recovery-requests/{rid}/approve")
    def approve(rid: str, body: Decision, ident: dict = Depends(who("decide"))):
        return store.decide(rid, ident["id"], True, body.comment)

    @app.post("/api/ops/recovery-requests/{rid}/deny")
    def deny(rid: str, body: Decision, ident: dict = Depends(who("decide"))):
        return store.decide(rid, ident["id"], False, body.comment)

    @app.post("/api/ops/recovery-requests/{rid}/cancel")
    def cancel(rid: str, ident: dict = Depends(who("read"))):
        return store.cancel(rid, ident["id"], I.can(ident["role"], "decide"))

    @app.get("/api/ops/audit")
    def audit_view(_: dict = Depends(who("read"))):
        return {"verificacion": audit.verify(), "entradas": audit.entries(100)}

    return app
