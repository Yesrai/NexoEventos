# Entregable 3 · Adaptación a cuentas gratuitas (solo planificación)

Fecha: 9-nov-2026. No se creó ni modificó ningún recurso; no hay commits.

## 1. Restricción obligatoria
No actualizar al plan Paid de AWS ni aceptar cargos a tarjeta. Todo diseño debe poder ejecutarse y probarse sin eso. Si algo exige pago, se marca **no viable** y se propone alternativa.

## 2. Qué dice AWS (fuentes oficiales)
Fuentes: [Choosing a plan](https://docs.aws.amazon.com/awsaccountbilling/latest/aboutv2/free-tier-plans.html), [Free Tier FAQs](https://aws.amazon.com/free/faqs/), [AWS Free Tier](https://aws.amazon.com/free/).

| Hecho | Estado |
|---|---|
| El plan Gratis "no incurre cargos" | Confirmado (oficial) |
| Termina a los **6 meses o al agotar créditos**, lo que ocurra primero | Confirmado |
| Al terminar, la cuenta se **cierra** y se conserva 90 días; seguir exige pasar a Paid | Confirmado |
| Excluye servicios que "agotarían los créditos" o requieren compra de hardware (Savings Plans, Reservas, algunos Marketplace) | Confirmado |
| Sin otros créditos promocionales | Confirmado |
| **Se actualiza automáticamente a Paid** si la cuenta entra a AWS Organizations, configura Control Tower, entra a APN, contrato de servicios profesionales, EA, suscripción Skill Builder Team o se declara HIPAA/SEC | Confirmado. **Nunca hacer nada de esto** |
| Tarjeta: no obligatoria para la mayoría, puede pedirse para verificar identidad | Confirmado, con matices |
| Caducidad de créditos: las FAQ dicen 6 meses en una parte y 12 en otra (actividades) | Inconsistente; planificar con **6 meses** |
| Lista exacta de servicios/instancias permitidos | **No publicada** en las páginas oficiales consultadas |
| Foros: instancias elegibles (`t3.micro`, `t3.small`, `t4g.*`, `c7i-flex.large`, `m7i-flex.large`) y límite de 1 vCPU en algunas cuentas nuevas | **Anecdótico, sin verificar** |
| ALB, NAT Gateway, RDS Multi-AZ en plan Gratis | **Desconocido**. Fuentes de terceros se contradicen. No asumir |

Los US$100 **no** significan "cualquier servicio": hay servicios bloqueados y, aunque se permitan, un NAT Gateway (~33 USD/mes) o un ALB encendido consumen el crédito y, al agotarse, la cuenta se cierra.

## 3. Cómo verificar sin crear nada
- En la consola, con la cuenta nueva: Billing → Free Tier (saldo de créditos y servicios elegibles). Solo lectura.
- CLI de solo lectura: `aws ec2 describe-instance-types --filters Name=free-tier-eligible,Values=true` y `aws service-quotas get-service-quota` (vCPU).
- La única prueba definitiva de si ALB/Multi-AZ están permitidos es intentar crearlos, y eso no se hace sin autorización. Si falla, el error es la evidencia.

## 4. Papel realista de cada cuenta

| Cuenta | Limitación | Papel propuesto |
|---|---|---|
| AWS Academy | Sesión efímera, token que caduca, recursos apagados al cerrar el lab, crédito 50 USD | **Primario de demostración (V2)**, encendido solo en ventanas de prueba |
| AWS cuenta nueva (Gratis) | Cierra a 6 meses o sin crédito; servicios restringidos; no unir a Organizations | **Opcional**: segunda cuenta AWS persistente para réplica/relé de BD con instancias pequeñas. No sustituye un DR fuera de AWS |
| OCI (Always Free) | Capacidad ARM variable | Sitio DR 2 + backups programados + testigo |
| Azure | Crédito limitado, VM desasignada | Sondas independientes, Grafana/Zabbix, línea de tiempo del RTO |
| Google Cloud | Cuenta por crear; **verificar si exige tarjeta/facturación** | Solo si cumple el criterio de la sección 5 |

**Hallazgo clave:** con Academy los tokens caducan y los recursos se apagan, por lo que la continuidad automática **no puede depender de nada que viva solo en Academy**. Los componentes de decisión (sondas, gateway, testigo) deben vivir en nubes con capa permanente gratuita (OCI, GCP, Azure).

Una segunda cuenta AWS no protege de una caída de AWS; protege de la pérdida de la cuenta Academy. Se documenta con esa honestidad.

## 5. Google Cloud: condición de uso
Solo entra si (a) se confirma que se puede usar sin tarjeta o dentro de una capa gratuita sin cargo automático, y (b) tiene función justificada (gateway de entrada redundante). Si no, **Plan B: gateway y sitio caliente en OCI** y GCP queda como mención de investigación, no como componente.

## 6. Qué es viable y qué no (sin plan Paid)

| Elemento | Viabilidad | Alternativa académica |
|---|---|---|
| Failover entre sitios con gateway en nube gratuita | Viable (OCI/GCP, instancias pequeñas) | — |
| Réplica lógica asíncrona RDS→PostgreSQL externo | Viable en Academy (RDS ya existe); requiere reinicio y grupo de parámetros propio | Probar primero con PostgreSQL local/contenedor |
| RDS Multi-AZ y ALB en la cuenta Gratis | **Sin confirmar** | Usar la cuenta Gratis solo con EC2 `t3.micro` + PostgreSQL |
| NAT Gateway | **No viable** (costo continuo) | Subredes públicas con SG estrictos, o VPC endpoints solo si son gratuitos |
| RPO ≈ 0 (Patroni síncrono) | No para el MVP (latencia y recursos) | Declarar RPO en segundos, medido |
| RTO ≤ 10 s | Solo lectura quizá; escritura 20–40 s | Declarar solo lo medido |
| Pruebas largas con todo encendido | No viable con 50 y 100 USD | Ventanas de 1–2 h con apagado inmediato |

## 7. Arquitectura mínima segura
1. Primario: AWS Academy V2 (ya construido), encendido solo en pruebas.
2. Gateway redundante (2 instancias HAProxy) en OCI (o GCP si pasa la sección 5), con enrutamiento por rol de escritor.
3. Réplica lógica asíncrona hacia PostgreSQL en OCI (hot standby).
4. Azure: sondas independientes y cronología.
5. Primera prueba con **base local/contenedor**, sin gastar crédito.

## 8. Controles de costo y de seguridad de cuenta
- Cuenta nueva: no ingresar tarjeta si no la piden; si la piden, solo para verificar y confirmar que el plan sigue en Gratis.
- Alertas de crédito revisadas a mano antes y después de cada ventana.
- Prohibido: Organizations, Control Tower, Marketplace de pago, Savings Plans, upgrade.
- Apagar todo al terminar cada prueba y dejarlo documentado.

## 9. Pendiente de datos tuyos
- Saldo real de créditos de la cuenta nueva y de Academy (capturas de la consola, sin números de cuenta).
- Si la cuenta nueva pidió tarjeta al registrarse.
- Fecha de entrega y pesos de la rúbrica.

## 10. Siguiente paso seguro (solo lectura)
En la consola de la cuenta nueva: abrir Billing → Free Tier y copiar el saldo y la lista de servicios elegibles; luego, con la CLI, solo los dos `describe/get` de la sección 3. No crear nada.
