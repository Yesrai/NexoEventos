# T6 — Bloqueos obligatorios (registrados el 22-nov-2026, al cerrar T4). **No se consideran resueltos sin una prueba real.**
T6 (failover real AWS→OCI) **no puede iniciarse** mientras cualquiera de estos bloqueos siga abierto. Ninguno se cierra con pruebas locales, simuladas ni con una declaración: cada uno exige la prueba real indicada, con evidencia (UTC, logs, criterio escrito antes).

## B-T6-1 · Persistencia del testigo (límite medido en T4) — ABIERTO
- **Qué se demostró (T4, real, en la VM de Azure):** autenticación por alcance (401/403/200), firma verificada con la clave pública anclada, estado conservado tras reiniciar el servicio, 27 pruebas del perfil Azure como usuario sin privilegios (kill -9, exclusividad, almacén alterado, cola truncada, sin permiso de escritura).
- **Qué NO está resuelto:** con el almacén en un **archivo local**, un **prefijo restaurado** (volver a una copia anterior válida del archivo) **no se detecta localmente**; por eso este perfil NO cumple `independent_infrastructure_validated` y no se declara «independencia validada». Tampoco se ha demostrado un testigo con almacén inmutable/WORM ni un quórum de testigos.
- **Prueba real exigida antes de T6:** (a) anclar la cabeza de la cadena (secuencia + hash) FUERA de la VM —en un almacén de solo adición con retención (p. ej. Object Storage de OCI con regla de retención) o en un segundo testigo— y demostrar con un caso real que una restauración a un prefijo anterior **se detecta**; (b) repetir la prueba de reinicio con el testigo **inicializado** (genesis real con las claves públicas de los informantes, hoy sin dueño); (c) medir la latencia real de atestación desde AWS y OCI.
- **Hoy:** el testigo está SIN INICIALIZAR y sin dueño (claves de informantes descartadas): nadie puede informar.

## B-T6-2 · Barreras contra el doble escritor — ABIERTAS
Lo demostrado es local/simulado (400 escenarios, dos PostgreSQL locales, `test_two_db_*`). Lo que sigue **sin prueba real**:
| # | Barrera pendiente | Prueba real exigida | Estado |
|---|---|---|---|
| D1 | Vallado fuerte en una **RDS real** (`validated_on_real_rds=false`): compuerta de escritura de la API de AWS en modo `enforce` y vallado de base «require» **desplegados** | demostrar en AWS real que, tras perder la autoridad, la API ya no confirma escrituras (0 respuestas 201) | abierto (hoy `REAL_WIRING_ENABLED=False`) |
| D2 | **Sello antirretroceso (WORM) en OCI real** | rechazo real de un sello retrocedido | abierto |
| D3 | **Lease real entre nubes** con latencia/atomicidad medidas | T1 midió el lease con PAR (PASS); falta el ciclo completo con AWS y OCI como actores | parcial (T1) |
| D4 | **Standby de OCI con compuerta**: la aplicación de OCI en modo standby con `WRITE_GATE_MODE` en `enforce`, lease y `fenced_db`; hoy `install-app.sh` solo instala la variante de solo lectura | desplegar y demostrar que OCI no escribe hasta tener el lease | abierto |
| D5 | **Clientes con DNS en caché** que siguen escribiendo en AWS | verificación por efecto: 0 respuestas 201 desde AWS tras la toma | abierto |
| D6 | **Pausas de VM y deriva de reloj reales** (el control negativo documenta que una pausa mayor que el presupuesto rompe la garantía) | medirlas con el lease real y registrar | abierto |
| D7 | **Cancelación y aborto limpio reales** (cancelar tras el lease y antes de `ENABLE_STANDBY`; standby no listo ⇒ aborta sin DNS) | simulacros reales con adaptadores en `dry_run=True` (T6.0) | abierto |
| D8 | **Failback manual real** con vallado del escritor de OCI primero | procedimiento ejecutado y medido (cierre de T6) | abierto |
Barreras de software que siguen en rojo a propósito: `REAL_EXECUTION_WIRED=False` (B11) y `REAL_WIRING_ENABLED=False`; solo un cambio de código revisado y una autorización específica con frase las cambian.

## Regla
Antes de pedir la autorización de T6 se presentará esta tabla actualizada con la prueba real de cada fila cerrada (o cerrada con su evidencia en T5/T4/T-previa). Una fila sin evidencia real mantiene T6 bloqueado. Orden T1–T8 sin cambios.
