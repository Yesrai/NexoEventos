# Imagen del servicio testigo (Cloud Run). Contexto de construcción: la RAÍZ del repositorio. Sin credenciales dentro de la imagen.
FROM python:3.12-slim
RUN useradd --system --create-home --uid 10001 witness
WORKDIR /srv
RUN pip install --no-cache-dir "cryptography==50.0.0"
# (Cloud Run real: añadir google-cloud-storage y google-cloud-kms; en el contenedor local no hacen falta)
COPY backend/app/__init__.py /srv/backend/app/__init__.py
COPY backend/app/failover /srv/backend/app/failover
COPY scripts/multicloud/witness/witness_service.py /srv/witness_service.py
ENV PYTHONPATH=/srv/backend PYTHONUNBUFFERED=1 PORT=8080
USER witness
EXPOSE 8080
HEALTHCHECK --interval=10s --timeout=3s CMD python -c "import urllib.request,os;urllib.request.urlopen('http://127.0.0.1:%s/healthz'%os.environ.get('PORT','8080'))"
CMD ["python", "/srv/witness_service.py"]
