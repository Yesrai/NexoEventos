# Plan único de ejecución cloud (PROPUESTA: nada de esto se ha ejecutado) — 3-nov-2026

Estado de partida (verificado en archivos, no en la nube): RDS `nexoeventos-academy-postgres` detenida el 28-oct 16:51 (UTC−5) con reactivación automática estimada el **4-nov 16:51 (UTC−5)**; EC2 de V1 detenida el 29-oct; VM de Azure desasignada; **V2 destruida** (no se asume que exista ninguna de sus piezas: AMI dorada, secreto compartido y certificado en ACM deben comprobarse). Todos los valores de coste son **estimaciones con tarifas públicas, no verificadas con la facturación**; el crédito restante de Academy **no está confirmado**.

## 0. Reglas de seguridad, presupuesto y parada (válidas en todas las fases)
- Una fase por autorización; nada pasa a la siguiente sin tu «sí» explícito. `NEXO_ALLOW_CLOUD_CHANGES=YES` solo dentro de la fase aprobada.
- **Techo de gasto de la sesión: 3 USD** (estimación pesimista de todo el plan: ≈ 1,5–2 USD). Si el crédito visible en Academy es menor que 10 USD, no se ejecutan las fases 3–6.
- **Criterios de parada inmediata:** error de identidad o región; `terraform plan` con destrucciones o cambios inesperados; cualquier recurso nuevo no listado aquí; el ALB sin destinos sanos más de 90 s; credenciales caducadas a mitad de una fase (se reanuda solo tras revisar el estado real); tiempo máximo del experimento superado (`--max-seconds`).
- Ningún secreto sale de AWS ni se imprime; las salidas se sanean antes de guardarlas en `docs/evidencias/`.
- Cada fase termina con una verificación de solo lectura del estado de los recursos y con la RDS y las EC2 en `stopped`/inexistentes.

## Fase 0 — Lectura de solo lectura (sin gasto relevante) · ≈ 15 min
**Qué:** identidad y región; estado de la RDS y de la EC2; `FreeStorageSpace` de la RDS (ventana del 28-oct 21:39–21:51 UTC, `get-metric-statistics`, 5 min) y `FreeableMemory`; configuración actual del lifecycle de S3 y lista de objetos en `backups/database/` (nombres, tamaños y fechas, sin contenido); existencia de la AMI dorada, del secreto compartido y del certificado en ACM; alarmas, temas SNS y trails existentes; confirmar que no hay ALB/ASG de V2.
**Por qué:** cierra la duda del aviso de 20 GiB con una medición real y decide qué fases son viables.
**Coste/riesgo:** ≈ 0 (las lecturas de CloudWatch se facturan a fracciones de centavo); riesgo nulo. **Evidencia:** `docs/evidencias/…-lectura-fase0/` saneada. **Si no se ejecuta:** `FreeStorageSpace` queda sin medir y el aviso se sigue documentando como «de configuración».

## Fase 1 — Seguimiento de la RDS · ≈ 10 min
**Qué:** si la RDS arrancó sola (evento «DB instance started» posterior al 28-oct), esperar a `available` (puede tener una copia automática en curso) y detenerla; si sigue detenida, decidir si arrancarla y detenerla reinicia el contador de 7 días (así se hizo el 28-oct).
**Coste:** ≈ 0,036 USD/h mientras corra (db.t3.micro Multi-AZ, estimado); ciclo corto ≈ centavos. **Rollback:** detener de nuevo. **Evidencia:** eventos de RDS y captura. **Requiere:** tu autorización específica sobre la RDS.

## Fase 2 — Cambios de V1 con `terraform plan` revisado y `apply` dirigido · ≈ 30 min (con RDS encendida solo si hace falta)
**Recursos (todos in situ o nuevos de coste ≈ 0):**
1. Subred de V1 sin IP pública automática (`map_public_ip_on_launch = false`): modificación in situ, **no recrea la subred**; la EC2 conserva su IP porque la pide explícitamente.
2. Lifecycle de S3 sobre `backups/database/` con **365 días** desde el 4-nov (`s3_backup_retention_days`; antes 90; véase `plan-despliegue-por-fases.md`, fase A): **riesgo de pérdida de respaldos**: los `.cms` del 19-oct y 23-oct caducarían hacia el 17-ene y 21-ene-2027 (la copia externa en OCI cubre el del 23-oct). Antes de aplicar, el plan debe mostrar solo el cambio de prefijo y de días; si se prefiere, subir a 365.
3. (Opcional) `enable_alarms = true`: tema SNS y alarmas; el correo se suscribe con `scripts/cloud/suscribir-correo-alarmas.sh` (**no pasa por Terraform ni por el estado**; la propietaria debe confirmar el mensaje de AWS). Detalle en [plan-fase2-alarmas.md](plan-fase2-alarmas.md), política del tema, 4 alarmas, suscripción a eventos de RDS. Coste ≈ 0,40 USD/mes (4 alarmas, capa gratuita de 10).
4. (Opcional) `enable_cloudtrail = true`: ver permisos de Academy; si `cloudtrail:CreateTrail` falla, se descarta.
**Riesgo:** un error de permisos de Academy; se detiene el `apply` (los recursos ya creados se pueden quitar con `destroy` dirigido). **Rollback:** `terraform apply` del estado anterior (valores previos de las variables) o `destroy -target` de lo nuevo; el lifecycle se revierte restaurando el prefijo/días anteriores (el bucket está versionado: los objetos borrados por caducidad dejan marca de borrado recuperable durante los días de versiones no vigentes). **Evidencia:** salida del plan y del `apply` saneadas; capturas de la regla de lifecycle, del tema SNS y de las alarmas.

## Fase 3 — AMI dorada con `/livez` · ≈ 60–75 min
**Recursos:** instancia temporal t3.small (≈ 0,02 USD/h) con SG sin entradas, volumen cifrado de 20 GiB, AMI y su instantánea (≈ 0,05 USD/GiB·mes → ≈ 0,5–1 USD/mes si se conserva). Requiere la EC2 de V1 encendida (≈ 10 min, solo para leer certificado y `backend.env`) **si el secreto compartido o el certificado ya no existen** (Fase 0 lo dirá).
**Dependencias:** Fase 0. **Riesgo:** instancia de construcción olvidada (se verifica `builder-delete`); coste pequeño. **Rollback:** `builder-delete`, anular el registro de la AMI y borrar su instantánea. **Evidencia:** versión de la AMI, `nginx -T` mostrando `location = /livez`, hash del paquete desplegado.

## Fase 4 — V2 con `ami_includes_livez = false`, luego `true` · ≈ 60 min
**Orden:** (1) `plan` y `apply` de `infra/aws-v2` con la AMI nueva y `ami_includes_livez = false` (21 recursos nuevos según el plan provisional anterior: ALB, 2–3 EC2, TG, ASG, políticas, panel; más alarmas si `enable_alarms`); (2) esperar 2 destinos sanos con `/healthz`; (3) **validar `/livez` en cada instancia nueva** (`curl` local por SSM: 200 y que la API detenida da 502, nunca 200 por `index.html`); (4) `ami_includes_livez = true` y `apply` (cambio in situ del health check del TG); (5) comprobar `HealthyHostCount = 2` sostenido.
**Coste:** V2 + RDS Multi-AZ ≈ 0,13 USD/h (ALB + 2 t3.small + RDS); 5 h ≈ 0,65 USD. **Riesgo:** falsa salud si se invierte el orden (protegido por la variable); la RDS debe estar `available`. **Rollback:** `ami_includes_livez = false` y `apply`; `terraform destroy` de la raíz V2. **Evidencia:** `HealthyHostCount`, actividades del ASG, captura del TG con la ruta `/livez`.

## Fase 5 — Experimentos reales (con tráfico ligero de lectura, sin carga) · ≈ 90 min
Todos con `--max-seconds`, el criterio de aborto del script y la RDS/EC2 en estado conocido antes de empezar.
| Experimento | Qué provoca | Hipótesis y criterio de éxito | Parada y rollback | Evidencia | Coste adicional |
|---|---|---|---|---|---|
| **B2** Autohealing repetido | `v2-failover-test.py --allow-replacement` (parar la API ≈ 60 s en 1 instancia) | El ASG reemplaza la instancia; `HealthyHostCount` nunca 0; `resultado.json` completo con la disponibilidad de `/api` separada de la de salud | Si el ALB queda sin sanos > 90 s o se supera el tiempo: restaurar la API (o dejar que el ASG termine el reemplazo) | `resultado.json`, `solicitudes.json`, actividades del ASG, 5xx y alarmas | ≈ 0 |
| **D2** Failover de RDS con V2 | `reboot-db-instance --force-failover` (≈ 14 s de interrupción) con tráfico de lectura | Con `/livez`: los 2 destinos **siguen sanos**, el ASG no lanza actividades, las peticiones de datos devuelven 503 con `Retry-After` y se recuperan en ≈ 14 s; sin `/livez` (control, `false`) el comportamiento acoplado se mediría | Si hay actividades del ASG o destinos no sanos > 90 s: parar el tráfico (la RDS se recupera sola) | `resultado.json` de `rds-failover-test.py` adaptado + métricas del ALB y del ASG | ≈ 0 (RDS ya encendida) |
| **N1** Cadena de notificación | `set-alarm-state` forzado sobre una alarma | El correo llega y la propietaria lo confirma | Volver al estado `OK` | Correo (captura) + historial; **marcado como estado forzado** | ≈ 0 |
| **N2** (opcional) Correo real de Azure | Ventana de la VM de Azure, carga de CPU controlada con el receptor ya verificado | Alerta activada **y** correo recibido | `az vm deallocate` y verificación | Correo recibido (captura) + historial de la alerta | ≈ 0,11 USD/h × ≈ 1 h |
**No se ejecutan:** zona completa, AWS FIS, carga alta. **Si no se hacen B2/D2:** el informe declara «corregido en código y probado en local, no validado en AWS».

## Fase 6 — Desmontaje y cierre · ≈ 30 min
`terraform destroy` de `infra/aws-v2` (plan guardado revisado: solo recursos de V2), borrar el constructor si quedara, **detener la RDS y la EC2 de V1**, verificar por lectura que no queda ALB, ASG ni EC2 de V2 y que RDS/EC2 están `stopped`; conservar los respaldos. **Evidencia:** verificación saneada y captura de «Detenida»/«Detención temporal».

## Resumen económico (estimación, no verificada)
| Concepto | Estimación |
|---|---|
| V2 + RDS Multi-AZ, 5 h | ≈ 0,65 USD |
| Constructor de AMI, 1,5 h | ≈ 0,03 USD |
| AMI + instantánea conservadas | ≈ 0,5–1 USD/mes (se puede borrar al terminar) |
| Alarmas (4–9) | ≈ 0,40–0,90 USD/mes (capa gratuita de 10 alarmas) |
| Azure N2 (opcional) | ≈ 0,11 USD |
| **Total de la sesión** | **≈ 1,3 USD (techo 3 USD)** |
**Si no se ejecuta nada de esto:** el proyecto queda con las correcciones en código (probadas en local y en CI) y los experimentos A, C, D (V1), E y R01 como evidencia real; B incompleto; sin validación de `/livez` ni de alarmas en AWS.

## Autorizaciones concretas que necesito (cada una independiente)
1. Sesión de Academy activa y **Fase 0** (solo lectura).
2. **Fase 1:** actuar sobre la RDS (detener si arrancó sola; o arrancar y detener para reiniciar el plazo).
3. **Fase 2** (cambios de V1): `plan` revisado juntos y `apply` dirigido; indicar el **correo** para SNS y si se prefiere 365 días en el lifecycle.
4. **Fase 3:** construir la AMI (y arrancar la EC2 de V1 solo si hace falta).
5. **Fase 4:** desplegar V2.
6. **Fase 5:** B2, D2, N1 (y N2 si quieres probar el correo de Azure).
7. **Fase 6:** desmontaje (se ejecuta siempre al terminar cualquier fase de creación).
8. Commit y push de los cambios locales pendientes para validarlos en el CI.
