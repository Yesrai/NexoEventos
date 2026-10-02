# Próximos pasos

1. Regenerar personalmente el token de `nexoeventos-demo.duckdns.org` justo antes del despliegue; introducirlo solo mediante el prompt sin eco.
2. Mantener la credencial Academy en un entorno temporal aislado y renovarla cuando expire; el perfil global no es necesario para el plan actual.
3. Revisar el plan vigente 30/0/0 guardado con modo `0600` en `work/terraform-plans/academy.tfplan`. El plan histórico de `25a12c1` no se reutilizó.
4. Revisar permisos pendientes y aprobar explícitamente antes de cualquier `apply`; el costo documentado no se recalculó en esta comprobación.
5. Si se aprueba, desplegar por etapas, comprobar lectura del secreto maestro, instalar AL2023, crear roles limitados y emitir HTTPS.
6. Registrar timestamps reales, estados y consumo; revisar al observar USD 30 y USD 40. No interpretar esos puntos como límites automáticos.
7. Reunir EV02–EV10 y medir rendimiento/RTO/RPO. No marcar evidencia cloud antes de observarla.
8. Mantener la migración a otra cuenta como pendiente hasta verificar destino, restaurar una copia y ejecutar la lista de comprobación.
9. Completar aparte Azure tras selección de cuenta/MFA, solo lectura.
