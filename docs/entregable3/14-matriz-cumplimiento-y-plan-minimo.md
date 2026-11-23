# Entregable 3 · Matriz de cumplimiento de la rúbrica y plan mínimo — 11-nov-2026

> ## ⚠ FECHAS CLAVE
> - **RDS se reinicia sola hacia el 2026-11-18 ~16:52 UTC** (detenida el 11-nov 16:52:03 UTC; ≈ 0,04 USD/h si queda encendida). Recordatorio: `recordatorio-rds-20261116.md`.
> - **AWS Academy expira ≈ 2026-11-26** (crédito estimado ≈ 27 USD; sin Cost Explorer). Al expirar se pierden S3, instantáneas de RDS, AMI y secretos de AWS; lo que sobrevive es lo que está en OCI y en el equipo local.
> - Fecha de entrega del E3: **no confirmada** (pendiente de tu confirmación).

> **ACTUALIZACIÓN 11-nov (cierre de etapa):** desde esta matriz se implementaron y probaron **localmente** B-17, B-10, B-11, B-12 y B-13 y se prepararon (sin ejecutar) la autoprueba del lease, el cambio de DNS y el simulacro (informes 19 y 20). **Esto no cambia el estado de los criterios 6 y 10 en la nube: el failover AWS–OCI NO está validado.** También se corrigió la afirmación sobre `verify-full` (criterio 5). Para el estado vigente de cada tarea ver 19 §9.

**Alcance: solo análisis y documentación local.** No se encendió AWS, no se creó nada en OCI, Azure intacto, laboratorio Docker `nexo-repl-lab` sin tocar, sin commits ni push.

## 1. La rúbrica
**Documento original localizado:** `~/Downloads/rúbrica proyecto_qod3szrctm (1).xlsx` (hoja «Rúbrica», idéntica a la copia sin «(1)»). **14 criterios, 20 puntos**, 4 niveles (Excelente / Bueno / En proceso / Deficiente) y un peso por criterio escrito en la propia hoja. El archivo **no nombra «Entregable 3»**; tú confirmaste que es la del E3. No hay otro enunciado: no invento requisitos. Las metas «RTO ≤ 10 s, RPO ≈ 0, cuatro nubes» son del equipo, **no** de la rúbrica (ésta solo exige integración real AWS–OCI en el criterio 10).

## 2. Cuatro cosas que no deben confundirse (para el informe y la defensa)
| Capa | Qué existe realmente | Dónde se probó | Qué NO demuestra |
|---|---|---|---|
| **A. Respaldo AWS–OCI** | `pg_dump` cifrado (CMS) en AWS, re-cifrado con clave independiente de OCI, subido a `nexoeventos-recovery` sin sobrescritura, verificado por SHA-256 en cada salto. 23-oct y **11-nov**. | AWS real + OCI real | Que sea continuo (es puntual) ni que el RPO sea bajo |
| **B. Restauración local** | El respaldo del 11-nov se descifró con la clave privada de OCI y se restauró en PostgreSQL 18 **en Docker local** (8–9 s), huella 10/10 idéntica. | Estación local (Docker) | Una restauración en OCI ni el RTO de producción |
| **C. Despliegue en OCI** | **El 23-oct** se restauró el respaldo de entonces y se **desplegó la aplicación en una VM temporal E5.Flex de OCI** (smoke test, recuperación completa 32 min 42 s, 14/14, huella 10/10); VM y Bastion destruidos (≈ 0,06 USD de lista). Con el respaldo del 11-nov **no** se repitió. | OCI real (23-oct) | Que el respaldo nuevo se restaure en OCI; tráfico real, DNS público ni dominio |
| **D. Failover multicloud** | **No existe en producción.** Hay diseño (informes 05–07) y simulaciones **solo en Docker** (testigo con lease, compuerta que falla cerrada, replicación lógica, fencing). | Laboratorio Docker local | Cualquier conmutación AWS↔OCI real, RTO/RPO entre nubes o fencing de RDS |
Nota de corrección: el informe 07 decía «app en OCI: diseñado»; la evidencia del 23-oct (`docs/evidencias/multicloud/oci/20261023-recuperacion-aplicacion/`) muestra que sí se ejecutó una vez.

## 3. Matriz de cumplimiento (estado = mi valoración con la evidencia del repositorio; **no** es la nota del profesor)
Pesos de la rúbrica entre paréntesis. Costo = costo adicional de cerrar lo que falta.
| # | Criterio (peso) | Evidencia existente | Estado | Falta demostrar | Costo |
|---|---|---|---|---|---|
| 1 | Análisis del problema y requisitos (1,0) | Informes E1/E2; `00`, `01`; matriz de amenazas | **Cumplido** | Añadir requisitos de continuidad (RTO/RPO medidos, no metas) | 0 |
| 2 | Arquitectura cloud (2,0) | V1/V2 (`infra/aws*`, diagramas E2); `07` (diseño AWS–OCI) | **Parcial** | Diagrama E3 con las 4 capas del §2 (qué es real y qué es diseño) | 0 |
| 3 | Redes VPC/VCN (2,0) | VPC AWS (subredes públicas/privadas, SG), VCN OCI privada + Service Gateway + NSG, Azure | **Parcial** | Declarar que la integración AWS–OCI es por almacenamiento cifrado HTTPS, **no** por red privada; sin IGW en OCI | 0 (doc); IGW de OCI gratis solo si se hace O2 |
| 4 | Cómputo, almacenamiento y BD (1,5) | RDS Multi-AZ (hoy detenida), EC2, S3 SSE, bucket OCI privado versionado, VM OCI temporal 23-oct | **Cumplido** | Documentar el estado actual apagado y cómo se reconstruye (`10` §6) | 0 |
| 5 | Seguridad cloud (2,5) | Cifrado CMS con dos claves independientes; OCI sin sobrescribir ni borrar (prueba negativa 11-nov); rol mínimo en OCI; `rds.force_ssl`; auditorías de solo lectura; Azure Monitoring Reader | **Parcial alto** | Sin trail de CloudTrail (solo Event History); `verify-full` demostrado en V2 el 4-nov (TLS 1.3; con otra CA se rechaza; evidencia `docs/evidencias/20261104-fase-c-d-v2/resultado.md`), estado de V1 sin verificar; capturas A8/A1/B4 | 0 (capturas manuales) |
| 6 | Alta disponibilidad y escalabilidad (1,5) | ALB+ASG 2–3 instancias+RDS Multi-AZ probados el 20–23-oct (escalado 2→3→2, failover Multi-AZ ≈ 14 s, fallos A–D) | **Parcial** | HA solo dentro de AWS; **el ALB está eliminado** (evidencia histórica); sin HA entre nubes (capa D = diseño) | 0 (doc); O2 si se quiere demostrar |
| 7 | Monitoreo y observabilidad (1,0) | CloudWatch (alarmas V2, ya borradas por el ahorro), Zabbix/Grafana en Azure, alertas de Azure disparadas y resueltas | **Parcial** | Capturas B3/B4/A9; aclarar que parte del monitoreo AWS se retiró por costo | 0 |
| 8 | Infrastructure as Code (1,5) | Terraform 6 raíces, destroy dirigido con plan guardado (11-nov), 29 comprobaciones IaC, Ansible | **Cumplido** | Mostrar reconstrucción del ALB (plan = 8 altas) sin ejecutarla | 0 |
| 9 | Backup, RTO/RPO y recuperación (1,5) | RDS 7 días + 5 manuales; CMS en S3 y OCI; recuperación en OCI 23-oct medida (32 m 42 s, 14/14); restauración local 11-nov (8–9 s) | **Cumplido con límites** | RPO real = intervalo manual; no hay respaldo programado; el respaldo nuevo no se restauró en VM de OCI | 0 (doc) / O1 |
| 10 | Arquitectura AWS–OCI / multicloud (1,5) | Integración real, segura y verificable: respaldo AWS→OCI, claves independientes, restauración. Despliegue en OCI (23-oct) | **Parcial (integración funcional limitada)** | Integración «viva» (réplica, failover) **no existe**; no presentar Docker como tal | 0 (honestidad) / O1–O2 |
| 11 | Costos y optimización (0,5) | Tarifas públicas, estimaciones; ahorros reales: ALB eliminado (−0,04 USD/h) y RDS detenida (−0,035 USD/h); ventana de respaldo ≈ 0,02 USD | **Parcial** | Tabla consolidada con consumo real (saldo del panel de Academy, captura manual), proyección al 26-nov (≈ 6–10 USD) y propuestas | 0 |
| 12 | Pruebas técnicas (1,0) | Funcionales 37/37 y 15/15, HA/escalado, fallos, 9/9 + 16/16 + 7 negativos del pipeline, restauración, seguridad (sobrescritura denegada) | **Parcial** | Matriz única de pruebas con enlaces; conectividad AWS↔OCI (HTTPS) y monitoreo con evidencia | 0 |
| 13 | Documentación técnica (0,5) | 14 informes E3 + E2 completo | **Parcial** | **Informe E3 consolidado** con diagramas legibles e índice de evidencias (hoy hay informes sueltos) | 0 |
| 14 | Sustentación y defensa (0,5) | Guion E2 (desactualizado) | **Pendiente** | Guion E3 y ensayo; demostración local reproducible (verificación + restauración Docker ≈ 10 s) | 0 |
Resumen: **cumplidos 3 (1, 4, 8)**, **cumplido con límites 1 (9)**, **parciales 9**, **pendiente 1 (14)**. El mayor peso sin cerrar: 5 (2,5), 2 (2,0), 3 (2,0), 6 y 10 (1,5 c/u).

## 4. Camino mínimo (prioridad por peso/costo; todo lo imprescindible es gratis)
### Imprescindible para la rúbrica (costo cloud 0)
1. **Informe E3 consolidado + diagramas** (crit. 13, 2, 3, 1): estructura honesta A/B/C/D del §2; red por proveedor; flujo de respaldo; RTO/RPO **medidos** (24 s / 32 m 42 s / 8–9 s) y límites.
2. **Matriz única de pruebas y evidencias** (crit. 12, 9): una tabla con enlace a cada archivo de `evidencias/`, incluidos los fallos corregidos (transparencia).
3. **Costos reales** (crit. 11): captura manual del saldo en la consola de Academy, consumo real, ahorros, proyección al 26-nov y propuestas de optimización.
4. **Guion de defensa y demo local** (crit. 14): verificación SHA-256 + restauración Docker en vivo (≈ 10 s), lectura del estado de RDS/OCI sin encender nada; ensayo con preguntas probables (por qué no síncrona entre nubes, qué es y no es failover).
5. **Cierre de seguridad con capturas** (crit. 5, 7): CloudTrail (Historial/Trails), EC2 V1, alertas y grupo de acción de Azure, bucket e IAM de OCI. Las de AWS exigen abrir el laboratorio (puede reencender EC2 V1 ≈ 0,03 USD/h): agruparlas en **una sola ventana**.
6. **Preservar evidencias** (ver §5): copia cifrada de `work/` y, cuando lo autorices, commits locales.
### Opcional (mejora de nota; cada uno requiere tu autorización aparte)
- **O1 · Restaurar el respaldo del 11-nov en una VM temporal de OCI** (crit. 4, 9, 10, 12): `E5.Flex` 1 OCPU/8 GB ≈ 0,05 USD/h × ≈ 1–1,5 h ≈ **0,05–0,10 USD de crédito de OCI** (de pago con el Free Trial; A1 sin capacidad el 23-oct); no usa AWS. **No se crea sin tu autorización explícita.** Requiere Terraform de `infra/oci`, Bastion, RPM verificados.
- **O2 · Conmutación controlada real AWS→OCI** (crit. 6, 10): exige O1 + entrada pública en OCI (IGW gratis) + DuckDNS + V1 encendida ≈ 1 h (≈ 0,07 USD/h AWS). Costo total ≈ 0,2–0,3 USD; **riesgo alto y es lo único que cambiaría la capa D de diseño a prueba**. Solo después de 1–5.
- **O3 · Medir 2–3 respaldos seguidos en una ventana** (crit. 9): RPO/tiempo de transferencia reales ≈ 0,03 USD/ventana.
- **No recomendado:** GCP/cuarta nube (la rúbrica no la exige), replicación síncrona entre nubes, CloudTrail de pago.
### Calendario sugerido
11–14 nov: puntos 1–4 y 6 (sin nube). 15–17 nov: **una** ventana AWS corta (capturas del punto 5 + O3, y O1 si lo autorizas) y **volver a detener RDS/EC2** (fija nueva fecha de reinicio). 18-nov 16:52 UTC: límite de RDS. 19–25 nov: ensayo de defensa. 26-nov: expira Academy.

## 5. Git y evidencias (inventario; **no se hizo commit ni push**)
Rama `entregable2-auditoria`; 19 rutas con cambios (594 archivos en `docs/entregable3/evidencias/`, 38 en `scripts/repl-lab/`).
| Grupo | Archivos | Recomendación |
|---|---|---|
| Conservar y versionar | `docs/entregable3/*.md` (14 + recordatorio); `docs/entregable3/evidencias/` (≈ 7 MB; incluye manifiesto SHA-256 y 2 tarballs del laboratorio de ≈ 62 y 98 KB); `scripts/repl-lab/`, `scripts/failover-lab/` (≈ 0,4 MB); `scripts/multicloud/{viabilidad-readonly-*,aws-planificacion-solo-lectura,auditar-solo-lectura*}`; `scripts/cloud/{db-backup-cms.py (M),test_db_backup_cms.py}`; `docs/evidencias/multicloud/aws/20261111-respaldo-rds/*.json` (huellas md5, sin datos personales) | Versionar en commits separados (tú decides cuándo) |
| Revisar antes de versionar | 3 `M` de `docs/entregable2/` y `docs/evidencias/20261105-ci-correccion/…` (cambios previos a esta sesión; revisar su diff); `docs/entregable2/*.docx|pdf|pptx` y `outputs/entregable2-final/` (**48 MB binarios, `outputs/` no está en `.gitignore`**) | Decidir: ignorar `outputs/`, o conservar fuera de Git / LFS |
| Sensibles: NO versionar | `work/` (ya ignorado): `recovery-keys/` (clave privada de AWS **sin frase**), `terraform-state/` y `terraform-envs/` (IDs de cuenta y recursos), `backups/external/` y `oci-transfer/` (CMS), `oci-drill/secrets/`, `ansible-secrets/`; fuera del repo: `~/.oci`, `~/.aws`, `~/.ssh`, `~/.nexoeventos/recovery-oci/` (clave privada de OCI con frase) | Mantener ignorado; copia cifrada fuera del equipo |
| Falsos positivos del escaneo de secretos | Coincidencias en `docs/entregable3/*auditoria*`, `08-…`, `scripts/multicloud/auditar-*`: son **ejemplos de prueba del filtro de enmascarado** (`AKIAIOSFODNN7EXAMPLE`, ARN falsos, IP `129.151.20.33`/`54.210.33.99` ficticias); ninguna clave real | Sin acción; repetir el escaneo antes de publicar |
| Valores de prueba | `compose.yml` de los laboratorios Docker (`POSTGRES_PASSWORD` de ensayo, solo local) | Aceptable; no reutilizar en entornos reales |
**Riesgos de pérdida de evidencias:** (1) `work/` y los 594 archivos de evidencia **no están en Git**: una sola copia en este equipo; (2) la clave privada de AWS está en claro en `work/recovery-keys/` y descifra los respaldos CMS de AWS; (3) la clave privada de OCI tiene una sola custodia (tu frase); (4) todo lo de AWS (S3, 5 instantáneas, AMI, secretos) se pierde el ≈ 26-nov; (5) el laboratorio Docker (volúmenes) es efímero; (6) el estado Terraform es local, sin copia.

## 6. Secretos y configuración para recuperar NexoEventos desde el respaldo (solo nombres; no leí valores)
| Elemento | Para qué | Dónde está / estado | Pendiente |
|---|---|---|---|
| Volcado cifrado `nexoeventos-rds-20261111T164610Z.oci.cms` + manifiesto | Datos | Bucket OCI ✔ y `work/oci-transfer/` | — |
| Clave privada de OCI (frase) | Descifrar el respaldo | `~/.nexoeventos/recovery-oci/` (solo tú) | Custodia alternativa documentada |
| `TICKET_ENCRYPTION_KEY`, `SECURITY_HASH_KEY` | Validar entradas QR y hashes | Paquete CMS del 23-oct (`work/oci-drill/secrets/`; objeto en OCI según el cierre del 23-oct) | Verificar en solo lectura que el objeto sigue en OCI y que las claves de AWS no cambiaron |
| Variables de aplicación: `APP_ENV`, `DATABASE_URL`, `FRONTEND_ORIGINS`, `SESSION_*`, `LOGIN_*`, `ARGON2_MAX_CONCURRENT`, `DB_POOL_*` | Configuración (no secretas salvo `DATABASE_URL`) | `backend/.env.example`, `deploy/env`, `08-recuperacion-aplicacion-oci.md` | — |
| Roles PostgreSQL (propietario/aplicación/lectura) | Acceso a la BD restaurada | Se recrean con `scripts/provision-database-roles.py`/`deploy/bootstrap-rds-secrets.sh` (contraseñas aleatorias en la VM) | No hay que respaldarlas |
| Certificado TLS de `nexoeventos-demo.duckdns.org` y su clave | HTTPS del dominio | Importado en ACM (clave no exportable); vence **1-ene-2027**; en OCI se usó autofirmado efímero | Token de DuckDNS y custodia de la clave: **no verificado** |
| Terraform: `work/terraform-state/*`, `work/terraform-envs/*.tfvars` | Reconstruir infraestructura | Solo local | Copia cifrada |
| Claves de acceso: API de OCI (`~/.oci/nexoeventos_uploader_api_key.pem`), SSH (`~/.ssh/nexoeventos_recovery`, `…_azure`), IP /32 del Bastion | Operar OCI/Azure | Local | Inventario y custodia |
| Clave privada de AWS (`work/recovery-keys/…`) | Descifrar los CMS de AWS (10 respaldos) | Local, **sin frase** | Proteger o re-cifrar |
| RPM de PostgreSQL 18, `frontend/dist`, ruedas Python | Imagen de recuperación | `work/oci-drill/rpms` (reproducibles) | — |
**Se pierde con Academy:** secretos de Secrets Manager (`nexoeventos/academy/backend-env` y el secreto gestionado por RDS), AMI V2, instantáneas y S3.

## 7. Siguiente decisión (nada ejecutado)
Dime cuál autorizas primero: (a) empezar el **informe E3 consolidado + matriz de pruebas + costos** (solo local), (b) la **copia cifrada de evidencias y claves** (solo local), (c) preparar el plan de O1 (VM de OCI) para decidirlo con su costo.
