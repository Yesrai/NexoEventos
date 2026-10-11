# Ensayo de recuperación completa del servicio (preparado, no ejecutado)

Este ensayo amplía R01. R01 ya demostró recuperación de datos (RPO 3 min 32 s y datos verificados en 21 min 4 s) y **no se repite**. El nuevo objetivo es medir el servicio completo aislado: infraestructura, aplicación, datos, claves, DNS, HTTPS y recorrido funcional.

## Alcance que requiere aprobación

El root separado `infra/aws-recovery/` reutiliza por lectura la VPC, subred pública y DB subnet group de V1, pero usa estado local independiente protegido. Crea exactamente:

- una EC2 `t3.small` AL2023 con 20 GiB gp3 e IPv4 pública, sin SSH;
- una RDS `db.t3.micro` privada y Single-AZ mediante PITR de `nexoeventos-academy-postgres`;
- dos security groups temporales: 80/443 público, PostgreSQL solo desde la EC2;
- ningún ALB, NAT, S3 nuevo, secreto nuevo, cambio IAM ni cambio al dominio principal.

Todo se etiqueta con `Purpose=full-recovery-drill` y un `RunId` UTC. El nombre y el estado son independientes de V1. Antes de aplicar deben existir: credenciales vigentes, AMI fijada, perfil de instancia existente, artefacto reproducible y un plan autenticado sin cambios al origen. El hostname temporal se deriva de la IPv4 como `nexoeventos-recovery-<ip-con-guiones>.sslip.io`; no necesita registro, token ni cambio DNS. El servicio [sslip.io](https://sslip.io/) resuelve hostnames con una IP embebida y admite certificados individuales mediante HTTP-01.

Archivos protegidos por ejecución:

```bash
install -d -m 700 work/recovery work/terraform-envs
# crear recovery-<RunId>.tfvars, runtime.yml e inventory.yml con umask 077
terraform -chdir=infra/aws-recovery init \
  -backend-config="path=$PWD/work/terraform-envs/recovery-<RunId>.tfstate"
terraform -chdir=infra/aws-recovery plan \
  -var-file="$PWD/work/terraform-envs/recovery-<RunId>.tfvars" \
  -out="$PWD/work/terraform-envs/recovery-<RunId>.tfplan"
```

Solo después de revisar el plan/costo y recibir aprobación: aplicar ese plan, generar el inventario a partir del output sensible sin imprimirlo y ejecutar:

```bash
ANSIBLE_CONFIG="$PWD/ansible/ansible.cfg" ansible-playbook \
  -i work/recovery/inventory.yml ansible/playbooks/recovery-base.yml \
  -e runtime_vars_file="$PWD/work/recovery/runtime.yml"
# Intervención privada por Session Manager: bootstrap-rds-secrets.sh y configure-https.sh
ANSIBLE_CONFIG="$PWD/ansible/ansible.cfg" ansible-playbook \
  -i work/recovery/inventory.yml ansible/playbooks/recovery-deploy.yml \
  -e runtime_vars_file="$PWD/work/recovery/runtime.yml"
```

Los ejemplos versionados son `infra/aws-recovery/recovery.tfvars.example`, `ansible/recovery-runtime.example.yml` y `ansible/recovery-inventory.example.yml`; no contienen valores reales.

## Secuencia y cronómetro

1. Comprobar origen, `LatestRestorableTime`, respaldo externo y huella/línea base ya definida; esperar a que el punto recuperable alcance esa línea base.
2. Registrar **T0 inmediatamente antes de `terraform apply`** del estado temporal. T0 representa el inicio del trabajo de recuperación después del incidente simulado.
3. Aplicar el plan revisado. Registrar **T1** cuando EC2, RDS y SSM estén disponibles.
4. Ejecutar `recovery-base.yml`. Por Session Manager, introducir sin eco credenciales aisladas de roles DB y las claves originales `TICKET_ENCRYPTION_KEY`/`SECURITY_HASH_KEY` obtenidas de su respaldo externo protegido. La credencial maestra RDS se obtiene por la vía autorizada del rol o la introduce la operadora; nunca va en Terraform, Ansible, logs o capturas. `sslip.io` no requiere token.
5. Verificar Alembic, tablas, reservas, huella y descifrado de entradas restauradas. Registrar **T2**: recuperación de datos y claves verificada.
6. Configurar el dominio de prueba (nunca `nexoeventos-demo.duckdns.org`), obtener Let's Encrypt y ejecutar `recovery-deploy.yml` con migraciones deshabilitadas. Registrar **T3** cuando HTTPS y `/healthz` respondan 200.
7. Con datos ficticios aislados: registro, login, reserva idempotente, entrada privada/QR, validación por operador y segundo ingreso 409. Confirmar además que una entrada restaurada puede descifrarse sin mostrar su token. Registrar **T4**.

Mediciones:

- recuperación de datos = T0→T2;
- recuperación completa/RTO = T0→T4;
- RPO = T0 menos el punto exacto restaurado, validado contra la línea base; elegir PITR por sí solo no demuestra RPO;
- tiempos T0→T1, T1→T2 y T2→T4 se conservan por separado para diagnosticar demoras.

Criterio de éxito: T4 dentro del objetivo de 60 min, RPO ≤24 h, datos/QR coincidentes y flujo completo correcto. Si solo se llega a T2, se informa recuperación de datos, no recuperación completa.

## Costo estimado y cargos persistentes

Supuestos públicos ya usados por el proyecto: EC2 t3.small USD 0.0208/h, RDS db.t3.micro USD 0.018/h, IPv4 USD 0.005/h, EBS 20 GiB prorrateado USD 0.0022/h y RDS 20 GiB prorrateado USD 0.0032/h. Temporal aproximado: **USD 0.0492/h; USD 0.10 por dos horas**. Con hasta 30 minutos del origen para línea base, logs, S3 y variación, se propone aprobar **USD 0.25** para la sesión; es estimación, no límite automático.

Si el ensayo deja recursos fuera de la ventana, siguen cobrando EC2/IPv4/RDS y almacenamiento. Los cargos persistentes normales de V1 (EBS, almacenamiento/backups RDS, S3, logs, secreto y snapshot) son independientes y no se atribuyen al temporal.

## Limpieza y reversión

Antes de borrar, guardar solo evidencia sanitizada. No hay registro DNS que retirar: al eliminar la IPv4 temporal, el hostname `sslip.io` deja de apuntar al entorno. Limpiar exclusivamente objetos S3 de transferencia identificados por el `RunId`. Revisar que el estado separado contenga solo recursos `Purpose=full-recovery-drill`/`RunId`; entonces ejecutar `terraform destroy` sobre **ese estado**, nunca `infra/aws` ni el estado Academy principal. Confirmar ausencia del RDS, EC2, volumen, IPv4 y SG temporales. Detener los recursos originales si se arrancaron.

Fallo antes de T4: no cambiar DNS principal ni el origen; conservar evidencias, diagnosticar y limpiar el mismo RunId. El origen es el rollback porque nunca recibe tráfico ni cambios del ensayo.

Estado previo a la ejecución: Terraform y Ansible preparados y validados localmente; faltaba generar/revisar el plan autenticado. **No declarar el RTO completo hasta obtener T4.**
