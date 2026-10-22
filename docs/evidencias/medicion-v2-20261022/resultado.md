# Medición AWS V1 vs V2 (perfil mixto k6, mismos niveles, duraciones y criterios) · 22-oct-2026

V1: 1 EC2 `t3.small` (ejecución del 19-oct, `perf/results/aws-v1-aws2` y `aws-v1-aws3`). V2: ALB + 2 EC2 `t3.small` en 2 zonas (`perf/results/aws-v2-v2b`). Mismo generador (Mac del autor vía Internet), mismo código `311a830`/`d3e52e8`, RDS `db.t3.micro` compartida. Sin errores inesperados, sin violaciones de integridad y sin criterios de parada en ningún nivel; limpieza completa con huella idéntica.

| Usuarios | p95 V1 → V2 (ms) | p99 V1 → V2 (ms) | req/s V1 → V2 | CPU máx. 2 min V1 → V2 (por instancia) | Memoria libre mín. V1 → V2 (MB) | Conexiones PostgreSQL V1 → V2 |
|---:|---|---|---|---|---|---|
| 1 | 230 → 187 | 523 → 294 | 1,3 → 1,3 | 1,9 % → 1,0 / 1,0 % | 1 326 → 1 439 / 1 416 | 8 → 7 |
| 10 | 219 → 141 | 309 → 253 | 15,9 → 17,1 | 8,9 % → 5,3 / 5,0 % | 1 285 → 1 374 / 1 394 | 8 → 9 |
| 20 | 236 → 185 | 581 → 594 | 31,1 → 33,4 | 16,4 % → 9,7 / 8,6 % | 1 248 → 1 371 / 1 369 | 12 → 22 |
| 40 | 232 → 223 | 359 → 446 | 61,5 → 65,4 | 31,7 % → 17,5 / 17,4 % | 1 220 → 1 317 / 1 345 | 11 → 22 |
| 50 | 288 → 190 | 556 → 375 | 71,6 → 78,0 | 39,4 % → 20,4 / 19,8 % | 1 205 → 1 337 / 1 328 | 11 → 22 |

Reparto de solicitudes /api entre las dos instancias (log de Nginx): 50 % / 50 % en todos los niveles (`reparto-por-nivel.json`). ALB: 35 366 solicitudes, 0 errores 5xx (de destino y del ALB), p95 de respuesta del destino ≤ 0,20 s, 2 instancias sanas todo el tiempo. Créditos excedentes de CPU: 0. RDS: CPU máx. 15 %, memoria liberable mín. 128 MB (> 80 MB), conexiones máx. 22 de 81, créditos de CPU de la RDS mín. 68 (vigilar si se deja encendida).

Lectura: con el mismo tráfico, cada instancia de V2 trabaja a la mitad de CPU que la V1 y la latencia p95 baja o se mantiene; el rendimiento solo crece lo que permite el generador (≈ 1,4 req/s por usuario), por lo que 50 usuarios no saturan ni V1 ni V2. Las conexiones a PostgreSQL se duplican (22) y siguen muy por debajo del límite.

Notas: (1) V1 se mide con 1 instancia con créditos acumulados; V2 con instancias nuevas en modo `unlimited` (criterio sobre créditos excedentes). (2) El reparto por nivel ≥ 20 se recalculó después con un conteo en la propia instancia porque el volcado completo del log excede el límite de salida de Session Manager. (3) Incidencia: durante el reinicio del laboratorio, el ASG no pudo lanzar instancias (`Client.InternalError`) hasta ~15:10 UTC, cuando el laboratorio volvió a estar activo; un primer intento de esta escalera no generó tráfico por Docker apagado (`aws-v2-v2a-sin-docker`).
