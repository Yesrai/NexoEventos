# Corrección de los 2 fallos del CI del commit `a0f1703` (5-nov-2026) — verificación LOCAL; el CI real aún no se ha repetido

## Fallos observados en GitHub Actions (run del commit `a0f1703`)
| Job | Fallo | Causa |
|---|---|---|
| Backend (pytest + PostgreSQL 18) | 1 prueba fallida de 97: `test_v2_bootstrap.py::test_bootstrap_installs_only_pinned_ca_and_rewrites_database_url_for_verify_full` («line 101: …/backend/.venv/bin/python: No such file») | **Error de la propia prueba**: fijaba la ruta local `backend/.venv/bin/python`, que no existe en el runner de CI |
| Imagen Docker + Trivy (imagen) | `exit code 1`: **2 hallazgos HIGH con corrección disponible** en Debian 12.15: paquetes **`apt` y `libapt-pkg6.0` 2.6.1 → CVE-2026-109518 (HIGH), corregido en 2.6.2** (ataque de intermediario en la actualización de paquetes) | Avisos nuevos posteriores a la imagen base fijada por digest; no es código del proyecto |
Frontend y Trivy de dependencias/secretos/configuración: en verde.

## Correcciones aplicadas (sin ocultar ni desactivar nada)
1. `backend/tests/test_v2_bootstrap.py`: la prueba usa `sys.executable` (el intérprete que ejecuta pytest) en vez de una ruta fija.
2. `backend/Dockerfile`: el paso que ya parcheaba OpenSSL ahora hace `--only-upgrade libssl3 openssl apt libapt-pkg6.0` (solo esos paquetes; la base sigue fijada por digest; se deja de aplicar cuando la base los incluya). **No se tocó `.trivyignore`** (0 entradas activas) **ni la configuración de Trivy** (HIGH/CRITICAL con corrección bloquean).

## Verificación local (sin CI)
- `pytest backend/tests`: **97 pasadas** (y 0 referencias a `.venv` en la prueba).
- Imagen construida con el Dockerfile corregido (arm64 en el equipo; el CI usa amd64): `apt` y `libapt-pkg6.0` **2.6.2** (≥ versión corregida), `openssl`/`libssl3` 3.0.22-1~deb12u2, usuario `10001` sin privilegios.
- **Trivy 0.76.0 (misma versión y parámetros del CI: `vuln,secret`, HIGH/CRITICAL, `--ignore-unfixed`, `--exit-code 1`) sobre la imagen corregida: exit 0**, sin hallazgos.
- Límite: la arquitectura local (arm64) difiere de la del CI (amd64); la confirmación definitiva es el CI de GitHub tras publicar. **No se declara el CI en verde hasta verlo.**
