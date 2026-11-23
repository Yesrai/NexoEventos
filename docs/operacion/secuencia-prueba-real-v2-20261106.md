# Secuencia de la prueba real de V2 (preparada el 6-nov-2026 15:30 hora de Perú)

**Estado de ejecución (actualizado):** ejecutados el 6-nov los pasos 1, 2, 3 y 7 (encendido con `v2-terraform.sh on`, verificación de zonas y destinos, 15 pruebas funcionales 15/15 y apagado con `off`); registros en `docs/evidencias/20261106-prueba-real-v2/`, `validacion-v2-20261106/` y `20261106-apagado-v2-tras-prueba/`. **Pasos 4, 5 y 6 (prueba en el navegador con hosts y capturas de consola): no confirmados**; siguen pendientes para el próximo encendido de V2.

Estado previo verificado: ASG 0/0/3; ALB activo; RDS `available` (Multi-AZ, 20 GiB, máximo 40); V1 `running` (`/healthz` 200); plan `v2-terraform.sh on --plan-only` → 1 modificación del ASG (`desired_capacity` 0→2, `min_size` 0→2), 26 sin cambios, 0 crear/destruir/reemplazar; estado de Terraform de V2 sin cambios. Laboratorio: arrancó ≈ 13:51; fin estimado ≈ 17:51 (≈ 145 min restantes a las 15:26; confirmar en el cronómetro de Academy).

## Condiciones para empezar (todas)
- Cronómetro de Academy con al menos 60 min libres; `./v2-status.sh` con RDS `available` y V1 `running`.
- Autorización explícita de la usuaria.

## Pasos y tiempos (≈ 35–45 min en total)
| # | Paso | Comando | Tiempo | Éxito |
|---|---|---|---|---|
| 1 | Encender V2 | `cd scripts/v2-ops && ./v2-terraform.sh on` → escribir `APLICAR ON` | 4–5 min | «Terraform y AWS coinciden con V2 'on'» |
| 2 | Verificar zonas y destinos | `./v2-status.sh` | 1 min | 2 instancias en us-east-1a y us-east-1b, 2 destinos `healthy` |
| 3 | 15 pruebas funcionales | `NEXO_ALLOW_CLOUD_CHANGES=YES backend/.venv/bin/python scripts/cloud/verify-v2-flow.py --out docs/evidencias/validacion-v2-AAAAMMDD` | 1–2 min | 15/15 OK; reparto ≈ 50 %/50 %; 0 errores 5xx |
| 4 | Navegador | `work/operacion/hosts/v2-hosts-on.sh`; abrir `https://nexoeventos-demo.duckdns.org/livez` (debe mostrar el JSON de V2), recorrer el catálogo, reservar (pago simulado) y ver el QR | 10–15 min | `/livez` en JSON y reserva con QR |
| 5 | Capturas de consola (la usuaria) | ver lista | 10 min | archivos legibles, sin número de cuenta |
| 6 | Quitar hosts | `work/operacion/hosts/v2-hosts-off.sh` | 1 min | el dominio vuelve a V1 |
| 7 | Apagar V2 | `./v2-terraform.sh off` → `APLICAR OFF` | 2–3 min | 0 instancias; V1 y RDS sin cambios |
Fuera de la secuencia (requieren autorización aparte): autohealing, failover, cualquier cambio de DNS o certificados.

## Qué guardar para el profesor (por criterio)
- **C1 evolución:** captura de EC2 → Instancias (2 de V2 en 2 zonas + 1 de V1); `v2-status` y el resumen del plan (0 crear, 1 modificar); diagrama V2 del informe.
- **C3 seguridad:** listener 443 del ALB con el certificado y la política TLS; Security Group de las instancias (entrada solo desde el SG del ALB); ejecución de `/livez` por HTTPS con certificado válido.
- **C4 disponibilidad:** grupo de destino con 2 destinos `healthy` y su zona; ASG (mínima 2, máxima 3, 2 zonas); CloudWatch `HealthyHostCount` y `RequestCount` de la última hora; `reparto-instancias.json`.
- **C5 pruebas y documentación:** salida y `resultado.json` de las 15 pruebas; captura del navegador con `/livez` y la reserva con QR; alarmas de V2 en `OK`; los 3 commits locales.
- Pendiente aparte: captura de Zabbix (bloqueo de IP de Azure) y capturas de Azure.

## Costo estimado (tarifas públicas; sin facturación)
Incremental de V2 mientras esté encendida ≈ 0,056 USD/h (2 EC2 + discos + IP públicas) → ≈ 0,04–0,05 USD en 45 min. Línea base que ya corre (ALB, RDS, V1) ≈ 0,11 USD/h → ≈ 0,08 USD en ese tiempo. Total de la ventana ≈ 0,12–0,13 USD. Sin cargos por créditos de CPU excedentes esperados (saldo 0 en las últimas pruebas; carga ligera).

## Después
Apagar V2 (paso 7), decidir si se detiene la RDS antes de que cierre el laboratorio (ahorra ≈ 0,04 USD/h pero V1 y V2 dejan de funcionar), y registrar resultados en `docs/evidencias/`.
