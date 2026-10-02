# Calendario de uso del crédito AWS hasta el 26 de noviembre

Propuesta operativa; no autoriza `apply` ni `destroy`. Si el despliegue se aprobara el 5 de octubre a las 09:00 y persistiera hasta el 26 de noviembre a las 23:59 (Lima), los recursos existirían 1,262.983 horas. Las ventanas activas máximas suman 37 horas.

| Fecha | Ventana máxima | Objetivo |
|---|---:|---|
| 5 oct | 4 h | despliegue por etapas, solo tras aprobación |
| 8 oct | 4 h | aplicación, migraciones y conectividad privada |
| 14, 20 y 26 oct | 3 h cada una | seguridad, backups y EV02–EV08 |
| 1, 7 y 13 nov | 3 h cada una | restauración, observabilidad y pruebas |
| 19 nov | 4 h | ensayo completo y rendimiento |
| 24 nov | 4 h | cierre de evidencias y documentación |
| 26 nov | 3 h | ventana final y contingencia |

Forecast corregido: USD 1.621 de EC2/RDS/IPv4, USD 7.769 de almacenamiento/servicios persistentes y USD 0.877 de consumo variable base; subtotal USD 10.267 y techo con margen USD 13.267. Las fechas de creación se reemplazarán por timestamps reales después de un eventual `apply`.

## Operación por sesión

1. Revisar presupuesto mostrado, inventario y estados antes de operar; el panel puede retrasarse.
2. Registrar `LaunchTime`, estado EC2 y `InstanceCreateTime`/estado RDS sin mostrar IDs completos.
3. Iniciar solo los recursos necesarios, comprobar servicio y detener EC2/RDS al terminar.
4. Confirmar que EC2 llega a `stopped` y RDS a `stopped`; una orden aceptada no demuestra el estado final.
5. Verificar backup y evidencia antes de una eliminación que requerirá autorización separada.

## Regla correcta de RDS detenido

[AWS documenta](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/USER_StopInstance.html) que RDS reinicia automáticamente una instancia que permanezca detenida siete días consecutivos. **Describirla, consultarla o volver a solicitar `stop-db-instance` no reinicia ese contador.** Para abrir un nuevo intervalo de detención es necesario:

1. obtener `DBInstanceStatus` e identificar la hora límite en el registro operativo;
2. antes de siete días, ejecutar una ventana controlada: `start-db-instance`;
3. esperar hasta estado `available` y ejecutar una comprobación mínima;
4. volver a ejecutar `stop-db-instance` y esperar hasta `stopped`;
5. registrar ambas transiciones y la siguiente fecha límite.

No se automatiza este ciclo: los permisos de EventBridge/Lambda/SSM necesarios no están comprobados en Learner Lab. Un recordatorio humano no cambia AWS por sí solo. Si no se puede realizar la ventana antes del límite, se debe asumir que RDS volverá a cobrar cómputo al arrancar automáticamente.

## Umbrales manuales

- USD 30 observados: reconciliar costos, detener lo no esencial y confirmar que evidencia/backup estén recuperables.
- USD 40 observados: congelar nuevas pruebas y decidir explícitamente conservación, snapshot final o desmontaje.

No son topes automáticos. Aunque EC2/RDS estén detenidos permanecen EBS, almacenamiento/backups RDS, S3, CloudWatch, alarma, secreto y snapshots. Perder el presupuesto del laboratorio podría deshabilitar la cuenta y comprometer el progreso.
