# Índice de capturas auténticas de consola (copias con datos sensibles ocultos)

Los originales permanecen en `~/Downloads/` sin alterar. Estas copias tienen tapados con rectángulos negros: ID de cuenta, nombre de usuario, ARN e IDs de recursos. Las horas de las consolas de RDS están en **UTC−05:00** (hora local de la autora); las de CloudWatch, en UTC. **Fase de anotación pendiente**: aún no llevan recuadros ni etiquetas.

| Archivo | Servicio / vista | Qué se observa | Qué demuestra | Límites |
|---|---|---|---|---|
| aws/01-rds-config.png | RDS → Configuración | Multi-AZ Sí, cifrado habilitado (`aws/rds`), IAM de BD no, umbral de almacenamiento 20 GiB | Configuración de V1 Multi-AZ y cifrada | ARN/IDs ocultos |
| aws/02-rds-seguridad.png | AWS CLI | Acceso público False, cifrado True, `stopped`, Multi-AZ True, protección contra borrado False | Controles de RDS; ausencia de protección contra borrado | Consulta del 28-oct |
| aws/04-web-sg-salida.png | EC2 → SG web → salida | DNS 53 (TCP/UDP) a 10.20.0.0/16; HTTPS 443 a 0.0.0.0/0; 5432 hacia un SG | Salida restringida | Destino del 5432 oculto; se apoya en API |
| aws/05-web-sg-entrada.png | EC2 → SG web → entrada | 443 y 80 desde 0.0.0.0/0; sin puerto 22 | Superficie de entrada mínima en V1 | — |
| aws/06-asg-escalabilidad.png | CloudWatch `GroupInServiceInstances` (Media, 1 min, 22-oct 14:00–18:00 UTC) | 0 → 2 → 3 → 2 → 0 | Secuencia observada de instancias | No asocia usuarios |
| aws/07-alb-errores-5xx.png | CloudWatch `HTTPCode_Target_5XX_Count` (Suma, 1 min, 22-oct 16:00–17:00 UTC) | Dos puntos: ≈25 (16:03) y ≈40 (16:38) unidos por una línea | 5xx solo en dos minutos | No prueba recuperación por sí sola |
| aws/08-alb-healthy-hosts.png | CloudWatch `HealthyHostCount` (Media, 1 min, mismo rango) | 2 destinos sanos con caídas a 1 en ≈16:03 y ≈16:38 | El ALB dejó de contar un destino como sano dos veces y volvió a 2 | La media por minuto no da segundos; la recuperación se mide en los registros de prueba |
| aws/09-alb-unhealthy-hosts.png | CloudWatch `UnHealthyHostCount` (Media, 1 min, mismo rango) | Un pico de 1 en ≈16:03; **no** se ve pico en ≈16:38 | El primer fallo se vio como destino no sano | En la repetición de 16:38 la métrica no muestra destino no sano: no se explica solo con la captura (hipótesis no verificada: retirada rápida del destino) |
| aws/10-rds-eventos-28oct.png | RDS → Eventos (última semana, UTC−05:00) | 28-oct 16:39 start, 16:41–16:43 backup, 16:45 aviso de almacenamiento, 16:51 stopped; 23-oct 10:04–10:17 restart/start/stop | Ciclo start-stop del 28-oct y reinicios del 23-oct | Hora local (= 21:39–21:51Z) |
| aws/11-rds-failover-22oct.png | RDS → Eventos (UTC−05:00) | 22-oct 20:08 «Multi-AZ instance failover started», 20:09 «The user requested a failover», «restarted», «failover completed»; 20:06–20:07 backup; 19:30 aviso de almacenamiento | Failover Multi-AZ **solicitado por el usuario** y completado en ≈ 1 min entre eventos | Equivale a **23-oct 01:08–01:09Z**; el ≈14 s medido por sonda es la indisponibilidad, no la duración entre eventos |

## Copias redactadas añadidas el 29-oct (origen: `~/Pictures/Capturas/`, originales intactos)
| Archivo | Demuestra | Limitación |
|---|---|---|
| aws/A1-EC2-IMDSv2-LabRole.png | EC2 de V1 con IMDSv2 `Required` y rol `LabRole`; **estaba en ejecución a las 11:18Z del 29-oct** | IDs, ARN, DNS y cuenta ocultos |
| aws/A2-RDS-Estado-Seguridad.png | RDS `Detención temporal`, db.t3.micro, IAM auth desactivada | ARN del secreto oculto |
| aws/A8-CloudTrail-Historial-Eventos.png | Historial de eventos de gestión (90 días) con latidos de SSM | No es un trail persistente |
| aws/A9-CloudTrail-Sin-Trails.png | No existe ningún trail en la cuenta | — |
| aws/A13-IAM-LabRole-Politicas.png | LabRole con 7 políticas, sin límite de permisos | No muestra permisos efectivos |
| aws/A14-IAM-Acceso-Denegado.png | `iam:GetPolicy` denegado: permisos efectivos no legibles | Texto del ARN oculto |
Pendientes de copia redactada: A3, A4, A5, B1–B10, OCI-01…06, DEVOPS-01/02.

## Segunda tanda (29-oct): copias redactadas por proveedor
Origen: `~/Pictures/Capturas/` (originales intactos). Cuenta, usuario, correo, ID de suscripción, namespace/OCID, ARN, IDs y direcciones ocultos; cada copia se revisó visualmente después de redactar.
- **AWS** (`aws/`): `A3` (RDS Multi-AZ/cifrado), `A4` (10 instantáneas), `A5` (retención 7 d; restaurable 15–22-oct), `A15` (**EC2 detenida 29-oct, control de costos**).
- **Azure** (`azure/`): `B1` (VM desasignada), `B3` ×4 (regla, activación, detalle, historial), `B4` (grupo de acciones, correo verificado), `B5` (métrica CPU), `B7`, `B8`, `B9` (grupo de acciones **desencadenado** 9:41 y 10:02), `B10` (sin reglas de supresión).
- **OCI** (`oci/`): `OCI-01…06` (bucket privado, clave Oracle, versionado, `backups/`, política).
- **GitHub** (`github/`): `DEVOPS-01` (31 ejecuciones), `DEVOPS-02` (run #31), `DEVOPS-03` (Trivy de la imagen).
Captura de la EC2 detenida: origen `~/Pictures/Capturas/AWS-EC2-Instancia-Detenida-29Oct2026.png` (guardada a las 13:49, hora del equipo).
Limitaciones clave: B9 muestra el grupo de acciones desencadenado, **no** la recepción del correo; OCI-06 trunca la lista de permisos; A5 indica que la última hora restaurable es el 22-oct 20:49 (UTC−5).
Sin redactar y no usadas: capturas genéricas «Captura de pantalla …» y 3 grabaciones de pantalla del mismo directorio (no se tocaron).

## Tercera tanda (3-nov)
| Archivo | Demuestra | Limitación |
|---|---|---|
| aws/A16-RDS-Eventos-Detencion-28oct-verificado-03nov.png | RDS → Eventos: detención 28-oct 16:51 (UTC−5); inicio 16:39, copia 16:41–16:43; aviso de almacenamiento 16:45 («20 GiB … umbral máximo 20 GiB»); 23-oct y 22-oct (failover 20:09) | No muestra el estado actual; el aviso es de configuración, no mide espacio libre. Cuenta y usuario ocultos. Origen: `~/Pictures/Capturas/AWS-RDS-Eventos-Detencion-28Oct-Verificado-03Nov2026.png` |
