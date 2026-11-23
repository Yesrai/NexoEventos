"""c04_par_meta.py: valida alcance y caducidad del PAR solo con metadatos y nunca copia la URL (access-uri). Sin OCI ni red."""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import c04_par_meta as pm  # noqa: E402

NOW = datetime(2026, 11, 19, 4, 30, tzinfo=timezone.utc)
PFX = "backups/c04-20261119/"


def par(**kw):
    base = {"name": "c04-escritura-20261119", "access-type": "AnyObjectWrite", "object-name": PFX, "time-created": "2026-11-19T04:25:00+00:00",
            "time-expires": "2026-11-19T06:05:00+00:00", "access-uri": "/p/TOKEN-INVENTADO/n/x/b/y/o/" + PFX}
    base.update(kw)
    return base


def run(items, **kw):
    return pm.evaluate(items, prefix=PFX, name="c04-escritura-20261119", now=NOW, **kw)


def test_correct_par_passes_and_the_uri_is_never_copied():
    r = run([par()])
    assert r["ok"], r
    assert "TOKEN-INVENTADO" not in repr(r) and "access-uri" not in repr(r)


def test_wrong_scope_type_or_lifetime_are_rejected():
    assert not run([par(**{"access-type": "AnyObjectReadWrite"})])["ok"]
    assert not run([par(**{"object-name": "backups/"})])["ok"]
    assert not run([par(**{"object-name": None})])["ok"]  # todo el bucket
    assert not run([par(**{"time-expires": "2026-11-19T09:00:00+00:00"})])["ok"]  # vida > 100 min
    assert not run([par(**{"time-expires": "2026-11-19T04:40:00+00:00"})])["ok"]  # casi caducado


def test_zero_or_several_pars_are_rejected():
    assert not run([])["ok"]
    assert not run([par(), par(name="otro")])["ok"]
