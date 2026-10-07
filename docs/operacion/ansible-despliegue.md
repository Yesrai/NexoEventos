# Actualización versionada de la EC2 con Ansible

Preparado y validado localmente el **7 de octubre de 2026**. No se ha ejecutado contra AWS. La V1 desplegada continúa ejecutando el commit documentado el 3 de octubre; el frontend y los ajustes locales posteriores **no están sincronizados** con la EC2.

## Alcance de la ventana de actualización

1. Renovar una sola vez el bloque completo de Academy y ejecutar `scripts/ansible-aws.sh preflight`.
2. Confirmar cuenta/región ocultas, una sola EC2 `nexoeventos-academy-app`, SSM `Online` y acceso al bucket privado.
3. Crear desde un commit limpio un artefacto protegido con `scripts/build-release.sh`.
4. Desplegar en `/opt/nexoeventos-deploy/releases/<commit>`, conservar `previous`, cambiar `current`, reiniciar FastAPI y recargar Nginx.
5. Exigir `/ready = 200`; si falla, restaurar el enlace anterior y reiniciar el servicio.
6. Comprobar por HTTPS registro → acceso → reserva simulada → entrada → validación única, sin capturar QR ni datos privados.

No crea infraestructura ni abre SSH. No lee ni reemplaza `/etc/nexoeventos/backend.env`, `/etc/nexoeventos/duckdns.env`, las claves QR, `/etc/letsencrypt` o la base. Solo comprueba que el entorno del backend y el certificado existan. Las migraciones no se ejecutan automáticamente: deben revisarse y ejecutarse con el usuario migrador separado antes de una revisión que las requiera.

## Comandos, después de revisar el alcance

```bash
./scripts/ansible-aws.sh preflight
NEXO_ALLOW_CLOUD_CHANGES=YES ./scripts/ansible-aws.sh deploy
# Solo si la validación funcional posterior exige una reversión manual:
NEXO_ALLOW_CLOUD_CHANGES=YES ./scripts/ansible-aws.sh rollback
```

La conexión usa `amazon.aws.aws_ssm`, no SSH. Requisitos del controlador: AWS CLI, Ansible Core, colección `amazon.aws` 10.1.2, `boto3`/`botocore` y el ejecutable Session Manager Plugin. El 7 de octubre se comprobaron Ansible 2.19.3, la colección y sus bibliotecas; **Session Manager Plugin no está instalado**, por lo que la conexión real está bloqueada y no se instaló nada automáticamente. Véanse los requisitos oficiales del [plugin de conexión Ansible](https://docs.ansible.com/projects/ansible/latest/collections/amazon/aws/aws_ssm_connection.html) y la [instalación oficial en macOS](https://docs.aws.amazon.com/systems-manager/latest/userguide/install-plugin-macos-overview.html).

La conexión Ansible por SSM requiere S3 incluso para módulos simples y permisos `GetObject`, `PutObject`, `ListBucket`, `DeleteObject` y `GetBucketLocation`. El preflight de solo lectura confirma el bucket, pero no demuestra `PutObject`/`DeleteObject`; la primera ejecución puede quedar bloqueada y deberá registrar el error sin ampliar IAM. Se propone reutilizar el bucket privado existente, pero está versionado: Ansible borra los objetos visibles y las versiones no actuales pueden permanecer. No se transfieren secretos ni archivos `/etc/nexoeventos`; sí pueden quedar versiones del código/los módulos y generar almacenamiento mínimo. Una ejecución real deberá registrar este efecto y decidir entre una regla de lifecycle específica o un bucket temporal no versionado mediante un plan separado. La denegación conocida de Object Lock no demuestra que esos permisos de objetos estén denegados.

## Artefacto y reversión

`scripts/build-release.sh` exige un árbol rastreado limpio, ejecuta `npm ci` y el build, empaqueta exactamente `HEAD` más `frontend/dist`, y guarda artefacto/hash en `work/releases/` (ignorado, modo restrictivo). `current` y `previous` apuntan a revisiones completas; Nginx y systemd siempre consumen `current`. La configuración Nginx candidata se valida antes de instalarse.

La reversión restaura código y frontend, no datos. Una migración destructiva exige un plan de reversión propio; por eso no se incluye en el playbook general.

## Costo de la ventana

Sin recursos nuevos: dos horas de EC2 `t3.small` + RDS `db.t3.micro` + IPv4 son **USD 0.0876** con las tarifas de `docs/costos-v1.md`. Se reserva un margen de **USD 0.20** para logs, solicitudes S3 y demoras. Es una estimación, no un límite ni consumo observado. Los componentes persistentes siguen cobrando aparte.

## Evidencia esperada

- commit y SHA-256 del artefacto, sin publicar el artefacto;
- recap de Ansible sin variables sensibles;
- `systemctl is-active`, `nginx -t`, `/ready` y HTTPS;
- versión anterior/nueva expresadas por commit, sin IDs de cuenta;
- prueba funcional sanitizada y, al terminar, estados EC2/RDS.
