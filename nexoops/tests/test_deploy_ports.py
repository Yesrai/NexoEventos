"""El despliegue en la VM no debe compartir puerto local con otro servicio (incidente A1: 8760 era del testigo
y /nexoops/healthz devolvía el 200 del testigo, un falso positivo)."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _port_of(text: str, pattern: str) -> set[str]:
    return set(re.findall(pattern, text))


def test_nexoops_unit_and_nginx_agree_and_do_not_collide():
    unit = (ROOT / "deploy/nexoops/nexoops.service").read_text()
    nginx = (ROOT / "deploy/nexoops/nginx-nexoops.conf").read_text()
    own = _port_of(unit, r"--port (\d+)")
    assert len(own) == 1 and own == _port_of(nginx, r"proxy_pass\s+http://127\.0\.0\.1:(\d+)/")
    taken = set()
    for svc in ("witness/witness.service", "ops-center/ops-center.service", "ops-center/ops-fastprobe.service"):
        t = (ROOT / "deploy" / svc).read_text()
        taken |= _port_of(t, r"PORT=(\d+)") | _port_of(t, r"--port[ =](\d+)")
    for conf in ("witness/nginx-witness.conf", "ops-center/nginx-ops.conf"):
        taken |= _port_of((ROOT / "deploy" / conf).read_text(), r"127\.0\.0\.1:(\d+)")
    taken |= {"3000", "5432", "10050", "10051"}  # Grafana, PostgreSQL, Zabbix
    assert not own & taken, f"puerto de NexoOps {own} ya usado en la VM: {sorted(taken)}"
