# syntax=docker/dockerfile:1
# Imagen del backend FastAPI. Solo para desarrollo, pruebas y CI: el despliegue actual en AWS no usa contenedores.
# La base se fija por digest (índice multi-arquitectura); actualizar a propósito, no por sorpresa.
ARG PYTHON_IMAGE=python:3.12-slim-bookworm@sha256:34386ef0cb081344d7ec1c103ba398e6e9f64e9ab3a1509accc92a4e24a07258

FROM ${PYTHON_IMAGE} AS builder
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /build
# Dependencias exactas (incluidas las transitivas) del archivo de bloqueo de producción.
COPY requirements-production.lock ./
RUN python -m venv /opt/venv && /opt/venv/bin/pip install -r requirements-production.lock

FROM ${PYTHON_IMAGE}
ENV PATH=/opt/venv/bin:$PATH PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
# Parches de seguridad de Debian posteriores a la imagen base fijada: OpenSSL (CVE-2026-84782, corregida en 3.0.22-1~deb12u2) y APT (CVE-2026-109518, HIGH,
# ataque de intermediario en la actualización; corregida en 2.6.2 según Trivy). Solo estos paquetes (libssl3, openssl, apt y su biblioteca libapt-pkg6.0);
# cuando se actualice el digest de la base a uno que ya los incluya, este paso deja de hacer cambios.
RUN apt-get update \
 && apt-get install -y --no-install-recommends --only-upgrade libssl3 openssl apt libapt-pkg6.0 \
 && rm -rf /var/lib/apt/lists/*
# Usuario sin privilegios, sin shell ni directorio personal.
RUN groupadd --system --gid 10001 nexo \
 && useradd --system --uid 10001 --gid nexo --no-create-home --shell /usr/sbin/nologin nexo
WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./
USER 10001:10001
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD ["python", "-c", "import sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3).status == 200 else 1)"]
# Los secretos y la base de datos llegan por variables de entorno en tiempo de ejecución; nada se hornea en la imagen.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
