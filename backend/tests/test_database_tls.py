import pytest

from app.database import build_engine, enforce_tls_policy

REMOTE = "postgresql+psycopg://nexoeventos_app:secreto-no-imprimir@mydb.abc123.us-east-1.rds.amazonaws.com/nexoeventos"


def test_local_socket_and_localhost_are_exempt() -> None:
    for url in ("postgresql+psycopg:///nexoeventos_test", "postgresql+psycopg://u@localhost/db", "postgresql+psycopg://u@127.0.0.1/db"):
        enforce_tls_policy(url)


@pytest.mark.parametrize("query", ["", "?sslmode=require", "?sslmode=verify-ca", "?sslmode=prefer", "?sslmode=disable"])
def test_remote_database_rejects_unverified_tls(query: str) -> None:
    with pytest.raises(RuntimeError, match="verify-full") as err:
        enforce_tls_policy(REMOTE + query)
    assert "secreto-no-imprimir" not in str(err.value)


def test_remote_verify_full_requires_an_existing_ca_file(tmp_path) -> None:
    with pytest.raises(RuntimeError, match="sslrootcert"):
        enforce_tls_policy(REMOTE + "?sslmode=verify-full")
    with pytest.raises(RuntimeError, match="sslrootcert"):
        enforce_tls_policy(REMOTE + f"?sslmode=verify-full&sslrootcert={tmp_path}/no-existe.pem")


def test_remote_verify_full_with_ca_file_builds_the_engine(tmp_path) -> None:
    ca = tmp_path / "ca.pem"
    ca.write_text("-----BEGIN CERTIFICATE-----\n-----END CERTIFICATE-----\n")
    engine = build_engine(REMOTE + f"?sslmode=verify-full&sslrootcert={ca}")  # no conecta: el pool es perezoso
    assert engine.url.query["sslmode"] == "verify-full"
