# CI en GitHub Actions: ejecuciones reales (consulta de solo lectura, 29-oct-2026)

Procedencia: `gh run list` y `gh run view` sobre el repositorio privado del proyecto (sin URLs ni usuario). Workflow `.github/workflows/ci.yml` (disparadores: `pull_request`, `push` a `main`, `workflow_dispatch`).

| Dato | Valor |
|---|---|
| Ejecuciones del workflow CI | **31** (19-oct 03:47Z → 23-oct 20:07Z) |
| Resultado | **30 exitosas, 1 fallida** |
| Última ejecución | commit `42dd9e0` (= HEAD actual), `success`, 1 min 28 s (23-oct 20:07–20:09Z) |
| Jobs de la última ejecución (todos `success`) | Backend (pytest + PostgreSQL 18) · Frontend (pruebas + build) · Imagen Docker + Trivy · Trivy (dependencias, secretos y configuración) |

**Qué valida realmente:** pruebas del backend con PostgreSQL 18, pruebas y build del frontend, construcción de la imagen y Trivy (vulnerabilidades HIGH/CRITICAL con corrección y cualquier secreto, bloqueante).
**Qué NO hace:** no despliega (sin CD), no usa credenciales de nube, no ejecuta `terraform validate` ni `check-iac-security.py` (se corren en local), no prueba contra AWS.
**Límites:** las 47 modificaciones locales posteriores al commit `42dd9e0` (incluida la política TLS de la base) **no se han ejecutado en CI** porque no se ha hecho commit ni push; eso requiere autorización. No se inspeccionó el motivo de la ejecución fallida.
**Pendiente (captura):** una captura de la pestaña Actions de GitHub, si el docente la pide.

Verificación local equivalente (29-oct): backend 52/52 (`pytest`, 8 pruebas nuevas), frontend 33/33 (`vitest`), YAML del workflow válido.
