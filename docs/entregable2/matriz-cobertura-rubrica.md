# Matriz de cobertura de la rúbrica — 18 puntos (29-oct-2026)

Criterios: **C1** Evolución V1→V2 (§2–6) · **C2** Amenazas (§8, 19) · **C3** Controles de seguridad (§7, 9, 10, 14) · **C4** Escalabilidad/HA/fallos (§11–13, 15) · **C5** Evidencias, pruebas y documentación (§16–18, 20).
Estados: **COMPLETO** · **EVIDENCIA PENDIENTE** (existe el hecho, falta la captura/documento) · **PRUEBA PENDIENTE** (falta ejecutar algo) · **NO APLICA JUSTIFICADO**.
Rutas relativas a `docs/`. «Cap.» = `evidencias/capturas/aws/`.

| # | Punto | Criterio | Implementado realmente | Prueba ejecutada | Evidencia (dónde) | Falta | Limitaciones a declarar | Estado |
|---|---|---|---|---|---|---|---|---|
| 1 | Arquitectura V1/V2 y mejoras | C1 | V1 (EC2+RDS Single-AZ); V2 (ALB+ASG 2–3 EC2 en 2 zonas+RDS Multi-AZ), `infra/aws`, `infra/aws-v2` | V1 vs V2 hasta 50 usuarios; validación V2 15/15 | `entregable2/informe-entregable2.md` §3,5,6; `entregable2/diagramas/`; `evidencias/medicion-v2-20261022/`; `evidencias/validacion-v2-20261022/` | Captura de la EC2 de V1 en consola (opcional, A1) | V2 **destruida**: no hay consola viva de ALB/ASG; se documenta con métricas históricas y Terraform | **COMPLETO** (capturas vivas de V2: NO APLICA JUSTIFICADO) |
| 2 | Amenazas, vulnerabilidades | C2 | Matriz de amenazas §8; Trivy en CI; `cryptography` corregida; Argon2/CSRF/roles | Pruebas automáticas 44/44; Trivy; ráfaga de login local (antes/después) | Informe §8, §19; `PROJECT_STATUS.md` §18, §22 | Límite de intentos y ráfaga **contra AWS** | Sin pruebas de intrusión; ráfaga solo en local | **COMPLETO** (análisis) · **PRUEBA PENDIENTE** opcional (ráfaga en AWS) |
| 3 | IAM, mínimo privilegio | C3 | PostgreSQL con 3 roles; OCI solo-subida; Azure *Monitoring Reader*; AWS: `LabRole` impuesto por Academy | Lectura por API: 0 usuarios/grupos, 7 políticas, 4 legibles sin `Action:*`; Azure escritura → 403 | `evidencias/multicloud/aws/20261028-auditoria-solo-lectura/detalle-seguridad.json`; `…/azure/20261028-vm/identidad-administrada.txt`; `…/oci/20261023-iam-carga/` | **Permisos efectivos de LabRole**: `VocLabPolicy1–3` ilegibles → intentar `iam simulate-principal-policy` (solo lectura) con sesión; captura A13 | Mínimo privilegio **propio** en AWS = diseño no implementado; no se afirma qué permite LabRole | **EVIDENCIA PENDIENTE** |
| 4 | Redes | C3 | VPC 10.20.0.0/16; subred pública; 2 subredes de datos sin ruta a Internet; SG web/base | Lectura por API; capturas SG | Cap. `04`, `05`; `…/20261028-auditoria-solo-lectura/red-y-cloudtrail.json` | (Opcional A4: tablas de rutas) | `pública-b` y SG de V2 ya no existen; web con IP pública en V1; destino del 5432 oculto en captura (se apoya en API) | **COMPLETO** |
| 5 | Cifrado en tránsito/reposo | C3 | Reposo: RDS, EBS, S3 AES256, CMS AES-256; tránsito: TLS 1.3 en Azure medido; `rds.force_ssl=1` | Lectura por API; TLS 1.3/HSTS en Azure | Cap. `01`, `02`; `detalle-seguridad.json`; `…/azure/20261028-vm/acceso-https-y-puertos.txt` | Despliegue de `verify-full` (autorización) | Las URL desplegadas usan `sslmode=require` (cifra sin validar CA); **verify-full implementado y probado en local, no desplegado** (`evidencias/tls-rds-verificacion-local-20261029/`); TLS del ALB es diseño (V2 destruida) | **COMPLETO** (cifrado) · mejora **PRUEBA PENDIENTE** de despliegue |
| 6 | CloudTrail | C3 | **No hay trail** | `lookup-events` responde (historial 90 días) | `red-y-cloudtrail.json` | Captura A8 (Historial y Trails vacío) | Event History ≠ trail persistente; riesgo declarado | **EVIDENCIA PENDIENTE** |
| 7 | CloudWatch: métricas, logs, alertas | C3, C5 | 1 alarma de CPU (0 acciones), 0 paneles, logs API/Nginx 7 días | Recepción real de logs (EV08); exportación de 40 series | `evidencias/multicloud/aws/20261028-cloudwatch/`; `evidencias/EV08/`; Cap. `06`–`09` | (Opcional A9: alarma) | Alarma sin notificación; EC2 solo a 300 s; sin memoria de EC2 | **COMPLETO** |
| 8 | Respaldos | C4, C5 | RDS 7 días, 4 manuales + 9 automáticos, CMS en S3 y OCI | R01 (21 min 4 s, RPO 3 min 32 s); CMS con hash; recuperación completa en OCI | `evidencias/EV07/`; `…/oci/20261023-*`; `…/aws/20261023-respaldo-0008/` | Captura de snapshots (opcional A6); (ya confirmada la deriva del ciclo de vida de S3; la propuesta 0003 no está aplicada) | **No hay respaldo programado**; el Terraform local declara `backups/database/` pero la cuenta tiene la regla sobre `database-backups/` (deriva **confirmada**: los volcados no expiran hoy); recuperación completa **en AWS** no acreditada | **COMPLETO** para lo probado · **PRUEBA PENDIENTE** (AWS completa, programado) |
| 9 | ALB: salud y 5xx | C4 | ALB con health check; TG `/healthz` | Pruebas de fallo (20,0 s) | Cap. `07`, `08`, `09`; `evidencias/tolerancia-fallos-v2-20261022*/` | — | La gráfica no prueba recuperación por sí sola; UnHealthy no aparece en la repetición de 16:38 (sin explicar) | **COMPLETO** |
| 10 | Auto Scaling | C4 | Política CPU objetivo 40 %, 2–3 instancias | Escalado 2→3→2 (alarma a 8 min 6 s) | Cap. `06`; `evidencias/escalado-v2-20261022/`; `…/20261028-cloudwatch/` | — | No se asocia a nº de usuarios; escalado reactivo ≈ 9 min; consola viva de políticas: NO APLICA (destruida) | **COMPLETO** |
| 11 | RDS Multi-AZ y failover | C4 | `multi_az=true` | Failover forzado: ≈ 14 s, huella idéntica | Cap. `01`, `10`, `11`; `…/20261023-rds-multiaz/failover/` | — | Una ejecución, sin carga de escritura; no es pérdida de zona; hora local UTC−5 (22-oct 20:08 = 23-oct 01:08Z) | **COMPLETO** |
| 12 | Chaos Engineering | C4 | Fallos controlados A–D | A (proceso), B, C, D ejecutados | `entregable2/plan-caos-fis.md`; resultados de tolerancia a fallos | E (caída de AZ) y F (FIS): **no ejecutados** | No se afirma AZ ni FIS; FIS probablemente no disponible en Academy | A–D **COMPLETO** · E/F **PRUEBA PENDIENTE** (opcional; requiere autorización y redespliegue) |
| 13 | DevOps | C5 | Git, Terraform (6 raíces), Ansible, Dockerfile, CI (pytest, Vitest, Docker+Trivy), 29 comprobaciones de IaC | Pruebas locales 44/44 y 33/33; `terraform validate` OK; CI **definido** | `.github/workflows/ci.yml`; `scripts/multicloud/check-iac-security.py` | (Opcional) captura de la pestaña Actions | **Sin CD**; despliegues manuales; el CI no usa credenciales de nube ni valida Terraform; cambios locales sin ejecutar en CI | **COMPLETO**: 31 ejecuciones reales, 30 exitosas (`evidencias/ci-github-actions-20261029/`) |
| 14 | Azure: Monitor, alertas, Zabbix, Grafana | C3, C5 | VM con Zabbix+Grafana; 3 alertas; grupo de acción | Alerta de CPU disparada y resuelta (17 min 54 s); Zabbix detectó V1 apagado y CPU | `evidencias/multicloud/azure/20261028-vm/` | Capturas B3 (alertas), B4 (grupo de acción, correo oculto), B1 (VM *Deallocated*); **paneles Grafana/Zabbix: requieren encender la VM** | **Entrega real de correo NO demostrada** (la verificación del receptor es otro hecho; la prueba de notificación devolvió «Free subscription not supported»); memoria/disponibilidad nunca disparadas | **EVIDENCIA PENDIENTE** (B1, B3, B4) · **PRUEBA PENDIENTE** (paneles, correo; requiere autorización) |
| 15 | OCI | C3, C4 | Bucket privado versionado, CMS con clave independiente, IAM solo-subida, VM temporal destruida | Recuperación completa 32 min 42 s, 14/14, huella 10/10 | `evidencias/multicloud/oci/20261023-*` | Capturas C1 (bucket/objetos), C2 (política IAM); requiere iniciar sesión en OCI | Acceso por Bastion sin DNS público; sin expiración definida en el bucket | **EVIDENCIA PENDIENTE** |
| 16 | Pruebas funcionales, carga, seguridad, disponibilidad, integridad | C5 | — | Funcional 37/37 y 15/15; carga ≤ 50 usuarios; integridad (12 sobre 4 cupos, etc.); disponibilidad A–D | Informe §16 y §16.1 | Carga ≥ 100 usuarios; ráfaga en AWS | ≥ 100 usuarios = **proyección** | **COMPLETO** para lo medido · **PRUEBA PENDIENTE** (carga >50, requiere V2 viva) |
| 17 | Costes y estado de recursos | C5 | Recursos apagados entre ventanas | Ciclo start-stop de RDS (28-oct ≈16 min) | `…/20261028-rds-ciclo-start-stop/`; informe §18 | **Estado actual** de EC2/RDS/VM (sesión CLI caducada): capturas EC2, RDS y Azure B1; saldo del crédito de Academy | Sin Cost Explorer: costes facturados **no verificados**; RDS se reinicia sola ≈ 4-nov | **EVIDENCIA PENDIENTE** |
| 18 | Documentación de los 5 criterios | C1–C5 | Informe de 20 secciones, matriz, Word/PDF, presentación | Verificador TODO CORRECTO; 0 enlaces rotos | `entregable2/` | Portada, retroalimentación docente literal (§04), capturas anotadas | Marcadores `[PENDIENTE]` visibles | **EVIDENCIA PENDIENTE** |

## Hallazgos nuevos de esta revisión
1. **Deriva IaC ↔ cuenta (S3), confirmada y ya documentada desde el 7-oct:** la cuenta filtra `database-backups/`; los respaldos reales y el Terraform local usan `backups/database/`. Corregir exige `terraform apply` (autorización).
2. **TLS a RDS:** las URL desplegadas usan `sslmode=require` (cifra sin validar). Implementado y probado en local `verify-full` + política en la aplicación; sin desplegar.
3. **CI:** corrección de una afirmación anterior: **sí hay ejecuciones reales** (31; 30 exitosas).

## INVENTARIO DEFINITIVO de faltantes (sin duplicados, por prioridad de rúbrica)
### Capturas manuales (no encienden nada)
| Prio | ID | Captura | Criterio | Ruta | Debe verse |
|---|---|---|---|---|---|
| 1 | A8 | CloudTrail | C3 | CloudTrail → Historial de eventos y Trails | Eventos recientes; Trails vacío |
| 2 | A1 | EC2 de V1 | C3, C5 | EC2 → Instancias → `nexoeventos-academy-app` | `Stopped`, IMDSv2 requerido, rol, SG |
| 3 | B3 | Alerta de Azure | C3, C5 | Monitor → Alertas → Todas | `alerta-vm-cpu` disparada y resuelta (28-oct) |
| 4 | B4 | Grupo de acción | C3 | Monitor → Grupos de acción → `ag-nexoeventos-obs` | Receptor (correo oculto) habilitado |
| 5 | B1 | VM de Azure | C5 | Grupo de recursos → VM | `Deallocated` |
| 6 | C1 | Bucket de OCI | C3, C4 | Almacenamiento → Buckets → `nexoeventos-recovery` | Privado, versionado, objetos `.cms` |
| 7 | C2 | Política IAM de OCI | C3 | Identidad → Políticas | Permisos solo-subida |
| 9 | R | Estado de costes | C5 | EC2 e RDS (lista); portal de Academy (crédito) | `Stopped` y saldo |
| 10 | A13 | `LabRole` (si Academy lo permite) | C3 | IAM → Roles → LabRole → Permisos | Políticas o «acceso denegado» |
| Opc. | A4, A6, A9 | Rutas, snapshots, alarma | C3, C4 | VPC / RDS / CloudWatch | Sin ruta 0.0.0.0/0 en datos; snapshots; alarma sin acciones |

### Verificaciones de solo lectura pendientes (necesitan sesión de AWS; sin cargos)
1. `iam simulate-principal-policy` para permisos efectivos de `LabRole` (puede ser denegado).
2. `terraform plan` solo-lectura de `infra/aws` para confirmar o descartar la deriva de S3.

### Pruebas que requieren autorización (ninguna indispensable para 4/4 si se declaran)
| Prueba | Requisito | Coste/riesgo | Recomendación |
|---|---|---|---|
| Paneles de Grafana/Zabbix y entrega real de correo de alerta (VM de Azure encendida ≈ 0,11 USD/h, ≈ 1–2 h) | C3/C5 (monitoreo) | Bajo | **Recomendada** si hay tiempo |
| Carga ≥ 100 usuarios, caída de AZ, FIS (redesplegar V2) | C4 | ≈ 0,5 USD, interrupción breve | No recomendada: declarar como proyección / no ejecutado |
| Recuperación completa en AWS (DNS + HTTPS) | C4 | Medio | Declarar como no acreditada |
| Respaldo programado | C4 | Cambia infraestructura | Declarar como mejora futura |

## Actualización 29-oct (segunda ronda; detalle en `auditoria-integral-20261029.md` §13)
| Requisito | Estado | Cambio |
|---|---|---|
| Trivy: hallazgos de configuración | VERIFICADO (conteo) / IMPLEMENTADO SIN VERIFICACIÓN COMPLETA (correcciones) | 8 hallazgos confirmados en el artefacto del run #31; AWS-0080 y AWS-0164 (×2) corregidos solo en código local, sin re-escaneo; AWS-0104 (×3), AWS-0053, AWS-0132 abiertos con justificación |
| CI histórico #16 | VERIFICADO | Falló el paso Trivy de dependencias/secretos (bloqueo por diseño); CVE exacto no recuperable |
| CloudTrail | VERIFICADO (sin trail persistente) | Capturas A8/A9: solo historial de 90 días |
| IAM `LabRole` | IMPLEMENTADO SIN VERIFICACIÓN COMPLETA | A13: 7 políticas (incluye EKS/ECR no usadas), sin límite; A14: permisos efectivos no legibles. No se afirma mínimo privilegio |
| Capturas OCI/Azure/DEVOPS | EVIDENCIA LOCALIZADA, copia redactada PENDIENTE | 30 capturas en `~/Pictures/Capturas/` |
| Costos | PENDIENTE | EC2 de V1 observada en ejecución el 29-oct; verificar |

## Actualización 29-oct (tercera ronda: capturas redactadas e incorporadas al informe §17 «Mejora 08» y §19)
| Requisito (rúbrica) | Estado | Evidencia nueva | Límite que se mantiene |
|---|---|---|---|
| C3 Cifrado y redes (RDS, Multi-AZ) | VERIFICADO | `aws/A3`, `A5` | Estado de consola |
| C4/C5 Respaldos | VERIFICADO (existen) / PRUEBA PENDIENTE (restauración AWS) | `aws/A4`, `A5` (10 instantáneas; retención 7 d) | No hay restauración ejecutada en AWS; última hora restaurable 22-oct |
| C3 Monitoreo (Azure) | VERIFICADO (alerta y grupo desencadenados) / EVIDENCIA PENDIENTE (correo) | `azure/B3`, `B5`, `B7`–`B10` | Entrega del correo **no** demostrada |
| C3 IAM/OCI | VERIFICADO (política y bucket) | `oci/OCI-01…06` | Permisos de objeto truncados en OCI-06; otras políticas no mostradas |
| C4 Recuperación entre nubes | VERIFICADO | `oci/OCI-03` (manifiesto + `.oci.cms`) | Procedimiento y RTO en registros originales |
| C5 DevSecOps | VERIFICADO (CI) | `github/DEVOPS-01…03` + artefactos Trivy | Solo CI, sin CD |
| Costos (control) | VERIFICADO (EC2 detenida 29-oct) / PENDIENTE (crédito restante) | `aws/A15`, `azure/B1` | Gasto real y crédito no confirmados |
| Trivy: 8 hallazgos | Ver informe §19 | artefactos run #31 | 5 abiertos/decisión, 3 corregidos solo en local |

## Actualización 29-oct (CI real)
| Requisito | Estado | Evidencia |
|---|---|---|
| CI de los cambios locales | VERIFICADO | PR #1, run del commit `37fb2c9`: 4/4 jobs correctos, 60 + 33 pruebas |
| Trivy: dependencias, lockfile, imagen, secretos | VERIFICADO (0 hallazgos) | artefactos del run; 2 vulnerabilidades nuevas halladas y corregidas |
| Trivy: configuración | VERIFICADO (7: 5 AWS + 2 Azure) | AWS-0080 y AWS-0164 ya no aparecen; AWS-0104 ×3, AWS-0053, AWS-0132 y AZU-0051 ×2 abiertos con justificación |
| Health check liveness/readiness | IMPLEMENTADO SIN VERIFICACIÓN COMPLETA | probado en CI/local; **no validado en AWS** |

## Actualización 3-nov
| Requisito | Estado | Nota |
|---|---|---|
| Orden AMI → ASG → ALB del health check | IMPLEMENTADO SIN VERIFICACIÓN COMPLETA | `ami_includes_livez` (false por defecto) evita la falsa salud; no desplegado |
| Resiliencia ante pool agotado | VERIFICADO (prueba local) | 503 + `Retry-After`; `/health` sigue 200 |
| CloudTrail persistente | DOCUMENTADO SIN IMPLEMENTACIÓN (código opcional, desactivado) | `infra/aws/cloudtrail.tf`; no aplicado; Academy puede denegarlo |
| Aviso de almacenamiento RDS | VERIFICADO como aviso de configuración / medición de espacio libre PENDIENTE | captura A16; `FreeStorageSpace` sin exportar |
| AZU-0051 | Reducción local (solo NTP UDP/123), sin verificar en la VM ni aplicar | 2 hallazgos siguen en Trivy |
