import os
from collections.abc import Generator

from fastapi import Request
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import Session, sessionmaker

DEFAULT_DATABASE_URL = "postgresql+psycopg://nexoeventos_app@/nexoeventos"
_LOCAL_HOSTS = {None, "", "localhost", "127.0.0.1", "::1"}


def enforce_tls_policy(database_url: str) -> None:
    """Rechaza al arrancar una base remota cuya URL no valide el certificado del servidor.

    `sslmode=require` cifra pero acepta cualquier certificado (no detecta un intermediario). Para una base remota (p. ej. RDS)
    se exige `sslmode=verify-full` (CA + nombre del servidor) y un `sslrootcert` existente. Los sockets Unix y localhost
    quedan fuera (desarrollo, pruebas y la recuperación con PostgreSQL local). No hay opción para desactivar la verificación.
    """
    url = make_url(database_url)
    host = url.host
    if host in _LOCAL_HOSTS or (host or "").startswith("/"):
        return
    if url.query.get("sslmode") != "verify-full":
        raise RuntimeError("La base remota exige sslmode=verify-full en DATABASE_URL (validación de CA y nombre del servidor).")
    root = url.query.get("sslrootcert")
    if not root or not os.path.isfile(root):
        raise RuntimeError("La base remota exige sslrootcert apuntando a un archivo de CA existente (paquete de CA de RDS).")


def build_engine(database_url: str | None = None) -> Engine:
    # El pool por worker se acota con variables de entorno (V2: varias instancias comparten una RDS pequeña); los valores por defecto son los de siempre.
    url = database_url or os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL)
    enforce_tls_policy(url)
    # Resiliencia ante un failover de RDS (≈ 14 s medidos el 22-oct): una conexión nueva falla en 5 s en lugar de esperar el tiempo
    # de TCP del sistema; el keepalive detecta antes un par que ya no responde; el reciclado fuerza a resolver de nuevo el DNS de RDS.
    # No hay reintentos automáticos: las peticiones fallan con 503 y el cliente decide (no se duplican operaciones).
    # connect_timeout/keepalives solo existen para conexiones TCP: se omiten en sockets Unix y localhost de pruebas.
    connect_args: dict[str, object] = {}
    if make_url(url).host not in _LOCAL_HOSTS and not (make_url(url).host or "").startswith("/"):
        connect_args = {
            "connect_timeout": int(os.getenv("DB_CONNECT_TIMEOUT", "5")),
            "keepalives": 1,
            "keepalives_idle": 30,
            "keepalives_interval": 10,
            "keepalives_count": 3,
        }
    if os.getenv("WRITE_GATE_MODE", "off").strip().lower() == "enforce":
        # Con la compuerta activa las conexiones de la API se etiquetan: el detector de escritores externos (failover/external_writers.py) distingue así la API
        # (protegida por la compuerta) de psql, scripts o migraciones que usen el mismo rol. Con `off` (valor por defecto) nada cambia.
        connect_args["application_name"] = "nexoeventos-api"
    return create_engine(
        url,
        pool_pre_ping=True,
        pool_size=int(os.getenv("DB_POOL_SIZE", "5")),
        max_overflow=int(os.getenv("DB_MAX_OVERFLOW", "10")),
        pool_timeout=int(os.getenv("DB_POOL_TIMEOUT", "30")),
        pool_recycle=int(os.getenv("DB_POOL_RECYCLE", "1800")),
        connect_args=connect_args,
    )


def build_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)


def get_session(request: Request) -> Generator[Session, None, None]:
    with request.app.state.session_factory() as session:
        yield session
