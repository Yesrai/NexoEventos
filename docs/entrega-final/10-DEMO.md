# 10 · Demo local reproducible

**Todo lo de esta demo es LOCAL.** No toca ninguna nube, no cambia DNS, no pide contraseñas ni tokens. Durante la exposición se dice explícitamente «esto es local».

Requisitos: el entorno `backend/.venv` del repositorio (Python 3.12 con pytest, fastapi, httpx, argon2-cffi). Rutas absolutas del equipo de la propietaria:

```bash
REPO=/Users/yeseniaramirezmedina/Workspace/NexoEventos
OPS=/Users/yeseniaramirezmedina/Workspace/NexoEventos-codex-t7-t8
PY=$REPO/backend/.venv/bin/python
```

## 1. Anclaje anti-rollback del testigo (B-T6-1, LOCAL) — ≈ 1 s

```bash
cd "$REPO"
PYTHONDONTWRITEBYTECODE=1 $PY -m pytest -p no:cacheprovider scripts/multicloud/tests/test_witness_anchor.py -q
```
Esperado: `19 passed` (verificado el 23-nov-2026: 19 passed en 0,29 s). Qué mostrar: una restauración del almacén del testigo a un prefijo anterior se detecta (`RollbackDetected`).

## 2. Exploración exhaustiva G5 (LOCAL) — ≈ 2 min 11 s con longitud 5

```bash
cd "$REPO"
G5_LEN=5 PYTHONDONTWRITEBYTECODE=1 $PY -m pytest -p no:cacheprovider scripts/multicloud/tests/test_g5_single_writer_exhaustive.py -q
```
Esperado: `1 passed` (la ejecución registrada tardó 131,26 s: `docs/evidencias/T6-local/g5-exhaustivo-len5.txt`). Recorre 9^5 = 59.049 secuencias con dos actores AWS/OCI y comprueba que nunca hay dos escritores; incluye el control negativo sin anclaje. Para la exposición, la versión por defecto (`G5_LEN` sin definir = longitud 4, 6.561 secuencias) es más rápida.

## 3. Regresión local de `scripts/multicloud` (LOCAL)

```bash
cd "$REPO"
PYTHONDONTWRITEBYTECODE=1 $PY -m pytest -p no:cacheprovider scripts/multicloud -q
```
Última ejecución registrada por el frente T6 (UTC 2026-11-23T04:19:10Z): `704 passed, 66 subtests passed` en 686,9 s, exit 0; `backend/tests` 343 passed (`docs/evidencias/T6-local/regresion-final.txt`). **No re-ejecutada al preparar este paquete** (tarda ≈ 11 min); si se repite antes de la defensa, anotar la cifra real.

## 4. Interruptores en rojo (LOCAL, lectura de código)

```bash
cd "$REPO"
grep -n "REAL_EXECUTION_WIRED = \|REAL_WIRING_ENABLED = " ops_center/barriers.py scripts/multicloud/failover/real_factory.py
```
Esperado: ambos en `False`.

## 5. Pruebas de NexoOps (LOCAL)

```bash
cd "$OPS"
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. $PY -m pytest -p no:cacheprovider nexoops/tests -q
```
Verificado el 23-nov-2026: `66 passed` en la copia de trabajo (el commit `040f116` tenía 59; hay cambios sin confirmar de otro frente: `nexoops/app.py`, `config.py`, `static/app.js`, `tests/test_base_path.py`).

## 6. NexoOps en el navegador (LOCAL, puerto 8088)

La propietaria ya tiene NexoOps corriendo en local (`python -m nexoops serve --port 8088`, ver `NexoEventos-codex-t7-t8/docs/nexoops/README.md`). **La demo no pide ni muestra contraseñas, OTP ni tokens**: la propietaria inicia sesión ella misma antes de proyectar.

> Comprobación al preparar este documento: `http://127.0.0.1:8088/` **no respondió** (el servidor no estaba levantado en ese momento). Verificar antes de exponer con:
> ```bash
> curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8088/healthz
> ```

Recorrido sugerido (4 min, del README de NexoOps):
1. Sin sesión, `/api/overview` responde 401.
2. Overview: cada métrica con fuente, hora UTC y frescura; sin recolector, «No verificado».
3. Recuperación: barreras, ledger, época; failover/failback **bloqueados por diseño**.
4. Incidentes: una solicitud de reinicio queda **bloqueada** (no hay segunda persona aprobadora).
5. Auditoría: cadena de hashes íntegra con `request_id`.
6. NexoOps AI: hechos / hipótesis / recomendaciones (motor de reglas, no IA generativa).

## 7. Lo que la demo NO muestra

Ninguna ejecución en AWS, OCI o Azure; ningún failover; ningún cambio de DNS. Los resultados reales se muestran con sus informes (`08-INDICE-EVIDENCIAS.md`).
