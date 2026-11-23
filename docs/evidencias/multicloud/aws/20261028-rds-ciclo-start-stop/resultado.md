# Ciclo controlado start → available → stop de la RDS (28-oct-2026)

Objetivo: renovar el plazo de 7 días de detención (el reinicio automático caía hacia 2026-10-30T15:18Z). Solo estados y tiempos; sin consultas de datos ni cambios de configuración. Instancia: `nexoeventos-academy-postgres` (única RDS de la cuenta), us-east-1, Multi-AZ, db.t3.micro.

| Hora UTC | Estado / evento |
|---|---|
| 21:35:13 | Preflight: `stopped`, sin modificaciones pendientes; EC2 `stopped` |
| 21:35:29 | Orden `start-db-instance` |
| 21:39:55 | Evento «DB instance started» |
| 21:41:11 | `available` (≈ 5 min 42 s tras la orden) |
| 21:41:14–21:43:47 | `backing-up`: copia automática posterior al inicio |
| 21:41:xx | Primer intento de `stop-db-instance` **rechazado** (`InvalidDBInstanceState`: no estaba `available`); sin efecto |
| 21:43:49 | `available` de nuevo |
| 21:43:57 | Segunda orden `stop-db-instance` (única reintentada, autorizada) |
| 21:51:22 | Evento «DB instance stopped»; estado `stopped` a las 21:51:26 |

- Tiempo encendida: ≈ 16 min (21:35:29 → 21:51:22); costo estimado ≈ 0,01–0,02 USD (Multi-AZ db.t3.micro), **no verificado** con facturación (no se usó Cost Explorer).
- Nuevo reinicio automático previsto: ≈ **2026-11-04T21:51Z** (7 días tras la parada; hora exacta variable). Ya no es riesgo del 30-oct.
- Aviso de AWS durante el ciclo: «Storage size 20 GiB is approaching the maximum storage threshold 20 GiB» (evento 21:45:19Z). No se cambió nada; queda como observación (autoescalado con umbral máximo = 20 GiB).
- Sin modificar otras instancias; EC2 sigue `stopped`.
