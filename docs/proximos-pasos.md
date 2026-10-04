# Próximos pasos

Actualizado el 4 de octubre de 2026 durante la revisión local posterior a `545a7f3`. Estado completo: [estado-proyecto.md](estado-proyecto.md).

## Locales (sin AWS)

1. Mantener `Equipo XX` como pendiente hasta recibir el identificador docente; registrar a Yesenia como autora individual y avanzar con el resto.
2. Ensayar `scripts/cloud/load-test.py` contra el backend local (5 usuarios × 30 s) para validar el script.
3. Preparar el Entregable 2 con el contraste oficial de [evidencias/revision-rubrica.md](evidencias/revision-rubrica.md).
4. Revisar por separado las propuestas de AMI fija y RDS en [operacion/terraform-advertencias.md](operacion/terraform-advertencias.md); el bucket permanece en estado.

## Siguiente sesión cloud (requiere aprobación)

5. Aprobar [operacion/sesion-cloud-siguiente.md](operacion/sesion-cloud-siguiente.md): máximo 3.5 h y techo estimado USD 0.75, después de comprobar el límite real de RDS.
6. Ejecutar en orden: `start`/`check`, inventario y capturas EV02–EV08/EV10, carga E01 (EV11), restauración `--pitr` + `cleanup` (EV07), `check` y `stop`. Procedimientos: [operacion/procedimientos-sesion-cloud.md](operacion/procedimientos-sesion-cloud.md).
7. Registrar el consumo del panel Academy antes y después. Revisar al observar USD 30 y USD 40; no son límites automáticos.

## Sesión dedicada posterior

8. Aplicar las correcciones de Terraform solo si el plan muestra 0 reemplazos y 0 eliminaciones; después, `plan` sin cambios para I01/EV09.
9. Mantener migración entre cuentas y Azure/GCP como mejoras pendientes; los Word oficiales no imponen esos proveedores.
