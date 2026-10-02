# Próximos pasos

1. La usuaria inicia sesión personalmente en DuckDNS, intenta reclamar `nexoeventos-demo` y comunica solo el FQDN aceptado; nunca el token. Alternativas propuestas: `nexoeventos-demo-2026` y `nexoeventos-upeu-demo`.
2. En Chrome, abrir la pestaña **Iniciar el Laboratorio de aprendizaje de AWS Academy**, pulsar `Start Lab`, esperar el indicador verde y descargar/copiar credenciales nuevas. Las actuales responden con `voc-cancel-cred`. Crear `work/terraform-envs/academy.tfvars` con el ID esperado sin versionarlo.
3. Ejecutar el nuevo plan con `scripts/terraform-account.sh plan academy`. El plan 30/0/0 de `25a12c1` es histórico y quedó invalidado por snapshot final/controles de portabilidad.
4. Revisar plan, permisos, costo corregido (techo previsto USD 13.267 hasta el 26 de noviembre) y aprobar explícitamente antes de cualquier `apply`.
5. Si se aprueba, desplegar por etapas, comprobar lectura del secreto maestro, instalar AL2023, crear roles limitados y emitir HTTPS.
6. Registrar timestamps reales, estados y consumo; revisar al observar USD 30 y USD 40. No interpretar esos puntos como límites automáticos.
7. Reunir EV02–EV10 y medir rendimiento/RTO/RPO. No marcar evidencia cloud antes de observarla.
8. Mantener la migración a otra cuenta como pendiente hasta verificar destino, restaurar una copia y ejecutar la lista de comprobación.
9. Completar aparte Azure tras selección de cuenta/MFA, solo lectura.
