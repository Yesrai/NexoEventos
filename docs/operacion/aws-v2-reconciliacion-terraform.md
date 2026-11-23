# Reconciliación de Terraform tras una limpieza de emergencia de AWS V2

Preparada el 22-nov-2026. **Nada de lo que describe se ha aplicado**: solo se ejecutaron `terraform plan` (con y sin `-refresh-only`) y consultas de solo lectura, con `-lock=false`, sin guardar los planes.

## 1. Qué pasó
El 20-nov-2026 la limpieza `rds-window.sh stop-now --also-v2` apagó V2 **por la API de AWS** (ASG a 0, ALB eliminado con `delete-load-balancer`, RDS detenida). Terraform no participó, así que su estado (`work/terraform-state/…`) sigue creyendo que existen el ALB y sus listeners y que el ASG está en 2.

## 2. Estado real frente al estado de Terraform (verificado en solo lectura el 22-nov)
| Recurso | AWS (real) | Estado de Terraform |
|---|---|---|
| `aws_lb.main` (ALB) y los 2 listeners | **No existen** | Existen |
| `aws_autoscaling_group.web` | 0/0/3, sin instancias | 2/2/3 |
| Panel y 4 alarmas del ALB | **Existen** | Existen (con dimensiones del ALB anterior) |
| Resto (grupos de seguridad, grupo de destino, plantilla, política de escalado, alarma de capacidad…) | Existen | Existen (sin diferencias) |
Resultados de solo lectura:
- `terraform plan` con V2 «on»: **3 a crear, 6 a modificar, 0 a destruir** (crear ALB y 2 listeners; modificar ASG 0→2, el panel y las 4 alarmas del ALB).
- `terraform plan` con V2 «off»: 3 a crear, 5 a modificar, 0 a destruir.
- `terraform plan -refresh-only`: llevaría al estado **eliminar** `aws_lb.main` y los 2 listeners y **actualizar** el ASG y las 4 alarmas del ALB (solo estado; sin cambios en AWS).

## 3. Qué hace `rds-window.sh chain` con esta situación
`chain --scenario resume` está diseñado para este caso y **no necesita** reconciliar antes: regenera el plan (que refresca el estado en memoria) y lo revisa **por recurso y por atributo** con `scripts/v2-ops/review-plan.py`. El plan real de hoy lo pasa (3 creaciones + ASG 0→2 + 5 actualizaciones limitadas a `dashboard_body`, `dimensions` y `metric_query`), y el escenario `first` lo bloquea (esperaba 8 creaciones). Reglas de la revisión, en ambos escenarios:
- 0 destrucciones y 0 sustituciones; solo se admiten `create` y `update` en la lista permitida.
- **Cualquier acción** sobre RDS, IAM, secretos, DNS (Route 53), redes (VPC, subredes, grupos de seguridad, rutas, NAT, IP elásticas), certificados, claves, S3, grupo de destino o plantilla de lanzamiento **bloquea**, aunque sea una modificación menor.
- ASG: solo cambian `min_size` y `desired_capacity` (0→2) y el máximo no cambia.
- ALB público (no interno), tipo `application`, nombre esperado; listener 80 redirige a 443 HTTPS; listener 443 con política TLS 1.3 que reenvía.
- Panel: solo `dashboard_body`; alarmas por destino: solo `dimensions`; alarma de capacidad: solo `metric_query` (nunca umbral, acciones, periodos…).
- `--scenario resume` exige que la última parada conste como `PARADA_VERIFICADA` en `work/operacion/rds-window.state`; una parada incompleta o desconocida bloquea.

## 4. Estrategia recomendada (orden)
**Paso A — recomendado: reconciliar el estado (solo estado, no cambia AWS).** Requiere autorización expresa.
1. Solo lectura: `terraform plan -refresh-only -var-file=<common> -var-file=<on>`. Debe listar **exactamente** lo de §2 (eliminar ALB y 2 listeners; actualizar ASG y 4 alarmas). Si aparece algo más (RDS, IAM, redes, secretos, grupo de seguridad…), **parar y analizar**: no reconciliar.
2. Copia de seguridad del estado: copiar el archivo de estado local a `work/terraform-state/backups/<fecha>-antes-de-refresh` (0600).
3. Con autorización: `terraform apply -refresh-only` (sin `-auto-approve`, revisando el resumen antes de escribir «yes»). No crea, modifica ni destruye recursos reales.
4. Verificar: `terraform plan` (on) → pasar el JSON por `review-plan.py resume`; debe seguir aceptándose (3 creaciones + ASG + 5 actualizaciones).
**Paso B — alternativa (requiere autorización de destrucción):** `terraform destroy -target` de los 5 recursos de monitoreo residuales (panel y 4 alarmas del ALB) para volver al plan de 8 creaciones y usar `--scenario first`. Pierde el historial de esas alarmas; el coste es de céntimos. Nunca un `destroy` general.
**Paso C — no reconciliar:** `chain --scenario resume` funciona igualmente. Riesgo: cualquier otro uso de Terraform parte de un estado falso; no ejecutar `apply` sin revisar el plan.
**Descartado:** editar el estado a mano (`terraform state rm`): más frágil y sin ventaja sobre `-refresh-only`.

## 5. Después de la próxima reanudación
Una reanudación correcta deja el estado y AWS coherentes (ALB y listeners recreados). Si luego se vuelve a hacer una limpieza de emergencia, el procedimiento es el mismo: `PARADA_VERIFICADA` → `--scenario resume`.

## 6. Pruebas simuladas de la revisión
`scripts/v2-ops/tests/test-rds-window.sh` (AWS y Terraform simulados; no toca la nube) cubre: plan correcto de cada escenario (se aplica una sola vez, solo el plan guardado); plan de primer despliegue bajo `resume` y viceversa; destrucción, sustitución y modificación menor de la RDS; IAM, secretos, DNS y redes; atributos no permitidos en alarmas, acciones y panel; ASG con máximo o capacidad distintos; recursos residuales o faltantes (listener, actualización, grupo de destino, alarma nueva); ALB interno y TLS débil; y precondiciones (sin limpieza verificada, parada incompleta, escenario inválido, ALB/EC2/ASG/RDS residuales).
