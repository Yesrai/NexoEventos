# Auditoría técnica integral (documento de trabajo) — 29-oct-2026

Estado: **borrador de trabajo, no es el entregable**. Sin operaciones en la nube en esta fase (solo lectura de archivos locales). Sin commits, push, apply ni Word/PDF.

## 1. Hallazgos de Trivy (configuración Terraform)

**Verificación del conteo:** el informe original de Trivy (artefacto `trivy-repositorio`, `trivy-config.txt`) **no está en el repositorio** y Trivy no está instalado en este equipo, por lo que **el número exacto de hallazgos no se puede confirmar localmente**. La lista siguiente procede de lo que usted pegó y cada ubicación se comprobó en el código. El paso de configuración del CI es informativo (`exit-code: "0"`) y distinto del de vulnerabilidades (que dio 0 en las dependencias e imagen analizadas). Para fijar el conteo hay que descargar el artefacto del run #31 desde GitHub (lectura, sin coste).

| ID | Archivo:línea | Recurso | Severidad | Activo / histórico | Control compensatorio | Estado |
|---|---|---|---|---|---|---|
| AWS-0080 | `infra/aws-recovery/main.tf` (`aws_db_instance.recovery`) | RDS de recuperación sin `storage_encrypted` explícito | HIGH | Plantilla de recuperación (no desplegada ahora) | La restauración PITR hereda el cifrado de la RDS de origen (`storage_encrypted = true`, `infra/aws/database.tf:14`) | **CORREGIDO localmente** (declarado `true`); `terraform fmt` y `validate` OK; sin desplegar |
| AWS-0104 | `infra/aws/network.tf:100-107`, `infra/aws-recovery/main.tf:52-59`, `infra/aws-v2/network.tf:75-82` | Salida 443 a `0.0.0.0/0` | CRITICAL (regla genérica) | V1 (detenida), V2 (destruida), recuperación (plantilla) | Sin entrada pública a la instancia salvo 80/443 (V2: solo desde el SG del ALB); salida solo 443/DNS/5432; IMDSv2 | **ABIERTO, sin solución gratuita segura** (ver §1.1) |
| AWS-0164 | `infra/aws/network.tf:19`, `infra/aws-v2/network.tf:6` | Subred con `map_public_ip_on_launch` | HIGH | V1/V2 | SG sin SSH; entrada 80/443 | **CORREGIDO en código** (ver §1.1); no aplicado en la nube |
| AWS-0053 | `infra/aws-v2/alb.tf:4` | ALB público (`internal = false`) | HIGH | V2 (destruido tras la medición) | Es el punto de entrada del sistema; HTTPS con redirección, `drop_invalid_header_fields` | **NO SE CAMBIA**: un ALB interno rompería el servicio público. Justificado por diseño |
| AWS-0132 | `infra/aws/storage_observability.tf:26` | S3 con SSE-S3 (AES256), no KMS propio | HIGH (según Trivy) | Activo | **Sí hay cifrado en reposo** (SSE-S3); acceso privado, versionado | **PROPUESTA**: KMS gestionado por el cliente añade coste por clave/solicitud y permisos que Academy puede denegar; no se cambia sin revisar |

### 1.1 Análisis de AWS-0104 y AWS-0164 (cambio de prioridad: corregir lo corregible)

**AWS-0164 — corregido en código.** Causa real: las subredes públicas asignaban IP pública a *cualquier* instancia. V1 y la recuperación ya piden la IP por instancia (`associate_public_ip_address = true`); solo el *launch template* de V2 dependía de la subred. Cambios locales: (1) `infra/aws-v2/compute.tf`: `network_interfaces { associate_public_ip_address = true, security_groups = [web] }` (el grupo de seguridad se movió ahí; no pueden convivir con `vpc_security_group_ids`); (2) `map_public_ip_on_launch = false` en `infra/aws/network.tf` y `infra/aws-v2/network.tf`; (3) `infra/aws-v2/tests/check_security.py` actualizado para exigir ese diseño. Validación local: `terraform fmt`/`validate` OK en las tres raíces; `check_security.py` sin fallos; `check-iac-security.py` OK. Sin coste, sin servicios nuevos, comportamiento de las instancias igual. **Límite honesto:** la instancia sigue teniendo IP pública porque no hay NAT; lo que desaparece es la asignación implícita a cualquier recurso futuro de esa subred. Cambiar la subred es una modificación *in situ* (no reemplaza la subred) pero **no se ha aplicado**; falta `terraform plan` revisado con credenciales.

**AWS-0104 — no se corrige sin cambiar la arquitectura.** Causa real: las instancias están en subred pública sin NAT y necesitan salir por HTTPS a destinos sin rango fijo: Secrets Manager/SSM/CloudWatch (V2 al arrancar: `bootstrap-instance.sh.tftpl`), y en V1/recuperación además repositorios de Amazon Linux, nodejs.org, PyPI, DuckDNS/sslip.io y Let’s Encrypt (`install-amazon-linux-2023.sh`, `duckdns/update.sh`, certbot). Alternativas evaluadas: (a) listas de prefijos o IP de AWS: solo existe lista gestionada para S3/DynamoDB, no para los demás servicios, y los destinos de terceros cambian; (b) *endpoints* de interfaz (Secrets Manager, SSM, logs): ≈0,01 USD/h por endpoint y zona + datos, es decir de pago, y Academy puede denegar su creación; (c) endpoint de pasarela de S3: gratuito, pero cubre solo S3 y no elimina la regla; (d) instancias privadas + NAT: de pago. Para V2, con AMI dorada, la dependencia real se reduce a servicios AWS, de modo que **la mejora futura viable es endpoints de interfaz (con coste)** y quitar la regla global; queda como propuesta con coste a aprobar. La regla ya está limitada al puerto 443 y no hay `0.0.0.0/0` en otros puertos de salida.

Conteo confirmado: ver §13.1.

## 2. Corrección realizada en esta fase
- `infra/aws-v2/compute.tf`, `infra/aws-v2/network.tf`, `infra/aws/network.tf`, `infra/aws-v2/tests/check_security.py`: AWS-0164 (ver §1.1).
- `infra/aws-recovery/main.tf`: `storage_encrypted = true` + comentario (AWS-0080). Validado: `terraform fmt -check` OK; `terraform validate` OK en `aws`, `aws-recovery` y `aws-v2`. No se aplicó nada.

## 3. Pruebas locales ejecutadas hoy
| Comando | Resultado |
|---|---|
| `pytest -q` (backend) | 52 passed |
| `npm test` (frontend) | 33/33 |
| `terraform validate` en `infra/aws`, `aws-recovery`, `aws-v2` | válido |
| `scripts/multicloud/check-iac-security.py` | OK |
Límite: los cambios locales no han corrido en CI (requiere commit/push, no autorizado).

## 4. GitHub Actions / DevSecOps (`.github/workflows/ci.yml`)
- **Es CI, no CD:** triggers `pull_request`, `push main`, `workflow_dispatch`; sin credenciales de nube, sin publicar imágenes, sin despliegue. No hay evidencia de despliegue automático.
- Buenas prácticas verificadas en el archivo: `permissions: contents: read`; acciones fijadas por SHA; `persist-credentials: false`; `concurrency`; timeouts; imagen PG fijada por digest; Trivy `vuln,secret` bloquea HIGH/CRITICAL con corrección; `.trivyignore` vacío a propósito.
- Brechas: sin escaneo de Terraform que bloquee (informativo); sin cobertura de pruebas (no hay `--cov`); `ignore-unfixed: true` omite CVE sin parche; sin SBOM ni firma; sin Dependabot/Renovate. Causa del fallo CI #16: **no está documentada**; no se inventa.
- Datos del run #31 (commit `42dd9e0`, 1 min 28 s, 33/33, Trivy 0 en lo analizado, 3 artefactos): proceden de lo que usted indicó y de `docs/evidencias/ci-github-actions-20261029/resultado.md`; el Docker/Trivy de ese run está en el resumen del run, no copiado aquí.

## 5. Evidencias (capturas)
- Localizadas en `~/Downloads` (originales, intactos) y con copias redactadas en `docs/evidencias/capturas/aws/`: 01, 02, 04–11 (10 capturas AWS: RDS config/seguridad, SG salida/entrada, ASG, ALB 5xx, hosts sanos/no sanos, eventos RDS, failover 22-oct). Indexadas en `docs/evidencias/capturas/INDICE.md`.
- **OCI y Azure:** mi búsqueda por patrón de nombre solo encontró las de AWS. Las capturas OCI (bucket, política) y las de Azure (alerta, grupo de acción) que usted dice haber tomado **no las he localizado todavía**; no las doy por incorporadas. Necesito su ubicación (o permiso para mirar Capturas/Recientes) y las tratará como copias redactadas.
- No se tomó ninguna captura nueva ni se alteró ninguna.

## 6. Chaos Engineering — estado
| Experimento | Estado | Evidencia |
|---|---|---|
| Caída de proceso/instancia y autocuración | EJECUTADO (detección 20,0 s, reemplazo ≈2,5 min, 25/275 respuestas 502) | `docs/evidencias/tolerancia-fallos-v2-20261022*` |
| Auto Scaling 2→3→2 | EJECUTADO (alarma a 8 min 6 s) | `docs/evidencias/escalado-v2-20261022` |
| Failover RDS Multi-AZ | EJECUTADO (≈14 s; `/healthz` ≈13 s según el registro original: **verificar cifras contra el archivo de EV antes de citarlas**) | `docs/evidencias/…`, capturas 10 y 11 |
| Recuperación en OCI | EJECUTADO, manual (32 min 42 s, 14/14, 10/10) | `docs/evidencias/multicloud/oci/…` |
| AWS FIS | **NO EJECUTADO** | `docs/entregable2/plan-caos-fis.md` (diseño) |
| Caída completa de una AZ | **NO EJECUTADO** | idem |
| Recuperación íntegra dentro de AWS | **NO EJECUTADO** (R01 restauró un punto PITR concreto, no el sistema completo) | — |
Los eventos del ALB y el failover de RDS son experimentos distintos y no se mezclan.

## 7. Multicloud (estado)
- **AWS:** V1 en pie pero detenida (EC2/RDS stopped según la última lectura; sesión actual caducada, estado no reverificado hoy); V2 destruida tras medir (ya no aparece en consola).
- **Azure:** VM desasignada (última lectura). Alerta `alerta-vm-cpu` disparada y resuelta (28-oct, 9:41–10:02 hora de Lima). **Entrega del correo NO demostrada** (409 «Free subscription not supported»). Alternativas posibles, sin ejecutar: leer el historial de la alerta/Activity Log del grupo de acción, o un webhook/receptor propio en una futura ventana autorizada.
- **OCI:** bucket privado versionado `nexoeventos-recovery`; política `nexoeventos-backup-uploaders` con OBJECT_CREATE/READ/INSPECT limitada al bucket (sin DELETE en esa regla; no se revisaron otras políticas del tenancy más allá de `Tenant Admin Policy`). Recuperación de aplicación completada y recursos temporales destruidos. No inspeccioné `secrets/`.
- **GCP:** `infra/gcp` contiene solo `versions.tf` (7 líneas, sin proveedor ni recursos) y un README: **marcador de posición**. No aporta valor a la rúbrica; se deja como propuesta futura. No está implementado.

## 8. Recuperación ante pérdida de AWS Academy (guía de reconstrucción, de trabajo)
**Se puede reconstruir:** código (repositorio), Terraform de V1/V2/recuperación, Ansible/despliegue, pruebas, documentación.
**Depende de datos/secretos externos:** (a) respaldo cifrado CMS de la BD, que existe en OCI (`backups/`, con manifiesto) y localmente en `work/backups/external/`; (b) clave privada de recuperación (solo en su poder; sin ella el respaldo no se descifra); (c) `tfvars` y estados en `work/` (git-ignored, **solo en esta Mac**: un punto único de fallo); (d) credenciales nuevas del laboratorio.
**Probado:** restauración y arranque de la aplicación **en OCI** (32 min 42 s, desde cero en una VM, con datos íntegros 10/10). **No probado:** reconstrucción completa de la infraestructura AWS en un laboratorio nuevo.
**Intervención manual:** crear laboratorio, cargar credenciales, `terraform init/plan/apply` revisado, restaurar BD, rotar secretos, DNS/certificados.
**Perdible:** datos creados después del último respaldo (**no se declara RPO**; el 3 m 32 s de R01 es de una prueba concreta de PITR, no una garantía), snapshots de RDS, métricas históricas de CloudWatch (parcialmente exportadas).
**RTO:** 32 m 42 s es el RTO **observado de la recuperación manual en OCI**, no del conjunto ni de AWS.
**Riesgo concreto a cubrir (indispensable, sin coste):** hacer copia del directorio `work/` (tfvars/estado) y de la clave de recuperación en un soporte seguro fuera de la Mac.

## 9. Costos y créditos
- Observado/estimado en docs: Azure VM ≈0,108 USD/h (solo en ventanas), disco 64 GiB ≈4,80/mes persiste aunque la VM esté desasignada; IP pública solo con la VM; OCI VM temporal destruida; RDS detenida **se reinicia sola a los 7 días** (plazo ≈4-nov 21:51Z) y EC2 puede arrancar al reiniciar el laboratorio.
- **Crédito restante real de AWS Academy y Azure: no confirmado** (la captura de costos está pendiente). Gasto no equivale a crédito.
- Riesgo mayor: el reinicio automático de RDS del 4-nov; si no se va a usar, hay que decidir con tiempo.

## 10. Evaluación por criterio (orientativa, no garantiza nota)
| Criterio | Demostrado | Falta / riesgo | Acción |
|---|---|---|---|
| 1 Evolución V1→V2 | Mediciones reales V1 vs V2 (p95 288→190 ms, CPU 39,4→20 %, 35.366 peticiones sin 5xx) | ALB/ASG V2 ya no existen: depender de capturas e historial | Cerrar con evidencias existentes |
| 2 Amenazas | Matriz de amenazas, hallazgos Trivy clasificados | Informe Trivy original no archivado; TLS verify-full solo local | Archivar artefacto de Trivy; desplegar TLS cuando autorice |
| 3 Controles | SG, cifrado, TLS 1.3, IAM de OCI, MI de Azure | `LabRole` sin permisos efectivos verificados; sin trail de CloudTrail persistente | No afirmar mínimo privilegio en AWS; P14 |
| 4 Escalabilidad/HA | Escalado, autocuración, failover RDS reales | FIS y caída de AZ no ejecutados; carga solo ≤50 usuarios | Declararlo como límite; no ejecutar sin necesidad |
| 5 Evidencias | 10 capturas AWS, CI real, 40 series CloudWatch | Capturas OCI/Azure por localizar; costos; correo de alerta | Localizar capturas; sin pruebas nuevas |

## 11. Pendientes priorizados
- **Crítico:** respaldo externo de `work/` y de la clave de recuperación; decisión sobre el reinicio de RDS del 4-nov.
- **Alto:** localizar capturas OCI/Azure; archivar artefacto Trivy del run #31 (confirma el conteo); captura de estado de costos.
- **Medio:** desplegar TLS verify-full (P11); alinear lifecycle de S3 (P12); commit/push para CI de los cambios locales (P13).
- **Bajo:** KMS para S3; instancias privadas con endpoints; cobertura de pruebas; SBOM.

## 12. Requiere su autorización
Commit/push (CI de los cambios locales); descarga del paquete de CA de RDS y ventana con RDS encendida (TLS); `terraform plan/apply` dirigido (S3, CloudTrail); cualquier ventana de Azure; cualquier lectura con sesión de AWS (permisos efectivos de `LabRole`, estado actual de EC2/RDS).


## 13. Segunda ronda (29-oct, tras aceptar AWS-0080/0164 como pendientes de revisión final)

### 13.1 Trivy del run #31: conteo exacto (artefactos descargados de GitHub, solo lectura; copiados a `docs/evidencias/ci-github-actions-20261029/artefactos-run31/`)
- **Configuración: 8 hallazgos** en 5 archivos: `aws-recovery/main.tf` (AWS-0080 HIGH, AWS-0104 CRITICAL), `aws-v2/alb.tf` (AWS-0053 HIGH), `aws-v2/network.tf` (AWS-0104 CRITICAL, AWS-0164 HIGH), `aws/network.tf` (AWS-0104 CRITICAL, AWS-0164 HIGH), `aws/storage_observability.tf` (AWS-0132 HIGH). Coincide con la lista previa; **AWS-0104 aparece 3 veces** (no una) y no se detectó nada en `infra/azure`, `infra/oci`, `infra/gcp` ni `backend/Dockerfile`.
- **Dependencias/secretos: 0** (`backend/requirements.txt` y `frontend/package-lock.json`); **imagen: 0** (Debian 12.15 y paquetes Python). Nota: Trivy escanea `requirements.txt`, mientras que el CI instala `requirements-production.lock`; conviene comprobar que ambos coinciden.
- Con los cambios locales, se esperan 5 hallazgos (8 − 3: AWS-0080 y 2 × AWS-0164; en la versión anterior de este documento escribí 6 por un error de cuenta): **esto es una expectativa, no un resultado**; solo lo confirmará un nuevo run (requiere commit/push) o Trivy local (no instalado).
- **CI #16 (fallo histórico):** falló el paso «Dependencias y secretos» del job *Trivy* (código de salida 1, bloqueo por diseño); los otros tres jobs pasaron. El log no imprime la tabla (se escribe al artefacto), por lo que **el CVE exacto no es recuperable**. Es coherente con la corrección de `cryptography` registrada en el informe, pero eso es una hipótesis, no un hecho.

### 13.2 Regresiones de AWS-0164 (revisión)
- **ASG:** usa `version = "$Latest"` y no tiene `instance_refresh`: la plantilla nueva solo afecta a instancias lanzadas después; no reemplaza las existentes. El *launch template* ya declara la interfaz con IP pública y el SG (verificado por `check_security.py`).
- **V1 y recuperación:** `aws_instance` ya tenía `associate_public_ip_address = true`; el cambio de la subred no altera esas instancias. El constructor de AMI (`scripts/cloud/v2-prepare.sh:67`) ya usa `--associate-public-ip-address`. No se encontraron otros lanzadores (`run-instances`) en scripts/Ansible.
- **Cambio en la subred:** modificación *in situ* de un atributo; no recrea la subred ni toca rutas. **Pendiente de `terraform plan` (no autorizado).**
- **Exposición:** asignar la IP de forma explícita **no elimina la exposición pública**; solo evita que otros recursos la reciban por defecto. Las instancias de V2 siguen con IP pública pero sin puertos abiertos hacia Internet (solo el SG del ALB al 80); la EC2 de V1 sí acepta 80/443 desde Internet (no hay ALB en V1). Decirlo así en el informe.
- **Diferencia código ↔ histórico:** el V2 que se midió el 22-oct se desplegó con la subred asignando IP automáticamente; el código actual lo declara en la plantilla. Es equivalente en comportamiento, pero **no es lo que estaba desplegado** y hay que decirlo si se cita el Terraform.

### 13.3 AWS-0104: mitigación parcial sin coste (análisis)
- El código de la API **no hace llamadas HTTP salientes** (no usa `requests`, `httpx`, `smtplib` ni `boto3`; solo la base de datos): la salida 443 de V2 es para el arranque (Secrets Manager) y los agentes AWS, no para la aplicación.
- Controles existentes que reducen el impacto: sin entrada desde Internet a las instancias de V2; IMDSv2 con límite de saltos 1 (V2); sin SSH; roles de base de datos separados; sin NAT ni rutas desde las subredes de datos. IAM: `LabRole` no se puede estrechar en Academy (7 políticas, 4 administradas por AWS, incluidas políticas de EKS y ECR no usadas por NexoEventos; sin límite de permisos; captura A13), así que esa vía queda **fuera de control del proyecto**.
- Sin coste no se puede acotar el destino de 443 (servicios AWS sin prefijo gestionado, repositorios y ACME/DuckDNS en V1). Mitigación viable pero **parcial**: monitoreo de conexiones salientes con VPC Flow Logs → tiene coste de ingesta; no se activa. Estado: **ABIERTO, riesgo aceptado con controles compensatorios**.

### 13.4 AWS-0053 y AWS-0132
- **AWS-0053:** el ALB es el único origen permitido en las instancias de V2 (comprobado por `check_security.py`: solo `alb_http`/`alb_https` abiertos a Internet; la instancia acepta 80 solo desde el SG del ALB; sin 22). Decisión arquitectónica justificada.
- **AWS-0132:** SSE-S3 (AES-256) **sí cifra** en reposo, gestionado por AWS. El hallazgo pide clave KMS administrada por el cliente (control de claves y auditoría de uso, con coste y permisos). Mejora opcional.

### 13.5 Capturas localizadas (rutas reales; originales intactos)
`~/Pictures/Capturas/` contiene **30 capturas PNG con nombre de proyecto**: AWS `A1, A2, A3, A4, A5, A8, A9, A13, A14`; Azure `B1, B3 (×4), B4, B5, B7, B8, B9, B10`; OCI `OCI-01…06`; GitHub `DEVOPS-01, DEVOPS-02 (×2)`. En `~/Downloads`: AWS `01, 02, 04–11` (ya incorporadas). Hay además capturas genéricas («Captura de pantalla …») de otras fechas y 3 grabaciones de pantalla que no se tocaron.
- Copias redactadas hechas hoy en `docs/evidencias/capturas/aws/`: `A1, A2, A8, A9, A13, A14` (cuenta, usuario, IDs, ARN y DNS ocultos; revisadas A1 y A14 tras el enmascarado).
- **Pendientes de copia redactada (revisar primero):** A3, A4, A5 (RDS), todas las de Azure, OCI y DEVOPS. Mi primer intento de copiar las A-series con solo la cabecera tapada **dejó visibles** ID de cuenta, ARN y DNS público en A1/A14: esas copias se borraron antes de usarlas; no entró nada en el informe.
- Lo que demuestran: A9 (CloudTrail **sin trails**: solo historial de 90 días), A8 (historial de eventos de gestión; los eventos de SSM de la instancia), A13 (LabRole con 7 políticas, sin límite de permisos), A14 (`iam:GetPolicy` denegado: los permisos efectivos no se pueden leer desde la consola de Academy), A2 (RDS detenida temporalmente).
- **ALERTA OPERATIVA:** A1 (11:18Z) muestra la **EC2 `nexoeventos-academy-app` en ejecución** y A8 muestra latidos de SSM de esa instancia cada 5 min entre 10:44 y 11:25Z del 29-oct. La EC2 arrancó al reiniciar el laboratorio. **No puedo verificar si sigue encendida** (mi sesión de AWS está caducada). Si sigue en ejecución, genera coste: conviene pararla desde la consola o autorizarme a hacerlo (con sesión activa).

### 13.6 Reconstrucción ante pérdida de Academy (revisión de dependencias críticas, sin copiar secretos)
- **Críticos y solo locales:** `work/terraform-envs/*.tfvars` (incluye correo y OCIDs), `work/terraform-state/*` (estados de OCI/Azure/AWS), `work/recovery-keys/` (clave privada de recuperación; sin ella el respaldo CMS no se descifra) y `~/.oci/` (claves API; **claves privadas en texto en el disco**). No se han copiado ni leído. **Acción segura sin coste:** copia cifrada a un soporte externo; no en el repositorio ni en la nube sin cifrar.
- **Externos al disco y verificados:** el respaldo CMS cifrado y su manifiesto están en el bucket de OCI (capturas OCI-03). El repositorio está en GitHub (`Yesrai/NexoEventos`, privado), **con 47 cambios locales sin subir**.
- **Se pierde si Academy desaparece:** RDS y sus instantáneas, EC2/AMI de V1/V2 (la AMI dorada de V2 no se conserva fuera de la cuenta), Secrets Manager, métricas de CloudWatch y el historial de CloudTrail (90 días).
- **Probado:** restauración en OCI. **No probado:** reconstrucción en un laboratorio AWS nuevo. No se declara RPO; RTO observado 32 min 42 s solo para OCI.

### 13.7 Coherencia código ↔ evidencias ↔ informe
- El informe habla de «subredes públicas (ALB/web)» y de IMDSv2 «límite de saltos 2» (V1) sin contradecir el código; **añadir una nota** de que las subredes ya no asignan IP pública por defecto (cambio local no desplegado) y que V1/V2 desplegados difieren de ese código en ese atributo.
- El informe cita 31 ejecuciones de CI y la política TLS `verify-full` como corrección **local**; sigue siendo correcto. Falta añadir los 8 hallazgos de configuración de Trivy con su estado (§13.1) a §19 del informe preliminar.

### 13.8 Qué falta realmente para aspirar al 20/20 (sin gasto)
1. **Crítico:** verificar que la EC2 no está en ejecución (coste) y la decisión sobre el reinicio automático de RDS del 4-nov.
2. **Alto:** incorporar al informe las capturas ya existentes (redactar copias de A3–A5, Azure, OCI, DEVOPS y citarlas en §§ 8, 9, 14, 16–17) y los 8 hallazgos de Trivy con estado; copia de seguridad externa de `work/` y claves.
3. **Alto:** captura/estado de costos (aún pendiente) y confirmar el crédito real.
4. **Medio:** commit/push para que el CI pruebe los cambios (requiere su autorización); TLS `verify-full` y S3 lifecycle (necesitan nube).
5. **Bajo/opcional:** KMS para S3, endpoints privados, FIS (no ejecutado).
**Siguiente tarea de mayor impacto sin gasto:** redactar las copias de las ~21 capturas restantes e integrarlas en el informe (criterios 3 y 5), porque convierten afirmaciones hoy «documentadas» en evidencia visible.


## 14. Cuarta ronda (29-oct): resiliencia, dependencias y CI
- **Cuenta corregida:** tras corregir AWS-0080 y los dos AWS-0164 quedarían **5** hallazgos (8 − 3), no 6 como escribí antes. Sigue siendo una expectativa hasta un nuevo escaneo (Trivy no está instalado y no hay un nuevo run de CI).
- **Dependencias:** `backend/requirements.txt` (10 directas) y `requirements-production.lock` (33 con transitivas) son **coherentes**: las 8 dependencias de producción de `requirements.txt` coinciden en versión con el lock; `pytest` y `httpx` son solo de pruebas y correctamente **no** están en producción. Trivy solo reconoce `requirements.txt`, de modo que el lock no se analizaba; el análisis de la **imagen** (0 vulnerabilidades) sí cubre lo instalado. **Corrección:** `.github/workflows/ci.yml` copia el lock con ese nombre a un directorio temporal y lo analiza (HIGH/CRITICAL con corrección bloquean) y publica `trivy-lock.txt`. YAML válido; todas las acciones siguen fijadas por SHA. **No validado en CI** (sin commit ni push).
- **Permisos del workflow:** `contents: read`; sin secretos ni credenciales de nube; sin despliegue: **solo CI, no CD**. Condiciones de fallo: pruebas y Trivy de vulnerabilidades/secretos bloquean; el análisis de configuración de Terraform es informativo.
- **Resiliencia de la base de datos (código):** `connect_timeout`, keepalives, `pool_recycle`, `pool_timeout` configurable; 3 pruebas nuevas; **55 pruebas de backend correctas**. Detalle y límites en `matriz-chaos-engineering.md` §2.
- **Hallazgo de diseño sin corregir:** el health check del ALB depende de PostgreSQL (`/healthz` → `/ready`); riesgo de reemplazo de instancias sanas en una caída larga de la base de datos (`matriz-chaos-engineering.md` §3); requiere AMI y despliegue.
- **Matriz de Chaos Engineering:** `docs/entregable2/matriz-chaos-engineering.md` (10 experimentos clasificados; 4 ejecutados y verificados con límites, 2 con evidencia parcial, 1 manual entre nubes; FIS y zona completa **no ejecutados**).
- **Docker:** imagen base fijada por digest, usuario no root (UID 10001), `HEALTHCHECK` sobre `/health`, secretos por entorno, dependencias del lock; sin problemas nuevos. Nota: `/health` es de vida (sin base de datos) y `/ready` es de preparación.
- **Corrección a mi resumen anterior:** el fallo de 25/275 respuestas 502 y la detección de 20,0 s son de la **primera** prueba (sin reemplazo); el reemplazo en ≈ 2,5 min es de la **segunda** (con 40 respuestas 5xx del destino): no son un único experimento.

## 15. Quinta ronda (29-oct): separación liveness/readiness
Corregido en código local el acoplamiento del health check del ALB con PostgreSQL (`/livez` → `/health` para el ALB; `/healthz` → `/ready` se conserva para monitoreo; `/health` asíncrono; errores de BD → 503 con `Retry-After`). 60 pruebas de backend, prueba de Nginx real en Docker local y comprobaciones de Terraform correctas. **Requiere AMI nueva, rotación de instancias y `apply` (en ese orden) y validación real contra un failover de RDS en V2**; si el ALB cambiara a `/livez` antes de renovar la AMI, el health check daría 200 con la API muerta. Detalle en `matriz-chaos-engineering.md` §3.

## 16. Resultado real del CI en GitHub (PR #1 en borrador, rama `entregable2-auditoria`)
- Run 1 (`1331a74`): backend y frontend correctos; **fallaron** el lockfile de producción y la imagen por vulnerabilidades nuevas con corrección (dnspython 2.8.0, CVE-2026-114605; libssl3/openssl, CVE-2026-84782). Corregidas en `37fb2c9`.
- Run 2 (`37fb2c9`): **4 de 4 jobs correctos**; backend 60 pruebas, frontend 33 pruebas; Trivy: dependencias 0, secretos 0, lockfile 0, imagen 0; configuración **7 hallazgos** (5 AWS esperados + 2 de Azure no contados antes).
- Sigue siendo **solo CI** (sin CD); nada desplegado ni aplicado en la nube.

## 17. Sexta ronda (3-nov-2026): corrección de lo corregible, sin desplegar
**Los 7 hallazgos de Trivy (CI del PR #1, artefacto `trivy-config.txt`) tras revisar el código y el informe original**
| ID | Veredicto | Qué se hizo |
|---|---|---|
| AWS-0104 ×3 | **Abierto, sin corrección gratuita segura** | Las instancias están en subred pública sin NAT y llegan a servicios AWS (Secrets Manager, SSM, CloudWatch) y, en V1/recuperación, a repositorios, DuckDNS/sslip.io y Let's Encrypt, que no tienen prefijo fijo; las listas gestionadas de AWS solo cubren S3 y DynamoDB; los endpoints de interfaz y el NAT son de pago. Controles compensatorios: sin entrada desde Internet a V2, IMDSv2, sin SSH, salida solo 443/DNS/5432. |
| AWS-0053 | **Decisión justificada** | El ALB es el único punto de entrada de V2; `check_security.py` exige que solo `alb_http`/`alb_https` estén abiertos a Internet y que las instancias solo acepten el puerto 80 desde el SG del ALB. |
| AWS-0132 | **Abierto, mejora opcional** | SSE-S3 (AES-256) **sí cifra** en reposo. La clave KMS administrada por AWS (`aws/s3`) no satisface la regla (pide clave del cliente), y una clave del cliente cuesta ≈ 1 USD/mes más solicitudes y permisos que Academy puede denegar: no se exige. |
| AZU-0051 ×2 | **Parcialmente corregido en código** | La regla `allow-dns-ntp-out` (protocolo `*`, puertos 53 y 123 a Internet) pasa a `allow-ntp-out` (**solo UDP/123**): el DNS de la VM sale por el resolvedor de Azure `168.63.129.16`, ya permitido por la regla 100, de modo que abrir el 53 a Internet sobraba. **No reduce el conteo de Trivy** (la regla sigue existiendo) pero cierra un canal innecesario. La regla de 80/443 a Internet se mantiene (apt, repositorios de Zabbix y Grafana, sondas). **No verificado en la VM** (está desasignada): antes de aplicar, comprobar en la próxima ventana autorizada con `resolvectl status` que el DNS apunta a `168.63.129.16`; el NSG desplegado hoy aún tiene la regla antigua. |
Ningún hallazgo se ocultó ni se ignoró; `.trivyignore` sigue vacío.

**Secuencia de despliegue del health check (riesgo del orden AMI → ASG → ALB), ahora protegida en el código**
- Nueva variable `ami_includes_livez` (por defecto **false**) en `infra/aws-v2`: con `false` el ALB usa `/healthz` (existe en todas las AMI); con `true`, `/livez`. Una AMI antigua con `/livez` devolvería 200 desde `index.html` aunque la API estuviera muerta (falsa salud); así ya no puede ocurrir por descuido. Orden: (1) reconstruir la AMI, (2) rotar instancias, (3) poner `ami_includes_livez = true`, `plan` y `apply` autorizados. **Estado real: sin esa secuencia, el comportamiento acoplado a PostgreSQL sigue vigente.**
- Pruebas nuevas (backend, 62 en total): agotamiento del pool → 503 con `Retry-After` y `/health` sigue 200; el valor por defecto de `ami_includes_livez` es `false`.

**PostgreSQL y almacenamiento**
- TLS `verify-full`: `scripts/test-db-tls-verification.sh` vuelve a dar 5/5 (require conecta sin validar; verify-full conecta solo con la CA correcta y rechaza otra CA, otro nombre y sin TLS). **No probado contra RDS real** (apagada) y falta distribuir el paquete de CA (`deploy/install-rds-ca-bundle.sh`, no ejecutado).
- S3 lifecycle: el código usa `backups/database/` en Terraform, scripts y evidencias; la regla desplegada en la cuenta filtra `database-backups/` (deriva conocida, propuesta `0003`); sin cambios en la nube.
- **Aviso «Storage size 20 GiB is approaching the maximum storage threshold 20 GiB» (28-oct 16:45 UTC−5; ya había aparecido el 22-oct):** es un **aviso de configuración**: el autoescalado está «Habilitado» con umbral máximo igual al almacenamiento asignado (20 GiB), de modo que RDS no puede crecer. **No hay evidencia de poco espacio libre, pero tampoco una medición**: `FreeStorageSpace` no está en las 40 series exportadas. Se puede leer sin iniciar la RDS (CloudWatch conserva la métrica de la ventana del 28-oct) con una sesión de solo lectura. Indicios indirectos, no concluyentes: el volcado cifrado pesa 89,9 KiB y la base tiene del orden de decenas de eventos y ≈ 135 reservas.
- Nueva captura de eventos de RDS (`aws/A16`): confirma la detención del 28-oct a las 16:51 (UTC−5) y que **no hay eventos posteriores** en la primera página; no prueba el estado actual. Aparece además el evento «The RDS Multi-AZ primary instance is busy and unresponsive» a las 16:39 junto con la activación Multi-AZ al iniciar: no se interpreta sin más datos. La reactivación automática por 7 días caería el **4-nov a las 16:51 (UTC−5)**.

**IAM y CloudTrail**
- `LabRole` (captura A13: 7 políticas, 4 administradas por AWS —incluidas EKS/ECR que no usamos— y 3 del laboratorio, sin límite de permisos; A14: `iam:GetPolicy` denegado). Academy impone el rol: **no se puede estrechar desde Terraform** ni leer el detalle de las políticas. Limitación no corregible; se documenta, no se afirma mínimo privilegio en AWS.
- Auditoría: solo existe el «Historial de eventos» de 90 días (A8/A9). Se añadió `infra/aws/cloudtrail.tf` **desactivado por defecto** (`enable_cloudtrail = false`): trail de eventos de gestión con validación de integridad y bucket S3 privado, cifrado AES-256, bloqueo de acceso público, política solo-TLS y caducidad de 90 días. Coste esperado: el primer trail de gestión es gratuito; solo almacenamiento S3 (centavos). `terraform validate` correcto; **no aplicado**: requiere comprobar que `cloudtrail:CreateTrail` esté permitido por Academy.
