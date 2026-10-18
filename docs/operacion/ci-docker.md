# Docker, CI y Trivy

Solo desarrollo, pruebas y CI. **El despliegue en AWS no cambia** (sigue siendo EC2 + systemd + Ansible); nada de esto publica imágenes ni usa credenciales AWS.

## Archivos
| Archivo | Para qué |
|---|---|
| `backend/Dockerfile`, `backend/.dockerignore` | Imagen del backend: base `python:3.12-slim-bookworm` fijada por digest, dependencias exactas de `requirements-production.lock`, multi-etapa, usuario `10001` sin shell, `HEALTHCHECK` a `/health`, sin `.env` ni tests en la imagen |
| `docker-compose.yml`, `scripts/docker-dev.sh` | Backend + PostgreSQL 18 local con los mismos roles que producción; migración con `alembic upgrade head` |
| `.github/workflows/ci.yml` | Pruebas de backend y frontend, build, imagen Docker (sin publicar) y Trivy |
| `.trivyignore` | Excepciones de Trivy: vacío; cada una exigiría CVE, justificación, responsable y fecha de revisión |

## Uso local
```bash
scripts/docker-dev.sh up        # crea .env con una clave local (ignorado por Git), levanta DB, migra y arranca el backend
curl http://127.0.0.1:8001/health
scripts/docker-dev.sh down      # añadir -v borra también los datos locales
```
Protección contra apuntar a producción: la URL de la base está escrita en el Compose (solo al servicio `db`), no hay `env_file` ni se lee `DATABASE_URL` de tu shell, PostgreSQL solo se publica en `127.0.0.1` y el contenedor corre con sistema de archivos de solo lectura, sin capacidades y sin escalada de privilegios.

## Pipeline (4 trabajos, permisos `contents: read`, acciones fijadas por SHA)
1. **Backend:** PostgreSQL 18, dependencias del lock + `pytest`/`httpx` fijados, `alembic upgrade head`, `pytest`.
2. **Frontend:** Node de `.node-version`, `npm ci`, `npm test`, `npm run build`.
3. **Imagen Docker:** construye, comprueba usuario no root y estado `healthy`, y la analiza con Trivy.
4. **Trivy del repositorio:** `package-lock.json`, `requirements.txt` y secretos.

**Política de vulnerabilidades:** bloquea el pipeline cualquier hallazgo **HIGH o CRITICAL con corrección disponible** y cualquier secreto. Los no corregibles (`--ignore-unfixed`) siguen visibles en la tabla pero no bloquean. El análisis de configuración (Dockerfile, Compose, Terraform) es **informativo**: muestra hallazgos sin bloquear porque varios son decisiones V1 conocidas (egreso 443 abierto y IP pública de la EC2, cifrado S3 con claves administradas por AWS, RDS temporal de recuperación).

## Ver el pipeline en GitHub
El repositorio aún no tiene remoto. Para publicarlo (decisión tuya; recomendado **privado**, revisando antes que no haya datos sensibles):
```bash
gh repo create NexoEventos --private --source=. --push
```
Luego: pestaña **Actions** → ejecución **CI**; en cada trabajo, el **resumen** muestra las tablas de Trivy y los artefactos `trivy-imagen` y `trivy-repositorio` contienen el texto completo. En un pull request aparecen como comprobaciones. Se puede relanzar con **Run workflow** (`workflow_dispatch`).

## Límites conocidos
- No se probó en GitHub (sin remoto); se validó la sintaxis con `actionlint` y se ejecutaron localmente los mismos pasos (pruebas con PostgreSQL 18, build, arranque saludable y Trivy 0.76.0).
- Las acciones y las imágenes base están fijadas: actualizarlas es una tarea periódica deliberada.
- Trivy usa su base de vulnerabilidades en línea; un CVE nuevo puede hacer fallar un pipeline que antes pasaba (es el comportamiento buscado).
