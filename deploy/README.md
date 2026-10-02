# Despliegue de aplicación en EC2

Esta carpeta prepara el despliegue, pero no demuestra que HTTPS esté operativo. Falta decidir un dominio, dirigir su registro DNS a la IPv4 pública y emitir un certificado válido antes de exponer el inicio de sesión.

## Componentes

- Nginx sirve `frontend/dist` y reenvía `/api` a FastAPI por loopback.
- systemd ejecuta Uvicorn sin `--reload`, con dos workers y reinicio ante fallo.
- `/healthz` consulta la preparación de PostgreSQL y devuelve únicamente un estado genérico.
- La cookie de sesión debe llevar `Secure` y los orígenes deben enumerarse como HTTPS en el archivo de entorno de producción.

## Preparación de una instancia autorizada

1. Crear el usuario de sistema `nexoeventos` sin acceso administrativo interactivo.
2. Copiar una versión identificada del repositorio a `/opt/nexoeventos` y compilar el frontend con Node 24 usando `VITE_API_URL=`.
3. Crear el entorno virtual del backend desde `backend/requirements.txt`.
4. Guardar `/etc/nexoeventos/backend.env` como `root:root` y modo `0600`. Sus valores deben provenir del mecanismo de secretos aprobado; no copiar el archivo local `.env`.
5. Ejecutar una sola vez `scripts/provision-database-roles.py` con `MIGRATION_DATABASE_URL`; solicita la contraseña del usuario limitado sin imprimirla. Después ejecutar Alembic con esa misma identidad de migraciones, separada de `nexoeventos_app`.
6. Instalar la unidad systemd y comprobar `systemctl is-active nexoeventos-api` y `curl --fail http://127.0.0.1:8000/ready`.
7. Emitir el certificado solo después de disponer del dominio. Sustituir `${DOMAIN}` en la plantilla de Nginx, validar con `nginx -t` y recién entonces habilitar el virtual host HTTPS.

No se debe abrir el puerto 8000 ni PostgreSQL a Internet. El SG web admite 443 y, temporalmente, 80 para redirección o validación ACME. La administración por 22 se limita a la IP autorizada `/32`, o se reemplaza por SSM si el laboratorio lo permite.

## Logs

Uvicorn se inicia sin access log. Los eventos propios no incluyen contraseñas, cookies, claves de sesión ni tokens QR completos. Nginx registra solicitudes estándar; no deben incorporarse credenciales en URL o query string. CloudWatch debe recoger únicamente `journalctl` de la unidad y los logs de Nginx con retención limitada.
