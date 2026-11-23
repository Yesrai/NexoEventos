# scripts/observability

Herramientas de observabilidad multicloud (Zabbix + Grafana en Azure). Diseño y plan: `docs/multicloud/09-azure-observabilidad.md`.

| Script | Para qué | Nubes |
|---|---|---|
| `zbx.py` | Cliente mínimo de la API de Zabbix 7.0 (biblioteca estándar) | — |
| `zabbix_configure.py` | Configuración idempotente de Zabbix (plantillas, hosts, usuarios de mínimo privilegio, medio y acción de alertas) | — |
| `gen_dashboards.py` | Genera los paneles de Grafana (JSON) | — |
| `export-oci-metrics.py` | Métricas reales de OCI Monitoring (solo lectura) → JSON | OCI (lectura) |
| `export-cloudwatch.py` | Métricas reales de CloudWatch de las ventanas de V1/V2 (solo lectura; `--selftest`, `--dry-run`) → JSON | AWS (lectura, lab activo) |
| `export-k6-results.py` | Resultados reales de las pruebas de carga (`perf/results`) → JSON | local |
| `export-failover-evidence.py` | Sondeo real del failover Multi-AZ → JSON | local |
| `push-history.py` | Carga los JSON en Zabbix (`history.push`) con su marca de tiempo original | Azure (HTTPS del operador) |
| `lab-validate.py`, `lab-grafana-validate.py` | Validación local en Docker (`work/obs-lab`): sondas, fallo real, `history.push`, paneles | ninguna |

Las exportaciones se escriben en `work/observability/` (0600, fuera de Git). Los secretos (token de carga histórica, contraseñas) viven en `work/ansible-secrets/monitoring/`.

## Ventana de la VM de Azure (preparados; nada se ejecuta solo)
- `azure-window-preflight.sh` — GO/NO-GO de solo lectura antes del apply.
- `azure-verify-hostkey.sh` — verifica la huella SSH por la consola serie de Azure y escribe `work/ssh/azure_known_hosts` solo si coincide.
- `azure-vm-watchdog.sh` — apagado automático: `az vm deallocate` a las 4 h con verificación del estado; `--check` no apaga nada.
- `azure-set-shutdown-window.sh` — fija la hora UTC del auto-shutdown (ahora + 4 h) y regenera el plan; ejecutar justo antes del apply.
