from app.database import build_engine


def test_pool_defaults_are_unchanged_and_env_bounds_it(monkeypatch) -> None:
    monkeypatch.delenv("DB_POOL_SIZE", raising=False)
    monkeypatch.delenv("DB_MAX_OVERFLOW", raising=False)
    engine = build_engine("postgresql+psycopg:///nexoeventos_test")
    assert (engine.pool.size(), engine.pool._max_overflow) == (5, 10)
    monkeypatch.setenv("DB_POOL_SIZE", "5")
    monkeypatch.setenv("DB_MAX_OVERFLOW", "5")
    bounded = build_engine("postgresql+psycopg:///nexoeventos_test")
    assert (bounded.pool.size(), bounded.pool._max_overflow) == (5, 5)
