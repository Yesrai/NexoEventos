# Registro de trabajo T7–T8 (Codex)

Rama de trabajo: `codex/t7-t8`  
Worktree: `NexoEventos-codex-t7-t8`  
Regla de evidencia: un resultado local no se presenta como prueba cloud. T6 permanece pendiente hasta que exista un expediente real aprobado.

## 2026-11-23T03:16:09Z — aislamiento e inventario documental

| Campo | Registro |
|---|---|
| Objetivo | Aislar T7/T8, leer criterios T1–T8 y localizar expedientes versionados. |
| Archivos modificados | `docs/codex/*.md` (borradores T8). |
| Implementación | Se creó una estructura de entrega que separa hechos medidos, pruebas locales, estimaciones, pendientes y bloqueos. |
| Comandos | `git worktree list --porcelain`; `git status --short`; lectura de `ops_center/criterios/T*.json`; búsqueda y lectura de `docs/evidencias/T*-resultado.md`; inspección de `docs/nexoops/*`. |
| Resultado | T1 12/12, T2 13/13, T3 19/19, T4 18/18 y T5 9/9 tienen informes versionados; se conservaron los intentos fallidos. T6 no tiene PASS y sigue pendiente. |
| Evidencias | `docs/evidencias/T1-20261122-resultado.md`, `T2-20261122-resultado.md`, `T3-20261122-intento3-resultado.md`, `T4-20261122-resultado.md`, `T5-20261123-resultado.md`. |
| Limitaciones | Los expedientes completos bajo `work/evidencias/` no están versionados. No se consultó ninguna nube ni facturación. |
| Estado | **PASS** (inspección local y trazabilidad documental). |
| Commit | Pendiente; no se creó commit durante esta entrada. |

## Historial que debe conservarse

- T1: primera ejecución FAIL por `NameError`; segunda ejecución PASS 12/12.
- T2: primera ejecución FAIL por almacén de CA ausente; segunda ejecución PASS 13/13 con TLS verificado.
- T3: intentos 1 y 2 FAIL; intento 3 PASS 19/19. El tiempo medido es reconstrucción OCI, no RTO de failover.
- T5: primer intento FAIL (95,21 % con dos instancias), segundo abortado por SCP, tercero PASS 9/9 con seis instancias. El PASS corresponde a una única ejecución con parada controlada y tráfico de solo lectura.

## Plantilla para las siguientes entradas

```text
## AAAA-MM-DDTHH:MM:SSZ — título
Objetivo:
Archivos modificados:
Implementación:
Comandos de prueba:
Resultados (incluidos fallos):
Evidencias:
Limitaciones:
Estado: PASS | FAIL | BLOCKED | NOT_TESTED
Commit local:
```

