# Migración reproducible entre cuentas AWS

Estado: **procedimiento preparado; migración entre cuentas no ejecutada**. No se asumen créditos en el destino ni se crea una cuenta.

## Aislamiento por cuenta

Cada cuenta usa su propio archivo ignorado `work/terraform-envs/<entorno>.tfvars`, directorio de plugins `work/terraform/<entorno>`, estado local `work/terraform-state/<entorno>/terraform.tfstate` y plan `work/terraform-plans/<entorno>.tfplan`. `expected_account_id` es obligatorio y `scripts/terraform-account.sh` compara STS antes de `plan` o `apply` sin imprimir el ID. Nunca se copia el estado de Academy para gestionar el destino.

Academy aporta roles precreados como `LabRole`/`LabInstanceProfile`, regiones/tamaños restringidos, sesiones temporales y presupuesto académico. Una cuenta normal puede tener SCP, IAM, cuotas, regiones y precios distintos; no tendrá necesariamente esos roles ni créditos. En destino se debe crear o seleccionar un perfil mínimo autorizado, verificar RDS/EC2/S3/CloudWatch/Secrets Manager, cuotas, facturación y alertas, y escribir su nombre solo en el tfvars local.

## Ensayo y conmutación

1. Inventariar origen y verificar backup lógico, snapshot, archivos, checksums y respaldo separado de claves QR.
2. Validar identidad de destino y ejecutar `fmt`, `validate`, `plan`; aprobar costos y recursos propios del destino.
3. Crear destino únicamente tras autorización. Instalar el commit fijado con el instalador AL2023.
4. Restaurar primero una **copia de prueba** en la base aislada del destino.
5. Verificar migraciones, roles owner/migrator/app, cantidades, usuarios, propiedad de reservas, descifrado QR y validación única. Usar solo datos ficticios.
6. Reducir TTL DNS con antelación si el proveedor lo permite. DuckDNS usa actualización dinámica y no ofrece control equivalente a Route 53; observar propagación real.
7. Programar pausa de escrituras en origen; impedir nuevas reservas/validaciones, esperar transacciones, tomar backup lógico final y checksums.
8. Transferir el paquete cifrado por un canal externo autorizado; transferir claves QR por un canal separado.
9. Restaurar destino, rotar secretos de base/sesión, cargar claves QR, ejecutar migraciones y pruebas privadas.
10. Cambiar DuckDNS a la IPv4 destino y verificar resolución, certificado HTTPS, login → reserva → QR → validación única.
11. Mantener el origen sin escrituras durante la ventana de observación. Solo después de evidencia y aprobación se decide su retirada.

## Retorno al origen

Si fallan integridad, autorización, DNS o HTTPS: reactivar el origen, actualizar DuckDNS a su IP, verificar certificado/flujo, reabrir escrituras allí y conservar el destino aislado para diagnóstico. Las escrituras no deben habilitarse simultáneamente. Cualquier reserva creada únicamente en destino durante la prueba debe reconciliarse explícitamente antes del retorno.

## Lista de comprobación entre cuentas

- [ ] identidad y región de ambas cuentas comprobadas sin exponer IDs;
- [ ] estado/plan separados y protegidos;
- [ ] perfil IAM de destino existente y permisos mínimos verificados;
- [ ] costos, cuotas, región, tipos EC2/RDS y secreto confirmados en destino;
- [ ] backup cifrado y checksums verificados fuera del origen;
- [ ] claves QR recuperables desde canal separado;
- [ ] restauración de prueba y roles limitados aprobados;
- [ ] pausa de escrituras y backup final registrados;
- [ ] DNS y HTTPS verificados externamente;
- [ ] rollback ensayado o documentado con responsables;
- [ ] migración marcada como realizada solo después de evidencias.
