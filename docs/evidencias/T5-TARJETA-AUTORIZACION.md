# T5 — AWS alta disponibilidad real (ALB + ASG + EC2): sustitución de una EC2 defectuosa — tarjeta de preparación (22-nov-2026)
**Estado: verificado en solo lectura con la sesión de Academy viva (22-nov 20:25 UTC). NADA se ha creado, encendido ni detenido. Falta tu autorización específica.** Orden T1–T8 intacto; T6 sigue bloqueado (`T6-BLOQUEOS-OBLIGATORIOS.md`).

## 1. Qué demostrará T5 (y qué no)
- **Sí:** con tráfico de salud constante a través del ALB, se detiene la API de UNA EC2 (de 2, en 2 zonas); se miden la **detección por el ALB**, la **continuidad del servicio**, la **sustitución real por el ASG** (la instancia defectuosa ya no está; el ASG lanza otra) y el tiempo hasta **2 destinos sanos**; sin pérdida de datos; y **Azure observa** la ventana con sondas reales desde su VM.
- **No:** failover a OCI (T6), compuerta de escritura ni elección de líder (sin OCI no hay lease entre nubes), caída de zona completa ni RDS failover (opcional, no incluido). Una prueba de caída parcial con ALB **no** produce «cero impacto»: en pruebas previas hubo 502 durante la detección (22-oct/4-nov: detección 22,6 s; 52 respuestas 502); el criterio de disponibilidad ≥ 99 % se mide y se informa tal cual.

## 2. Estado REAL verificado (solo lectura, 22-nov-2026 20:14–20:25 UTC; sesión de Academy iniciada por la propietaria)
| Verificación | Resultado |
|---|---|
| Credenciales (perfil `nexoeventos-lab`, rol `voclabs`) | ✔ válidas; cuenta = `expected_account_id`; región `us-east-1`. Sesión: 03:58 al iniciar ⇒ caduca ≈ **00:16Z del 23-nov** |
| Crédito | USD 27,60 usado de 50 ⇒ **22,40 restantes** (bajó 0,30 desde el dato anterior: la **EC2 de V1 se encendió sola al iniciar el laboratorio**, 20:14:34Z) |
| Puertas de entrada (`t5-puertas-solo-lectura.sh`, `puertas.json`) | ✔ **8/8**: cuenta, región, RDS Multi-AZ, ASG 0/0, sin EC2 de V2, AMI `available`, ACM emitido, secreto presente |
| RDS `nexoeventos-academy-postgres` | `db.t3.micro`, **Multi-AZ**, 20 GB gp2, **stopped** (hay que iniciarla ≈ 15 min; se detiene al cerrar) |
| ASG `nexoeventos-academy-v2-asg` | mín 0 / deseada 0 / máx 3, `health_check_type = ELB`, gracia 120 s; plantilla de lanzamiento y 1 grupo de destino existen |
| **ALB** | **no existe** (fue eliminado por la limpieza del 20-nov; hay que recrearlo) |
| AMI | `nexoeventos-v2-20261022t051316z`, 22-oct, `available`; `ami_includes_livez = true` ⇒ health check `/livez` |
| Certificado ACM | importado, **Let's Encrypt**, `nexoeventos-demo.duckdns.org`, válido hasta 1-ene-2027 (CA pública ⇒ el recolector lo valida con `verify_as`, sin fijar nada) |
| Alarmas CloudWatch | existen (EC2, RDS, ALB 5xx, tracking del ASG); el estado de las del ALB cambia al recrearse el ALB |
| Facturable ahora | **EC2 de V1 `nexoeventos-academy-app` (t3.small) en ejecución** (≈ 0,021 USD/h + EBS 20 GB), sin NAT ni EIP sueltas |
| **`rds-window.sh check`** | ✔ cuenta, RDS stopped, ASG 0, sin ALB; ❌ **BLOQUEO: hay 1 EC2 en ejecución (la de V1)** ⇒ hay que detenerla antes de la ventana |
| **Terraform (plan guardado, sin aplicar)** | **3 a crear, 6 a modificar, 0 a destruir**: crear ALB + listener 80 (redirección) + listener 443; modificar ASG (mín/deseada 0→2, máx sin cambio), panel y 4 alarmas (solo atributos que dependen del ALB nuevo). `review-plan.py resume`: **PLAN REVISADO, 0 destrucciones, 0 sustituciones** (ningún cambio en RDS, IAM, secretos, DNS, redes, certificados, claves o S3) |
| Azure | VM desasignada; apagado original 17:38 UTC guardado; presupuesto `presupuesto-nexoeventos` **USD 60/mes, gastado 14,32**; T4 costó ≈ 0,21 |
| Git | rama `entregable2-auditoria` = `33b6a8e` (CI 6/6); estos archivos de T5 siguen sin commitear |

## 3. Procedimiento propuesto (una ventana AWS ≤ 2 h; todo con marcas UTC; reloj desde el `apply`)
Hay que empezar **antes de las 23:30Z** (todo lo facturable detenido ≥ 45 min antes de caducar la sesión a las ≈ 00:16Z). Con la sesión viva, conviene hoy mismo.
| Paso | Quién | Acción | Cambia |
|---|---|---|---|
| 0 | Yo (con tu autorización) | **detener la EC2 de V1** (`stop-instances`; reversible, conserva el disco); es requisito del `check` y ahorra crédito | EC2 de V1 → stopped |
| 1 | Yo | **Azure primero:** `azure-t4-ventana.sh --iniciar 3` (+ vigilante en el Mac), paquete con el recolector actualizado; el historial muestra AWS en ERROR antes del despliegue (línea base real) | VM de Azure encendida |
| 2 | Yo | `rds-window.sh watchdog` armado y `chain --scenario resume`: enciende la RDS, regenera y **revisa** el plan (0 destrucciones; cualquier otra cosa aborta y apaga), aplica **solo el plan guardado**, espera 2 destinos sanos en 2 zonas y comprueba HTTPS/`/livez` | RDS, ALB, 2 EC2 |
| 3 | Yo | `targets.json` de Azure con el DNS del ALB (`verify_as` = dominio del certificado); ≥ 5 min de ciclos reales | — |
| 4 | Yo | baseline: reparto (200 GET, ambas instancias reciben), sesión sin afinidad, flujo y reservas concurrentes (`verify-v2-flow.py`) y huella de datos ANTES | datos de prueba |
| 5 | Yo | `v2-failover-test.py --allow-replacement` con tráfico constante: detiene la API de UNA EC2; el ALB la marca no sana; el ASG la sustituye; mide detección, 502, continuidad y recuperación | una EC2 sustituida |
| 6 | Yo | huella y flujo DESPUÉS; compilar Azure (`ejecutar_t5.py azure`), zonas, datos, costos | no |
| 7 | Yo | **limpieza:** `v2-terraform.sh off`/`v2-down.sh` (EC2 terminadas), ALB eliminado por plan revisado, **RDS detenida y verificada `stopped`**; `azure-t4-ventana.sh --cerrar` (apagado restaurado exacto); V1 queda detenida (o encendida si lo pides) | revierte |
| 8 | Yo | `ejecutar_t5.py evidencia` → PASS/FAIL; `record-evidence T5` solo si PASS | no |

## 4. Costos, riesgos y límites
- **AWS (≤ 2 h):** ALB 0,0225 + LCU ≈ 0,008 · 2×t3.small 0,042 · IPv4 (2 EC2 + 2 del ALB) ≈ 0,02 · EBS ≈ 0,003 · RDS Multi-AZ db.t3.micro ≈ 0,034 ⇒ ≈ **0,13 USD/h ⇒ ≈ 0,26 USD** (tarifas públicas, sin verificar con facturación). Detener V1 ahorra ≈ 0,02 USD/h. **Techo duro 1,5 USD**; **parar si el crédito baja de 21,40** (−1,0) o si aparece un recurso no previsto.
- **Azure (≈ 3 h):** 0,108 USD/h ⇒ ≈ 0,33 USD; gastado 14,32 de 60 en el mes.
- **Riesgos:** (R1) la sustitución tarda más de 300 s (medido antes: ALB marca no sana a los 22,6 s y capacidad restaurada ≈ 110–138 s); (R2) 502 durante la detección ⇒ la disponibilidad ≥ 99 % puede no cumplirse y se informa tal cual; (R3) la RDS Multi-AZ tarda 5–15 min en arrancar y en detenerse (el watchdog del Mac la detiene; si el Mac se apaga, la red de seguridad última es la sesión de Academy); (R4) caducidad de credenciales a mitad de la ventana ⇒ comprobación de vida antes de cada paso; (R5) la EC2 de V1 vuelve a encenderse si se reinicia el laboratorio; (R6) Zabbix: el host `aws-nexoeventos-v2` sigue deshabilitado (la web check con el DNS del ALB no coincide con el certificado); la observación desde Azure es la del recolector.
- **Parar de inmediato si:** plan con destrucciones o fuera de los 9 cambios; ALB sin destinos sanos > 90 s; credenciales caducadas; recurso o identidad no previstos; OOM; cualquier barrera en rojo. **Tiempo:** si la ventana supera 2 h, limpieza aunque falte una prueba.

## 5. Criterios de PASS (9; todos medidos y cumplidos; `ops_center/criterios/T5.json`)
`disponibilidad_livez_pct` ≥ 99 · `deteccion_s` ≤ 30 · `sustitucion_sana_s` ≤ 300 · `ec2_reemplazada_por_asg` (la defectuosa ya no está y hay actividad de lanzamiento; una restauración manual **no** cuenta) · `dos_zonas_y_reparto` · `perdida_de_datos` (= sin pérdida) · `azure_observa_continuidad` (≥ 5 ciclos continuos, hueco ≤ 120 s; las alteraciones quedan en el historial) · `limpieza_verificada` · `costo_dentro_del_techo` ≤ 1,5 USD. Ausente o fallida ⇒ nunca PASS; un FAIL se registra con su causa y no se reinterpreta.

## 6. Autorización específica solicitada
«AUTORIZO T5: detener la EC2 de V1; ventana AWS ≤ 2 h (RDS Multi-AZ, ALB, 2 EC2 de V2 vía plan revisado con 0 destrucciones); inyección de fallo en UNA EC2 por detención de la API; limpieza completa con RDS detenida; techo USD 1,5; y ventana de Azure ≤ 3 h con apagado restaurado exacto.» Sin T6, sin DNS, sin OCI, sin S14, failover real bloqueado.
