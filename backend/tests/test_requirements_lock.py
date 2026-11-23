import re
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
DEV_ONLY = {"pytest", "httpx"}  # solo pruebas: no deben estar en el lockfile de producción


def _pins(path: Path) -> dict[str, str]:
    pins: dict[str, str] = {}
    for line in path.read_text().splitlines():
        match = re.match(r"^([A-Za-z0-9_.\-]+)(\[[^\]]+\])?==([^\s;#]+)", line.strip())
        if match:
            pins[match.group(1).lower().replace("_", "-")] = match.group(3)
    return pins


def test_production_lock_matches_requirements_for_runtime_dependencies() -> None:
    direct = _pins(BACKEND / "requirements.txt")
    lock = _pins(BACKEND / "requirements-production.lock")
    runtime = {name: version for name, version in direct.items() if name not in DEV_ONLY}
    assert runtime, "requirements.txt no tiene dependencias de ejecución"
    mismatched = {name: (version, lock.get(name)) for name, version in runtime.items() if lock.get(name) != version}
    assert not mismatched, f"requirements.txt y el lock de producción difieren: {mismatched}"


def test_production_lock_has_no_test_only_packages_and_pins_everything() -> None:
    lock_text = (BACKEND / "requirements-production.lock").read_text()
    lock = _pins(BACKEND / "requirements-production.lock")
    assert DEV_ONLY.isdisjoint(lock)
    unpinned = [l for l in lock_text.splitlines() if l.strip() and not l.startswith("#") and "==" not in l]
    assert not unpinned, f"líneas sin versión exacta en el lock: {unpinned}"
