# Observabilidad real con CloudWatch Agent

La instalación se limita a la EC2 V1 existente, Amazon Linux 2023, y no amplía IAM. El rol debe permitir efectivamente `logs:CreateLogStream` y `logs:PutLogEvents` en los dos grupos ya administrados por Terraform.

```bash
./scripts/ansible-aws.sh preflight
NEXO_ALLOW_CLOUD_CHANGES=YES ./scripts/ansible-aws.sh observability
NEXO_ALLOW_CLOUD_CHANGES=YES ./scripts/cloud/verify-observability.sh
```

El rol instala `amazon-cloudwatch-agent` y `logrotate`, valida Nginx antes de recargar, conserva el proceso FastAPI bajo systemd y consulta el estado/version del agente. La primera activación rota el log histórico de FastAPI antes de capturarlo. Los logs rotados permanecen en la EC2 y no forman parte del patrón de ingesta.

El acceso Nginx usa un formato mínimo: fecha ISO, método, `$uri` sin argumentos, estado, bytes, tiempo e ID de solicitud. Nunca se agregan IP, `$request`, query string, cabeceras, cookies, cuerpo, referente ni agente de usuario. Uvicorn sigue con `--no-access-log`; el log de servicio conserva solo salida/error de la aplicación, que no debe registrar cuerpos ni secretos.

La ruta `/_observability/ev08-<fecha>` responde 204 y existe exclusivamente para crear una señal identificable sin datos de usuario. El verificador cuenta esa señal y los streams, escanea patrones sensibles sin descargar mensajes y registra la definición de la alarma. La retención de 7 días sigue en Terraform; no se incluye `retention_in_days` en el agente para evitar `PutRetentionPolicy` o cambios accidentales.

Documentación oficial consultada: [instalación manual del agente](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/manual-installation.html), [archivo de configuración](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/create-cloudwatch-agent-configuration-file.html) y [diagnóstico/estado](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/troubleshooting-CloudWatch-Agent.html).
