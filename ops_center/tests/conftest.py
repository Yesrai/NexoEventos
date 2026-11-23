import json
import os
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from ops_center import identities as I
from ops_center.app import create_app
from ops_center.settings import Settings

FMT = "%Y-%m-%dT%H:%M:%SZ"
TOKENS = {"viewer": "tok-viewer-" + "v" * 40, "requester": "tok-requester-" + "r" * 40, "approver": "tok-approver-" + "a" * 40, "approver2": "tok-approver2-" + "b" * 40}


class Clock:
    def __init__(self, t=None): self.t = t or datetime(2026, 11, 23, 12, 0, tzinfo=timezone.utc)
    def __call__(self): return self.t
    def advance(self, **kw): self.t += timedelta(**kw)


def write_identities(path):
    ids = [{"id": "ti-lectura", "role": "viewer", "token_sha256": I.hash_token(TOKENS["viewer"])},
           {"id": "ti-solicitante", "role": "requester", "token_sha256": I.hash_token(TOKENS["requester"])},
           {"id": "propietaria", "role": "approver", "token_sha256": I.hash_token(TOKENS["approver"])},
           {"id": "aprobador-2", "role": "approver", "token_sha256": I.hash_token(TOKENS["approver2"])}]
    path.write_text(json.dumps({"identities": ids})); os.chmod(path, 0o600)


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def settings(tmp_path, clock):
    sd = tmp_path / "state"; sd.mkdir()
    write_identities(sd / "identities.json")
    bk = tmp_path / "backups"; bk.mkdir()
    (bk / "cycles.jsonl").write_text(json.dumps({"ok": True, "finished_at": (datetime.now(timezone.utc) - timedelta(minutes=10)).strftime(FMT), "name": "x.cms", "env": "t", "duration_s": 3, "cms_bytes": 10}) + "\n")
    fo = tmp_path / "failover"; fo.mkdir(); (fo / "ledger.json").write_text(json.dumps({"state": "NONE"}))
    return Settings(state_dir=sd, identities_file=sd / "identities.json", evidence_dir=sd / "evidence", failover_dir=fo, backup_state_dir=bk,
                    deadline="2026-11-26T00:00:00Z", env={})


@pytest.fixture
def client(settings, clock):
    return TestClient(create_app(settings, clock=clock))


def H(role):
    return {"Authorization": "Bearer " + TOKENS[role]}


def write_evidence(settings, stage, clock, result="PASS", age_h=0):
    settings.evidence_dir.mkdir(parents=True, exist_ok=True)
    (settings.evidence_dir / f"{stage}.json").write_text(json.dumps({"etapa": stage, "resultado": result, "at": (clock() - timedelta(hours=age_h)).strftime(FMT), "report_sha256": "a" * 64}))
