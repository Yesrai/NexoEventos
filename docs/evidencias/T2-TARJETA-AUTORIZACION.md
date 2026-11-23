# T2 — Cambio real de DNS en el subdominio de pruebas · TARJETA DE AUTORIZACIÓN
> **ESTADO FINAL (22-nov, 14:26Z): T2 CERRADA con PASS en la 2.ª ejecución (13/13 criterios; apply 62,1 s, rollback 62,0 s; segundo cambio rechazado; DNS final = inicial; token ausente). No se reejecuta.**
> Historial: 1.ª ejecución FAIL sin cambios de DNS (el Python no tenía almacén de certificados y rechazó el TLS de DuckDNS); corregido y verificado en local y contra el servidor real (plan LISTO con prerrequisito TLS nuevo). Ver `T2-20261122-resultado.md`. Una nueva ejecución requiere nueva autorización.**

## 0. Pasos previos que SOLO puedes hacer tú (el token y tus IP no pasan por el chat)
1. En DuckDNS, crea el subdominio **`nexoeventos-test`** apuntando a una IP pública tuya (será la IP «a» de partida) y espera ≈ 1 min. **No uses ni modifiques `nexoeventos-demo`.**
2. En **tu terminal** ejecuta el asistente (pide la IP «b» y el token **sin eco**, y escribe `work/dns-switch/{config-prueba.json,token}` con permisos 0600; hace solo consultas DNS de lectura, **ningún cambio** en DuckDNS):
```bash
backend/.venv/bin/python scripts/ops/preparar_t2.py
```
   - **IP «b»:** debe ser una **IPv4 pública (global) distinta de «a»**. ⚠ Corrección: el procedimiento anterior sugería «una IP de documentación»; `dns_switch.py` **la rechaza** (solo acepta IP globales). Recomendado: la **IP pública estática de tu VM de Azure** (es tuya y el DNS de pruebas no le enviará tráfico del proyecto).
3. Yo ejecutaré entonces el **modo plan (solo lectura)** (`backend/.venv/bin/python scripts/ops/ejecutar_t2.py`, sin `--autorizo`): valida archivos, lista blanca y que los 3 resolvedores coincidan en «a». Si no da LISTO, no hay nada que autorizar.

## 1. La acción exacta que se autoriza
```bash
backend/.venv/bin/python scripts/ops/ejecutar_t2.py --autorizo "AUTORIZO T2 EN DUCKDNS: dns_switch.py, subdominio nexoeventos-test, cambio A a B y reversión"
```
Duración ≈ 6–8 min (propagación ≈ 60–180 s por cambio). Una sola ejecución.

## 2. Qué se modifica y qué NO
| Se modifica | No se modifica |
|---|---|
| El **registro A** de `nexoeventos-test.duckdns.org`: A → B → A (2 llamadas a la API de DuckDNS) | `nexoeventos-demo` y cualquier otro subdominio; ningún recurso de AWS/OCI/Azure; ninguna base de datos |
| Archivos locales: `work/dns-switch/` (estado y auditoría 0600) y el expediente de evidencia | El token (nunca se imprime ni se guarda en la evidencia) |

## 3. Permisos y **riesgo real del token**
- El token de DuckDNS es **de la cuenta**: técnicamente permite cambiar **todos** tus subdominios, incluido `nexoeventos-demo`. La protección es el código, no el token: lista blanca de **un solo** dominio (el ejecutor **aborta** si la lista incluye el de producción o no empieza por `nexoeventos-test`), frase de confirmación exacta por operación, `NEXO_ALLOW_DNS_CHANGE=YES` solo en los pasos de cambio, intervalo mínimo de 300 s y bloqueo contra cambios concurrentes.
- Esas protecciones están **probadas**: un plan sobre `nexoeventos-demo` es rechazado (código 2) antes de cualquier consulta.
- **Recomendación (no obligatoria): usa para `nexoeventos-test` una cuenta de DuckDNS distinta** de la de producción, de modo que su token **no pueda** tocar `nexoeventos-demo`. Si no, **regenera el token al cerrar T2/T8**.

## 4. Pruebas que ejecuta (en este orden) y condiciones de seguridad
| # | Paso | Esperado |
|---|---|---|
| N1 | `plan` sobre `nexoeventos-demo` | **RECHAZADO** (código 2), sin consultas |
| N2 | `apply` sin `NEXO_ALLOW_DNS_CHANGE` | **RECHAZADO** (código 2), sin consultas |
| N3 | `apply` con frase de confirmación errónea | **RECHAZADO** (código 2), sin cambios |
| 1 | `plan` | los 3 resolvedores (1.1.1.1, 8.8.8.8, 9.9.9.9) coinciden en «a» |
| 2 | `apply` A→B (frase exacta) y espera de propagación (≤ 180 s) | OK en los 3 |
| 3 | `verify` B | OK en los 3 |
| 4 | segundo `apply` inmediato hacia otro destino | **RECHAZADO** por intervalo mínimo (código 3) y **sin llamar** a DuckDNS |
| 5 | `rollback` B→A (frase exacta) y espera (≤ 180 s) | OK en los 3 |
| 6 | `verify` A + `plan` final | vuelve a «a» en los 3 |
**Si algo falla tras haber emitido el `apply`: el ejecutor SIEMPRE intenta la reversión** (2 intentos; también ante Ctrl-C/SIGTERM). Si el proveedor respondió KO (el estado no cambió) lo detecta y no revierte nada.

## 5. Criterios medibles de PASS (`ops_center/criterios/T2.json`; todos medidos y cumplidos, si no ⇒ PARCIAL/FAIL)
`dominio_de_pruebas` · `produccion_rechazada` · `sin_variable_rechazada` · `confirmacion_incorrecta_rechazada` · `punto_de_partida_verificado` · **`propagacion_apply_s` ≤ 180** · `resolvedores_coinciden_en_B` (3/3) · `segundo_cambio_rechazado` · **`propagacion_rollback_s` ≤ 180** · `rollback_correcto` · `ip_final_igual_a_inicial` · `auditoria_dns_switch_registrada` · `token_ausente_de_salidas`.

## 6. Abortos
Archivos con permisos distintos de 0600, lista blanca con producción, `allowed_targets` ≠ {a, b}, `min_interval_s` < 120, el dominio no parte de «a» en los 3 resolvedores, fallo de cualquier negativo (**no se cambia nada**), `apply` incompleto o KO (se revierte o se confirma que no hubo cambio), interrupción (se revierte).

## 7. Reversión, estado final y fallo de la reversión
- Reversión automática (arriba) y comprobación independiente: `verify` de «a» en los 3 resolvedores + `plan` final.
- **Si la reversión fallara** (el script lo avisa en rojo y lo registra): restaurar a mano en el panel de DuckDNS la IP «a» (anotada en tu `config-prueba.json`); el expediente indica el paso exacto. Impacto máximo: el subdominio **de pruebas** apuntaría a «b»; nada del proyecto lo usa hasta T6.

## 8. Costo y limitaciones
- **Costo: 0** (DuckDNS gratuito; sin recursos Cloud).
- Limitaciones: la propagación se mide **desde este Mac con 3 resolvedores públicos**, no en clientes con caché propia; DuckDNS admite **una sola IP por registro y no tiene comprobación de salud** (por eso T6 la decisión de conmutar la toma el orquestador, no el DNS); el TTL asumido es 60 s y el observado se registra; el cambio de DNS **no demuestra un failover**.

## 9. Evidencias que se conservan (`work/evidencias/T2-<UTC>/`, manifiesto SHA-256 verificado)
`meta.json` · `events.jsonl` (marcas UTC: inicio, dns_aplicando, dns_aplicado, b_verificado, segundo_cambio_probado, dns_revertido, a_verificado, fin) · `capturas/paso-*.txt` (salida saneada de cada paso, **IP/URL/token ocultos por el saneador**) · `resultado.json/.md` (veredicto y criterios) · `MANIFIESTO.sha256`; más el registro de auditoría de `dns_switch` (`work/dns-switch/nexoeventos-test.audit.jsonl`, con hora UTC, IP anterior y nueva — **local, no compartir**).

## 10. Verificación local ya hecha
`dns_switch` 14 pruebas · ejecutor T2 con DuckDNS y 3 resolvedores UDP **simulados** (retraso de propagación): **8 pruebas** — modo plan sin cambios, plan NO LISTO, PASS completo con reversión y sin token en la evidencia (solo 2 llamadas al proveedor), proveedor KO, **propagación incompleta con reversión**, **reversión fallida avisada**, producción en la lista blanca (aborto), frase incorrecta. Resolvedores `host:puerto` añadidos a `dns_switch` solo para probar (compatibles hacia atrás).
