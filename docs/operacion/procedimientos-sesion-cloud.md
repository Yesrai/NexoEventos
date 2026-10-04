# Procedimientos para la siguiente sesión cloud

Preparado el 3 de octubre de 2026 (Lima) sobre el commit `545a7f3`. **Ningún procedimiento de este documento se ha ejecutado todavía**; los resultados se registrarán solo después de observarlos. Plan, alcance, costo y riesgos: [sesion-cloud-siguiente.md](sesion-cloud-siguiente.md).

Todos los scripts:

- verifican la identidad AWS contra `expected_account_id` de `work/terraform-envs/<entorno>.tfvars` sin imprimir el ID;
- escriben resultados en `work/` (ignorado por Git, modo `0700`/`0600`);
- nunca imprimen contraseñas, cookies, tokens QR, endpoints RDS ni IDs de cuenta;
- bloquean cualquier cambio externo salvo `NEXO_ALLOW_CLOUD_CHANGES=YES` (o `NEXO_LOAD_TEST_APPROVED=YES` para la carga).

| Script | Cambia AWS | Uso |
|---|---|---|
| `scripts/cloud/cloud-session.sh status` | no | estados EC2/RDS y fecha de reinicio automático de RDS |
| `scripts/cloud/cloud-session.sh check` | no | DNS, redirección HTTP→HTTPS, `/`, `/healthz`, `/api/events`, certificado y respaldos |
| `scripts/cloud/cloud-session.sh start` | **sí** | inicia RDS → espera `available` → inicia EC2 → espera `status-ok` → `check` |
| `scripts/cloud/cloud-session.sh stop` | **sí** | revisa respaldos, pide escribir `DETENER`, detiene EC2 y RDS y espera `stopped` |
| `scripts/cloud/capture-inventory.sh` | no | inventario sanitizado EV02–EV08 y búsqueda de fugas en logs |
| `scripts/cloud/load-test.py` | escribe datos ficticios | prueba E01 con usuarios virtuales |
| `scripts/cloud/restore-drill.sh run/cleanup` | **sí** | restauración aislada cronometrada y eliminación de la copia temporal |
| `deploy/verify-restore.sh` | no (solo lectura en BD) | verificación dentro de la EC2; viaja por SSM, no requiere redeploy |

Los recursos reales usan el prefijo `nexoeventos-academy-` (entorno `academy`; confirmado en el estado y el registro del plan). El 4 de octubre se reconstruyó `work/terraform-envs/academy.tfvars` desde el estado real `academy-current`, sin inventar valores, y quedó ignorado por Git con modo `0600`. Si vuelve a faltar, usar `scripts/reconstruct-academy-tfvars.py`; el script falla si no reconoce exactamente el estado y los nombres esperados. El archivo no se imprime ni se versiona. Los scripts verifican además que `project_slug` + `environment` produzcan exactamente `nexoeventos-academy`.

Si un bloque completo recién emitido con `Lab environment ready` vuelve a fallar en STS, no regenerarlo en bucle ni arrancar recursos a ciegas. Registrar hora, estado del lab y código de error sin secretos, y escalarlo a docente/soporte. Incidencia del 4 de octubre: `outputs/informe-sesion-aws-2026-10-04.md`.

Antes de empezar, cada terminal necesita la sesión AWS temporal del Learner Lab en un entorno aislado (como en EV09). No pegar credenciales en chats ni capturas.

## 1. Arranque y apagado con DNS, HTTPS y respaldos

```bash
export NEXO_ENV=academy
./scripts/cloud/cloud-session.sh status
NEXO_ALLOW_CLOUD_CHANGES=YES ./scripts/cloud/cloud-session.sh start
# ... trabajo de la sesión ...
./scripts/cloud/cloud-session.sh check
NEXO_ALLOW_CLOUD_CHANGES=YES ./scripts/cloud/cloud-session.sh stop
```

Criterios de aceptación de `check` (todos deben estar en `[OK]` antes de tomar evidencias públicas):

1. `dig` contra 1.1.1.1 devuelve la misma IPv4 que la EC2. Como la IPv4 cambia al arrancar, se esperan hasta 6 min al timer DuckDNS (cada 5 min). La IP se muestra enmascarada (`a.b.x.x`).
2. `http://` responde `301` hacia `https://`.
3. `https://…/` `200`, `/healthz` `200` (proxy a `/ready`, comprueba la BD) y `/api/events` `200`.
4. El certificado es Let's Encrypt y faltan ≥ 14 días para su vencimiento.
5. Respaldos: fecha y tamaño del último objeto en `backups/database/` (nombre del bucket oculto), antigüedad frente al objetivo RPO de 24 h, snapshot manual más reciente y `LatestRestorableTime`.

`stop` muestra de nuevo los respaldos y solo continúa si la operadora escribe `DETENER`. Registra cada transición en `work/operacion/sesiones-cloud.log`. Una orden aceptada no equivale al estado final: el script espera `stopped` en ambos servicios. Al terminar, recuerda que RDS se reinicia sola a los 7 días.

## 2. Capturas sanitizadas de red, seguridad y CloudWatch

### 2.1 Inventario textual (EV02–EV08)

```bash
./scripts/cloud/capture-inventory.sh
```

Genera `work/evidencias/<fecha>/` con: VPC y DNS (EV02); subredes, tablas de ruta e IGW (EV03); reglas efectivas de SG de entrada y salida (EV04); EC2 sin IP completa (EV05); RDS privado (EV06); snapshots y configuración S3, sin contenido (EV07); grupos de logs, retención, alarma y `ev08-log-scan.md` (EV08). Este último cuenta las coincidencias de `password`, `Authorization`, `Cookie`, nombres de cookie, `token=`, `Bearer` y `DUCKDNS_TOKEN` sin imprimir mensajes. `sanitize.py` enmascara cuentas, ARN, IDs (`vpc-…1a2b`), IPv4 públicas y endpoints. El script falla si queda un número de 12 dígitos o un endpoint RDS.

### 2.2 Capturas de consola

| ID | Pantalla de consola | Debe verse | Ocultar |
|---|---|---|---|
| EV02 | VPC › Your VPCs, detalle | nombre `nexoeventos-academy-vpc`, CIDR `10.20.0.0/16`, DNS hostnames/resolution habilitados, región | ID de cuenta (menú superior), ID completo de VPC |
| EV03 | Subnets + Route tables (pestaña Routes y Subnet associations) | 3 subredes `/24` y sus zonas; `public-rt` con `0.0.0.0/0 → igw`; `data-rt` solo `local` | IDs completos, cuenta |
| EV04 | Security groups › Inbound/Outbound rules | web: 443 y 80 desde `0.0.0.0/0`, **sin 22**; db: 5432 solo desde el SG web | IDs de SG, cuenta |
| EV06 | RDS › Connectivity & security | `Publicly accessible: No`, subnet group, SG de datos, cifrado | endpoint, ARN, cuenta |
| EV07 | S3 › bucket › Properties/Permissions | Block public access activado, versionado, SSE | nombre completo del bucket (contiene la cuenta) |
| EV08 | CloudWatch › Log groups, Alarms y gráfico CPU de la sesión | retención 7 días, alarma CPU con estado, gráfico con la carga | ARN, cuenta, contenido de mensajes |
| EV10 | Navegador en la URL pública | candado HTTPS, fecha/hora del sistema, página del proyecto | sesión, cookies, QR completo |

Reglas para cada captura:

1. Usar zoom 100 % y una ventana que muestre fecha/hora (barra del sistema) y región `us-east-1`.
2. Antes de capturar, cerrar el menú de cuenta y paneles con ARN. En macOS, `Cmd+Shift+4` captura un área. Después, tapar los identificadores con rectángulos opacos en Vista Previa (Herramientas › Anotar › Rectángulo relleno). **No usar desenfoque**, porque puede revertirse.
3. Exportar como PNG nuevo (no conservar la versión sin editar en el repositorio) y nombrar `EVxx-descripcion-AAAA-MM-DD.png` dentro de `docs/evidencias/EVxx/`.
4. Revisar a 200 % que no se lea ningún dígito de cuenta, endpoint, IP completa, token, cookie ni dato personal.
5. Completar en el README de la evidencia: título e ID, fecha/hora, servicio, configuración, resultado esperado, resultado obtenido y criterio oficial relacionado.

## 3. Prueba de carga con datos ficticios (E01)

Objetivo del caso, **no resultado**: 20 usuarios virtuales durante 5 min, p95 < 2 s y errores inesperados < 1 %. Opcionalmente, 40 usuarios si los primeros resultados y el crédito lo permiten.

Ensayo previo sin costo, contra el backend local:

```bash
python3 scripts/cloud/load-test.py --base-url http://localhost:8000 --origin http://localhost:5173 \
  --vus 5 --duration 30 --ramp 5
```

Ejecución en la nube (solo con aprobación):

```bash
NEXO_LOAD_TEST_APPROVED=YES python3 scripts/cloud/load-test.py \
  --base-url https://nexoeventos-demo.duckdns.org --vus 20 --duration 300 --ramp 30
```

- Cada usuario virtual registra un cliente `carga-<run>-NNN@example.com` (dominio reservado) con una contraseña aleatoria que solo existe en memoria. Esos registros, con Argon2, no entran en las percentiles medidas, pero se informan aparte.
- Mezcla: 60 % catálogo, 25 % detalle, 10 % mis entradas y 5 % reservas **solo** si se indica `--event-id` de un evento ficticio dedicado cuyo nombre empieza por `[CARGA]`. Sin él, no se consumen cupos de los eventos de demostración. Los `409` por cupo agotado se cuentan como resultado de negocio.
- Los 20 registros deben completarse antes de la ventana medida. Si alguno falla, el script marca el ensayo como inválido aunque p95 y errores parezcan cumplir.
- La latencia se mide desde el Mac, así que incluye Internet y TLS. Debe declararse así.
- Durante la prueba, observar CloudWatch (CPU EC2) y, si se desea, `CPUUtilization`/`DatabaseConnections` de RDS para la captura EV08.
- Salidas: `work/carga/<run>/resumen.md` y `resumen.json`. Copiar `resumen.md` revisado a `docs/evidencias/EV11/`.
- Después: las cuentas `carga-*@example.com` quedan como datos ficticios. Se pueden conservar o eliminar en una tarea separada aprobada; no hay endpoint para borrarlas.

El script termina con código 3 si no cumple E01. Un incumplimiento se registra como resultado, no se oculta.

## 4. Restauración cloud aislada y cronometrada (R01)

Objetivo del caso, **no resultado**: RTO ≤ 60 min y RPO ≤ 24 h.

```bash
# Modo recomendado: último punto recuperable del backup automático (RPO realista)
NEXO_ALLOW_CLOUD_CHANGES=YES ./scripts/cloud/restore-drill.sh run --pitr
# Alternativa: snapshot manual cifrado del 3 de octubre
NEXO_ALLOW_CLOUD_CHANGES=YES ./scripts/cloud/restore-drill.sh run
# Siempre al terminar
NEXO_ALLOW_CLOUD_CHANGES=YES ./scripts/cloud/restore-drill.sh cleanup nexoeventos-academy-restore-AAAAMMDDtHHMM
```

Secuencia y marcas de tiempo:

| Marca | Evento |
|---|---|
| T-pre | API pausada y línea base lógica/QR comprobada |
| T0 | la operadora escribe `RESTAURAR` (incidente simulado declarado) |
| T1 | AWS acepta la restauración en `nexoeventos-academy-restore-<ts>` |
| T2 | la instancia temporal está `available` |
| T3 | `verify-restore.sh` termina con `VERIFICACION_RESTAURACION=OK` por SSM |

- **Aislamiento:** instancia nueva `db.t3.micro`, privada (se comprueba `PubliclyAccessible=False`), Single-AZ, mismo subnet group y SG de datos. Solo la EC2 puede alcanzarla. La aplicación pública sigue usando la RDS original.
- **Verificación:** pausa brevemente `nexoeventos-api`, genera una huella lógica exacta con el rol de migración/owner, comprueba reservas y descifra **todas** las entradas sin mostrar tokens. La copia debe coincidir en revisión Alembic, conteos, huella y QR. Después se reanuda el servicio original.
- **Medidas:** se informa el desfase T0 − punto recuperable, el tiempo hasta RDS `available` y el tiempo hasta datos verificados. PITR solo acredita el RPO porque se compara con la línea base; su mera disponibilidad no basta. Un snapshot antiguo puede restaurarse correctamente y aun así no representar el punto esperado.
- **Alcance honesto:** no se conmutan aplicación, DNS ni HTTPS. Por ello no se etiqueta el resultado como RTO del servicio completo; ese tiempo exige una prueba adicional de conmutación y flujo funcional.
- Resultado en `work/restauracion/<ts>/resumen.md`. La limpieza solo acepta el recibo `recurso.json`, ARN y etiquetas de esa misma ejecución. Copiar la versión revisada a `docs/evidencias/EV07/`.
- **Restauración del dump lógico (opcional, separada):** descifrar el paquete CMS de S3 en un directorio temporal de la EC2 y restaurarlo con `pg_restore --no-owner --no-acl` en una base `nexoeventos_restore_dump` de la instancia temporal, usando la credencial maestra leída en memoria como en `bootstrap-rds-secrets.sh`. Luego se verifica igual y se borra junto con la instancia. Requiere aprobar el uso de la credencial maestra y la clave privada de recuperación; no está automatizado.

## 5. Orden recomendado dentro de la sesión

1. `status` → revisar el panel Academy y anotar el consumo inicial.
2. `start` → `check` en verde.
3. `capture-inventory.sh` y capturas de consola EV02–EV08 y EV10.
4. Prueba de carga de 20 usuarios y captura del gráfico CloudWatch durante la carga.
5. `restore-drill.sh run --pitr`, captura de la copia privada, verificación y `cleanup`.
6. `check` final, `stop` y anotación del consumo final.
