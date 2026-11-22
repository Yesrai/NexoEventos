from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_DEADLINE = "2026-11-26T00:00:00Z"   # vencimiento REPORTADO de Academy (por confirmar en la consola); las pruebas AWS deben acabar antes con margen
FAILOVER_PHRASE = "AUTORIZO EL FAILOVER REAL AWS A OCI T6"


@dataclass
class Settings:
    state_dir: Path
    identities_file: Path
    evidence_dir: Path
    failover_config: Path | None = None
    failover_dir: Path | None = None       # ledger.json y last-run.json (los mismos que lee app.ops)
    backup_state_dir: Path | None = None
    deadline: str = DEFAULT_DEADLINE
    deadline_margin_h: float = 12.0
    env: dict = field(default_factory=lambda: dict(os.environ))

    @property
    def kill_switch(self) -> Path:
        return Path(self.state_dir) / "KILL_SWITCH"

    @classmethod
    def from_env(cls, env=None):
        e = dict(os.environ if env is None else env)
        p = lambda k: Path(e[k]) if e.get(k) else None
        sd = p("OPS_CENTER_STATE_DIR") or Path("work/ops-center")
        return cls(state_dir=sd, identities_file=p("OPS_CENTER_IDENTITIES_FILE") or sd / "identities.json", evidence_dir=p("OPS_CENTER_EVIDENCE_DIR") or sd / "evidence",
                   failover_config=p("OPS_CENTER_FAILOVER_CONFIG"), failover_dir=p("OPS_FAILOVER_DIR"), backup_state_dir=p("OPS_BACKUP_STATE_DIR"),
                   deadline=e.get("OPS_CENTER_DEADLINE", DEFAULT_DEADLINE), env=e)
