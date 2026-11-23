# Entregable 3 · Procedimientos cloud PREPARADOS (no ejecutados) — 11-nov-2026

> **Fechas clave:** RDS se reinicia sola hacia el **18-nov-2026 ~16:52 UTC** · AWS Academy expira ≈ **26-nov-2026** · Free Trial de OCI: vencimiento **sin verificar** (consola).
> **Estado: NADA de este documento se ejecutó.** No se creó ningún bucket, usuario ni permiso en OCI; no se hizo la autoprueba contra OCI real; no se cambió ningún DNS; no se hizo failover; no se encendió AWS ni se inició Academy; no se creó VM ni recurso en Azure; no se ejecutó Terraform `apply/destroy`. **El failover AWS–OCI NO está validado en la nube.** Cada procedimiento exige tu autorización explícita, con la frase indicada.

## A. Autoprueba REAL del lease (almacén condicional de OCI)
**Para qué:** comprobar contra un bucket real que `If-Match` es atómico y que el protocolo del lease funciona con latencias reales (supuesto S1 del informe 19). **Criterios afectados:** 6 (HA), 10 (multicloud), 5 (seguridad), 12 (pruebas).
**Preparado localmente:** módulo Terraform `infra/oci/modules/lease` (apagado por defecto: `create_lease_test = false`; `terraform validate` OK; **no aplicado**), script `scripts/multicloud/lease_selftest.py` (PLAN por defecto; 10/10 pruebas con una CLI simulada; rechaza el bucket de respaldos), y `OciCliStore` con su autoprueba.
### A.1 Qué se crearía (permisos mínimos)
| Recurso | Detalle |
|---|---|
| Bucket `nexoeventos-lease-test` | Standard, **NoPublicAccess**, **versionado deshabilitado** (el de respaldos está versionado y su usuario no puede sobrescribir: no sirve) |
| Grupo `nexoeventos-lease-writers` y usuario `nexoeventos-lease-svc` | Solo clave API (sin consola, tokens, SMTP ni credenciales de BD) |
| Política `nexoeventos-lease-writers` | `read buckets` y `manage objects` **limitado a** `OBJECT_INSPECT, OBJECT_READ, OBJECT_CREATE, OBJECT_OVERWRITE` **solo en ese bucket**. **Sin borrado** (la limpieza la hace el administrador) |
Costo estimado: **0 USD** (unos KB; Always Free de Object Storage 20 GB y solicitudes; IAM sin cargo). No verificado en el panel de OCI.
### A.2 Pasos exactos
| # | Acción | Quién | Compuerta |
|---|---|---|---|
| 0 | Autorizar con la frase: **«AUTORIZO crear el bucket e identidad de la autoprueba del lease en OCI y ejecutarla»** | Tú | — |
| 1 | `terraform -chdir=infra/oci plan -var-file=<tu tfvars local> -var create_lease_test=true -out=<ruta en work/>` y mostrar el resumen | Yo | **Esperado: 6 a crear (bucket, grupo, usuario, capacidades, membresía, política), 0 modificar, 0 destruir.** Cualquier otra cosa → se detiene |
| 2 | `terraform apply <ese plan>` (sin `-auto-approve`) | Yo | Plan revisado contigo |
| 3 | Generar una clave API para `nexoeventos-lease-svc` **fuera del repositorio**, registrar su parte pública en la consola y crear el perfil `NEXOEVENTOS_LEASE` en `~/.oci/config` | Tú | La clave privada nunca se pega en el chat |
| 4 | Lectura previa: `oci os bucket get --profile NEXOEVENTOS_LEASE --namespace-name <ns> --bucket-name nexoeventos-lease-test` | Yo | `versioning: Disabled` y `NoPublicAccess` |
| 5 | Plan del script: `python3 scripts/multicloud/lease_selftest.py --namespace <ns> --bucket nexoeventos-lease-test --profile NEXOEVENTOS_LEASE --cleanup-profile DEFAULT` (no llama a la nube) | Yo | Muestra pasos y topes |
| 6 | Ejecución: `NEXO_ALLOW_LEASE_SELFTEST=YES python3 scripts/multicloud/lease_selftest.py … --execute --confirm "EJECUTAR AUTOPRUEBA DEL LEASE EN nexoeventos-lease-test"` | Yo | Tope de 15 min |
| 7 | Guardar el informe JSON y las evidencias (sin claves ni OCID) y ejecutar `verify_clean.py --live` | Yo | — |
| 8 | **Decidir**: conservar el bucket e identidad (para el simulacro) o destruirlos: `plan` con `create_lease_test=false` → esperado **0 a crear, 6 a destruir** → `apply` | Tú | Plan revisado |
### A.3 Criterios de éxito (todos obligatorios)
1. Semántica condicional: `create` duplicado rechazado, CAS con ETag viejo rechazado, lectura inmediata tras escribir, carrera de 16 escritores → **exactamente 1 ganador**.
2. **20 rondas × 16 procesos de la CLI en paralelo: en cada ronda exactamente 1 éxito** (la carrera real).
3. Protocolo con relojes reales: A adquiere; B no; B toma tras ≥ TTL + margen; A pierde al renovar.
4. Latencia: **p95 de `replace` < margen/2** (con margen 5 s: < 2,5 s); si no, se cambia el margen o el almacén (la validez del diseño depende de ello).
5. Limpieza: todos los `selftest-*` borrados; `verify_clean.py --live` sin residuos (el bucket y la identidad, si se conservan, se declaran como esperados).
### A.4 Cancelar si…
La CLI no ofrece `--if-match`; el bucket resulta versionado o público; alguna validación falla (se detiene, se conserva la evidencia, se limpia); un plan de Terraform muestra algo distinto de lo esperado; se supera el tope de tiempo; aparece cualquier cargo o aviso de costo; el perfil usado fuera el de respaldos. **Un fallo de la autoprueba NO se reintenta en silencio: se analiza primero.**
### A.5 Riesgos
La CLI de OCI podría no traducir `--if-match` como se espera (la autoprueba lo detecta); el trial de OCI podría haber vencido (el bucket Always Free seguiría); crear usuarios requiere permisos de administrador.

## B. Cambio de DNS real (con un subdominio de PRUEBAS)
**Para qué:** medir la propagación real y validar la reversión sin tocar el dominio de producción. **Criterios:** 6, 10, 12. **Preparado:** `scripts/multicloud/dns_switch.py` (14/14 pruebas simuladas).
### B.1 Prerrequisitos
1. Crear en tu cuenta de DuckDNS un subdominio **de pruebas** (p. ej. `nexoeventos-test`; DuckDNS admite varios por cuenta). **No se usa `nexoeventos-demo` en la prueba.**
2. Dos IP públicas **inocuas** (por ejemplo la IP pública de tu casa y una IP de documentación pública que no reciba tráfico del proyecto): solo se cambia el registro, no se envía tráfico.
3. Archivo de configuración **fuera de Git** (`work/dns-switch/config-prueba.json`):
```json
{"allowed_domains": ["nexoeventos-test"], "allowed_targets": {"a": "<IP-A>", "b": "<IP-B>"}, "assumed_ttl_s": 60, "min_interval_s": 300, "resolvers": ["1.1.1.1", "8.8.8.8", "9.9.9.9"], "state_dir": "work/dns-switch"}
```
4. Token de DuckDNS en `work/dns-switch/token` con permisos `0600` (o `DUCKDNS_TOKEN`); nunca en el chat.
### B.2 Pasos exactos
| # | Orden | Resultado esperado |
|---|---|---|
| 0 | Autorización: **«AUTORIZO el cambio de DNS de prueba en nexoeventos-test»** | — |
| 1 | `python3 scripts/multicloud/dns_switch.py plan --config work/dns-switch/config-prueba.json --domain nexoeventos-test --target b` | PLAN; IP actual, destino, TTL; **sin cambios** |
| 2 | `NEXO_ALLOW_DNS_CHANGE=YES … apply --target b --confirm "CAMBIAR DNS nexoeventos-test A <IP-B>"` (token por entorno/archivo) | OK; propagación medida en 3 resolvedores |
| 3 | `… verify --expect-ip <IP-B>` | OK con tiempo y TTL observado |
| 4 | `NEXO_ALLOW_DNS_CHANGE=YES … rollback --confirm "REVERTIR DNS nexoeventos-test A <IP-A>"` | Vuelve a la IP anterior; propagación medida |
| 5 | Guardar `state` y auditoría (sin token) en las evidencias | — |
**Éxito:** propagación completa en ≤ 3 × TTL en los 3 resolvedores, reversión correcta, el token no aparece en ninguna salida ni archivo, el segundo cambio inmediato es rechazado por el intervalo mínimo. **Costo:** 0 USD.
**Cancelar si:** DuckDNS devuelve KO (el estado no cambia); el dominio no es el de pruebas; la propagación no termina en 3 min; cualquier discrepancia entre el registro y el estado. **Riesgos:** DuckDNS admite **una IP por registro** y sin comprobación de salud; el TTL real no se conoce hasta medirlo.

## C. Simulacro REAL de failover AWS → OCI
**Para qué:** medir RTO/RPO reales y comprobar por efecto que el sitio anterior queda cerrado. **Criterios:** 6 (1,5), 10 (1,5), 9 (1,5), 12 (1,0), 7 (1,0), 5 (2,5). **NO se ejecutará hasta cumplir todos los prerrequisitos.**
### C.1 Prerrequisitos (BLOQUEANTES)
| # | Prerrequisito | Estado |
|---|---|---|
| P1 | Autoprueba A superada (almacén del lease verificado) | Pendiente |
| P2 | Cambio de DNS de prueba B superado | Pendiente |
| P3 | VM de OCI con PostgreSQL restaurado y la aplicación (O1 + despliegue; E5 solo con tu autorización; A1/Micro si hay capacidad) y **punto de entrada público** con TLS | Pendiente |
| P4 | **Adaptadores reales** del orquestador: restauración (envolver `run-from-mac.sh`/`app-recovery.sh`), sondas externas independientes (≥ 3), estado del standby (`GET /write-gate`), `dns_switch` (plan/apply), sonda de «el sitio anterior puede escribir» y escritura sintética | **No construidos** |
| P5 | La compuerta desplegada con `WRITE_GATE_MODE=enforce` en AWS **y** en OCI, con el almacén del lease y credenciales mínimas en ambos sitios (decidir: perfil en AWS, principal de instancia en OCI, o un cliente REST propio que evite depender de la CLI) | **No construido; decisión pendiente** |
| P6 | Dominio de pruebas (no el de producción) y TLS válido en ambos sitios | Pendiente |
| P7 | Ventana con Academy activo (EC2 + RDS encendidas) y **antes** del 18-nov 16:52 UTC si RDS sigue detenida; saldo verificado | Pendiente |
### C.2 Secuencia propuesta (≈ 2 h de ventana)
1. **Línea base:** ambos sitios con la compuerta; el primario (AWS) tiene el lease; el standby (OCI) en `standby` sin archivo de promoción. Comprobar: escritura en AWS → 201; en OCI → 503. Capturar `/write-gate` de ambos.
2. **Respaldo reciente** en OCI (RPO = antigüedad del respaldo; documentar).
3. **Inyección de fallo controlada y reversible** en el primario (detener solo el servicio de la aplicación en la EC2, no la cuenta ni RDS).
4. **Orquestador** (`--execute` con frase y adaptadores reales): DECIDE (3 rondas, quórum 2), PREPARE_STANDBY (restauración + huella), FENCE_AND_ACQUIRE (espera ≥ TTL + margen), ENABLE_STANDBY, SWITCH_DNS (solo el dominio de pruebas), VERIFY.
5. **Medición:** tiempos de detección, de toma del lease, de restauración, de propagación DNS y **RTO total**; RPO; resultado de la prueba «el sitio anterior no puede escribir» **por efecto**.
6. **Retorno al primario (failback): MANUAL**, con vallado del escritor de OCI primero; no es automático.
7. **Apagado y limpieza:** detener EC2/RDS, destruir la VM de OCI, `verify_clean.py --live` en ambas nubes.
### C.3 Criterios de éxito
Un solo escritor en todo momento (0 respuestas 201 del sitio anterior tras la toma); DNS cambiado solo después de lease + datos verificados; RTO medido y documentado (incluye TTL); verificación por efecto de que el anterior queda cerrado; limpieza completa verificada. **Si el sitio anterior sigue aceptando escrituras (compuerta ausente o fallida), el simulacro se declara FALLIDO y no se presenta como éxito.**
### C.4 Costos estimados (tarifas públicas; sin verificar)
AWS EC2 + RDS Multi-AZ ≈ 0,07 USD/h × ≈ 2 h ≈ 0,15 USD · OCI E5 1 OCPU/8 GB ≈ 0,05 USD/h × ≈ 2 h ≈ 0,10 USD (crédito del trial; 0 con A1/Micro si cupiera) · DNS y lease 0 → **≈ 0,25–0,5 USD**. Si Academy ya expiró o el trial venció, el simulacro no es viable.
### C.5 Cancelar si…
Falla A o B; hay más de un escritor; el lease no se adquiere en 60 s sin causa clara; la restauración no verifica la huella; cualquier paso excede su tope; el saldo no alcanza; aparece un costo inesperado. **En cualquier duda: apagar primero, depurar después.**
### C.6 Qué NO demostrará
Disponibilidad continua, RPO cero, tolerancia a particiones totales, ni el comportamiento de RDS fuera de Academy; sigue siendo una conmutación **controlada** con interrupción medida.

## Orden recomendado
**A → B → (O1 y despliegue en OCI) → construir P4/P5 localmente → C.** Cada paso con su propia autorización; ninguno se ejecuta por inercia.
