"""El espejo de solo lectura (A1) debe ser coherente entre la unidad de NexoOps, el servicio de espejo y el instalador."""
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
D = ROOT / "deploy/nexoops"


def test_service_reads_feed_dir_not_ops_center_state():
    unit = (D / "nexoops.service").read_text()
    assert "OPS_CENTER_STATE_DIR=/var/lib/nexoops-feed" in unit
    assert "ReadOnlyPaths=/var/lib/nexoops-feed" in unit
    assert "/var/lib/ops-center" not in unit


def test_feed_service_is_readonly_on_source_and_has_no_network():
    svc = (D / "nexoops-feed.service").read_text()
    assert "ReadOnlyPaths=/var/lib/ops-center" in svc and "ReadWritePaths=/var/lib/nexoops-feed" in svc
    assert "PrivateNetwork=true" in svc


def test_feed_script_never_copies_identities_and_syntax_is_valid():
    sh = (D / "nexoops-feed.sh").read_text()
    assert "identities.json" not in sh.replace("nunca identities.json", "")
    for f in ("nexoops-feed.sh", "instalar-en-vm.sh"):
        assert subprocess.run(["bash", "-n", str(D / f)]).returncode == 0


def test_installer_installs_feed_timer_before_enabling_service():
    s = (D / "instalar-en-vm.sh").read_text()
    assert s.index("nexoops-feed.timer") < s.index("systemctl enable --now nexoops\n")
