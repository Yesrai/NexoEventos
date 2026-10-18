# Plan de actualización cloud a la versión actual (17 de octubre de 2026)

Resumen operativo, sin ejecutar nada. Reutiliza [ansible-despliegue.md](ansible-despliegue.md), [sesion-cloud-siguiente.md](sesion-cloud-siguiente.md), [calendario-credito-aws.md](calendario-credito-aws.md) y [terraform-advertencias.md](terraform-advertencias.md). **Requiere autorización antes de cada paso con efecto en AWS.**

## Estado

| Tema | Hecho verificado en la documentación | Falta |
|---|---|---|
| Arquitectura V1 | VPC con 1 subred pública y 2 privadas, EC2 `t3.small` (Nginx + FastAPI, IMDSv2, EBS cifrado), RDS PostgreSQL privada Single-AZ cifrada, S3 privado, CloudWatch (logs + alarma CPU), DuckDNS + Let's Encrypt, Session Manager sin SSH | V2 (ALB + 2 EC2) solo diseñada |
| Código en cloud | commit `7955e7e` | HEAD local está 36 commits adelante |
| Base de datos cloud | Alembic **0005** (comprobado en las restauraciones del 10 y 12 de octubre) | **Pendientes 0006, 0007 y 0008** (no solo 0007/0008): 0006 separa recintos/planos y es previa a las otras |
| Terraform | estado protegido `academy-current`; `validate` correcto con las 3 correcciones | **ningún plan autenticado**; el refresh de S3 lo bloquea la política del laboratorio (Object Lock) |
| Evidencias cumplidas | E01 (20 VU × 5 min: p95 421 ms, 0 errores), R01 (RPO 3 min 32 s, datos verificados), EV08 (logs reales) | EV02–EV04 capturas de consola, EV09 plan, EV10 con la versión nueva, recuperación completa (RTO, T3/T4), matriz de riesgos, V2 medida, consumo real |

## Hallazgo corregido hoy

`ansible/roles/nexoeventos/tasks/main.yml` exigía literalmente la revisión `0005` tras `alembic upgrade head`: con 0008 habría fallado y no publicado la aplicación. Ahora compara la base con el head del release (cambio local, sin efecto en AWS).

## Orden de ejecución propuesto

0. **Hoy, solo lectura** (antes de las 19:23 Lima, hora límite aproximada del reinicio automático de la RDS original, detenida desde el 10-oct): renovar credenciales, comprobar cuenta/región, `cloud-session.sh status` (EC2, RDS, fecha límite) y consumo en el panel. Decidir: aprovechar el reinicio para la ventana 2, o aceptar ≈ USD 0.43/día de cómputo RDS.
1. **Local previo (sin AWS):** commit limpio, `scripts/build-release.sh`, decidir los dos puntos de datos de abajo.
2. **Ventana de actualización (≤ 2 h):** `ansible-aws.sh preflight` → respaldo previo con recibo `0600` → `deploy` (migra 0005→0008, siembra catálogo con `ON CONFLICT DO NOTHING`, exige `/ready`) → flujo público registro→reserva→QR→validación → detener EC2 y RDS y confirmar `stopped`.
3. **Plan Terraform autenticado** (sin `apply`): detenerse ante cualquier `-/+` o eliminación; registrar la denegación S3.
4. **Sesión de evidencias (≤ 3.5 h):** EV02–EV04, EV10 con la versión nueva, y la recuperación completa pendiente; después `stop`.

## Decisiones antes de la ventana 2

- **Fechas del catálogo:** el catálogo cloud se sembró el 3-oct con fechas relativas; el seed no modifica eventos existentes, y la interfaz ya oculta los pasados, así que la demo podría verse casi vacía. Opciones: actualizar fechas de los eventos demo sin reservas (cambio de datos cloud), o sembrar eventos nuevos.
- **Descripciones y fotos nuevas:** el seed no las aplica a eventos existentes. Se necesitan `update-demo-descriptions.py` y la asignación de 5 imágenes (cambio de datos cloud, solo `description`/`image_path`).

## Costos aproximados (estimaciones, no consumo observado)

| Concepto | Importe |
|---|---:|
| Ventana de actualización 2 h (EC2 + RDS + IPv4) | USD 0.09 (reserva USD 0.20) |
| Sesión de evidencias 3.5 h | ≤ USD 0.75 |
| Componentes persistentes (EBS, RDS, snapshot, S3, secreto, logs, alarma) | ≈ USD 0.21/día |
| Reinicio automático de RDS sin intervención | ≈ USD 0.43/día |
| Pronóstico histórico hasta el 26-nov | USD 10.7 (techo 13.7), por reconciliar con el panel |

## Riesgos principales

Credenciales del laboratorio que expiran a mitad de tarea; punto único de fallo (una EC2, RDS Single-AZ); DuckDNS/Let's Encrypt dependen de la IPv4 vigente; migraciones aditivas pero sin reversión de datos (por eso el respaldo previo); el plan puede proponer reemplazar la EC2 (no aplicar); capturas que filtren identificadores.
