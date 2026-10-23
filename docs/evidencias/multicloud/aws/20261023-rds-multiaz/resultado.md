# RDS Single-AZ → Multi-AZ (AWS Academy, us-east-1) — 2026-10-23 UTC

Estado: **implementado y verificado** (conversión y estado). Failover **no probado** (pendiente, requiere autorización).

- Inicio de RDS (stopped → available): ~249 s (23:5x UTC del 22-oct).
- Plan dirigido `-target=aws_db_instance.postgres`, estado `academy-current`: 0 crear, 1 cambiar, 0 destruir.
- Primer `apply` rechazado por estado transitorio `configuring-enhanced-monitoring` (InvalidDBInstanceState), no por política de Academy; el plan quedó obsoleto, se regeneró y se aplicó (solo `multi_az`).
- Conversión (eventos RDS): 00:17:12 → 00:25:11 UTC (~8 min). `terraform apply` tardó 584 s.
- Resultado: `available`, `MultiAZ=true`, primaria us-east-1b, secundaria us-east-1a.
- Sin cambios en EC2, S3, CloudWatch, datos ni respaldos. EC2 V1 detenida.
- Aviso de RDS: "Storage size 20 GiB is approaching the maximum storage threshold 20 GiB" (autoescalado desactivado por diseño).
- Costo estimado (no verificado con facturación): ~USD 0,02/h extra de instancia + ~USD 2/mes de almacenamiento duplicado.
