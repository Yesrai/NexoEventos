# Centro de operaciones en Azure (L0, implementado y probado SOLO en local) — 22-nov-2026

Código: `ops_center/` (reutiliza `app.ops` para respaldo/failover y `failover_config.validate`; no reescribe nada existente). **Nada se ha desplegado en Azure ni se ha llamado a ninguna nube.**

## 1. Qué es y qué no es
- **Es:** un servicio FastAPI pequeño (127.0.0.1:8750, TLS por Nginx en la VM de Azure) con panel web, estado de las tres nubes, flujo **solicitar → validar → aprobar** de recuperaciones y auditoría encadenada.
- **No es:** un ejecutor. No existe ningún endpoint, rol ni botón que haga failover, cambie DNS o habilite un escritor. `REAL_EXECUTION_WIRED = False` (`barriers.py`) es la última barrera y solo cambia con una modificación de código revisada.
- **Independiente de AWS:** no usa la base de datos de la aplicación, ni credenciales AWS, ni red hacia AWS. Probado: con `socket.connect/getaddrinfo` sustituidos por excepciones, el panel responde y registra solicitudes. Si AWS cae, el panel sigue vivo y mostrará «No verificado» o el último dato fresco, nunca «OK» por defecto.

## 2. Flujo y garantías (probadas en `ops_center/tests`, 26 pruebas)
1. `requester` crea la solicitud (tipo en lista blanca, justificación 10–500 caracteres, una activa por tipo, idempotencia).
2. **Validación automática** contra barreras de solicitud (B01–B07). Si alguna falla → `RECHAZADA_VALIDACION` y no se puede aprobar.
3. `approver` distinto del solicitante aprueba o deniega. La solicitud caduca a los 30 min y la aprobación a los 60 min.
4. «APROBADA» **no ejecuta**: la ejecución real queda como acto humano posterior, bloqueado además por B08–B11 (variable de ejecución, autorización específica con frase y vigencia ≤ 6 h, solicitud aprobada vigente, adaptadores cableados).
5. Cada solicitud, validación, decisión, denegación de acceso y cambio del interruptor de emergencia se escribe en `audit.jsonl` con cadena SHA-256. Detecta ediciones y borrados intermedios; **no** impide que quien tenga el archivo lo reescriba entero: copie el último hash fuera del servidor tras cada sesión.

| Barrera | Qué exige |
|---|---|
| B01 | interruptor de emergencia apagado (`ops_center kill-switch on/off`) |
| B02 | cadena de auditoría íntegra |
| B03 | ahora < vencimiento de Academy − 12 h (por defecto 26-nov-2026 00:00Z, **a confirmar**) |
| B04 | registro de promoción en `NONE` (en `failback_manual`: `PROMOTED`) |
| B05 | último respaldo dentro del RPO |
| B06 (T1–T4) | evidencia `PASS` reciente registrada con `record-evidence` (SHA-256 del informe) |
| B07 | `failover_config.validate` correcto y sin dominio de producción permitido |
| B08–B11 | solo ejecución: variable, autorización humana, solicitud aprobada, adaptadores reales |
Limitación honesta: la evidencia T1–T4 la registra quien tiene acceso local al servidor; no es una prueba criptográfica contra un operador malicioso, sino un control de procedimiento auditado.

## 3. Propuesta de identidades y permisos mínimos (D2)
Regla: **ninguna identidad administrativa se reutiliza** y ninguna identidad del centro puede ejecutar.
| Identidad | Dónde | Permisos | Prohibido |
|---|---|---|---|
| `ti-lectura` (viewer) | token del centro | leer estado y auditoría | solicitar, aprobar |
| `ti-solicitante` (requester) | token del centro | solicitar/cancelar lo propio | aprobar |
| `propietaria-aprobador` (approver) | token del centro, solo la propietaria | aprobar/denegar solicitudes ajenas | solicitar, ejecutar |
| Usuario del SO `opscenter` | VM de Azure | leer/escribir `work/ops-center` (0700); sin sudo, sin claves de nube | acceso a `~/.oci`, `~/.aws`, `~/.ssh` |
| Identidad administrada de la VM (existente) | Azure | `Monitoring Reader` en el grupo de recursos (ya existe) | escribir recursos |
| Recolector de estado (T4) | VM de Azure, proceso aparte | **Preferido:** sondas HTTPS públicas (`/livez`, `/api/events`), sin credenciales. Opcional OCI: usuario `nexoeventos-ops-reader` con `inspect instances` y `read metrics` solo en el compartimento `nexoeventos`. Opcional AWS (solo lectura): `ec2:DescribeInstances`, `rds:DescribeDBInstances`, `elasticloadbalancing:DescribeLoadBalancers/DescribeTargetHealth`, `autoscaling:DescribeAutoScalingGroups`, `cloudwatch:DescribeAlarms/GetMetricData` | cualquier acción de escritura |
| Lease en OCI, lado AWS | bucket `nexoeventos-lease-test` | usuario `nexoeventos-lease-aws`, clave API 0600, **solo ese bucket**: `OBJECT_INSPECT/READ/CREATE/OVERWRITE`, sin borrado | el bucket de respaldos |
| Lease en OCI, lado OCI | VM standby | principal de instancia (grupo dinámico) con los mismos 4 permisos en ese bucket | credenciales en disco |
| Token de DuckDNS | archivo 0600 del ejecutor humano | solo el subdominio de pruebas `nexoeventos-test` | dominio `nexoeventos-demo`; nunca en el centro |
| Acciones AWS del failover (parar API en una EC2, leer RDS) | las hace la propietaria con las credenciales del laboratorio, a mano | — | el centro no las tiene |
**Restricción de Academy (verificar antes de T1):** la evidencia previa muestra permisos denegados en el laboratorio (p. ej. `iam:GetPolicy`); es posible que Academy **no permita crear usuarios/roles IAM**. Si es así, el lado AWS del lease usa el usuario de OCI de arriba (no necesita IAM de AWS) y las lecturas de estado AWS se hacen por HTTPS público o con las credenciales temporales del laboratorio sin guardarlas.
Rotación y retirada: tokens del centro y claves API de OCI se rotan o se revocan al cerrar T8; los tokens se guardan en el gestor de contraseñas, nunca en el repositorio.

## 4. Despliegue previsto en la VM de Azure (NO ejecutado; requiere ventana y autorización de Azure)
`/opt/nexoeventos` con `backend/` y `ops_center/` → venv con `requirements-production.lock` → `python -m ops_center init-identities --dir /var/lib/ops-center` → unidad systemd (usuario `opscenter`, `ProtectSystem=strict`, `NoNewPrivileges=true`, `ReadWritePaths=/var/lib/ops-center`) → ubicación `/ops/` en el Nginx existente con TLS 1.3 y la IP /32 ya permitida (o Tailscale). Costo adicional: 0 (misma VM).

## 5. Verificar localmente
```bash
backend/.venv/bin/python -m pytest ops_center -q
```
