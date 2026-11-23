"""Centro de operaciones de NexoEventos (se despliega en Azure; NO depende de AWS ni de la base de datos de la aplicación).

Qué hace: consulta de estado (reutilizando las secciones de solo lectura de `app.ops`), flujo de SOLICITUD → VALIDACIÓN → APROBACIÓN de recuperaciones y
auditoría encadenada de cada solicitud y decisión. Qué NO hace: ejecutar failover, cambiar DNS, habilitar escritores ni llamar a ninguna nube.
La ejecución real sigue siendo un acto humano posterior, bloqueado por `barriers.py` y por `REAL_EXECUTION_WIRED = False`.
"""
