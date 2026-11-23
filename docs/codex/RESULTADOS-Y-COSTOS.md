# Resultados y costos

## Resultados medidos

| Etapa | Resultado | Métricas destacadas | Fuente |
|---|---|---|---|
| T1 | PASS 12/12 | CAS 20/20; lease 20/20; p95 PUT 0,414 s; 0 residuos | `T1-20261122-resultado.md` |
| T2 | PASS 13/13 | Propagación A→B 62,1 s; reversión 62,0 s; producción intacta | `T2-20261122-resultado.md` |
| T3 | PASS 19/19 | Aplicación 11 recursos; humo 11/11 + 23/23; inventario final idéntico | `T3-20261122-intento3-resultado.md` |
| T4 | PASS 18/18 | 38 ciclos/2315 s; hueco máx. 67 s; alerta y correo; 0 OOM | `T4-20261122-resultado.md` |
| T5 | PASS 9/9 | 99,49 %; detección 9,6 s; recuperación 125 s; 6 instancias | `T5-20261123-resultado.md` |

## Costos: observado frente a estimado

| Concepto | Costo observado en factura | Estimación del expediente | Clasificación |
|---|---:|---:|---|
| T1 OCI | No consultado | USD 0 | Operación dentro del alcance gratuito; no es extracto de facturación. |
| T2 DuckDNS | No aplicable | USD 0 | Servicio sin cargo en la prueba. |
| T3 OCI | No consultado | USD 0 | Recursos Always Free y destruidos; no equivale a factura. |
| T4 Azure (55 min) | No consultado | ≈ USD 0,21 | Tarifa estimada; umbral USD 1,50. |
| T5 AWS + Azure | No consultado | ≈ USD 0,29 | Cota de la ventana; umbral USD 1,50. |
| **T1–T5 total citado** | **No disponible** | **≈ USD 0,50** | Suma de estimaciones de expedientes, no costo facturado. |

## Escenarios de operación (estimados, no facturación)

| Escenario | Estimación | Fuente/límite |
|---|---:|---|
| AWS V2 económico | ≈ USD 0,13/h | Dos instancias; T5 mostró 95,21 % bajo la prueba aplicada. |
| AWS V2 alta disponibilidad | ≈ USD 0,26/h | Seis instancias; una ejecución T5 alcanzó 99,49 %. |
| Arquitectura académica 24×7 del informe previo | ≈ USD 101,7/mes | `docs/entregable2/informe-entregable2.md`; tarifas públicas, sin créditos/impuestos. |
| Azure desasignada con disco + IP | ≈ USD 0,30/día | Estimación documentada; verificar Cost Management antes de presentarla como real. |

No se afirma un costo real acumulado porque no existe evidencia versionada de facturación para estas ventanas. En exposición debe decirse “estimado según tarifas/expediente”, nunca “cobrado”.

