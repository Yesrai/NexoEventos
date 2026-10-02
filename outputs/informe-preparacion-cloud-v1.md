# Informe de preparación cloud V1 — NexoEventos

Fecha: 1 de octubre de 2026. No se crearon, modificaron, detuvieron ni eliminaron recursos cloud. No se ejecutó `terraform plan`, `apply` ni `destroy`.

## Resultado

La aplicación local conserva React/TypeScript, FastAPI y PostgreSQL con autenticación, roles, reservas transaccionales e idempotentes y entradas QR. Se preparó una arquitectura AWS V1 de bajo costo, configuración de servicio y una matriz EV01–EV10. Terraform está formateado y validado localmente, pero aún no existe un plan autenticado ni un despliegue.

## Cambios realizados

- Producción: Nginx sirve `frontend/dist`, redirige HTTP a HTTPS y reenvía `/api` a Uvicorn por loopback; systemd usa dos workers, sin `--reload` ni access log.
- Seguridad: producción exige cookies `Secure`, orígenes HTTPS explícitos, claves separadas, CSRF y límite persistente de cinco fallos de login por 15 minutos con bloqueo de 15 minutos.
- PostgreSQL: migración `0003_auth_rate_limits`; propietario sin login, usuario de aplicación sin privilegio `CREATE`, procedimiento seguro para preparar roles nuevos y Alembic separado mediante `SET ROLE`.
- Salud/logs: `/ready` comprueba PostgreSQL y responde solo estado genérico; la configuración evita cuerpos/cookies/tokens QR en logs.
- Recuperación: script de dump/restore aislado y documentación de respaldo separado de `TICKET_ENCRYPTION_KEY`.
- IaC: VPC, una EC2, dos subredes RDS privadas, RDS Single-AZ, S3 privado, CloudWatch y reglas SG mínimas. Sin NAT, ALB, Auto Scaling, réplica o Multi-AZ.
- Evidencias: matriz y espacios EV01–EV10 bajo `docs/evidencias/`.

## Pruebas ejecutadas

| Verificación | Resultado |
|---|---|
| Node efectivo | `v24.21.0` |
| Terraform `fmt -check` | correcto |
| Terraform `validate` AWS/Azure/GCP | 3 configuraciones válidas |
| Backend/PostgreSQL | 16 pruebas aprobadas |
| Frontend | 1 prueba aprobada |
| TypeScript + Vite | compilación correcta; 44 módulos |
| Restauración aislada | 3 eventos, 1 reserva y 1 entrada; hash/cifrado QR coherentes |
| Rol DB de aplicación | sin `CREATE` en esquema ni base |

La suite backend verifica sesión requerida, registro sin elevación de rol, propiedad de reservas/entradas, asignaciones de operador, cierre de sesión, rate limit, persistencia tras reinicio, último cupo concurrente, idempotencia por usuario y validación QR exactamente una vez.

Advertencias no bloqueantes: Starlette depreca la integración actual con `httpx` y Pydantic emitió una advertencia intermitente sobre metadata `alias`; las pruebas no fallan, pero conviene resolverlas antes de actualizar dependencias.

## Arquitectura desplegable propuesta

- Región AWS candidata: `us-east-1`, pendiente de sesión/permisos efectivos.
- VPC `10.20.0.0/16`; pública `10.20.1.0/24`; RDS privadas `10.20.21.0/24` y `10.20.22.0/24` en zonas distintas.
- EC2 `t3.small`, 20 GiB gp3 cifrado, Nginx + React + FastAPI, IPv4 pública, IMDSv2 y `LabInstanceProfile`.
- RDS PostgreSQL `db.t3.micro`, 20 GiB gp2 cifrado, Single-AZ, backup 7 días, secreto maestro administrado.
- S3 privado/versionado/SSE-S3 con ciclo de vida; CloudWatch con logs 7 días y alarma CPU.
- PostgreSQL 5432 solo SG de aplicación → SG de base. SSH cerrado salvo `/32` temporal.

HTTPS no está operativo: faltan dominio, DNS y certificado. No se inventó una URL.

## Terraform y recursos previstos

`terraform init -backend=false`, `fmt` y `validate` fueron satisfactorios. `plan` está bloqueado porque AWS CLI no tiene credenciales y Learner Lab no se inició. Antes del plan deben confirmarse `LabInstanceProfile`, permisos para RDS/Secrets Manager/S3/CloudWatch y cuotas. El plan se guardará solo en `work/` o `*.tfplan`, ambos ignorados.

## Costos

Estimación `us-east-1` On-Demand, sin créditos/Free Tier/impuestos: USD 0.050552 por hora prorrateada, USD 0.4044 por ocho horas y USD 36.903 por 730 horas. Supone 1 GiB S3, 1 GB de logs/mes, una alarma y transferencia menor de 100 GB. Es una estimación oficial por tarifa, no consumo medido.

Al detener EC2 continúa EBS. Al detener RDS continúan almacenamiento/backups y AWS vuelve a iniciarlo tras siete días. S3, logs, snapshots y secretos siguen cobrando mientras existan. El presupuesto AWS comunicado/asignado de USD 50 no es saldo actual confirmado.

## Cuentas cloud

### AWS

Las instrucciones leídas previamente permiten `us-east-1`/`us-west-2`, `LabRole` y `LabInstanceProfile`, EC2 On-Demand hasta large bajo límites, EBS gp2/gp3 hasta 100 GB y RDS PostgreSQL nano–medium/gp2 hasta 100 GB sin enhanced monitoring. En esta revisión la página quedó en blanco aun tras recargar. No se inició el laboratorio, no hubo identidad ni inventario y no se confirmó saldo actualizado.

### Azure

Confirmado: `Azure for Students`, estado activo, plan Azure, rol Propietario a nivel de suscripción, costo/previsión 0.00 y cero recursos. Una directiva `Deny` permite únicamente `southcentralus`, `mexicocentral`, `westus3`, `canadacentral` y `centralus`. `Microsoft.Compute`, `Microsoft.Network` y `Microsoft.Storage` están no registrados; no se modificaron. Cuotas de VM/tamaños no se pudieron leer.

El saldo y vencimiento del crédito están pendientes: el portal oficial quedó en selección de cuenta para que la usuaria complete ese paso/MFA. USD 100 es información comunicada por la usuaria, no saldo verificado. El 8 de junio de 2027 es vencimiento de servicios gratuitos, no prueba del vencimiento del crédito.

## Evidencias

- EV01: disponible localmente (pruebas, build y pantallas); falta ejecución pública.
- EV02–EV08: código/configuración preparados; evidencia de recursos reales pendiente.
- EV09: `fmt`/`validate` disponibles; plan y post-apply pendientes.
- EV10: flujo local probado; HTTPS público pendiente.

Las pantallas localmente revisadas fueron catálogo y área “Mis reservas y entradas”. La entrada mostrada ya estaba usada y no se reveló el QR. No se considera evidencia pública.

## Decisiones mínimas antes de desplegar

1. Completar selección de cuenta del portal de patrocinio para verificar saldo/vencimiento Azure.
2. Autorizar en otro momento el inicio de Learner Lab para inventario y plan AWS de solo lectura.
3. Elegir dominio/subdominio y método de certificado.
4. Confirmar que `LabInstanceProfile` puede leer el secreto mínimo o elegir un mecanismo permitido.
5. Revisar y aprobar el `terraform plan` y el costo actualizado. Solo después se consideraría `apply`.

El sistema no está listo para producción: es una implementación académica local y una arquitectura cloud todavía no desplegada.
