# Ventana única de pruebas (AWS + OCI + Azure) — preparación, prerrequisitos, costo y autorizaciones — 22-nov-2026

**NADA ejecutado. AWS NO se enciende hasta que cada prerrequisito de §3 conste cumplido.** Obtiene en una sola sesión de laboratorio las evidencias de: (1) sustitución de EC2 por ASG+ALB (T5), (2) recuperación real AWS → OCI (T6), (3) supervisión y operaciones desde Azure durante la recuperación (T7).

## 1. D4 actualizado (datos de la propietaria + lecturas de solo lectura de hoy)
| Dato | Valor | Fuente | Estado |
|---|---|---|---|
| Crédito de AWS Academy | total USD 50; usado 27,30; **restante 22,70**; indicador **rojo**; temporizador 00:00 (laboratorio **no iniciado**, no hay sesión viva) | consola, lectura de la propietaria | **confirmado el 22-nov** |
| Fecha exacta de vencimiento del laboratorio | **no confirmada** (reportado ≈ 26-nov 00:00Z) | — | **PENDIENTE: bloquea T5/T6** |
| Saldo de Azure for Students | no leído | — | pendiente |
| OCI Free Trial | **vencimiento no legible por API.** Señal fuerte de que terminó: límite de servicio `standard-e5-core-count` = **0** (E4 = 0), mientras `standard-a1-core-count` = 2 y `standard-e2-micro-core-count` = 2 (Always Free). El 23-oct se usó E5.Flex | OCI CLI, solo lectura, perfil `DEFAULT` | **probablemente vencido: confirmar en consola** |
| OCI: bucket y PAR | `nexoeventos-recovery`: NoPublicAccess, versionado, Standard; **0 PAR activos**; el usuario del perfil `DEFAULT` es miembro de **Administrators** | OCI CLI, solo lectura | ✔ T1 es ejecutable |
Consecuencia: el saldo de AWS (22,70) sobra para esta ventana (≈ 0,5–1 USD). **El factor limitante es la fecha de vencimiento**, no el dinero. Con el laboratorio en rojo hay que iniciarlo (sesión de ≤ 4 h) y esa es parte de la autorización.

## 2. Hallazgos de hoy que condicionan la ventana
1. **OCI sin formas de pago:** E5 = 0 ⇒ la VM de T3 solo puede ser **E2.1.Micro** (x86, 1/8 OCPU, 1 GB; compatible con los RPM x86_64 ya preparados) o **A1.Flex** (ARM, 2 OCPU, sin capacidad en octubre; **faltarían RPM aarch64**: `work/oci-drill/rpms` solo tiene x86_64). Recomendación: E2.1.Micro con `ARGON2_MAX_CONCURRENT=1` y swap; si hay OOM, A1 (requiere descargar RPM aarch64: pedir permiso aparte). Costo OCI: **0 USD** si Always Free.
2. **La compuerta de escritura NO está desplegada en AWS ni en su AMI/lanzamiento** (ningún `WRITE_GATE_*` en `infra/aws-v2`, `deploy` ni `ansible`; `test_failover_defaults.py` impide activarla por defecto). Para T6 hay que actualizar las instancias de V2 **en sitio** (Ansible/SSM, como la actualización del 7-oct) con el backend actual y la configuración de la compuerta, **con el ASG congelado** (`suspend-processes`: Launch, Terminate, ReplaceUnhealthy, AZRebalance) para que ninguna instancia sin compuerta aparezca durante T6. T5 va **antes** (la sustitución del ASG se prueba sobre la configuración actual) y la congelación **después**.
3. **Estado de Terraform desfasado** desde el 20-nov (3 a crear, 6 a modificar, 0 a destruir): la ventana debe adaptar la revisión del plan (3+6) o reconciliar antes (`aws-v2-reconciliacion-terraform.md`).
4. **La RDS reinicia sola ≈ 27-nov 23:37Z** (después del vencimiento reportado): no interfiere, pero hay que dejarla `stopped` al cerrar.

## 3. Prerrequisitos para encender AWS (todos obligatorios) y su estado hoy
| # | Área | Prerrequisito | Estado | Cómo se cumple |
|---|---|---|---|---|
| P1 | Seguridad | Centro de operaciones con barreras, auditoría y `REAL_EXECUTION_WIRED=False` hasta T6 | ✔ local (43 pruebas, en CI) | — |
| P2 | Seguridad | Custodia de claves (clave protegida + frase fuera del Mac) | ❌ acción de la propietaria | `custodia-clave-y-copia-externa.md` §6 |
| P3 | Seguridad | Clave C-04 en ruta absoluta **fuera del repositorio**, 0600 (la validación lo exige) | ❌ | mover/copiar con tu autorización |
| P4 | OCI | **T1 PASS** (CAS + carrera de adquisición + latencia + limpieza) | ❌ requiere tu autorización | `PRIMERA-OPERACION-CLOUD.md` |
| P5 | DNS | **T2 PASS** en `nexoeventos-test` | ❌ | `PROCEDIMIENTOS-T2-T4.md` |
| P6 | OCI | **T3**: VM con respaldo restaurado, TLS y entrada pública de prueba (módulo `public_entry` listo y probado en local; falta `apply` autorizado) | ❌ | Terraform con plan guardado + `RECOVERY_TLS_SAN`, `RECOVERY_READONLY=1` |
| P7 | OCI | Sello del failover (objeto + clave pública del operador) | ❌ | `oci_seal_lab_f0/f1.py` + autorización |
| P8 | Azure | **T4**: centro de operaciones y **testigo** desplegados; NSG abierto solo a orígenes explícitos durante la ventana | ❌ | paquete verificado ya construido; despliegue con autorización |
| P9 | Código | Proveedores reales de la fábrica (G1) escritos, **revisados** y `REAL_WIRING_ENABLED` cambiado en un commit revisado | ❌ | tras T1–T4 |
| P10 | AWS | Actualización en sitio de V2 con compuerta `enforce` + vallado en la base (hybrid B2–B4) y ASG congelable | ❌ | Ansible/SSM; ventana |
| P11 | Humano | Fecha de vencimiento de Academy y saldo de Azure confirmados | ⏳ parcial | §1 |
| P12 | Evidencia | Recolector, plantillas T1–T8 y verificación de manifiesto | ✔ local | `ops_center/evidence*.py` |
**Estado: 4 de 12 cumplidos (P1, P12 y parcialmente P11); la ventana NO puede abrirse hoy.** P4–P8 son las operaciones Cloud previas (OCI/Azure/DNS), sin gasto de AWS.

## 4. Secuencia de la ventana (≈ 3–3,5 h; todo con marcas UTC del recolector)
| Min | Paso | Etapa | Corte seguro |
|---|---|---|---|
| 0 | Iniciar el laboratorio; lectura de solo lectura: identidad, 0 EC2/ALB, RDS `stopped`, saldo | — | si algo no coincide, no continuar |
| 10 | Azure encendida con panel y testigo; OCI con la VM de T3 ya lista (restaurada del respaldo más reciente) | T4/T3 | — |
| 20 | RDS `available` y `apply` del plan revisado (ALB + 2 EC2) con watchdog de apagado | B1+B2 | watchdog a 4 h |
| 45 | **T5:** detener la API en 1 EC2; medir 5xx, detección, sustitución | T5 | el ASG repone |
| 75 | Congelar el ASG; actualizar V2 en sitio con la compuerta; lease inicializado | G5 | restaurar procesos del ASG |
| 100 | Respaldo fresco a OCI (RPO) y solicitud de recuperación en el panel de Azure → validación → aprobación | T7 | cancelar la solicitud |
| 115 | **T6.0** ensayo en seco; simulacro de cancelación; simulacro de aborto por standby no listo | T6 | kill-switch |
| 140 | **T6** failover real controlado (DNS solo de pruebas); verificación por efecto (0 × 201 de AWS); RTO/RPO | T6 | cancelación/aborto limpios |
| 170 | Failback manual y estado final | T6 | — |
| 185 | Limpieza: reanudar ASG → ASG a 0, ALB eliminado, RDS `stopped`; Azure desasignada; OCI destruida; `verify_clean --live` | T8 | — |

## 5. Costo estimado (tarifas públicas citadas en la documentación; sin verificar con facturación)
| Nube | Concepto | Estimado | Tope propuesto |
|---|---|---|---|
| AWS | RDS Multi-AZ + 2 EC2 t3.small + ALB ≈ 0,10–0,20 USD/h × ≈ 3,5 h (el 20-nov: ≈ 0,10 USD en 58 min) | **≈ 0,4–0,8 USD** | **1,50 USD** y hora límite escrita |
| OCI | E2.1.Micro Always Free; IGW/IP pública efímera | **0 USD** (si el trial ya venció no hay cargo posible: sin método de pago) | 0,30 USD |
| Azure | VM D2s_v4 0,108 USD/h × ≈ 4 h; fijos 0,33–0,43 USD/día | **≈ 0,43 USD + fijos** | 1,00 USD |
| **Total** | | **≈ 1,0–1,7 USD** (saldo AWS 22,70 USD) | |

## 6. Autorizaciones específicas que se pedirán (una por bloque; ninguna implícita)
1. **T1** (OCI, 0 USD): `AUTORIZO ejecutar T1: oci_par_probe.py …` (tarjeta aparte).
2. **T2** (DuckDNS de pruebas): `AUTORIZO el cambio de DNS de prueba en nexoeventos-test`.
3. **T3** (OCI): `terraform apply` del plan guardado del módulo `public_entry` + VM, con tope 0,30 USD / 3 h.
4. **T4** (Azure): encender la VM, desplegar paquete (SHA-256 verificado), abrir NSG a orígenes explícitos durante la ventana.
5. **Ventana AWS**: iniciar el laboratorio, `rds-window.sh chain`, `suspend-processes` del ASG, actualización en sitio por SSM; tope 1,50 USD y hora límite.
6. **T6 real**: frase de `autorizacion-T6.json` + solicitud aprobada + cambio de código revisado de `REAL_*`.


## 7. Cómo verificar la fecha exacta de vencimiento de AWS Academy SIN iniciar el laboratorio ni generar costos (investigado el 22-nov)
Lo que dicen las fuentes: el fin del laboratorio **lo fija el docente/institución** (el Learner Lab dura el curso, no hay una fecha universal) y el presupuesto visible es aproximado. Por eso la fecha hay que leerla en **tu** curso. Opciones, de más a menos fiable, todas gratuitas (no inician el laboratorio):
1. **Canvas → tu curso → Inicio/Resumen y Programa (Syllabus):** la fecha de fin del curso suele figurar ahí o en el calendario.
2. **Canvas → Panel de control:** la tarjeta del curso o la lista «Cursos» indica si el curso está activo/concluido y, a veces, su fecha de fin.
3. **API de Canvas con tu sesión ya iniciada, solo lectura:** abre `https://<tu-institución>.instructure.com/api/v1/courses/<id-del-curso>` en el navegador; el JSON incluye `start_at`, `end_at`, `workflow_state` y `access_restricted_by_date`. (Es lo que usaría yo con tu navegador si me lo pides; no requiere credenciales mías.)
4. **Página del Learner Lab en Canvas, sin pulsar «Start Lab»:** muestra el presupuesto («Used $ of $») y avisos del curso; abrirla no inicia nada.
5. **Docente o mesa de ayuda de la universidad** (fuente oficial; pueden renovar créditos): registra la respuesta por escrito.
Qué NO usar: ejecutar `aws sts`/consolas (requiere laboratorio iniciado) ni «Start Lab» solo para mirar. Hasta tener la fecha, la ventana de AWS no se agenda y T5/T6 siguen **pendientes obligatorios**, no opcionales.
Fuentes consultadas: [Universidad de Michigan — AWS Academy Learner Lab](https://www.its.umich.edu/computing/virtualization-cloud/amazon-web-services/aws-academy-learner-lab), [AWS Academy Learner Lab — Student Guide](https://yogevshani.github.io/mta-bootcamp-2026/pdf/AWS%20Academy%20Learner%20Lab%20-%20Student%20Guide.pdf), [Universidad de Charlotte — créditos del Learner Lab](https://services.help.charlotte.edu/TDClient/33/Portal/KB/Article/329/How-many-AWS-Academy-Learner-Lab-credits-do-I-get).

## 8. OCI Always Free: qué sigue disponible (lectura de solo lectura, 22-nov)
Disponible ahora en la región `sa-saopaulo-1`: **Object Storage 20 GiB** (uso 0,5 MB), **E2.1.Micro ×2** (x86, 1 GB), **A1.Flex hasta 2 OCPU/12 GB** (ARM; la capacidad real solo se sabe al crear), almacenamiento por bloques 200 GB, **1 Internet Gateway**, 1 IP pública reservada, 2 VCN, Bastion y PAR sin límite relevante. Costo de los últimos 30 días: 0. **No se presupone el fin del trial**: la cuota 0 de E5/E4 y la ausencia de E5.Flex en el dominio son coherentes con él pero no lo demuestran; basta para el plan porque **T1–T3 usan solo Always Free**.
