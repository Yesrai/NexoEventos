"""Las configuraciones de monitoreo que cita la documentación deben coincidir con el código (comprobación estática; no consulta ninguna nube)."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_zabbix_media_type_defines_problem_recovery_and_update_templates() -> None:
    # El 28-oct las 5 alertas de la caída de V1 fallaron con «No message defined for media type»: sin plantillas Zabbix 7.0 descarta la alerta.
    script = (ROOT / "scripts/observability/zabbix_configure.py").read_text()
    assert '"message_templates"' in script and "for r, sub in ((0," in script
    assert all(f"({n}, " in script for n in (0, 1, 2)) and '"eventsource": 0' in script


def test_azure_cpu_alert_matches_what_the_evidence_describes() -> None:
    monitor = (ROOT / "infra/azure/modules/monitor/main.tf").read_text()
    cpu = re.search(r'cpu = \{[^\n]*\}', monitor).group(0)
    assert 'metric = "Percentage CPU"' in cpu and 'operator = "GreaterThan"' in cpu and "threshold = 80" in cpu
    assert 'window = "PT15M"' in cpu and 'freq = "PT5M"' in cpu and "severity = 2" in cpu
    assert "auto_mitigate       = true" in monitor and "use_common_alert_schema = true" in monitor


def test_azure_alerts_only_exist_with_an_email_receiver_and_a_vm() -> None:
    monitor = (ROOT / "infra/azure/modules/monitor/main.tf").read_text()
    assert "var.create_vm_alerts && length(var.alert_emails) > 0" in monitor
    assert "length(var.alert_emails) > 0 ? 1 : 0" in monitor


def test_aws_alarms_are_opt_in_and_do_not_fire_for_stopped_or_scaled_to_zero_resources() -> None:
    for rel in ("infra/aws/alarms.tf", "infra/aws-v2/alarms.tf"):
        text = (ROOT / rel).read_text()
        assert re.search(r'variable "enable_alarms" \{.*?default\s*=\s*false', text, re.S)
        assert '"breaching"' not in text  # datos ausentes nunca cuentan como incumplimiento
    v2 = (ROOT / "infra/aws-v2/alarms.tf").read_text()
    assert "IF(sanos < deseada, 1, 0)" in v2 and "IF(en_servicio < deseada, 1, 0)" in v2


def test_alarm_thresholds_are_justified_by_measurements() -> None:
    v2 = (ROOT / "infra/aws-v2/alarms.tf").read_text()
    # p95 medido ≤ 0,395 s en la prueba de escalado (4.202 inicios de sesión): 1,5 s deja margen > 3 veces sin saltar en carga normal.
    assert "threshold           = 1.5" in v2 and "extended_statistic  = \"p95\"" in v2
    v1 = (ROOT / "infra/aws/alarms.tf").read_text()
    assert "default     = 2147483648" in v1  # 2 GiB = 10 % de los 20 GiB asignados
