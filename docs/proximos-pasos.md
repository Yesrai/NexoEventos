# Próximos pasos

Actualizado el 7 de octubre de 2026. Estado completo: [estado-proyecto.md](estado-proyecto.md).

## Locales (sin AWS)

1. Mantener `Equipo XX` como pendiente hasta recibir el identificador docente; registrar a Yesenia como autora individual y avanzar con el resto.
2. Preparar el Entregable 2 con el contraste oficial de [evidencias/revision-rubrica.md](evidencias/revision-rubrica.md) y la [V2 propuesta](arquitectura-v2.md).
3. Mantener las correcciones Terraform validadas sin apply hasta obtener un plan autenticado; el bucket permanece en estado.
4. Instalar/verificar Session Manager Plugin solo en una tarea autorizada; después ejecutar el preflight de [Ansible](operacion/ansible-despliegue.md).

## Siguiente sesión cloud (requiere aprobación)

5. Con el lab listo, renovar credenciales mediante el script protegido; ejecutar STS una sola vez, inventario/consumo y el plan Terraform.
6. Si el plan no propone reemplazos/eliminaciones, revisar por separado si se autoriza aplicar las tres correcciones. No usar `-refresh=false` como evidencia de ausencia de deriva.
7. Actualizar la aplicación por Ansible en una ventana de dos horas (margen estimado USD 0.20), probar HTTPS y detener recursos.
8. En la sesión de evidencias de máximo 3.5 h: `start`/`check`, EV02–EV10, carga 20 VU × 300 s, restauración `--pitr` + limpieza, `stop`. Techo estimado histórico USD 0.75.
9. Registrar consumo antes/después. Revisar al observar USD 30 y USD 40; no son límites automáticos.

## Sesión dedicada posterior

10. Solo después de resultados V1, decidir si la V2 ALB + dos EC2 aporta evidencia suficiente frente a su costo; no usar EKS sin una necesidad demostrada.
11. Mantener migración entre cuentas y Azure/GCP como mejoras pendientes; los Word oficiales no imponen esos proveedores.
