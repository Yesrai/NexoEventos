# Arquitectura V1 verificable

## Implementación local medida

React/TypeScript consume FastAPI; FastAPI usa PostgreSQL para catálogo, usuarios, sesiones, reservas, entradas y auditoría. Las reservas bloquean la fila del evento, tienen idempotencia por usuario y generan una entrada por cupo. Las pruebas automatizadas cubren autorización y concurrencia. Los pagos permanecen simulados.

## Despliegue AWS preparado, aún no ejecutado

```text
Internet
   │ 80/443
   ▼
EC2 pública (Nginx + React compilado + FastAPI/systemd)
   │ 5432, solo SG→SG
   ▼
RDS PostgreSQL privado (Single-AZ, dos subredes de datos)

EC2 ──HTTPS──► S3 privado / CloudWatch
```

- VPC: `10.20.0.0/16`.
- Subred pública V1: `10.20.1.0/24`.
- Subredes privadas RDS: `10.20.21.0/24` y `10.20.22.0/24`.
- Reservadas para evolución, no creadas en V1: `10.20.2.0/24`, `10.20.11.0/24`, `10.20.12.0/24`.
- EC2 `t3.small`, Amazon Linux 2023, EBS gp3 20 GiB cifrado, IMDSv2 y un perfil IAM existente definido por entorno (`LabInstanceProfile` solo en Academy).
- RDS PostgreSQL `db.t3.micro`, Single-AZ, gp2 20 GiB cifrado, privado, backup siete días y snapshot final obligatorio.
- S3 privado con bloqueo público, versionado, SSE-S3 y expiración de respaldos de demostración.
- CloudWatch: logs API/Nginx por siete días y alarma CPU.

No hay NAT Gateway, balanceador, Auto Scaling, réplica ni Multi-AZ. La V1 prioriza demostración y costo; no debe describirse como alta disponibilidad ni producción. Azure queda como recuperación futura, no implementada.

## Seguridad de red y aplicación

Nginx es el único punto HTTP(S); FastAPI escucha en loopback y PostgreSQL nunca se expone a Internet. SSH está cerrado de forma predeterminada; la administración preferida es Session Manager con el perfil existente, y un `/32` temporal queda solo como contingencia. Las cookies se exigen `Secure` en producción, los orígenes CSRF son explícitos y HTTPS usará `nexoeventos-demo.duckdns.org` con Let's Encrypt; aún no está operativo.

Terraform fue formateado y validado sin credenciales. El plan autenticado, permisos efectivos, cuotas y despliegue siguen pendientes; ver `infra/aws/README.md` y `docs/costos-v1.md`.
