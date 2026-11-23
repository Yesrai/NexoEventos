"""PostgreSQL DESECHABLE para pruebas: un clúster NUEVO (initdb) en un directorio temporal, con socket Unix propio y sin red (listen_addresses=''), que se detiene y se borra al terminar.
No toca el clúster local existente, ni contenedores, ni volúmenes, ni instalaciones. Permite crear roles privilegiados (superusuario, BYPASSRLS) sin afectar a nadie.
Si initdb/pg_ctl no están disponibles, quien lo use debe omitir la prueba (pytest.skip)."""
import shutil
import socket
import subprocess
import tempfile
from pathlib import Path


def available() -> bool:
    return bool(shutil.which("initdb") and shutil.which("pg_ctl"))


class TempCluster:
    def __init__(self):
        self.base = Path(tempfile.mkdtemp(prefix="npg", dir="/tmp")).resolve()      # ruta corta: el socket Unix tiene un límite de longitud
        self.data = self.base / "data"
        s = socket.socket(); s.bind(("127.0.0.1", 0)); self.port = s.getsockname()[1]; s.close()
        subprocess.run(["initdb", "-D", str(self.data), "-U", "postgres", "-A", "trust", "-N", "--no-locale", "-E", "UTF8"], check=True, capture_output=True)
        subprocess.run(["pg_ctl", "-D", str(self.data), "-o", f"-p {self.port} -k {self.base} -c listen_addresses='' -c fsync=off -c max_connections=50", "-w", "-l", str(self.base / "log"), "start"],
                       check=True, capture_output=True)

    def url(self, db: str = "postgres", user: str = "postgres", app_name: str | None = None) -> str:
        extra = f"&application_name={app_name}" if app_name else ""
        return f"postgresql+psycopg://{user}@/{db}?host={self.base}&port={self.port}{extra}"

    def stop(self):
        subprocess.run(["pg_ctl", "-D", str(self.data), "-m", "immediate", "-w", "stop"], capture_output=True)
        shutil.rmtree(self.base, ignore_errors=True)
