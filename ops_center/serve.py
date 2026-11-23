"""Arranque: `python -m ops_center.serve` (uvicorn en 127.0.0.1:8750; el TLS lo termina Nginx en la VM de Azure). Falla cerrada si faltan identidades."""
import os
import uvicorn
from .app import create_app
from .settings import Settings

if __name__ == "__main__":
    uvicorn.run(create_app(Settings.from_env()), host=os.getenv("OPS_CENTER_HOST", "127.0.0.1"), port=int(os.getenv("OPS_CENTER_PORT", "8750")), log_level="warning")
