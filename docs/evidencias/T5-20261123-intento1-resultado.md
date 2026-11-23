# T5 — Alta disponibilidad AWS (ALB + ASG): 1.er intento (23-nov-2026, 00:10–00:52 UTC) · **FAIL (8/9 criterios)**
Expediente: `work/evidencias/T5-20261123T005244Z-9eed/` (manifiesto SHA-256 verificado, 0 alterados). Veredicto **FAIL**; no se registra como PASS. Criterios sin cambios (los originales).

## Medido (real, AWS us-east-1 + Azure)
| Criterio | Regla | Valor | Resultado |
|---|---|---|---|
| `disponibilidad_livez_pct` | ≥ 99 | **95,21 %** (480 sondeos `/healthz`, 23 fallos; todo el tráfico: 94,38 %) | **NO CUMPLE** |
| `deteccion_s` | ≤ 30 | 24,9 | cumple |
| `sustitucion_sana_s` | ≤ 300 | 159,8 | cumple |
| `ec2_reemplazada_por_asg` | sí | sí: «Launching … i-03602…» y «Terminating … i-04d72…» (ningún arranque manual) | cumple |
| `dos_zonas_y_reparto` | sí | us-east-1a + us-east-1b; 101 y 100 solicitudes (50/50) tras la recuperación | cumple |
| `perdida_de_datos` | sin pérdida | 32 eventos y huella del catálogo idéntica antes/después; `/ready` 200; RDS available | cumple (solo lectura; ver límite) |
| `azure_observa_continuidad` | ≥ 5 ciclos, hueco ≤ 120 s | 13 ciclos reales en 739 s, hueco máx 65 s, AWS = OK en todos | cumple |
| `limpieza_verificada` | sí | ASG 0/0/0, 0 EC2, 0 ALB, RDS `stopped`, V1 `stopped`, Azure desasignada con apagado restaurado exacto | cumple |
| `costo_dentro_del_techo` | ≤ USD 1,5 | ≈ USD 0,15 (estimación; confirmar en la consola) | cumple |

## Cronología (UTC; segundos desde T0 del tráfico)
00:10:59 V1 detenida · 00:13 Azure encendida (apagado → 03:12) · 00:13:39 RDS iniciando (watchdog armado) · 00:21 RDS disponible · plan **3/6/0** revisado (0 destrucciones) y aplicado · 00:23:55 2 destinos sanos en 2 zonas · 00:24 Azure empieza a ver AWS=OK (certificado validado contra el dominio de NexoEventos) · previas OK (zonas, HTTPS, RDS, reparto, datos) · ≥ 6 min de línea base de Azure · 00:31:xx tráfico constante (5 req/s, 4 clientes): T0 → **fallo a +28,8 s** (API detenida en UNA EC2) → **ALB la marca no sana a +53,7 s (24,9 s)** → ASG la termina y lanza otra → **2 sanos de nuevo a +188,6 s (159,8 s)** → fin a +204,9 s · 00:44 limpieza · 00:51:08 RDS `stopped` verificada · 00:52 Azure cerrada.
Denominador de la disponibilidad: todas las solicitudes `/healthz` emitidas desde T0 hasta 15 s tras recuperar; los 502, timeouts y -1 cuentan como fallos (ninguno excluido). El único contacto con la víctima fue la detención de su API; no hubo reemplazo manual.

## Por qué falla la disponibilidad (causa medida, no supuesta)
Durante los **24,9 s** de detección el ALB siguió repartiendo ≈ **50 %** de las solicitudes a la EC2 cuya API estaba detenida (Nginx devolvía 502): **112 solicitudes en la ventana 29,5–52,5 s, 56 fallos**. CloudWatch lo confirma: `HTTPCode_Target_5XX` = **56**, `HTTPCode_ELB_5XX` = 0; `HealthyHostCount` bajó a 1 durante 3 minutos. Con salud de ALB (intervalo 10 s × 2 fallos) y 5 req/s en una ventana de ≈ 205 s, la fracción de fallos es ≈ 0,5 × 24,9 / 205 ≈ 6 %: **no es un defecto de configuración sino el límite del mecanismo**. Coincide con las medidas previas (22-oct y 4-nov: detección 22,6 s, `/api` 97,7 %, 52 respuestas 502).

## Opciones DENTRO de T5 (requieren tu decisión; no se aplicó ninguna)
1. **Acelerar la detección** (intervalo 5 s × 2 = ≈ 10–12 s, el mínimo del ALB; cambio de Terraform en el grupo de destino): fallos esperados ≈ 25–30 ⇒ ≈ **97–98 %** (estimación, no medición): **mejora pero no alcanza 99 %**.
2. **Mantener 99 %** y aceptar que, con este tipo de fallo (el proceso muere, la instancia sigue), el criterio no es alcanzable con un ALB de comprobaciones activas en una ventana corta; T5 queda en FAIL honesto con 8/9.
3. **Replantear el criterio** (solo tú puedes): p. ej. medir la disponibilidad de **clientes con reintento** o sobre una ventana de servicio mayor, o un umbral realista (≥ 95 %) con la detección ≤ 30 s ya exigida. Un cambio así se registraría como cambio de criterio, no como PASS del criterio original.
Además, para mejorar la observación: las sondas de Azure son **cada 60 s** y NO capturaron el episodio de 22 s (todo «OK»); durante una prueba convendría muestrear cada 5–10 s.

## Incidentes y notas honestas
- El laboratorio se reinició antes de la ventana (credenciales nuevas 00:09Z; la EC2 de V1 se relanzó sola a las 00:07Z y se detuvo a las 00:11Z): la sesión nueva caduca ≈ 04:07Z.
- Mi primer script de comprobaciones usó el almacén de CA equivocado (fallo de TLS del intérprete, no del ALB) y el recuento por instancia vía SSM se truncaba a 24 kB (artefacto de medición): se corrigieron y se repitieron; los intentos previos están en `work/t5/logs/`.
- La limpieza elimina el ALB por la API (como el 20-nov): el estado de Terraform queda desfasado (3 a crear, 6 a modificar, 0 a destruir) y el siguiente plan es el escenario «resume» ya revisado.
- Límite del «sin pérdida de datos»: tráfico de solo lectura (no se prepararon fixtures porque requerían la EC2 de V1, detenida por autorización).
- El crédito real hay que confirmarlo en la consola (esperado ≈ USD 22,2). `REAL_EXECUTION_WIRED=False`; S14, DNS y OCI sin cambios; T6 sigue bloqueado.
