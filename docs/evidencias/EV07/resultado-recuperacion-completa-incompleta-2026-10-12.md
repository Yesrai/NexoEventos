# Ensayo de recuperación completa — resultado incompleto

Ejecución aislada `20261011t1613`, cerrada el 12 de octubre de 2026. Este resultado **no sustituye R01** ni acredita recuperación completa del servicio.

## Resultado conservado

- El plan separado creó 11 recursos temporales: EC2, RDS restaurada, dos security groups y siete reglas; no cambió el estado principal.
- T0: 11-oct 16:14:37 UTC, antes del `apply`.
- Punto restaurado: 11-oct 00:14:20 UTC; desfase observado de 16 h 00 min 17 s, dentro del objetivo de RPO de 24 h.
- T1: 12-oct 02:58:55 UTC, EC2/RDS/SSM disponibles. La demora T0→T1 de 10 h 44 min 18 s incluye la interrupción real de la sesión y no representa solo provisión AWS.
- T2: 12-oct 03:07:18 UTC, Alembic `0005`, seis tablas, reservas sin huérfanos y 135/135 entradas QR descifrables. T1→T2: 8 min 23 s; T0→T2: 10 h 52 min 41 s.
- Las claves QR se recuperaron desde la copia externa protegida y los archivos finales fueron comprobados como `root:root 0600`; sus valores no se imprimieron.

## Punto donde terminó

El primer intento HTTP-01 no llegó a T3: al reactivarse el laboratorio, la EC2 temporal tenía una IPv4 pública nueva y el hostname temporal aún contenía la anterior. DNS y reglas 80/443 eran correctos para el valor antiguo, pero la autoridad certificadora agotó el tiempo de conexión. Se corrigió localmente la automatización para consultar la IPv4 actual y reutilizar los secretos al rotar exclusivamente el hostname temporal. Por cambio explícito de prioridad no se reintentó HTTPS ni se ejecutó el recorrido reserva → entrada → validación.

T3 y T4 no existen. Por tanto:

- recuperación de datos y claves dentro de este ensayo: verificada en T2;
- recuperación completa/RTO: **incompleta y no acreditada**;
- objetivo RTO ≤ 60 min: **no cumplido en esta ejecución**, incluso antes de T4.

## Cierre seguro

Terraform destruyó los 11 recursos del estado separado. La comprobación posterior informó estado administrado vacío, cero EC2/RDS temporales para el `RunId`, EC2 original `stopped` y RDS original `stopped`. Los respaldos, snapshot, evidencias históricas e infraestructura original se conservaron.

El costo no fue observado en facturación. Como cota conservadora, 21.4 h al máximo temporal documentado de USD 0.0492/h serían aproximadamente USD 1.05; el cómputo real puede ser menor por los períodos en que el laboratorio o la instancia estuvieron detenidos. No es un límite ni un cargo confirmado.
