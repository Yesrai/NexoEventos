# RDS compartida: máximo de autoescalado de almacenamiento 20 → 40 GiB (6-nov-2026, 14:29 hora de Perú, saneado)

Autorizado por la usuaria (solo `MaxAllocatedStorage`).

Antes (14:29): identificador `nexoeventos-academy-postgres` (única RDS de la cuenta), `available`, Multi-AZ, `db.t3.micro`, gp2, **AllocatedStorage 20 GiB**, **MaxAllocatedStorage 20**, retención 7 días, sin modificaciones ni mantenimiento pendientes, restaurable hasta 5 minutos antes (PITR), último respaldo automático del 6-nov 07:45 UTC, 17,05 GiB libres, V1 con 200 en `/healthz` y `/api/events`.

Comando (única llamada de escritura): `aws rds modify-db-instance --db-instance-identifier nexoeventos-academy-postgres --max-allocated-storage 40 --apply-immediately`.

Después (14:29:26 en adelante; sondeo cada ~6 s durante 1 min 48 s): `available` en todas las lecturas, AllocatedStorage 20, MaxAllocatedStorage 40, Multi-AZ activo, sin modificaciones pendientes; V1 `/healthz` = 200 en las 18 lecturas, `/api/events` y `/livez` = 200; sin eventos de RDS en los 10 minutos posteriores; alarmas de RDS en `OK`; 17,05 GiB libres. La comparación completa antes/después (`rds-antes.json`, `rds-despues.json`, sin ARN, secretos ni endpoint) muestra **una sola diferencia: `MaxAllocatedStorage` 20 → 40**.

Observación honesta: en este intervalo no se observó ninguna interrupción; el cambio es de metadatos, pero solo se afirma lo medido. Comprobación posterior (14:47 hora de Perú): el aviso periódico de RDS («approaching the maximum storage threshold»), que llegaba cada 2 horas (último: 17:45 UTC), **no apareció en el ciclo de las 19:45 UTC (14:45)**; no hay eventos de RDS en los últimos 90 minutos. Es una sola observación; conviene confirmarla en los próximos ciclos.

Costo adicional potencial: 0 hoy; si el almacenamiento llegara a crecer hasta 40 GiB, ≈ +4,6 USD/mes (gp2 0,115 USD/GiB-mes × 20 GiB × 2 por Multi-AZ), sin posibilidad de reducirlo después.

Consistencia local (fuera de Git): `work/terraform-envs/academy-multiaz.tfvars` y `academy.tfvars` ahora declaran `db_max_allocated_storage_gib = 40`. No se ejecutó terraform sobre V1.
