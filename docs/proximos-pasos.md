# Próximos pasos

1. Regenerar personalmente el token de `nexoeventos-demo.duckdns.org` justo antes del despliegue; introducirlo solo mediante el prompt sin eco.
2. Resolver la credencial CLI de Academy: el Lab y la consola web están activos, pero el bloque temporal recién emitido responde `InvalidClientTokenId`. Cerrar/iniciar otra sesión o solicitar regeneración al laboratorio y comprobar STS antes de Terraform. Crear `work/terraform-envs/academy.tfvars` con el ID esperado sin versionarlo.
3. Ejecutar el nuevo plan con `scripts/terraform-account.sh plan academy`. El plan 30/0/0 de `25a12c1` es histórico y no se reutiliza; el intento del 2 de octubre no produjo binario.
4. Revisar plan, permisos, costo corregido (techo previsto USD 13.719 hasta el 26 de noviembre) y aprobar explícitamente antes de cualquier `apply`.
5. Si se aprueba, desplegar por etapas, comprobar lectura del secreto maestro, instalar AL2023, crear roles limitados y emitir HTTPS.
6. Registrar timestamps reales, estados y consumo; revisar al observar USD 30 y USD 40. No interpretar esos puntos como límites automáticos.
7. Reunir EV02–EV10 y medir rendimiento/RTO/RPO. No marcar evidencia cloud antes de observarla.
8. Mantener la migración a otra cuenta como pendiente hasta verificar destino, restaurar una copia y ejecutar la lista de comprobación.
9. Completar aparte Azure tras selección de cuenta/MFA, solo lectura.
