# Actualización versionada de la EC2 con Ansible

Preparado y ejecutado por SSM el **7 de octubre de 2026**. La V1 quedó sincronizada con el commit `7955e7e`: frontend público, FastAPI y Alembic `0005` fueron comprobados por HTTPS. El 9-oct la usuaria informó apagado de AWS por falta de tokens; los estados finales no pudieron revalidarse por API.

## Alcance de la ventana de actualización

1. Renovar una sola vez el bloque completo de Academy y ejecutar `scripts/ansible-aws.sh preflight`.
2. Confirmar cuenta/región ocultas, una sola EC2 `nexoeventos-academy-app`, SSM `Online` y acceso al bucket privado; generar inventario estático protegido en `work/ansible/`.
3. Crear desde un commit limpio un artefacto protegido con `scripts/build-release.sh`.
4. Exigir un recibo `0600` que identifique snapshot/dump preactualización.
5. Desplegar en `/opt/nexoeventos-deploy/releases/<commit>`, pausar la API, migrar `0003→0005`, insertar el catálogo ficticio sin alterar IDs ya existentes y comprobar Alembic antes de cambiar `current`. La migración es aditiva, pero el catálogo de esta ventana no habilita asientos numerados ni 3D.
6. Conservar `previous`, reiniciar FastAPI/recargar Nginx y exigir `/ready = 200`; si falla el código, restaurar el enlace anterior.
7. Comprobar por HTTPS registro → acceso → reserva simulada → entrada → validación única, sin capturar QR ni datos privados.

No crea infraestructura ni abre SSH. No lee ni reemplaza `/etc/nexoeventos/backend.env`, `/etc/nexoeventos/duckdns.env`, claves QR o `/etc/letsencrypt`. Las migraciones se ejecutan con `migration.env` y el usuario separado, con `no_log`, únicamente después de comprobar un recibo de respaldo. El rollback de código no revierte el esquema: para eso se conserva snapshot/dump y se restaura de forma aislada.

## Comandos, después de revisar el alcance

```bash
./scripts/ansible-aws.sh preflight
NEXO_ALLOW_CLOUD_CHANGES=YES ./scripts/ansible-aws.sh deploy
# Solo si la validación funcional posterior exige una reversión manual:
NEXO_ALLOW_CLOUD_CHANGES=YES ./scripts/ansible-aws.sh rollback
```

El despliegue exige además `NEXO_MIGRATION_BACKUP_RECEIPT=/var/lib/nexoeventos/backups/<nombre>.receipt`; el wrapper rechaza otras rutas o la ausencia del archivo remoto `0600`.

La conexión usa `amazon.aws.aws_ssm`, no SSH. Requisitos del controlador: AWS CLI, Ansible Core, colección `amazon.aws` 10.1.2, `boto3`/`botocore` y Session Manager Plugin. El 7 de octubre se comprobaron Ansible 2.19.3 y el plugin oficial ARM64 1.2.835.0, instalado para la usuaria en `~/.local/` porque la instalación global requería privilegios administrativos. Véanse los requisitos oficiales del [plugin de conexión Ansible](https://docs.ansible.com/projects/ansible/latest/collections/amazon/aws/aws_ssm_connection.html) y la [instalación oficial en macOS](https://docs.aws.amazon.com/systems-manager/latest/userguide/install-plugin-macos-overview.html).

La conexión Ansible por SSM requiere S3 incluso para módulos simples y permisos `GetObject`, `PutObject`, `ListBucket`, `DeleteObject` y `GetBucketLocation`. El 7 de octubre un `ping` y la inspección real por SSM confirmaron esos permisos. Las pruebas acumularon 18 versiones/marcadores bajo el prefijo temporal exclusivo de la EC2; se eliminaron por clave y version ID, se verificó que quedaron **0**, y el respaldo `backups/database/` permaneció intacto. No se transfirieron secretos ni archivos `/etc/nexoeventos`. Cada despliegue debe repetir esa limpieza acotada; una regla lifecycle específica o un bucket temporal no versionado requerirían un plan separado y no se ampliará IAM automáticamente.

El inventario dinámico `amazon.aws.aws_ec2` descubrió la instancia, pero su worker terminó de forma anómala en este Mac. El mismo módulo funcionó con inventario estático. Por ello el wrapper usa AWS CLI para exigir exactamente una instancia por etiqueta y genera `work/ansible/inventory.yml` con modo `0600`; no codifica el ID en Git.

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
