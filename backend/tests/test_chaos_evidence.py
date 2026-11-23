"""Las cifras de Chaos Engineering que cita el informe deben reproducirse a partir de los datos crudos conservados en docs/evidencias/.
No ejecuta nada en la nube: solo lee archivos locales y comprueba cálculo y completitud."""
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("validate_chaos", ROOT / "scripts/cloud/validate-chaos-result.py")
V = importlib.util.module_from_spec(spec)
spec.loader.exec_module(V)
EV = ROOT / "docs/evidencias"


def test_experiment_a_api_failure_numbers_reproduce_and_availability_is_flagged_as_not_representative() -> None:
    result = V.validate_api_failure(EV / "tolerancia-fallos-v2-20261022")
    metrics = result["metricas"]
    assert (metrics["solicitudes"], metrics["errores"], metrics["estados_error"]) == (275, 25, [502])
    assert metrics["rutas_con_error"] == ["/healthz"]
    assert (metrics["deteccion_s"], metrics["recuperacion_s"]) == (20.0, 15.8)
    assert any("NO representa" in w for w in result["advertencias"])


def test_experiment_b_autohealing_is_incomplete_because_the_script_lost_its_results() -> None:
    result = V.validate_autohealing(EV / "tolerancia-fallos-v2-20261022-b")
    assert result["estado"] == "incompleto"
    assert result["metricas"]["respuestas_5xx_destino"] == 40 and result["metricas"]["respuestas_5xx_elb"] == 0
    assert any("resultado.json" in w for w in result["advertencias"])


def test_experiment_d_rds_failover_durations_are_recomputed_from_raw_samples() -> None:
    result = V.validate_rds_failover(EV / "multicloud/aws/20261023-rds-multiaz/failover")
    assert result["estado"] == "completo" and result["metricas"]["huella_igual"] is True
    assert abs(result["metricas"]["interrupcion_postgres_s"] - 14) < 0.5
    assert abs(result["metricas"]["interrupcion_healthz_s"] - 13) < 0.5
    assert any("sin explicar" in w for w in result["advertencias"])  # los 2 timeouts aislados posteriores


def test_experiment_e_oci_recovery_numbers_and_the_registered_failure_are_reported() -> None:
    result = V.validate_oci_recovery(EV / "multicloud/oci/20261023-recuperacion-aplicacion")
    assert result["metricas"]["pruebas_humo"] == "14/14" and result["metricas"]["huella_valores"] == 10
    assert result["metricas"]["duracion_desde_apply"] == "32 min 42 s"
    assert any("no es una ejecución limpia" in w for w in result["advertencias"])


def test_validator_rejects_inconsistent_or_missing_results(tmp_path) -> None:
    assert V.validate_api_failure(tmp_path)["estado"] == "incompleto"
    (tmp_path / "solicitudes.json").write_text(json.dumps([{"t": 0, "path": "/healthz", "status": 200, "ms": 5}]))
    (tmp_path / "resultado.json").write_text(json.dumps({"client": {"requests": 99, "errors": 0}, "events": {}}))
    result = V.validate_api_failure(tmp_path)
    assert result["estado"] == "incompleto"
    assert any("no coincide" in w for w in result["advertencias"])


def test_functional_and_health_availability_are_reported_separately() -> None:
    import json as _json

    requests = _json.loads((EV / "tolerancia-fallos-v2-20261022/solicitudes.json").read_text())
    split = V.split_availability(requests)
    assert (split["requests_api"], split["requests_health"]) == (138, 137)
    assert split["availability_api_pct"] == 100.0 and split["availability_health_pct"] == 81.8
    # Aviso: 100 % de /api/events NO prueba disponibilidad: el ALB envió todo ese tráfico a la instancia sana (sesgo de reparto documentado).
    assert V.split_availability([]) == {"availability_api_pct": None, "availability_health_pct": None, "requests_api": 0, "requests_health": 0}
