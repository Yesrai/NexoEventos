# T5 — Alta disponibilidad AWS (ALB + ASG): **PASS 9/9 con la variante C (6 instancias)** — 23-nov-2026
Expediente PASS: `work/evidencias/T5-20261123T023342Z-0532/` (manifiesto SHA-256 verificado, 0 alterados). **Historia completa conservada:** 1.er intento **FAIL** con 2 instancias (`work/evidencias/T5-20261123T005244Z-9eed/`, 95,21 %), 2.º intento abortado por la SCP (`T5-20261123-intento2-abortado.md`) y este 3.er intento. Criterios **sin cambios** desde el 1.er intento. No se registra en el centro de operaciones (solo admite T1–T4).

## Resultado medido (una sola ejecución oficial, sin ensayos previos)
| Criterio | Regla | Valor | |
|---|---|---|---|
| Disponibilidad `/healthz` por el ALB | ≥ 99 % | **99,49 %** (396 sondeos, 2 fallos; el 99 % admitía como máximo 3) | cumple |
| Detección (parada → ALB marca `unhealthy`) | ≤ 30 s | **9,6 s** | cumple |
| Recuperación con 6 destinos sanos | ≤ 300 s | **125,0 s** | cumple |
| Sustitución real por el ASG | sí | «Terminating …02332a2e…» y «Launching …0f7e95a7…»; ninguna restauración manual | cumple |
| Dos zonas y reparto | sí | 3 + 3 (us-east-1a/b); 15–17 % por instancia antes y después | cumple |
| Sin pérdida de datos | sí | 32 eventos, huella del catálogo idéntica antes/después y a la del 1.er intento; `/ready` 200; RDS disponible | cumple (solo lectura) |
| Azure observa | sonda de 5 s que capture el incidente | **capturado**: muestra 02:14:37,412Z con 1 de 6 solicitudes en 502, dentro de la ventana del generador (02:14:30,263–02:14:38,293Z); 0 fallos inexplicados; hueco máx 5,0 s; 372,9 s de línea base; recolector (60 s) 12 ciclos | cumple |
| Limpieza | sí | ASG 0/0 (máx 6), 0 EC2, sin ALB, RDS `stopped`, V1 `stopped`, Azure desasignada con apagado restaurado exacto | cumple |
| Costo | ≤ USD 1,5 | ≈ USD 0,29 (AWS ≈ 0,20 cota alta + Azure ≈ 0,10) | cumple |
Metodología idéntica a la del 1.er intento: 5 req/s, 4 clientes, conexión nueva por solicitud, ruta al azar `/api/events`|`/healthz`, base 25 s, retención 60 s, cola 15 s, mismo fallo (parada controlada de la API). Denominador: todas las solicitudes `/healthz` de T0 a +15 s tras recuperar; **los 8 errores (502) cuentan**; el contador no se reinició y la ventana no se amplió (169,8 s frente a 204,9 s del 1.er intento: la fija el propio proceso y la recuperación fue más rápida). Sobre **todo** el tráfico: 816/824 = **99,03 %**. CloudWatch: `HTTPCode_Target_5XX` = 9, `HTTPCode_ELB_5XX` = 0; `HealthyHostCount` mínimo 5.

## Lo que este PASS demuestra y lo que NO (honestidad)
- **Es un resultado estadístico de una sola ejecución.** El 99 % admitía 3 fallos de 396 sondeos de salud y hubo 2; el modelo previo daba ≈ 45–60 % de probabilidad sin ATW. **No** se infiere que repetirlo dé siempre PASS; el FAIL de N = 2 (95,21 %, 56 errores) se conserva y se cita junto a este resultado.
- **Qué lo explica:** la detección activa fue de 9,6 s (health check 5 s × 2) y un fallo afecta a 1/6 de las solicitudes (8 errores en lugar de 56). **No** se atribuye a ATW: no hay evidencia de que haya acortado nada (los errores cesan 0,4 s antes de que el ALB marque `unhealthy`; las métricas `AnomalousHostCount`/`MitigatedHostCount` tienen resolución de 1 min y no se analizaron como causa).
- **Arquitectura:** la V2 documentada es de **dos instancias**; **6 es un punto de operación de alta disponibilidad** (≈ 0,26 USD/h frente a ≈ 0,13). La arquitectura final debe documentar **dos puntos**: económico (mín 2) y alta disponibilidad (mín 6). Con N = 2 el criterio de disponibilidad **no** se cumple (límite del mecanismo, demostrado).
- **Tipo de fallo:** parada controlada del servicio (Nginx responde 502 al instante), el caso más benigno; **la caída abrupta de una instancia NO se midió** (`--fault instance` quedó disponible como prueba informativa aparte) y no se promete que alcance el 99 %.
- **Datos:** el tráfico fue de solo lectura; no se probó una ruta de escritura durante la sustitución.
- **Relojes:** Mac frente a NTP −0,03 s; Azure frente al Mac +0,80 s con incertidumbre ±0,85 s (RTT de SSH 1,7 s: medida basta para el umbral, no precisa); la correlación Azure↔generador (muestra fallida dentro de la ventana de 8 s) es consistente.
- **Incidencias:** el primer ciclo del recolector tras apuntar al ALB nuevo (02:08:16Z) dio ERROR por `gaierror` (el DNS del ALB aún no se resolvía); la sonda rápida y la 2.ª comprobación no se vieron afectadas.

## Estado final (a tener en cuenta)
AWS: **ASG 0/0 con máximo 6** (la SCP de Academy permite 6 y deniega 7; el valor por defecto de Terraform sigue siendo 3), 0 EC2, sin ALB (eliminado por la API como en 20-nov y 23-nov), RDS `stopped`, V1 `stopped`. **Aplicados y coherentes con el estado de Terraform:** grupo de destino con health check 5 s/3 s, `weighted_random` y mitigación de anomalías `on`; plantilla de lanzamiento versión 2 (pool de BD 3+2). El próximo plan de la variante C da 3 a crear + 6 a modificar + 0 a destruir; **volver a la configuración económica (mín 2/máx 3, `least_outstanding_requests`, pool 5+5) requiere un plan revisado** (decisión tuya). Azure desasignada con el apagado de las 17:38 UTC restaurado exacto. `REAL_EXECUTION_WIRED=False`; S14, DNS y OCI sin cambios; T6 sigue bloqueado.

## Modos operativos de la V2 (documentados a petición de la propietaria, 23-nov-2026)
| | **Económico** | **Alta disponibilidad** |
|---|---|---|
| Instancias (ASG) | mín 2 / deseada 2 / máx 3 (valores por defecto de Terraform) | mín 6 / deseada 6 / máx 6 (`academy-v2-t5c.tfvars`; la SCP de Academy deniega un máximo de 7) |
| Health check del ALB | 10 s / 5 s, umbrales 2/2, `least_outstanding_requests` | 5 s / 3 s, umbrales 2/2, `weighted_random` + mitigación de anomalías; pool de BD 3+2 |
| Costo aproximado de AWS | ≈ 0,13 USD/h | ≈ 0,26 USD/h (peor caso) |
| Resultado medido de T5 (parada controlada de 1 instancia) | **FAIL de disponibilidad: 95,21 %** (56 errores); detección 24,9 s; recuperación 159,8 s | **PASS 9/9: 99,49 %** (2 errores en 396 sondeos); detección 9,6 s; recuperación 125,0 s |
**Alcance exacto del PASS:** el 99,49 % corresponde a **una sola ejecución** de la configuración de **6 instancias**; no se repitió ni se promedió. **La caída abrupta de una instancia (p. ej. pérdida de la instancia o del hipervisor) NO fue probada en T5** (solo una parada controlada del servicio), **ni se probó tráfico de ESCRITURA** durante la sustitución (el tráfico fue de solo lectura).
