# T5 — Análisis de la disponibilidad (95,21 %) y propuesta técnica para un 2.º intento — 23-nov-2026
**Nada se ha ejecutado en la nube para este análisis** (solo lecturas y planes sin aplicar). El criterio original (≥ 99 %) **no se modifica**. El expediente FAIL del 1.er intento se conserva íntegro: `work/evidencias/T5-20261123T005244Z-9eed/` (manifiesto verificado, `resultado.json` sha256 `8a0aa30797ec3f16…`), `work/t5/` y su copia `work/backups/t5-intento1-20261123T010440Z/` (SHA-256 verificado).

## 1. Mecanismo exacto: por qué la instancia defectuosa siguió recibiendo tráfico 24,9 s
Cronología medida (s desde T0 del tráfico): fallo pedido 28,8 → **primer error 29,98** (1,2 s) → ALB marca `unhealthy` **53,7** (23,7 s después del primer error) → **último error 51,96** (1,7 s antes de marcarla) → el ASG la termina y lanza otra → 2 sanos de nuevo a 188,6 s.
- El ALB enruta a **todo destino registrado que NO esté marcado `unhealthy`**. Su estado solo cambia por las comprobaciones **activas** de salud: tras `unhealthy_threshold` (2) fallos **consecutivos**, cada uno separado por `interval` (10 s). Un fallo puede ocurrir en cualquier punto del intervalo: 1.ª comprobación fallida entre 0 y 10 s después, 2.ª 10 s más tarde ⇒ 10–20 s, más propagación a los nodos del ALB y mi sondeo (≈ 2 s). Medido: 23,7 s. El enrutamiento cesó **al cambiar el estado** (los errores terminan 1,7 s antes de la marca, el tiempo de mi muestreo/propagación).
- Reparto durante la ventana: **112 solicitudes, 56 fallos = 50 %** (N = 2 destinos). Todos los fallos fueron **502 generados por la Nginx de la propia instancia** (la API estaba detenida, Nginx seguía vivo y respondía al instante): CloudWatch `HTTPCode_Target_5XX` = **56** = los 502 del cliente; `HTTPCode_ELB_5XX` = 0. No hubo timeouts ni errores de conexión.
- Fallo **rápido** (Nginx contesta 502 de inmediato) ⇒ el ALB no tiene otra señal pasiva: **sin ATW, el ALB no reintenta ni reacciona a los 5xx de un destino; espera a las comprobaciones activas**.

## 2. Límites reales de las comprobaciones de salud y configuración
| Parámetro | Límite del ALB (documentación de AWS) | Configurado (antes) | Mínimo posible |
|---|---|---|---|
| `interval` | 5–300 s | 10 | **5** |
| `timeout` | 2–120 s | 5 | 2 (aquí se exige además `< interval`) |
| `healthy_threshold` | 2–10 | 2 | 2 |
| `unhealthy_threshold` | 2–10 | 2 | **2** |
Detección activa más rápida posible = 2 × 5 = **≈ 10 s** (+ propagación): no existe configuración de ALB por debajo. Configuración previa en Terraform (`infra/aws-v2/alb.tf`): intervalo 10, timeout 5, umbrales 2/2, algoritmo `least_outstanding_requests`, `deregistration_delay` 30, ruta `/livez`, `matcher 200`. **Corrección preparada (sin aplicar):** variables `alb_health_interval`, `alb_health_timeout`, `alb_lb_algorithm`, `alb_anomaly_mitigation` con **valores por defecto idénticos a los actuales** (probado: el plan por defecto sigue siendo 3/6/0 y pasa el revisor «resume»). Los umbrales y la ruta no cambian.

## 3. Cálculo con las muestras reales (reproducible: `python3 scripts/ops/t5_contrafactual.py work/t5/medidas/solicitudes.json`)
- Denominador sin cambios (todas las solicitudes `/healthz` desde T0 hasta 15 s tras recuperar; 502, timeouts y -1 cuentan): **480** sondeos ⇒ el 99 % admite **como máximo 4 fallos** (con 5 ya es 98,96 %). Sobre todo el tráfico (997): máximo 9. Observado: **23** y **56**.
- **CONTRAFACTUAL (estimación a partir de recortar/escalar las muestras reales; NO es una medición ni una demostración)** — disponibilidad de `/healthz` si el ALB hubiera dejado de enrutar a la víctima D s tras el primer error, con N destinos (cada uno recibe 1/N; fallos escalados por (1/N)/(1/2)):
| N \ D | 22 s (observado, N=2) | 12 s | 10 s | 8 s | 5 s |
|---|---|---|---|---|---|
| 2 | **95,21 %** (medido) | 97,50 | 97,71 | 98,12 | 98,54 |
| 3 | 96,81 | 98,33 | 98,47 | 98,75 | 99,03 |
| 4 | 97,60 | 98,75 | 98,85 | 99,06 | 99,27 |
| 6 | 98,40 | **99,17** | **99,24** | 99,38 | 99,51 |
| 8 | 98,80 | 99,38 | 99,43 | 99,53 | 99,64 |
- **Respuesta a «¿llega la configuración de 5 s?»: NO, con N = 2.** Con D ≈ 10–12 s (5 s × 2) se estiman 97,5–97,7 %. Con N = 2 el 99 % exigiría que el enrutamiento cesara en **≤ 2,5 s**. Con N = 3 y 5 s: ≈ 98,5 % (falla). Detección máxima que tolera el 99 % (estimada): N=2 → 2,5 s · N=3 → 3,3 s · N=4 → 7,5 s · **N=6 → 12,4 s** · N=8 → 15,6 s.

## 4. Qué mecanismos válidos hay dentro de la arquitectura (y cuáles NO)
Separando tres cosas: **detección** (≤ 30 s: ya cumple, 24,9 s), **recuperación de capacidad por el ASG** (≤ 300 s: ya cumple, 159,8 s) y **disponibilidad real** (≥ 99 %: falla). La sustitución del ASG **no puede** mejorar la disponibilidad: ocurre después; lo que importa es cuántas solicitudes llegan al destino muerto antes de que el ALB deje de enrutarlo.
| Mecanismo | Efecto | Estado |
|---|---|---|
| **A. Health check 5 s × 2** | detección activa ≈ 10–12 s (mínimo del ALB) | válido; **insuficiente por sí solo** (N=2: 97,5 %) |
| **B. Más destinos (N+1)** | un fallo afecta a 1/N de las solicitudes (cambio de parámetro del ASG existente: `asg_min/desired/max`; la AMI y el ALB no cambian) | válido; con 5 s: N=3 → 98,5 %, **N=6 → 99,2 %** (estimado) |
| **C. ATW** (`weighted_random` + mitigación de anomalías) | compara el % de errores (5xx y errores de conexión) de cada destino con sus pares, **independiente** de las comprobaciones de salud; reduce su tráfico en pasos (cada 5 s) hasta lo mínimo | válido y nativo; AWS exige **≥ 3 destinos sanos**, no es compatible con `slow_start` ni afinidad, **no publica umbrales ni un tiempo garantizado**: su efecto solo se sabe midiéndolo (métricas `AnomalousHostCount`/`MitigatedHostCount`) |
| D. Auto-baja del destino al detener el servicio (hook systemd que lo desregistra) | evita los 502 en una **parada controlada** | **NO se aplica**: convertiría la parada controlada en un no-evento y ocultaría el fallo que se prueba; además no ayuda en una caída abrupta |
| E. Reintentos del cliente / más ventana / otro denominador / excluir 502 | «mejora» el número sin mejorar el servicio | **descartado** (violaría tus reglas 5 y la decisión de no forzar un PASS) |
**Parada controlada vs caída abrupta.** El fallo del 1.er intento fue `systemctl stop` de la API: parada **controlada y rápida** (SIGTERM; Nginx vivo; 502 inmediato). Es el caso **más benigno**: una pérdida abrupta de la instancia (`ec2 stop-instances`, caída de kernel o de hipervisor) no devuelve 502 sino **silencio de TCP**: las solicitudes enrutadas al destino muerto esperan al tiempo de conexión del ALB antes de fallar, y los errores duran lo mismo (la detección activa es la misma) pero con mayor latencia. Por eso se añadió `--fault instance` al generador (por defecto sigue `stop`, para comparabilidad y para el criterio original). **Mi recomendación honesta:** el criterio de T5 se mide sobre la parada controlada (como se definió); la caída abrupta se mide como prueba **adicional informativa** y no se promete que alcance el 99 %.

## 5. Medición de extremo a extremo (sin cambios)
Se reutiliza el mismo generador (5 req/s, 4 clientes, conexión nueva por solicitud, ruta aleatoria `/api/events`|`/healthz`), la misma base sana (25 s), la misma retención tras detección (60 s) y la misma cola (15 s). No se reinicia ningún contador tras el fallo, no se amplía la ventana y los 502, timeouts y errores de conexión (-1) cuentan como fallos (`v2-failover-test.py` y `ejecutar_t5.py` + sus pruebas lo verifican). Nuevo: marcas **UTC con milisegundos** de cada hito (`events.utc`, `t0_utc`) y tipo de fallo en el resultado.

## 6. Observabilidad de Azure (corregida, probada en local)
`ops_center/fastprobe.py` + `ops-fastprobe.service`: GET `/livez` al ALB (certificado validado contra el dominio de NexoEventos) **cada 5 s** con marca UTC en ms, programado por reloj (sin deriva), fallos registrados nunca omitidos; se arranca **solo durante la ventana** y se detiene al cerrarla. `azure_observa_continuidad` pasa a exigir: recolector (hueco ≤ 120 s) **y** sonda rápida (hueco ≤ 15 s, ≥ 5 min de línea base) que **capture el incidente** (≥ 1 muestra fallida dentro de su ventana) sin fallos inexplicados fuera de él. Es un criterio **más estricto**: una ventana de 22 s a un 50 % de fallos y un muestreo de 5 s da ≈ 94 % de probabilidad de capturarlo; si no lo captura, falla honestamente. Relojes: `scripts/ops/t5_relojes.py` mide Mac↔NTP (hoy −0,03 s) y Azure↔Mac (Cristian, error ≤ RTT/2); exige ≤ 1 s.

## 7. Coherencia AWS ↔ Terraform tras la limpieza (planes sin aplicar, 23-nov ≈ 01:00Z)
`terraform plan` con el estado real: **3 a crear, 6 a modificar, 0 a destruir**, idéntico al previo a la prueba: ALB y sus 2 listeners **eliminados** (limpieza por API ⇒ «has been deleted», se recrean); ASG existe a 0/0 (in-situ → 2); panel y 4 alarmas dependen del ALB (in-situ); grupo de destino, plantilla de lanzamiento, AMI, certificado y secreto sin cambios; **la RDS no está en este estado de Terraform** (se opera con `rds-window.sh`; real: `stopped`, Multi-AZ). `review-plan.py resume` lo acepta; las variantes B (3 inst.) y C (6 inst.) dan **3 a crear, 7 a modificar, 0 a destruir** y las aceptan los nuevos escenarios `t5b` y `t5c` del revisor estricto (solo permiten ALB/listeners, monitoreo, ASG y **únicamente** algoritmo/ATW e intervalo/timeout del health check); cada escenario rechaza los planes de los otros.

## 8. Pruebas locales de regresión (todas en verde)
`backend/tests/test_v2_plan_review.py` (15: escenarios t5b/t5c, desviaciones, recursos sensibles, valores por defecto), `ops_center/tests/test_fastprobe.py` (8), `test_t5_tool.py` (19; incl. captura del incidente, falsos inexplicados, resolución, **bug de zona horaria hallado y corregido**), `test_v2_failover_t5.py` (6: tipos de fallo, UTC, denominador, relojes), `ops_center` completo 246 pasan.

## 9. Tiempo y crédito de Academy
Sesión nueva iniciada ≈ 00:07Z ⇒ caduca ≈ **04:07Z** (confirma el temporizador en la consola); el orquestador exige `ahora + ventana + 45 min ≤ caducidad`: una ventana de **90 min solo cabe si empieza antes de ≈ 01:50Z**; de lo contrario hay que reiniciar el laboratorio (credenciales nuevas) y repetir las puertas. Crédito: 22,40 antes del intento; gasto estimado del intento ≈ USD 0,15 ⇒ **≈ 22,25** (confírmalo en la consola). La cuota de vCPU de EC2 no se puede leer con este rol (`servicequotas` denegado): 6 × t3.small = 12 vCPU + V1 detenida; si la cuota fuera insuficiente, el `apply` fallaría sin dañar nada y se revertiría.

## 10. Propuesta (requiere tu autorización; no se ejecuta nada)
**Variante C** (más posibilidades reales): 6 instancias (`asg_min=desired=max=6`), health check 5 s/3 s, umbrales 2/2 sin cambio, `weighted_random` + mitigación de anomalías, **misma** parada controlada y mismos parámetros de tráfico; criterios intactos (≥ 99 %, ≤ 30 s, ≤ 300 s, ASG, dos zonas, datos, Azure con sonda rápida, costo, limpieza). Costo estimado ≈ 0,23 USD/h de AWS (6 × t3.small 0,125 + ALB 0,031 + RDS 0,034 + IPv4 ≈ 0,04) ⇒ ≈ USD 0,3 por ≈ 80 min; techo duro 1,5. **Probabilidad honesta:** el cálculo contrafactual sitúa N=6 con D ≈ 10–12 s en el límite (99,2 % estimado; el 99 % admite solo 4 fallos de 480): el resultado es **incierto** y puede quedar entre 98 y 99,5 %. **Alternativa B** (3 instancias): estimado 98,5 % — **no** alcanzaría 99 % salvo que ATW actúe en < 5 s; solo tendría sentido como experimento de ATW. En cualquier caso, **ninguna** de estas cifras es un resultado: solo la ventana real decide.
