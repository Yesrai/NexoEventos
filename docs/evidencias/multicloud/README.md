# Evidencias multicloud

Convención: `<nube>/AAAAMMDD-<tema>/` con `resultado.md` (qué se hizo, comando u origen, resultado real, limitaciones) y archivos originales sanitizados (sin secretos, tokens, claves ni identificadores de cuenta; revisar capturas a 200 %). Nada de lo que aquí aparezca puede ser inventado: si no se ejecutó, no hay carpeta.

| Carpeta | Contenido previsto | Estado |
|---|---|---|
| `aws/` | inventario real (VPC, SG, RDS), respaldos, V1/V2 | las evidencias AWS anteriores siguen en `docs/evidencias/` y `perf/results/` (no se mueven) |
| `oci/` | base Terraform, transferencia con SHA-256, simulacro de restauración | PENDIENTE |
| `azure/` | base, presupuesto, Zabbix/Grafana, pruebas externas | PENDIENTE |
| `integracion/` | fallo real → detección → alerta → recuperación entre nubes | PENDIENTE |
| `automatizacion/` | CI estático, `terraform validate/plan`, Ansible | PENDIENTE |
| `informe-material/` | diagramas y tablas finales derivadas de las evidencias | PENDIENTE (el informe aún no se redacta) |
