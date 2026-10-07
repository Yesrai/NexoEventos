# Arquitectura V1 verificable

## Implementación local medida

React/TypeScript consume FastAPI; FastAPI usa PostgreSQL para catálogo, usuarios, sesiones, reservas, entradas y auditoría. Las reservas bloquean la fila del evento, tienen idempotencia por usuario y generan una entrada por cupo. Las pruebas automatizadas cubren autorización y concurrencia. Los pagos permanecen simulados.

## Despliegue AWS V1 implementado

Desplegado y verificado el 3 de octubre de 2026 en `us-east-1` (ver `outputs/informe-despliegue-aws-2026-10-03.md`). Entre sesiones EC2 y RDS permanecen detenidas. El diagrama corresponde a los recursos reales del estado Terraform; las capturas de consola de red y seguridad (EV02–EV04) siguen pendientes.

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

Nginx es el único punto HTTP(S); FastAPI escucha en loopback y PostgreSQL nunca se expone a Internet. SSH está cerrado de forma predeterminada; la administración preferida es Session Manager con el perfil existente, y un `/32` temporal queda solo como contingencia. Las cookies se exigen `Secure` en producción, los orígenes CSRF son explícitos y HTTPS opera en `nexoeventos-demo.duckdns.org` con Let's Encrypt (comprobado el 3 de octubre de 2026). La administración se realizó por Session Manager, sin abrir SSH.

Componentes reales añadidos al diagrama lógico: secreto maestro administrado por RDS (Secrets Manager), Systems Manager Session Manager, DuckDNS + Let's Encrypt, snapshot manual cifrado y copia externa del respaldo.

| Tipo | Contenido |
|---|---|
| Medido | 30 recursos desplegados; suite pública HTTPS; persistencia RDS tras reinicio; respaldo cifrado en S3, copia externa y snapshot |
| Objetivo | E01 (20 usuarios/5 min, p95 < 2 s, errores < 1 %), R01 (RTO ≤ 60 min, RPO ≤ 24 h), I01 (plan posterior sin cambios) — **sin medir** |
| Supuesto | cifras del caso empresarial y estimación de costos |

Cambios Terraform locales pendientes de plan (AMI fija, máximo de almacenamiento RDS, prefijo de respaldos) y lectura Object Lock denegada: `docs/operacion/terraform-advertencias.md`.
