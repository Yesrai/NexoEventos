# Guion oral (≈ 12 min) y preguntas difíciles — NexoEventos, Entregable 2

Regla: cada afirmación se etiqueta **medido**, **proyección** o **no probado**. Las diapositivas llevan las notas.

## Guion por diapositiva
1. **Portada (0:20).** «Presento la evolución de NexoEventos de V1 a V2: seguridad, escalabilidad y resiliencia, con la evidencia que realmente medí.»
2. **Problema (0:40).** Reservas con QR, aperturas masivas, sin sobreventa. Producción en AWS Academy, con sus restricciones reales.
3. **V1 → V2 (1:00).** V1 tenía dos puntos únicos de fallo: una EC2 y una base Single-AZ. V2 añade ALB, Auto Scaling 2–3 EC2 en dos zonas y Multi-AZ.
4. **Medición (1:00).** Con el mismo generador y hasta 50 usuarios: p95 288 → 190 ms, CPU 39,4 → 20 %, 0 5xx en 35 366 solicitudes. «No mido 100 o más usuarios: es proyección.»
5. **Multicloud (0:40).** AWS produce, OCI recupera, Azure observa. No hay conmutación automática.
6. **Seguridad (1:30).** Lo verificado por API y consola; lo ausente (CloudTrail, acciones de alarma, MFA, permisos efectivos de LabRole). Las capturas llevan datos sensibles ocultos.
7. **Escalabilidad (1:00).** Secuencia 0→2→3→2→0 instancias en CloudWatch. «No asocio esa secuencia a un número de usuarios.»
8. **Fallos (1:30).** A–D medidos. «No probé la caída de una zona completa ni usé AWS FIS.»
9. **Observabilidad (1:00).** Alerta de Azure disparada y resuelta (17 min 54 s); Zabbix y Grafana. «La entrega real del correo no está demostrada.»
10. **Recuperación (1:00).** R01, copia cifrada en OCI y aplicación completa en OCI en 32 min 42 s. «En AWS la recuperación completa no está acreditada.»
11. **DevOps, costes, conclusiones (1:30).** CI que construye y prueba; no hay CD. Riesgos de coste. Cierre con lo no probado.

## Preguntas difíciles y respuestas honestas
1. **¿Probaste la caída de una zona de disponibilidad?** No. Probé fallo de proceso, destino no sano, reemplazo por Auto Scaling y failover de RDS. La caída de zona es diseño (subredes y EC2 en dos zonas), no una prueba. Existe un plan documentado; no lo ejecuté por costo y porque V2 estaba destruida.
2. **¿Usaste AWS FIS?** No hay evidencia ni la afirmo. En Academy probablemente no es utilizable (LabRole no lista FIS entre los servicios de confianza que leí; no lo comprobé a fondo).
3. **¿Cuántos usuarios soporta?** Medido: 50 simultáneos con 0 errores 5xx y p95 190 ms. Más allá es extrapolación lineal, marcada como proyección.
4. **¿Por qué el escalado tardó tanto?** El escalado reactivo por CPU tardó 8 min 6 s en activar la alarma y ≈ 9 min en tener la tercera instancia sana. Para aperturas masivas haría falta capacidad precalentada o escalado programado.
5. **¿El gráfico de 5xx prueba que se recuperó solo?** No por sí solo. Muestra 5xx en dos minutos; la recuperación (detección 20,0 s, reemplazo ≈ 2,5 min) sale de los registros de las pruebas.
6. **¿Por qué en la repetición de las 16:38 no aparece UnHealthyHostCount?** No lo sé con certeza; lo declaro como límite. Una hipótesis (retirada rápida del destino) no está verificada.
7. **¿Tu failover de 14 s es real?** Es la indisponibilidad medida con sondas, en una sola ejecución y sin carga de escritura concurrente. Los eventos de RDS del 22-oct a las 20:08–20:09 (hora local; 01:08Z del 23-oct) confirman que fue forzado por el usuario.
8. **¿Hay mínimo privilegio en AWS?** No propio: Academy impone LabRole (7 políticas, 3 no legibles). Lo compenso con SG→SG, sin SSH, cifrado y roles separados en PostgreSQL. Un rol propio es diseño, no implementado.
9. **¿Hay auditoría de la API (CloudTrail)?** No hay trail configurado; solo el historial de eventos por defecto. Es un riesgo residual declarado.
10. **¿Las alertas funcionan?** La de CPU de Azure se disparó y se resolvió. Zabbix generó alertas, cinco fallaron al inicio por una plantilla ausente y se corrigieron. La entrega real de correo no está demostrada: el correo de verificación del receptor es otro hecho.
11. **¿Qué pasa si se pierde AWS?** La copia cifrada en OCI recuperó la aplicación completa en 32 min 42 s (14/14 pruebas, por túnel, sin DNS público). La recuperación completa en AWS (DNS + HTTPS) quedó incompleta el 12-oct.
12. **¿Tienen CI/CD?** CI (GitHub Actions): pruebas de backend con PostgreSQL, frontend, imagen Docker y Trivy. No hay despliegue continuo: los despliegues fueron manuales con Terraform y Ansible.
13. **¿Cuánto costó?** No lo sé con certeza: no usé Cost Explorer. Hay estimaciones por ventana y recursos apagados; el costo facturado real está sin verificar.
14. **¿Por qué la base es el cuello de botella?** La `db.t3.micro` llegó a 22 de 81 conexiones con 2 instancias; al crecer, conexiones y memoria saturan antes que la capa web.
15. **¿Qué mejorarías primero?** Respaldo programado (RPO ≤ 24 h), trail de CloudTrail, acciones en alarmas, protección contra borrado, MFA y prueba de pérdida de zona.
