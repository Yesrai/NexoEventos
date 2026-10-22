# Propuesta: demostrar el escalado horizontal de V2 (2 → 3 instancias) con la política existente

Sin cambios de Terraform: política de seguimiento `ASGAverageCPUUtilization` con objetivo **40 %**, grupo 2–3, calentamiento 120 s, gracia del health check 120 s.

## Por qué el perfil mixto actual no basta
Con 50 usuarios (78 req/s) cada instancia usa ~20 % de CPU: la media del grupo (20 %) queda por debajo del objetivo. El generador está limitado a 50 usuarios, así que hace falta tráfico **más caro en CPU por solicitud**: el login (Argon2) cuesta ~0,16 s de CPU y una instancia alcanza ~6 logins/s al 100 % (medido en V1).

## Carga controlada
Un escenario k6 nuevo `login_rate` (executor `constant-arrival-rate`, ≤ 50 usuarios, usuarios ficticios `k6-*` creados en `setup`, sin tocar datos reales): **8 inicios de sesión/s durante 8 min** ⇒ ~4/s por instancia ≈ **60–65 % de CPU**. La alarma de seguimiento exige 3 minutos consecutivos por encima de 40 %. El máximo del grupo (3) acota el escalado y el costo. Al terminar la carga, la media baja a ~0 %.
Alternativa (requiere `terraform apply` de un solo recurso, no incluida): bajar `scale_cpu_target_pct` a 15 y usar el perfil mixto de 50 usuarios.

## Qué se mide (cada 10 s)
`DesiredCapacity`, instancias y su estado en el ASG, destinos sanos del ALB, estado de las alarmas `AlarmHigh/AlarmLow` de la política, CPU/memoria por instancia (muestreo por Session Manager), RDS (CPU, conexiones, memoria liberable, créditos), créditos excedentes, latencia/errores de k6 y reparto de solicitudes por instancia (3 al final).
Hitos: inicio de carga → alarma alta → capacidad deseada 3 → instancia en `pending` → `InService` → **tercera instancia `healthy`** (objetivo ≈ 7–9 min tras iniciar la carga) → fin de carga → alarma baja → deseada 2 → instancia terminada (≈ 15–20 min tras terminar la carga: el escalado hacia dentro exige 15 min por debajo de ~36 %).

## Criterios de parada (se corta la carga y se informa; sin reintentos ni terminaciones manuales)
Cualquier error inesperado o 5xx; p95 de login > 3 s sostenido 60 s; CPU > 85 % durante 2 min en una instancia; memoria disponible < 300 MB; CPU de RDS > 60 %, memoria liberable < 100 MB o conexiones > 50; créditos excedentes > 50 por instancia; menos de 2 destinos sanos; la tercera instancia no está sana a los 12 min de iniciar la carga; el grupo no vuelve a 2 a los 25 min de terminar la carga.

## Duración y costo (estimaciones por tarifa)
Duración total ≈ **35–40 min** (5 min de comprobaciones, 8 min de carga, 20–25 min de espera del escalado hacia dentro). La tercera instancia existe ≈ 25–30 min: EC2 + IPv4 ≈ USD 0,026/h ⇒ **≈ USD 0,013**. Créditos excedentes de CPU (modo `unlimited`) ≈ USD 0,01. Base ya en marcha (V2 + RDS ≈ USD 0,11/h) ≈ USD 0,07 en la ventana. **Total ≈ USD 0,10, techo con reserva USD 0,30.**
Requisitos: encender temporalmente la EC2 de V1 solo para crear/limpiar los usuarios ficticios y la huella (identidad migradora), como en la medición V1/V2; añadir el escenario `login_rate` a `perf/k6/nexo.js` y un orquestador de observación (cambios de herramientas de prueba, no de infraestructura).
