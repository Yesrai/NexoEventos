# Pruebas de rendimiento e integridad (k6, solo entorno local)

Reproducibles, sin AWS, con datos ficticios en la base de pruebas del Compose (`127.0.0.1:55432`). Los scripts **rechazan** cualquier otro host.

```bash
scripts/docker-dev.sh up                                   # backend + PostgreSQL 18 aislados
python3 perf/run_local.py --profile smoke                  # validación rápida (≈ 2 min)
python3 perf/run_local.py --profile progressive            # carga progresiva limitada, máx. 50 VUs (≈ 10 min)
python3 perf/run_local.py --scenarios same_seat --label mi-prueba
```
k6 se ejecuta con la imagen `grafana/k6:2.3.0` (sin instalar nada global). Resultados ligeros en `perf/results/<etiqueta>/` (`<escenario>.json` + `summary.json`, esquema `schema: 1`), pensados para comparar V1/V2 con el mismo formato.

## Escenarios (`perf/k6/nexo.js`)
| Escenario | Qué hace |
|---|---|
| `catalog` | `GET /api/events` |
| `detail` | `GET /api/events/{id}` de eventos del catálogo demo |
| `availability` | detalle de eventos con asientos numerados (inventario de zonas y asientos) + estado de ventas |
| `reserve` | usuarios ficticios registrados y autenticados: reservas de zona, entrada general y asiento, repetición idempotente, «mis entradas» |
| `same_seat` | 50 usuarios intentan el **mismo asiento** casi a la vez, en 20 oleadas (un asiento por oleada) |

El fixture (`perf/fixture.py`) crea los eventos `90001–90004` (cupos enormes para no agotarse y 20 asientos para la disputa) y los recrea en cada ejecución; no toca otros datos.

## Criterios de aceptación
| Criterio | Umbral |
|---|---|
| Latencia p95 de las solicitudes (global y de la reserva) | < 2 000 ms (objetivo del proyecto, E01). La latencia del inicio de sesión se informa aparte: es CPU (Argon2) y no es un umbral |
| Tasa de solicitudes fallidas inesperadas | < 1 % |
| Errores inesperados (5xx, 4xx no esperados, 409 por otro motivo) | 0 |
| Disputa por el mismo asiento | exactamente 1 ganador por asiento; el resto, 409 «ya no están disponibles»; 0 errores del servidor |
| Repetición con la misma `Idempotency-Key` | devuelve la misma reserva y no crea otra |
| Integridad en PostgreSQL (`perf/check_integrity.py`) | 0 violaciones en las 11 comprobaciones (asiento con más de una entrada, asiento ocupado sin entrada, contadores de evento/zona distintos de las entradas, sobreventa de evento o zona, claves de idempotencia duplicadas, reservas sin entradas…) |

**Conflicto esperado:** `409` con «ya no están disponibles» o «No hay cupos». Todo lo demás distinto de 2xx es error inesperado.

## Límites
Los resultados locales (un Mac, un worker de uvicorn, PostgreSQL en contenedor) **no equivalen** a la EC2 `t3.small` + RDS de AWS: sirven para validar la lógica, la integridad y para fijar una base reproducible. Las pruebas de 100, 500 y 1 000 usuarios y la comparación V1/V2 se harán en AWS con autorización y control de presupuesto.

## Nube (AWS V1): `run_cloud.py`
No se ejecuta sin autorización. Un peldaño por invocación (`smoke`, `10`, `20`, `40`, `50` usuarios), guardas en la cabecera del script, SQL del fixture y su limpieza con `perf/cloud_fixture.py up|down` (se ejecuta en la EC2 con la identidad migradora). `--plan` muestra el plan sin generar tráfico; `--local-rehearsal` solo admite 127.0.0.1. La integridad (`check_integrity.py`) se ejecuta en la EC2 y los resultados llevan `metrics_window_utc` para consultar CloudWatch con la misma ventana.
