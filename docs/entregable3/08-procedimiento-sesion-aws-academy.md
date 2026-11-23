# Entregable 3 · Procedimiento seguro para la sesión de AWS Academy (solo lectura) — 10-nov-2026

**Estado: preparado, NO ejecutado.** No se inició el laboratorio, no se ejecutó ningún comando contra AWS, no se modificó ninguna nube; sin commits ni push. Este procedimiento solo se pone en marcha cuando la usuaria lo autorice.

## 1. Script auditado
- **Archivo:** `scripts/multicloud/viabilidad-readonly-aws.sh` (v2). **SHA-256:** `6b9524178e96adcb00de19bc1c5152f8af821c50d306fd7ea4ddcd227700e9b3`.
- La v1 se conserva en `evidencias/viabilidad-aws-script-v1-sustituido.sh.txt`. Defectos de la v1 corregidos: no se detenía ante errores; la sección de identidad no mostraba nada útil (el filtro convertía el ARN en `<arn>`); sin filtro propio para claves y tokens (dependía de `scripts/cloud/mask.sh`, que podía cambiar sin invalidar la autorización); sin comprobar el estado de EC2, ALB, Auto Scaling, NAT, IP elásticas ni volúmenes (lo que factura); sin límite de tiempo ni paginador; dependía del perfil `nexoeventos-lab` aunque el proyecto usa la sesión aislada del Learner Lab por variables de entorno.
- Auditoría estática automatizada: `scripts/multicloud/auditar-solo-lectura-aws.py` → **APTO** (resultado en `evidencias/auditoria-estatica-viabilidad-aws-v2.txt`). 18 consultas `--query` comprobadas con jmespath en local (0 errores de sintaxis). Lógica probada con una CLI falsa (todo correcto; credenciales caducadas; sin autorización; sin CLI).

## 2. Comandos exactos y permisos IAM necesarios
Todas las llamadas son `describe-*`, `sts get-caller-identity` o (solo sección opcional) `iam simulate-principal-policy`. Nada de create/modify/delete/start/stop/reboot/run/terminate/put/attach/authorize/allocate.
| Sección | Comando | Permiso IAM |
|---|---|---|
| 0 identidad | `sts get-caller-identity` (se imprime solo el **nombre del rol**) | ninguno |
| 1 estado | `ec2 describe-instances` · `autoscaling describe-auto-scaling-groups` · `elbv2 describe-load-balancers` · `ec2 describe-nat-gateways` · `ec2 describe-addresses` · `ec2 describe-volumes` · `rds describe-db-instances` | `ec2:DescribeInstances`, `autoscaling:DescribeAutoScalingGroups`, `elasticloadbalancing:DescribeLoadBalancers`, `ec2:DescribeNatGateways`, `ec2:DescribeAddresses`, `ec2:DescribeVolumes`, `rds:DescribeDBInstances` |
| 2 rds | `rds describe-db-instances --db-instance-identifier …` · `rds describe-events --duration 20160` · `rds describe-db-parameter-groups` · `rds describe-db-engine-versions --engine postgres --engine-version 18.3` | `rds:DescribeDBInstances`, `rds:DescribeEvents`, `rds:DescribeDBParameterGroups`, `rds:DescribeDBEngineVersions` |
| 3 parametros | `rds describe-db-parameters --db-parameter-group-name default.postgres18` filtrado a `synchronous_standby_names`, `synchronous_commit`, `rds.logical_replication`, `wal_level`, `max_wal_senders`, `max_replication_slots`, `max_logical_replication_workers`, `max_slot_wal_keep_size`, `wal_sender_timeout`, `rds.force_ssl`… (muestra `IsModifiable` y `ApplyType`) | `rds:DescribeDBParameters` |
| 4 red | `ec2 describe-vpcs` · `describe-subnets` · `describe-route-tables` · `describe-security-groups` · `describe-vpn-gateways` | `ec2:DescribeVpcs`, `DescribeSubnets`, `DescribeRouteTables`, `DescribeSecurityGroups`, `DescribeVpnGateways` |
| 5 permisos (**opcional, se pide aparte**) | `iam simulate-principal-policy` con nombres de acción como texto (no se ejecutan) | `iam:SimulatePrincipalPolicy` (probablemente denegado en Academy: entonces el script se detiene y no se insiste) |
Un permiso ausente detiene el script en esa llamada (código 3). No hay instalaciones, ni escritura de archivos, ni lectura de `~/.aws`; solo se comprueba si existe la variable `AWS_ACCESS_KEY_ID` (no se lee ni se imprime).

## 3. Qué ocultan los resultados (también los errores)
Filtro propio dentro del script: ARN, IDs de cuenta de 12 dígitos, claves de acceso (`AKIA…`/`ASIA…`), valores de `aws_secret_access_key`/`SessionToken`/contraseñas/firmas, usuario de sesión de Academy, IDs de recursos (`i-`, `vpc-`, `subnet-`, `sg-`, `igw-`…), IP, correos, bloques de claves privadas y cadenas largas. Probado localmente con 9 ejemplos. Se conservan legibles los mensajes de error útiles (p. ej. `ExpiredToken`).

## 4. ¿Se puede consultar el estado de RDS, EC2, ALB y permisos sin activar nada?
**Sí.** Las consultas `describe-*` no inician ni modifican recursos y no cuestan. Lo único que exige es una sesión de Academy activa (credenciales vigentes). Los **permisos** solo pueden *simularse* (`iam:SimulatePrincipalPolicy`, probablemente denegado); la única prueba fiable de un permiso de escritura es intentarlo, y eso necesitaría otra autorización.

## 5. La regla de los 7 días de RDS
- **Regla general de AWS (documentación oficial):** una instancia RDS detenida se **reinicia sola tras 7 días consecutivos** para aplicar mantenimiento; aplica a PostgreSQL y a Multi-AZ; mientras está detenida se cobra almacenamiento, copias y la IPv4 pública (no las horas de instancia). Consultarla o describirla no reinicia el contador.
- **Academy:** las fuentes **discrepan** sobre qué ocurre con RDS al terminar la sesión del Learner Lab (una de ellas indica que RDS **no** se detiene sola; otra, que si la dejas detenida 7 días AWS la reinicia). Para EC2 consta que Academy las detiene al cerrar la sesión y puede reiniciarlas al empezar otra. **No hay una fuente clara para Multi-AZ en Academy.**
- **Dato propio, más importante:** la última evidencia del 6-nov (apagado de V2) dejó **RDS `available` (Multi-AZ), V1 `running` y el ALB activo**; no consta que RDS se haya detenido después. El estado Terraform local que dice `stopped` es del 4-nov y está desactualizado. Por tanto la regla de los 7 días probablemente **no sea el riesgo actual**: el riesgo es que RDS (y el ALB) sigan encendidos facturando.
- La comprobación de verdad es la sección `estado` + los eventos de RDS de los últimos 14 días.

## 6. Riesgos de costo (tarifas públicas documentadas en el repositorio; no hay facturación)
| Recurso (según la última evidencia) | Costo |
|---|---|
| ALB | ≈ 0,03–0,04 USD/h |
| RDS Multi-AZ `db.t3.micro` | ≈ 0,042 USD/h |
| EC2 V1 `t3.small` + IPv4 | ≈ 0,03 USD/h (si Academy la detiene al cerrar la sesión, ≈ 0,08 USD/h en total sin ella) |
| Total si todo siguió encendido | ≈ 0,11 USD/h ≈ 2,6 USD/día |
Si ALB y RDS siguen encendidos desde el 6-nov (≈ 4 días), el gasto acumulado podría ser del orden de **8–11 USD** (**estimación sin verificar**: depende de qué se apagó realmente). El saldo declarado era de USD 11,2 de 50 el 5-nov; el actual es desconocido. **Ejecutar el script cuesta USD 0**, pero:
1. Tú tienes que iniciar el laboratorio (Start Lab) y eso puede **reiniciar la EC2 de V1** si Academy la deja en marcha o la restaura (≈ 0,03 USD/h).
2. Si el script muestra recursos encendidos, **cada hora que sigan encendidos cuesta**; apagarlos o destruirlos es una escritura que requiere tu autorización aparte.
3. La sesión de Academy dura unas 4 h por defecto; el crédito llega al 26-nov.

## 7. Procedimiento (solo cuando lo autorices)
**Antes (tú):**
1. Mira en la consola de Academy el **saldo/presupuesto** y anótalo (no lo copies con capturas que incluyan cuentas).
2. Confirma por escrito que autorizas ejecutar el script con el SHA-256 `6b952417…e9b3`, qué secciones (`todo` = estado + rds + parametros + red; `permisos` opcional) y que **no** autorizas ningún cambio de recursos.
**Sesión:**
3. En AWS Academy → Learner Lab pulsas **Start Lab** (tú; yo no lo inicio) y esperas el círculo verde.
4. Abres **AWS Details** y actualizas **tú** las credenciales temporales del perfil local `nexoeventos-lab` (`~/.aws/credentials`, que ya existe) — así las verá la CLI cuando yo ejecute el script desde mi sesión; yo no leo ni imprimo ese archivo (el script solo usa el perfil o, si hay variables `AWS_ACCESS_KEY_ID` en el entorno, esas). **No las pegues en el chat ni las guardes en archivos del repositorio.** Región `us-east-1`. (Un terminal tuyo aislado con variables de entorno no es visible para mi sesión.)
5. Me avisas con "lab iniciado". Yo verifico el SHA-256 y ejecuto **primero solo `estado`** (qué hay encendido) y te muestro el resultado.
6. **Puerta de decisión:** si `estado` muestra recursos que facturan (ALB, RDS Multi-AZ en `available`, EC2), **me detengo**, te doy el costo por hora y espero tu decisión (aceptar el gasto, apagar o destruir con autorización explícita). No continúo con las demás secciones hasta entonces, salvo que lo pidas.
7. Con tu visto bueno ejecuto `rds`, `parametros` y `red`. Ante `ExpiredToken` o permiso denegado el script se detiene y no intenta arreglarlo.
8. Guardo la salida filtrada en `docs/entregable3/evidencias/aws-consulta-solo-lectura-AAAAMMDD.txt` y actualizo los informes.
**Después (tú):** decides si terminas la sesión (**End Lab**). Terminar la sesión **no garantiza** que RDS o el ALB se detengan (§5).

## 8. Autorización que necesito
1. **Ejecutar `viabilidad-readonly-aws.sh` v2** (SHA-256 `6b9524178e96adcb00de19bc1c5152f8af821c50d306fd7ea4ddcd227700e9b3`), secciones `estado`, luego `rds`, `parametros` y `red`. Solo consultas; USD 0 por las consultas.
2. Que **tú inicies el laboratorio** y me avises (yo no lo inicio). Eres consciente de que puede reiniciar la EC2 de V1.
3. **Aparte y opcional:** la sección `permisos` (simulación IAM).
4. **No** autorizado ahora (se pedirá por separado si hace falta): apagar o destruir ALB/RDS/EC2, crear VPN, IP o instancias, modificar parámetros, iniciar o detener recursos.
