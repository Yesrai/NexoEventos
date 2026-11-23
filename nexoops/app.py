"""API de NexoOps. Sesión por cookie HttpOnly + SameSite=Strict (+ Secure fuera de dev), CSRF por cabecera en métodos mutantes, comprobación de Origin, cabeceras estrictas.
Sin sesión completa (contraseña + OTP) todo `/api/*` (salvo el flujo de login) devuelve 401."""
from __future__ import annotations

import secrets
import time
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import assistant as AI, mailer as M, ops as O
from .actions import ActionError, Actions
from .auth import AuthError, AuthService
from .integrations.aws import Aws
from .integrations.grafana import Grafana, RANGES
from .integrations.zabbix import Zabbix
from .config import Config

STATIC = Path(__file__).resolve().parent / "static"
SESSION_COOKIE, CHALLENGE_COOKIE = "nexoops_session", "nexoops_challenge"


class LoginBody(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(max_length=256)


class OtpBody(BaseModel):
    code: str = Field(max_length=12)


class ActionBody(BaseModel):
    name: str = Field(max_length=64)
    params: dict = Field(default_factory=dict)
    confirm: bool = False


class AskBody(BaseModel):
    question: str = Field(default="", max_length=300)


def create_app(cfg: Config, mailer=None, aws=None, grafana=None, zabbix=None, audit=None, clock=None) -> FastAPI:
    from ops_center.audit import AuditLog
    cfg.validate()
    app = FastAPI(title="NexoOps", docs_url=None, redoc_url=None, openapi_url=None)
    audit = audit or AuditLog(Path(cfg.data_dir) / "audit.jsonl")
    kw = {"clock": clock} if clock else {}
    auth = AuthService(cfg, mailer or M.build(cfg), audit, **kw)
    aws, grafana, zabbix = aws or Aws(cfg), grafana or Grafana(cfg), zabbix or Zabbix(cfg)
    deps = {"cloud_overview": lambda: O.cloud_overview(cfg, aws, zabbix), "recovery_view": lambda: O.recovery_view(cfg), "ocs": lambda: O._ocs(cfg), "aws": aws}
    actions = Actions(cfg, audit, deps)
    app.state.auth, app.state.audit = auth, audit
    frame = f" {cfg.grafana_url}" if cfg.grafana_embed and cfg.grafana_url else ""
    csp = ("default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; font-src 'self'; connect-src 'self'; base-uri 'none'; form-action 'self'; "
           f"frame-ancestors 'none'; frame-src{frame or ' '+chr(39)+'none'+chr(39)}")

    @app.middleware("http")
    async def guard(request: Request, call_next):
        if request.method in ("POST", "PUT", "PATCH", "DELETE"):
            origin = request.headers.get("origin")
            host = request.headers.get("host", "")
            if origin and origin.split("://", 1)[-1] != host:
                return JSONResponse({"detail": "Origen no permitido"}, status_code=403)
        resp = await call_next(request)
        resp.headers.update({"Content-Security-Policy": csp, "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer", "Cache-Control": "no-store", "X-Frame-Options": "DENY"})
        return resp

    @app.exception_handler(AuthError)
    async def _ae(_, e: AuthError):
        h = {"Retry-After": str(e.retry_after)} if e.retry_after else None
        return JSONResponse({"detail": str(e)}, status_code=e.code, headers=h)

    @app.exception_handler(ActionError)
    async def _acte(_, e: ActionError):
        return JSONResponse({"detail": str(e)}, status_code=e.code)

    def ip(request):
        return request.client.host if request.client else "?"

    def user(request: Request):
        u = auth.session(request.cookies.get(SESSION_COOKIE))
        if not u:
            raise HTTPException(401, "No autenticado")
        if request.method in ("POST", "PUT", "PATCH", "DELETE") and not secrets.compare_digest(request.headers.get("x-csrf-token", ""), u["csrf"]):
            audit.append(u["email"], "csrf_rechazado")
            raise HTTPException(403, "CSRF inválido")
        return u

    def setc(resp: Response, name, val, max_age):
        resp.set_cookie(name, val, max_age=max_age, httponly=True, secure=cfg.cookie_secure, samesite="strict", path=cfg.base_path or "/")

    # ---- páginas ----
    @app.get("/")
    def index():
        # Subruta detrás de Nginx: los recursos y la API se resuelven bajo NEXOOPS_BASE_PATH (validado en Config: solo [a-z0-9-]).
        html = (STATIC / "index.html").read_text(encoding="utf-8")
        if cfg.base_path:
            html = html.replace('"/static/', f'"{cfg.base_path}/static/').replace("<head>", f'<head>\n<meta name="nexoops-base" content="{cfg.base_path}">', 1)
        return HTMLResponse(html)

    @app.get("/healthz")
    def healthz():
        return {"ok": True}

    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    # ---- autenticación ----
    @app.post("/api/auth/login")
    def login(b: LoginBody, request: Request, response: Response):
        r = auth.login(b.email, b.password, ip(request))
        setc(response, CHALLENGE_COOKIE, r["challenge_id"], 300)
        return {"step": "otp", "expires_in": r["expires_in"]}

    @app.post("/api/auth/resend")
    def resend(request: Request):
        return auth.resend(request.cookies.get(CHALLENGE_COOKIE))

    @app.get("/api/auth/challenge")
    def challenge(request: Request):
        return auth.challenge_status(request.cookies.get(CHALLENGE_COOKIE))

    @app.post("/api/auth/verify")
    def verify(b: OtpBody, request: Request, response: Response):
        r = auth.verify_otp(request.cookies.get(CHALLENGE_COOKIE), b.code, ip(request))
        setc(response, SESSION_COOKIE, r["token"], 8 * 3600)
        response.delete_cookie(CHALLENGE_COOKIE, path=cfg.base_path or "/", httponly=True, secure=cfg.cookie_secure, samesite="strict")
        return {"user": r["user"], "csrf": r["csrf"]}

    @app.get("/api/auth/session")
    def session(u: dict = Depends(user)):
        return {"user": {"email": u["email"], "role": u["role"]}, "csrf": u["csrf"]}

    @app.post("/api/auth/logout")
    def logout(request: Request, response: Response, u: dict = Depends(user)):
        auth.logout(request.cookies.get(SESSION_COOKIE), u["email"])
        response.delete_cookie(SESSION_COOKIE, path=cfg.base_path or "/")
        return {"ok": True}

    # ---- datos (solo lectura) ----
    @app.get("/api/overview")
    def overview(u: dict = Depends(user)):
        return O.cloud_overview(cfg, aws, zabbix)

    @app.get("/api/infra/aws")
    def infra_aws(u: dict = Depends(user)):
        return aws.summary()

    @app.get("/api/infra/oci-azure")
    def infra_oa(u: dict = Depends(user)):
        return {"snapshot": O.OA.snapshot(cfg.ops_state_dir), "oci_sdk": {"estado": "pendiente", "detalle": "sin SDK de OCI cableado; el estado de OCI proviene de las sondas del recolector"}}

    @app.get("/api/monitoring/grafana")
    def g_list(u: dict = Depends(user)):
        return grafana.dashboards()

    @app.get("/api/monitoring/grafana/{uid}")
    def g_panels(uid: str, range: str = "1h", u: dict = Depends(user)):
        if range not in RANGES:
            raise HTTPException(400, "rango inválido")
        return grafana.panels(uid, range)

    @app.get("/api/monitoring/grafana/{uid}/panels/{panel_id}/metrics")
    def g_metrics(uid: str, panel_id: int, range: str = "1h", u: dict = Depends(user)):
        if range not in RANGES:
            raise HTTPException(400, "rango inválido")
        return grafana.metrics(uid, panel_id, range)

    @app.get("/api/monitoring/zabbix")
    def z(u: dict = Depends(user)):
        return {"hosts": zabbix.hosts(), "problems": zabbix.problems(), "history": zabbix.history()}

    @app.get("/api/recovery")
    def recovery(u: dict = Depends(user)):
        return O.recovery_view(cfg)

    @app.get("/api/incidents")
    def incidents(u: dict = Depends(user)):
        return {"zabbix": zabbix.history(), "solicitudes_intervencion": actions.list_requests()}

    @app.get("/api/audit")
    def audit_view(u: dict = Depends(user)):
        return {"verificacion": audit.verify(), "entradas": audit.entries(100)[::-1]}

    @app.get("/api/config")
    def config(u: dict = Depends(user)):
        return {"integraciones": {"grafana": grafana.configured(), "zabbix": zabbix.configured(), "aws": bool(cfg.aws_region), "correo": cfg.mail_mode, "ia": cfg.llm_provider or "pendiente"},
                "grafana_embed": cfg.grafana_embed, "entorno": cfg.env, "roles": ["SUPER_ADMIN_TI"], "politica": "NexoOps no omite IAM, SCP de AWS Academy, fencing ni la prevención de doble escritura."}

    # ---- acciones y asistente ----
    @app.get("/api/actions")
    def catalog(u: dict = Depends(user)):
        return {"acciones": actions.catalog()}

    @app.post("/api/actions")
    def run(b: ActionBody, request: Request, u: dict = Depends(user)):
        return actions.run(u, b.name, b.params, b.confirm, "rq-" + secrets.token_hex(5))

    @app.post("/api/assistant")
    def assistant(b: AskBody, u: dict = Depends(user)):
        out = AI.diagnose(b.question, O.cloud_overview(cfg, aws, zabbix), O.recovery_view(cfg), zabbix.problems(), cfg.llm_provider)
        audit.append(u["email"], "asistente_consulta", rol=u["role"], operacion="assistant.diagnose", resultado="ok", request_id="rq-" + secrets.token_hex(5))
        return out

    return app
