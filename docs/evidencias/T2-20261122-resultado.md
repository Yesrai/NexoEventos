# T2 — Resultado de la 1.ª ejecución autorizada (22-nov-2026, 14:13:51–14:13:53 UTC): **FAIL, sin ningún cambio de DNS**

Expediente: `work/evidencias/T2-20261122T141351Z-84bb/` (0600/0700; manifiesto SHA-256 verificado, 0 discrepancias; `resultado.json` sha256 `ecb27c1569e6690f…`). Autorización: «AUTORIZO T2 EN DUCKDNS: dns_switch.py, subdominio nexoeventos-test, cambio A a B y reversión». Una sola ejecución; **no se repite sin nueva autorización.**

## Qué ocurrió (UTC)
| Hora | Paso | Resultado |
|---|---|---|
| 14:13:51.19 | N1 plan sobre `nexoeventos-demo` | **RECHAZADO** (código 2): «no está en la lista blanca» |
| 14:13:51.24 | N2 apply sin `NEXO_ALLOW_DNS_CHANGE` | **RECHAZADO** (código 2) antes de cualquier consulta |
| 14:13:51.79 | N3 apply con frase errónea | **RECHAZADO** (código 2), sin cambios |
| 14:13:52.20 | plan inicial | 3 resolvedores en A ✔ |
| 14:13:52.20 | **apply A→B** | **código 4: «DuckDNS no respondió (URLError); el estado NO cambió»** (0,5 s) |
| 14:13:52.73 | comprobación antes de revertir | el DNS sigue en A: **no hay nada que revertir** (`sin_cambio_que_revertir`) |
| 14:13:53.0 | cierre | veredicto **FAIL** |
Criterios: 9 CUMPLEN (incluidos los 3 negativos de seguridad, punto de partida, token ausente, IP final = inicial), 4 **SIN MEDIR** (propagación, B en 3 resolvedores, segundo cambio, reversión) y 1 **NO CUMPLE** (`auditoria_dns_switch_registrada`: no hubo apply ni rollback que registrar).

## Estado final (verificado con lectura DNS posterior)
`nexoeventos-test`: 1.1.1.1, 8.8.8.8 y 9.9.9.9 responden **A** (TTL 60 s). `work/dns-switch/` sin estado ni auditoría de cambios (solo configuración, token y el archivo de bloqueo). **Ningún registro DNS fue modificado**; el token no llegó a enviarse a DuckDNS (la conexión falló antes) y no aparece en la evidencia.

## Causa raíz (reproducida)
El Python 3.12.0 del entorno (`backend/.venv`, instalación de python.org) **no tiene almacén de certificados**: `ssl.get_default_verify_paths()` → `cafile: None, capath: None`. Python rechazó **correctamente** el certificado de `www.duckdns.org` (`CERTIFICATE_VERIFY_FAILED: unable to get local issuer certificate`); con `certifi` el mismo apretón de manos funciona. No fue un fallo de DuckDNS ni del token. Mi procedimiento solo había probado `dns_switch` con servidores locales (http) y resolvedores simulados, por lo que no ejercitaba TLS real.

## Corrección (local; la verificación TLS **no se desactiva**)
1. Nuevo `backend/app/failover/tlsctx.py` (`verified_ssl_context`): almacén del sistema/`SSL_CERT_FILE`; si no hay ninguna CA cargada, `certifi`; sin `certifi`, sigue verificando (falla cerrado). Aplicado a **todos** los clientes HTTPS del failover: DuckDNS (`dns_switch`), almacén del lease por PAR (`ParHttpStore`), lector de respaldos de OCI, sondas de salud y cliente del testigo; también `probe_http` del recolector. Habría roto igual T3–T6 desde este Mac.
2. `test_tls_context.py` (5 pruebas): cae a `certifi` solo sin CA cargada; **un certificado autofirmado no confiable sigue rechazándose** y `SSL_CERT_FILE` se respeta; todas las copias del contexto se comportan igual; `dns_switch` y `ParHttpStore` usan el contexto verificado.
3. **Prerrequisito nuevo en el modo plan de T2:** apretón de manos TLS verificado con DuckDNS (sin petición ni token). Con el defecto original el plan habría dado **NO LISTO**. Verificado hoy contra el servidor real: TLS 1.2, CERT_REQUIRED, nombre comprobado, 121 CA, emisor Amazon, vigente hasta 13-ene-2027; **plan real: LISTO**.

## Hallazgo adicional de la regresión: carrera real en el testigo (corregida)
Al repetir la regresión, `test_witness_hardening::…informes_simultaneos…[archivo]` falló de forma **intermitente (~50 %)**: «almacén del testigo ALTERADO (cadena rota)». No era por TLS. **Causa:** `Witness` no era seguro entre hilos dentro de una misma instancia: `entries` y `last_hash` se actualizaban por separado, y otro hilo podía leer «secuencia nueva + hash viejo» y escribir una entrada con `prev` incorrecto. (El servicio desplegado ya lo evitaba con un cerrojo global; la clase no.) **Reproducción:** `test_witness_thread_safety.py` (35 rondas) falló **23/35** antes de corregir. **Corrección:** cerrojo reentrante por instancia en `report`, `attest` y `report_with_receipt`. Después: 35/35 en tres repeticiones y el test original 6/6.

## Verificación tras las correcciones
Regresión de DNS, TLS, lease por PAR, lector de OCI, e2e del failover (83), testigo (service + perfil Azure + hardening + hilos), carrera del lease, probe de PAR, fábrica y `ops_center`: **303 aprobadas, 0 fallos**. Ambas pruebas nuevas añadidas al CI.

## Siguiente paso
Nueva autorización específica de T2 (la anterior cubre una ejecución). Sin cambios de alcance. `REAL_EXECUTION_WIRED = False`, `REAL_WIRING_ENABLED = False`; T3 y demás sin tocar; S14 intacto.

---
# 2.ª ejecución (autorizada de nuevo): **PASS** — 2026-11-22 14:24:43 → 14:26:52 UTC
Expediente: `work/evidencias/T2-20261122T142443Z-9eec/` (0600/0700; manifiesto SHA-256 verificado, 0 discrepancias; `resultado.json` sha256 `3c280f7bb9bff1ea…`). Registrada en el centro de operaciones (`record-evidence T2 … PASS`; barrera B06_T2 cumplida; auditoría íntegra). Token: **0 apariciones** en la evidencia y en los registros de pruebas. Las IP A y B aparecen ocultas ([oculto]); solo constan en la evidencia las de los resolvedores públicos.

## Mediciones reales (13 de 13 criterios medidos y cumplidos)
| Paso (UTC) | Resultado |
|---|---|
| N1 plan sobre `nexoeventos-demo` | RECHAZADO (código 2) · N2 apply sin variable: RECHAZADO (2) · N3 frase errónea: RECHAZADO (2) |
| 14:24:44.93 **apply A→B** | OK; **propagación en 62,1 s** en los 3 resolvedores (≤ 180 s) · fin 14:25:48.04 |
| 14:25:48.39 verify B | OK en 1.1.1.1, 8.8.8.8 y 9.9.9.9 (TTL observado 60 s = supuesto) |
| 14:25:48.43 **segundo apply inmediato** (destino A) | **RECHAZADO por intervalo mínimo (código 3, «300 s desde el último cambio») y sin llamar a DuckDNS** (el proveedor recibió solo 2 llamadas) |
| 14:25:48.88 **rollback B→A** | OK; **propagación en 62,0 s** · fin 14:26:51.74 |
| 14:26:51.75 verify A + plan final | OK en los 3; **IP final = IP inicial** |
| Auditoría de `dns_switch` | `apply` (14:24:45Z, destino «b») y `rollback` (14:25:49Z, «anterior») con hora UTC |

## Estado final (lectura independiente tras T2)
`nexoeventos-test`: 1.1.1.1, 8.8.8.8 y 9.9.9.9 responden **A** (TTL 60/60/45 s). Cambios realizados en DuckDNS: exactamente dos (A→B, B→A); `nexoeventos-demo` sin tocar. Costo: 0.

## Límites que se registran tal cual
- La propagación (≈ 62 s ≈ 1 × TTL) se midió **desde este Mac con 3 resolvedores públicos**; clientes con caché propia pueden tardar hasta el TTL asumido (60 s) más su propia caché. DuckDNS admite **una IP por registro y no comprueba salud**.
- Demuestra actualización, resolución y reversión del DNS de pruebas; **no demuestra un failover**.
- El token sigue siendo de la cuenta (puede tocar también `nexoeventos-demo`): se recomienda **regenerarlo** ahora o al cerrar T8.

**T2 CERRADA con PASS.** Siguiente: T3 (recuperación y funcionamiento real de NexoEventos en OCI), con su propia preparación y autorización.
