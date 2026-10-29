# Evidencias multicloud

Convención: `<nube>/AAAAMMDD-<tema>/` con `resultado.md` (qué se hizo, comando u origen, resultado real, limitaciones) y archivos originales sanitizados (sin secretos, tokens, claves ni identificadores de cuenta; revisar capturas a 200 %). Nada de lo que aquí aparezca puede ser inventado: si no se ejecutó, no hay carpeta.

| Carpeta | Contenido previsto | Estado |
|---|---|---|
| `aws/` | inventario real (VPC, SG, RDS), respaldos, V1/V2 | las evidencias AWS anteriores siguen en `docs/evidencias/` y `perf/results/` (no se mueven) |
| `oci/` | base Terraform, IAM, transferencia con SHA-256, simulacro y recuperación de la aplicación | **Ejecutado el 23-oct** (ver `oci/README.md`) |
| `azure/` | base, presupuesto, VM con Zabbix/Grafana, alertas, identidad, métricas | **Ejecutado el 28-oct** (ver `azure/README.md`); entrega de correo de alertas no comprobada |
| `integracion/` | fallo real → detección → alerta → recuperación entre nubes | PENDIENTE como prueba única; integraciones parciales probadas (ver `integracion/README.md`) |
| `automatizacion/` | CI estático, `terraform validate/plan`, Ansible | Preparación local ejecutada (22-oct) |
| `informe-material/` | diagramas y tablas finales derivadas de las evidencias | Ver `docs/entregable2/` (informe, diagramas y matriz) |
