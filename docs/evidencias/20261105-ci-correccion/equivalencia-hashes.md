# Equivalencia de hashes tras la reescritura de mensajes (5-nov-2026)

El 5-nov-2026 se reescribieron **solo los mensajes** de los 8 commits propios de `entregable2-auditoria` para quitar el trailer `Co-Authored-By` de Claude. **Árbol de archivos, autor, committer, fechas y orden quedaron idénticos** (comprobado commit por commit); solo cambiaron los hashes. `main` no se modificó (`42dd9e0`).

| Hash anterior | Hash actual | Asunto |
|---|---|---|
| `1331a74` | `ca983f1` | Auditoría del Entregable 2: TLS verify-full, health check liveness/readiness, … |
| `37fb2c9` | `088f9a8` | fix(security): dnspython 2.9.0 y parche de OpenSSL en la imagen |
| `aa23233` | `f8935fa` | docs: resultado real del CI del PR #1 |
| `610bcb0` | `dc05eb2` | Resiliencia y seguridad (sexta ronda): guardia ami_includes_livez, … |
| `054424b` | `e68db65` | Ronda integral: retención S3 separada de RDS, … |
| `c8092b6` | `303bb00` | Alarmas, monitoreo y Chaos Engineering: … |
| `a0f1703` | `3dc64e2` | docs(entregable2): consolidate verified multicloud evidence |
| `92f4b06` | `7755e48` | fix(ci): repair bootstrap test and patch Debian apt packages |

## Cómo leer las referencias a hashes antiguos en la documentación
Se **conservan** (no se sustituyen automáticamente) porque describen hechos históricos exactos; los resultados de CI de GitHub Actions están asociados al hash con el que se ejecutaron:
- Citan **resultados de ejecuciones de CI** (p. ej. «run del commit `37fb2c9`», «`a0f1703` falló 2 de 4 checks»): referencia histórica legítima; el run permanece en el historial de Actions bajo el hash antiguo.
- Citan el commit **desde el que se construyó un artefacto** (el paquete de la AMI de V2 se llama `nexoeventos-c8092b67…tar.gz`): referencia histórica legítima; el commit actual `303bb00` tiene el **mismo árbol**, por lo que el contenido es el mismo.
- La CI vigente se comprobó sobre `92f4b06` (4/4) y sobre `7755e48` (4/4, mismo árbol que el anterior).
Si algún día se prefiere actualizar los textos, esta tabla permite hacerlo sin ambigüedad.
