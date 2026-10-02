# Calendario de uso del crédito AWS hasta el 26 de noviembre

Este calendario es una propuesta, no autoriza despliegue. Preserva datos entre sesiones y evita dejar RDS detenido durante siete días, momento en que AWS puede volver a iniciarlo automáticamente.

| Fecha | Ventana máxima | Objetivo |
|---|---:|---|
| 5 oct | 4 h | Despliegue por etapas, solo tras aprobación del plan |
| 8 oct | 4 h | Aplicación, migraciones y conectividad privada |
| 14, 20 y 26 oct | 3 h cada una | Seguridad, backups y evidencias EV02–EV08 |
| 1, 7 y 13 nov | 3 h cada una | Restauración, observabilidad y pruebas |
| 19 nov | 4 h | Ensayo completo y rendimiento |
| 24 nov | 4 h | Cierre de evidencias y documentación |
| 26 nov | 3 h | Ventana final y contingencia |

Total máximo propuesto: 37 horas activas. Con los supuestos de costos V1, son aproximadamente USD 1.621 de cómputo/IPv4, USD 7.677 de almacenamiento y servicios persistentes durante 52 días y USD 0.867 de consumo de logs: **USD 10.164**. No incluye créditos de CPU T3, solicitudes S3, transferencias facturables, exceso de backups ni olvidos operativos.

En cada sesión:

1. Revisar el panel de presupuesto antes de operar; puede retrasarse 8–12 horas.
2. Inventariar recursos y confirmar que no se iniciaron cargas ajenas.
3. Tener presente que Learner Lab vuelve a iniciar EC2 detenidas al abrir una sesión; detener la instancia en cuanto no sea necesaria y nuevamente antes de terminar.
4. Usar RDS solo durante la ventana y volver a detenerlo; iniciar/detener al menos cada seis días mientras se conserve.
5. Comprobar backup/evidencia antes de cualquier eliminación posterior. La configuración actual usa `skip_final_snapshot = true`, por lo que no debe ejecutarse `destroy` como mecanismo de ahorro.

Aunque EC2 esté detenida siguen cobrando EBS, almacenamiento/backups RDS, S3, CloudWatch, alarmas y Secrets Manager. El laboratorio conserva recursos entre sesiones y perder el presupuesto puede deshabilitar la cuenta y borrar el progreso.
