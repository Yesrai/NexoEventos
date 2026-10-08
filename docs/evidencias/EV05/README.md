# EV05 — EC2 y aplicación

Comprobado en AWS el 3 de octubre de 2026:

- Amazon Linux 2023 y Node.js 24.21.0;
- cliente PostgreSQL 18.6 compatible con RDS PostgreSQL 18.3;
- `nexoeventos-api.service`, Nginx y temporizadores DuckDNS/Certbot activos durante la prueba;
- FastAPI limitado a `127.0.0.1:8000`, con `/health` y `/ready` correctos;
- HTTPS público y catálogo servidos por Nginx;
- instalación y operación mediante Session Manager, sin abrir SSH.

La captura `public-home-2026-10-03.png` muestra el sitio real sin sesión, credenciales ni QR. Los recursos se detienen después de obtener respaldo y evidencias.

Lectura del 7 de octubre: Academy inició la EC2 a las 14:41 Lima; estaba `running`, `t3.small`, con IMDSv2 requerido. HTTPS `/` respondió 200 y el certificado vence el 1 de enero de 2027. El código remoto sigue en disposición legacy, anterior al rediseño local.
