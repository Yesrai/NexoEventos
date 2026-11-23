# Matriz de cierre Cloud de NexoEventos (AWS · OCI · Azure) — 22-nov-2026 (rev. 2: requisitos obligatorios)

> **Borrador SIN commit.** Corrección de alcance de la propietaria: el failover real AWS→OCI es **obligatorio**, y se exigen tres capacidades: (1) EC2 falla → ALB+ASG mantienen/recuperan el servicio; (2) AWS indisponible → OCI asume el servicio con procedimiento real, seguro y verificable; (3) Azure como centro de supervisión y operaciones (Grafana, alertas y un panel para consultar el estado de las nubes y solicitar recuperaciones controladas). La versión 1 de esta matriz los trataba como opcionales; esa clasificación queda anulada. El plan de ejecución está en `PLAN-PRUEBAS-OBLIGATORIAS-CLOUD.md`.

Construida **solo leyendo** la documentación y evidencias del repositorio (`INDICE-PRUEBAS-AWS.md`, `entregable3/14` y `15`, `evidencias/*`). No se ejecutó nada en ninguna nube. Una sola arquitectura final; V1/V2/B1–B3 son etapas de prueba, no proyectos distintos.

Leyenda: **DEMOSTRADO** = ejecutado en la nube real con evidencia · **PARCIAL** = demostrado con límites declarados · **LOCAL/SIMULADO** = Docker/Mac, no es nube · **DISEÑO** = documentado, no ejecutado · **NO EVIDENCIA** = no encontré registro.

## 1. Demostrado (no repetir sin un cambio que invalide la evidencia)
| Área | Prueba | Estado | Evidencia | Límite declarado |
|---|---|---|---|---|
| AWS | Despliegue V1 (VPC, EC2, RDS, S3, HTTPS) y suite pública | DEMOSTRADO | EV05–EV10 | Una sola instancia |
| AWS | Carga 20 VU × 300 s, 0 % inesperados, sin sobreventa | DEMOSTRADO | EV11 | Carga moderada |
| AWS | Restauración PITR de RDS a instancia temporal (RPO 3 min 32 s; datos a 21 min 4 s; 135/135 QR) | DEMOSTRADO | EV07 | Solo datos, no aplicación completa |
| AWS | Despliegue V2 (ALB + 2 EC2 + RDS Multi-AZ), suite 15/15 | DEMOSTRADO | `20261104-fase-c-d-v2`, `20261106-prueba-real-v2` | — |
| AWS | Reconstrucción B1+B2 con watchdog (RDS 5 min 8 s; ALB y 2 destinos sanos en 2 zonas; HTTPS 200) y limpieza verificada (≈ 0,10 USD) | DEMOSTRADO | `20261120-b1-b2-v2` | No incluye autohealing ni failover |
| AWS | Escalado 2→3→2 | DEMOSTRADO | `escalado-v2-20261022` | Carga cortada poco después |
| AWS | Failover Multi-AZ de RDS (V1 ≈ 14 s; V2 con `/livez`: 0 fallos de 803) | DEMOSTRADO | `multicloud/aws/20261023-rds-multiaz`, `20261104-d2-failover-rds-v2` | `/api/events` 3 fallos de 836 (99,6 %) |
| AWS | Autohealing del ASG en V2 (detección 22,6 s; `/api` 97,7 %) | PARCIAL | `20261104-b2-autohealing-v2` | 52 respuestas 502 durante la sustitución |
| AWS | Alarmas: CPU real V1 detectada y recuperada; notificación V2 por estado forzado | DEMOSTRADO / forzado | `20261104-p2-cpu-real`, `fase-d-notificacion-v2` | V2 no es detección real |
| AWS | Lifecycle de S3 (prefijo `database-backups/`, 365 días) aplicado y verificado | DEMOSTRADO | `20261104-fase-a1-lifecycle-s3` | Dependerá de que Academy exista |
| AWS | Nueva AMI con `/livez` y certificado ACM | DEMOSTRADO | `fase-b1-acm`, `fase-b2-ami` | En la misma cuenta |
| AWS | TLS `verify-full` a RDS | DEMOSTRADO | `20261104-fase-c-d-v2`, `tls-rds-verificacion-local-20261029` | — |
| OCI | Base (VCN, NSG, bucket), IAM de mínimo privilegio, transferencia cifrada con SHA-256 | DEMOSTRADO | `multicloud/oci/20261023-*` | — |
| OCI | Recuperación de la aplicación en VM temporal (32 min 42 s; 14/14; huella 10/10); VM y Bastion destruidos | DEMOSTRADO | `20261023-recuperacion-aplicacion` | Con el respaldo del 23-oct, no el del 11-nov |
| AWS→OCI | Respaldo cifrado con dos claves independientes, 23-oct y 11-nov; prueba negativa de sobrescritura | DEMOSTRADO | `entregable3/13`, `20261111-respaldo-rds` | Puntual, no continuo |
| Local | Restauración del respaldo del 11-nov en PostgreSQL (6,7 s; huella 10/10) | DEMOSTRADO (local) | `c04-20261119` | No es RTO de nube |
| Local | Paquete cifrado de reconstrucción: Mac, Drive y OneDrive idénticos; restaurado localmente (HEAD `a711929`) | DEMOSTRADO (local) | `20261122-copia-externa-respaldo` | No es reconstrucción en AWS |
| Azure | VM con Zabbix + Grafana + Azure Monitor; alerta de CPU real disparada y resuelta | DEMOSTRADO | `multicloud/azure/20261028-vm` | — |
| Azure | Entrega de correo de alertas | DEMOSTRADO (5-nov) | `20261105-azure-ventana2` (confirmado por la usuaria y archivado) | El índice AWS aún cita «no demostrada» por la fecha anterior: **corregir la redacción** |
| Azure | Acceso a Grafana/Zabbix por Tailscale | DEMOSTRADO | `20261109-azure-tailscale` | — |
| Failover | Lease, compuerta fail-closed, fencing, orquestador, DNS-switch, replicación lógica | LOCAL/SIMULADO | `entregable3/03–06`, `evidencias/repl-*`, 65 pruebas | **No es** failover AWS↔OCI |

## 1B. Auditoría de los tres requisitos obligatorios (qué funciona realmente)

### 1B.1 Capacidad 1 — AWS: falla de EC2, ALB y Auto Scaling
| Elemento | Estado | Evidencia |
|---|---|---|
| ALB + ASG 2–3 EC2 en 2 zonas + RDS Multi-AZ desplegados | DEMOSTRADO (6-nov y 20-nov) | `20261106-prueba-real-v2`, `20261120-b1-b2-v2` |
| Caída de 1 de 2 instancias: servicio mantenido por la otra | DEMOSTRADO con límites | `tolerancia-fallos-v2-20261022`: 25 × 502, todas de `/healthz` |
| Sustitución por el ASG (autohealing) | DEMOSTRADO con límites | `20261104-b2-autohealing-v2`: 22,6 s de detección; 52 × 502 (24 en `/api/events`); `/api` 97,7 % |
| Misma prueba sobre la arquitectura final (20-nov) | **FALTA** | El 20-nov solo se desplegó y se apagó |
**Veredicto:** capacidad demostrada con cifras honestas, no «cero impacto». Falta una repetición en la arquitectura final con criterio de éxito escrito antes (T5).

### 1B.2 Capacidad 2 — OCI asume el servicio si AWS cae
| Elemento | Estado | Evidencia / hueco |
|---|---|---|
| Respaldo AWS→OCI cifrado, verificado, sin sobrescritura | DEMOSTRADO | `entregable3/13` |
| Aplicación recuperada en VM de OCI (manual, 32 min 42 s, 14/14) | DEMOSTRADO (23-oct) | `multicloud/oci/20261023-*` |
| Lease/compuerta de escritura, fencing, orquestador (9 etapas), DNS-switch | LOCAL/SIMULADO | `backend/app/failover`, `scripts/multicloud/failover`, 65 pruebas; el propio orquestador declara que los adaptadores reales **no existen** |
| Autoprueba real del lease contra un bucket de OCI (CAS `If-Match`) | **FALTA** (P1, 0 USD) | `entregable3/20` §A |
| Cambio de DNS real en subdominio de pruebas | **FALTA** (P2, 0 USD) | `entregable3/20` §B |
| VM de OCI con PostgreSQL restaurado, app y **entrada pública con TLS** | **FALTA** (P3; la VCN actual es privada, sin IGW; cuota E5/A1 a verificar) | `entregable3/18`, consulta de OCI del 10-nov |
| Adaptadores: composición completa `FullRecoveryAdapters` (sondas, lease, respaldo OCI, standby con vallado, DNS) | EXISTE y probado en **local** con servidores falsos; **falta el cableado a los extremos reales** y su configuración válida (`failover_config`) | `scripts/multicloud/failover/adapters_*.py`, `test_failover_e2e.py` (corrección de la rev. 2: antes se describieron como «no construidos») |
| Compuerta `WRITE_GATE_MODE=enforce` desplegada en AWS y OCI + credenciales mínimas del lease | **FALTA** (P5, decisión pendiente) | `entregable3/20` §C.1 |
| Failover real controlado con RTO/RPO medidos y verificación por efecto de que AWS no escribe | **FALTA** (T6) | — |
**Veredicto:** hay diseño, código y simulación sólidos, pero **ninguna conmutación real**. Falta construir P4/P5 y ejecutar T1–T6.

### 1B.3 Capacidad 3 — Azure: supervisión y operaciones
| Elemento | Estado | Evidencia |
|---|---|---|
| VM con Zabbix, PostgreSQL y Grafana 13.2.4; HTTPS; acceso solo por IP /32 o Tailscale | DEMOSTRADO | `multicloud/azure/20261028-vm`, `20261105-azure-ventana3`, `20261109-azure-tailscale` |
| Alertas de Azure Monitor `alerta-vm-cpu` (CPU real) y `alerta-vm-up`, Fired y Resolved | DEMOSTRADO (28-oct, 4/5-nov, 2 veces) | `20261105-azure-ventana2/alertas-api.json`, `metrica-cpu-vm.txt` |
| Correos de las 4 transiciones recibidos y archivados | DEMOSTRADO | `20261105-azure-ventana2/correos-azure-monitor.png` |
| Captura de Grafana con CPU 2 %→100 %→1 % | DEMOSTRADO como **histórico** (4-nov), recorte sin barra de direcciones | `grafana-azure-vm-historico-20261104.png` |
| Zabbix sondeando AWS V1 en vivo; fallo AWS detectado (trigger 14:28Z) | DEMOSTRADO contra **V1** | `multicloud/azure/20261028-vm` |
| Series de AWS y OCI en Grafana | **HISTÓRICAS** (`history.push`): 468 puntos AWS, 734 OCI, rotulados «histórico» | `docs/multicloud/09` |
| Sondas de Zabbix hacia **V2 (ALB)** y hacia el **sitio de OCI** en vivo | **FALTA** | las sondas apuntan a V1 |
| Panel de operaciones (`/api/ops/overview`, `Operations.tsx`) | EXISTE, **SOLO LECTURA**, con datos de archivos locales (`sin_datos`/«No verificado» cuando no hay evidencia) | `backend/app/ops.py`; 331+44 pruebas |
| Panel alojado **fuera de AWS** | **IMPLEMENTADO y probado en LOCAL** (`ops_center/`, D1 = Azure); sin desplegar en Azure | `docs/operacion/centro-operaciones-azure.md`, 26 pruebas |
| **Solicitar recuperaciones controladas** | **IMPLEMENTADO en local:** solicitar → validar (barreras) → aprobar (otra persona) → auditar; **no ejecuta** | `ops_center/recovery.py`, `barriers.py`, `audit.py` |
**Veredicto:** monitoreo y alertas reales sí; **centro de operaciones no**. Falta (a) sondas en vivo a los sitios finales, (b) un panel que viva en Azure y muestre las tres nubes con el origen de cada dato, (c) un flujo de **solicitud** de recuperación (registro y aprobación; la ejecución sigue siendo humana con frase de confirmación, nunca automática).

## 2. Lo que falta de verdad (con propuesta mínima)
| # | Pendiente de tu lista | Estado real | ¿Bloqueante? | Cierre mínimo |
|---|---|---|---|---|
| F1 | Restauración de un **volcado CMS** en RDS | R01 restauró PITR en RDS (real); el volcado se restauró solo en PostgreSQL local y OCI | No (R01 cubre «restauración en RDS») | Documentar la distinción; no repetir |
| F2 | Reconstrucción en **cuenta AWS nueva** | NO EVIDENCIA; solo simulaciones (90 pruebas) y guías | No (Academy no permite otra cuenta; criterio de rúbrica no lo exige) | Declararla **diseño/procedimiento documentado** |
| F3 | Reconciliar Terraform state | Drift conocido tras limpieza del 20-nov: 3 a crear, 6 a modificar, 0 a destruir | Solo si se vuelve a encender V2 | Documentar; decidir `refresh-only` o destroy dirigido **únicamente** si hay otra ventana |
| F4 | AMI y dependencias en cuenta nueva | AMI verificada en la cuenta actual; en cuenta nueva NO EVIDENCIA | No | Igual que F2 |
| F5 | Capacidad 1: caída de EC2 → ALB+ASG | Medida el 22-oct y el 4-nov (detección 22,6 s; `/api` 97,7 %; 52 respuestas 502 durante la sustitución). El 20-nov la arquitectura final se desplegó pero **sin inyección de fallo** | **Sí, para afirmarla sobre la arquitectura final** | Repetir una vez en la ventana AWS única (T5), con el criterio de éxito definido de antemano |
| F6 | Failover real AWS → OCI | **No existe.** Solo diseño y simulación local; faltan adaptadores reales, compuerta `enforce` desplegada, VM de OCI con entrada pública y TLS | **SÍ, OBLIGATORIO** | Ver `PLAN-PRUEBAS-OBLIGATORIAS-CLOUD.md` (T1–T6) |
| F7 | Falla de zona completa | NO EVIDENCIA | No | Mejora futura |
| F8 | FIS | NO EVIDENCIA (sin recursos ni resultados) | No | Mejora futura; los experimentos de caos manuales ya cubren el criterio |
| F9 | Alta disponibilidad B3 | NO EVIDENCIA como prueba; B1+B2 sí | No | Mejora futura; HA intra-AWS ya demostrada con V2 |
| F10 | Capacidad 3: Azure como centro de supervisión y operaciones | Ver §2.3: Grafana/Zabbix/alertas/correos **demostrados**; panel con estado de las tres nubes y **solicitud** de recuperaciones: **no existe integrado** | **SÍ, OBLIGATORIO** | T7–T8 |
| F11 | **Google Cloud** | Sin recursos ni evidencia; el plan lo condicionaba a justificación y marcaba GCP como «no recomendado» | No | Declararlo **fuera de alcance** (Plan B: OCI) |
| F12 | Lifecycle de S3 | Ya aplicado (ver §1); **no está abierto** | No | Quitar de pendientes |
| F13 | Restaurar el respaldo del 11-nov en una VM de OCI (O1) | Solo análisis (`entregable3/18`); no ejecutado | No | Opcional, ver §3 |

## 3. Pendientes OBLIGATORIOS (orden de ejecución; detalle, costos y riesgos en el plan)
1. **L0 local (0 USD): HECHO** — centro de operaciones, flujo de solicitud/aprobación, barreras, auditoría, identidades mínimas (26 pruebas). Pendiente de L0: cableado real de adaptadores (T6) y decidir P5.
2. **T1 lease real en OCI** (0 USD) · **T2 DNS de pruebas** (0 USD) · **T3 VM de OCI con entrada pública** (≈ 0,10 USD OCI).
3. **T4 Azure:** sondas y panel en vivo hacia V2 y OCI (≈ 0,1 USD + costos fijos diarios).
4. **Ventana AWS única:** **T5** caída de EC2 con ALB+ASG y **T6** failover real AWS→OCI (≈ 0,3–0,6 USD AWS).
5. **T7–T8:** panel/solicitud de recuperación demostrado de extremo a extremo y cierre/limpieza con `verify_clean --live`.
Más los bloqueantes no Cloud: custodia de claves (propietaria), documentación coherente (`estado-proyecto.md` obsoleto), decisión sobre binarios y confirmación de lo que sobrevive a Academy (≈ 26-nov).

## 4. Mejoras que SIGUEN siendo opcionales
FIS, falla de zona completa, B3 completo, cuenta AWS nueva (F2/F4), Google Cloud (`infra/gcp` es solo un marcador sin cuenta), failback automático. El **failover real ya NO es opcional**.

## 5. Estado del paquete de respaldo
El paquete cifrado `…T044516Z.tar.cms` contiene HEAD `a711929`. El commit `21a35e8` (script `--expect-head` y documentos de custodia/verificación) **está en GitHub, pero no en ese paquete**. Se conserva el paquete validado a propósito; regenerarlo no es necesario para el cierre salvo decisión posterior.

## 6. Estado tras la verificación local del 22-nov (rev. 3; sin ejecutar nada Cloud)
- **Hecho en local (ver `docs/evidencias/20261122-verificacion-local/`):** backend 331/331 en PostgreSQL desechable; centro de operaciones 37/37 (en CI como job `ops-center`, con guardia de `REAL_EXECUTION_WIRED = False`); batería de failover 589 + 107 (ver `docs/operacion/auditoria-fallos-seguros-y-doble-escritor.md`); `terraform fmt/validate` de `infra/oci`, `infra/azure` e `infra/aws-v2`; paquete de despliegue de Azure construido y verificado (no desplegado); recolector de evidencias con plantillas T1–T8.
- **Hallazgos que cambian el plan:** (1) el adaptador real exige lease **por PAR**, no por CLI → T1 = `oci_par_probe`; (2) no existe fábrica que construya los adaptadores reales desde la configuración (G1); (3) `infra/oci` no tiene entrada pública (G9); (4) la configuración exige testigo, sello y vallado fuerte aun con `automatic=false` (G3–G5); (5) el testigo previsto era GCP, fuera del alcance aprobado (D6).
- **Sigue SIN demostrar en nube real:** capacidad 1 sobre la arquitectura final (T5), capacidad 2 completa (T6), capacidad 3 integrada (T4/T7). Ninguna se declara completa.
- Documentos: `PRIMERA-OPERACION-CLOUD.md`, `PROCEDIMIENTOS-T2-T4.md`, `PLAN-PRUEBAS-OBLIGATORIAS-CLOUD.md`, `docs/operacion/{auditoria-adaptadores-failover,centro-operaciones-azure}.md`.

## 7. T1 (22-nov-2026): CERRADA con PASS
Lease real por PAR en OCI: CAS 20/20 y adquisición del lease 20/20 con exclusividad (1 ganador, ≤ 1 válido, épocas +1), p95 de PUT 0,414 s, 0 PAR y 0 residuos, inventario intacto. Detalle, fallo previo y corrección en `T1-20261122-resultado.md`. **Siguiente: T2 (DNS de laboratorio); requiere su propia autorización y los datos de DuckDNS.** T3–T8 siguen pendientes; ninguna capacidad obligatoria se da por completa.

## 8. T2 (22-nov-2026): 1.ª ejecución FAIL sin cambios de DNS → corrección → pendiente de nueva autorización
Fallo: TLS a DuckDNS (el Python del entorno no tenía almacén de certificados). Corregido para todos los clientes HTTPS del failover (verificación nunca desactivada); además se corrigió una carrera real del testigo detectada en la regresión (cadena rota con hilos compartidos). Detalle en `T2-20261122-resultado.md`. T1 sigue CERRADA (PASS); T3–T8 pendientes.

## 9. T2 (22-nov-2026): CERRADA con PASS
Cambio real de DNS en `nexoeventos-test`: A→B en 62,1 s y reversión en 62,0 s (3 resolvedores), 3 negativos de seguridad rechazados, segundo cambio rechazado por el intervalo mínimo, DNS final = inicial, token ausente de la evidencia. Detalle y fallo previo en `T2-20261122-resultado.md`. **Siguiente: T3.** T1 y T2 cerradas; T3–T8 pendientes; ninguna capacidad obligatoria se da por completa.

## 10. T3 (22-nov-2026): preparada, NO ejecutada
Plan real contra OCI (solo lectura): 11 altas/0 cambios/0 destrucciones, validado por la guarda; 3 defectos míos corregidos antes de llegar a la nube (red del Bastion, CIDR fuera de la VCN, `cidrcontains`) y 3 detalles de la aplicación (origen CORS, `verify=False`, Argon2). Tarjeta en `T3-TARJETA-AUTORIZACION.md`. T1 y T2 cerradas; T3–T8 pendientes.

## 11. T3 rev. 2 (22-nov-2026): lista para autorización
Añadidas a petición de la propietaria: fase funcional (login, reservas, idempotencia, concurrencia, QR) en la copia desechable, integridad del respaldo verificada sin descifrar (MD5 del bucket = copia verificada), memoria en dos fases, procedimiento de reconstrucción para T6 y reversibilidad probada. 19 criterios. T1 y T2 cerradas; T3 pendiente de autorización.

## 12. T3 (22-nov-2026): 1.er intento FAIL (abortado, destruido, 0 residuos) → corregido → pendiente de nueva autorización
Demostrado en OCI real: red y guarda (11/0/0), Bastion, SSH, RPM verificados en la VM, destrucción con inventario idéntico. Falló: instalación de PostgreSQL (dnf sin límites saturó la E2.1.Micro). Detalle y corrección en `T3-20261122-intento1-resultado.md`. T1 y T2 cerradas; T3 incompleta.
