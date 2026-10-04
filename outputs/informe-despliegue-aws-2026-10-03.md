# Informe de despliegue AWS — 3 de octubre de 2026

## Resultado

La arquitectura V1 aprobada se desplegó en `us-east-1`. El estado Terraform protegido contiene los 30 recursos administrados del plan: VPC, subred pública, dos subredes privadas de datos, rutas, grupos de seguridad, EC2, RDS PostgreSQL, bucket S3 privado, perfil de instancia, CloudWatch y alarma. No se ejecutó `destroy` ni se abrió SSH.

La aplicación estuvo disponible durante la verificación en `https://nexoeventos-demo.duckdns.org`. Al terminar respaldos y evidencias, AWS confirmó EC2 y RDS en estado `stopped`; por ello la URL está temporalmente fuera de servicio.

## Instalación y seguridad comprobadas

- EC2 usa Amazon Linux 2023 y administración por Session Manager.
- FastAPI corre mediante systemd como usuario `nexoeventos`, sin privilegios, sin `--reload` y escuchando solo en `127.0.0.1:8000`.
- Nginx sirve el frontend React compilado y actúa como proxy HTTPS.
- DuckDNS se actualiza mediante timer; el token se lee de un archivo `root:root 0600` y no aparece en argumentos ni evidencias.
- Let's Encrypt emitió el certificado del dominio, válido desde el 3 de octubre de 2026 hasta el 1 de enero de 2027; el timer de renovación quedó activo.
- Los archivos `backend.env`, `migration.env`, `duckdns.env` y `demo-accounts.env` son `root:root 0600`.
- El rol de instancia pudo leer el secreto maestro administrado por RDS. Esa credencial se usó en memoria y no quedó en la configuración de la aplicación.
- Los roles `nexoeventos_owner`, `nexoeventos_migrator` y `nexoeventos_app` no tienen `SUPERUSER`, `CREATEDB`, `CREATEROLE`, `REPLICATION` ni `BYPASSRLS`; `owner` no permite login.

## Datos y migraciones

RDS ejecuta PostgreSQL 18.3. La EC2 utiliza el cliente 18.6 del repositorio oficial de AL2023. Alembic aplicó las revisiones `0001`, `0002` y `0003` con la identidad de migración; FastAPI se conectó con el usuario limitado de aplicación. La persistencia de reserva y entrada se confirmó después de reiniciar el servicio API.

Las cuentas ficticias de organizador y operador se aprovisionaron mediante el procedimiento explícito `--deployed-demo`. Sus contraseñas son aleatorias y solo residen en `/etc/nexoeventos/demo-accounts.env`; no se incluyen aquí. Para probarlas, se recuperan personalmente en una sesión autorizada de Session Manager, sin capturas ni pegarlas en chats.

## Suite pública ejecutada

Todas las comprobaciones siguientes pasaron contra la URL HTTPS real:

1. ruta privada sin sesión: `401`;
2. intento de asignar rol durante registro público: `422`;
3. registro de cliente y cookie `Secure`/`HttpOnly`: `201`;
4. reserva y creación de una entrada: `201`;
5. repetición con la misma clave de idempotencia: `200`, sin otra entrada;
6. consulta de entrada por su propietario: `200`;
7. inicio de sesión del operador: `200`;
8. operador no asignado a otro evento: `403`;
9. QR inexistente: `404`;
10. dos validaciones simultáneas: exactamente un `200` y un `409`;
11. entrada ya utilizada: `409`;
12. token QR completo ausente del log de API;
13. cierre de sesión: `204`, seguido por `401`;
14. reserva y entrada persistentes después de reiniciar FastAPI.

La cámara no fue probada en un dispositivo físico. La alternativa manual por código sí quedó comprobada.

## Respaldos

- Las claves de cifrado QR y hash se cifraron en EC2 con una clave pública RSA y se copiaron al Mac fuera del repositorio y de AWS. La clave privada permanece `0600` bajo FileVault.
- Se creó un dump PostgreSQL con cliente 18.6, empaquetado mediante CMS cifrado.
- El paquete se cargó en el bucket S3 privado, cifrado y versionado, y se descargó una copia externa `0600`.
- Se verificaron hash, descifrado y estructura interna sin mostrar datos.
- Se confirmó `available` un snapshot manual RDS cifrado de 20 GiB antes de detener RDS.

Sigue pendiente un ensayo de restauración cloud aislado y cronometrado. No se declara cumplido el RTO/RPO.

## Limitaciones reales

- La política del Learner Lab deniega `s3:GetBucketObjectLockConfiguration`; el bucket tuvo que completarse con un plan objetivo sin reemplazarlo. Un refresh general puede volver a fallar por esa lectura.
- La AMI se selecciona con `most_recent`; un plan futuro puede proponer reemplazar EC2 aunque no cambie la intención arquitectónica. Debe revisarse antes de cualquier aplicación.
- RDS emitió una advertencia porque el máximo de autoescalado coincide con los 20 GiB asignados. No se modificó durante esta sesión; debe corregirse mediante un plan revisado antes de depender del autoescalado.
- Detener EC2 y RDS no elimina cargos de EBS, almacenamiento RDS/backups, S3, logs, secreto administrado ni snapshot.
- Las cuentas de demo no son un mecanismo de administración para producción.
- La infraestructura y la aplicación son una demostración académica; no están declaradas listas para producción.
