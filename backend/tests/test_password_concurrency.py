"""El hash/verificación de contraseñas (Argon2id, ~64 MiB cada uno) nunca supera el límite de operaciones simultáneas por proceso."""
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from app import auth


def test_concurrent_password_operations_never_exceed_the_limit_and_all_complete(monkeypatch) -> None:
    monkeypatch.setattr(auth, "_argon2_slots", threading.BoundedSemaphore(2))
    state = {"now": 0, "max": 0}
    lock = threading.Lock()

    def slow(*_args, **_kwargs):
        with lock:
            state["now"] += 1
            state["max"] = max(state["max"], state["now"])
        time.sleep(0.05)
        with lock:
            state["now"] -= 1
        return "ok"

    monkeypatch.setattr(auth.password_hash, "hash", slow)
    monkeypatch.setattr(auth.password_hash, "verify", lambda *a, **k: slow() == "ok")
    with ThreadPoolExecutor(20) as pool:
        results = list(pool.map(lambda i: auth.hash_password("x") if i % 2 else auth.verify_password("x", "h"), range(20)))
    assert state["max"] <= 2 and state["now"] == 0
    assert results.count("ok") == 10 and results.count(True) == 10


def test_default_limit_is_small_and_real_hashes_still_verify() -> None:
    from app.config import ARGON2_MAX_CONCURRENT

    assert 1 <= ARGON2_MAX_CONCURRENT <= 4
    encoded = auth.hash_password("Contraseña-de-prueba-1")
    assert auth.verify_password("Contraseña-de-prueba-1", encoded) and not auth.verify_password("otra", encoded)
