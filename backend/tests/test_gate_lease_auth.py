import base64, json, os
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from app.failover.gate import _load_lease_authenticator


def pair(tmp_path, mode=0o600):
    ka, ko = Ed25519PrivateKey.generate(), Ed25519PrivateKey.generate()
    raw = lambda k: k.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())
    pub = lambda k: k.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    kf, pf = tmp_path / "k", tmp_path / "p"
    kf.write_text(base64.b64encode(raw(ka)).decode()); pf.write_text(json.dumps({"oci": [base64.b64encode(pub(ko)).decode()]})); os.chmod(kf, mode); os.chmod(pf, 0o600)
    return {"WRITE_GATE_LEASE_SIGNING_KEY_FILE": str(kf), "WRITE_GATE_LEASE_PEER_PUBKEYS_FILE": str(pf)}


def test_carga_ed25519_y_rechaza_permisos_abiertos_o_archivos_incompletos(tmp_path):
    a = _load_lease_authenticator(pair(tmp_path), "aws"); assert a is not None and a.can_sign("aws") and not a.can_sign("oci")
    with pytest.raises(RuntimeError, match="0600"): _load_lease_authenticator(pair(tmp_path / "x" if (tmp_path / "x").mkdir() is None else tmp_path, mode=0o644), "aws")
    assert _load_lease_authenticator({}, "aws") is None
    with pytest.raises(RuntimeError): _load_lease_authenticator({"WRITE_GATE_LEASE_SIGNING_KEY_FILE": "x"}, "aws")
    bad = pair(tmp_path); (tmp_path / "k").write_text("basura"); os.chmod(tmp_path / "k", 0o600)
    with pytest.raises(RuntimeError) as e: _load_lease_authenticator(bad, "aws")
    assert "basura" not in str(e.value)
