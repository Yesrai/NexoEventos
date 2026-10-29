# Alternativa V2: dos instancias y balanceador

> **Actualización del 28-oct-2026:** este documento es el **diseño del 7-oct**. La V2 se implementó (`infra/aws-v2`, 21 recursos), se desplegó, se midió el 22-oct (validación 15/15, escalera V1 vs V2, escalado 2→3→2 y fallos) y se **destruyó**; la RDS de V1 pasó a Multi-AZ el 23-oct. Resultados y diagramas reales: [`entregable2/informe-entregable2.md`](entregable2/informe-entregable2.md).

Diseño del **7 de octubre de 2026**; no desplegado ni incorporado a Terraform.

## Diseño mínimo útil

- ALB público en dos subredes públicas y HTTPS en el balanceador.
- Dos EC2 AL2023 en zonas distintas, con SG que permita HTTP únicamente desde el SG del ALB; sin SSH.
- despliegues versionados idénticos mediante Ansible y health check `/healthz`;
- RDS privada y S3/CloudWatch existentes; una segunda fase debería evaluar RDS Multi-AZ, porque dos EC2 no eliminan el SPOF de la base;
- sesiones almacenadas en PostgreSQL y frontend sin estado local de autorización, por lo que las peticiones pueden llegar a cualquiera de las instancias;
- DuckDNS puede apuntar a un nombre ALB mediante CNAME si el proveedor lo admite para el subdominio; TLS requiere una decisión verificable (ACM en ALB o terminación alternativa).

La variante de menor costo coloca las EC2 en subredes públicas, sin permitir tráfico de Internet hacia ellas salvo respuestas salientes y tráfico desde el ALB. Cada instancia tendría IPv4 pública para SSM/repositorios, lo que reduce aislamiento. La variante recomendada de seguridad usa subredes privadas y endpoints VPC o NAT; NAT Gateway elevaría notablemente el costo y no se añade sin justificarlo.

## Utilidad y límites

| Aspecto | V1 | V2 ALB + 2 EC2 |
|---|---|---|
| caída de una EC2 | sitio fuera de servicio | ALB retira el destino no sano |
| despliegue | interrupción posible | actualización por instancia con health checks |
| capacidad web | una `t3.small` | dos `t3.small`; escalado horizontal demostrable |
| base de datos | RDS Single-AZ, SPOF | igual hasta habilitar Multi-AZ |
| complejidad | baja | SG adicionales, segunda subred pública, target group, ALB y certificado |
| evidencia necesaria | carga V1 | misma carga, fallo de una instancia y comparación antes/después |

## Estimación mensual comparativa

Supuestos `us-east-1`, 720 h, sin impuestos/créditos: dos `t3.small`, un ALB 24/7, 1 LCU media, RDS Single-AZ actual y almacenamiento V1. Estimación orientativa:

| Partida V2 | Importe 30 días |
|---|---:|
| dos EC2 `t3.small` | USD 29.952 |
| ALB (USD 0.0225/h) | USD 16.200 |
| 1 LCU media (USD 0.008/h) | USD 5.760 |
| RDS Single-AZ actual | USD 12.960 |
| almacenamiento/secretos/logs/alarma base V1 | ≈ USD 4.929 |
| IPv4 públicas, hasta cuatro como supuesto conservador | hasta USD 14.400 |
| **orden de magnitud** | **USD 69.80–84.20/30 días**, más consumo variable |

Multi-AZ, NAT, transferencia, más LCU y logs aumentarían la cifra. Deben cotizarse con el plan real antes de aprobar.

## Comparación con EKS

EKS no aporta valor proporcional para esta aplicación individual: el control plane estándar cuesta **USD 0.10 por clúster-hora (USD 72/720 h)**, antes de nodos, ALB, EBS, IPv4, RDS y logs. También añade imágenes, registro, manifiestos, upgrades, observabilidad de clúster y permisos probablemente restringidos en Academy. Dos EC2 detrás de ALB permiten demostrar escalado y tolerancia web con menos costo y superficie operativa. EKS solo sería razonable si la rúbrica exigiera orquestación, múltiples servicios/equipos o escalado de pods medido; no se agrega para aparentar complejidad.

Fuentes oficiales: [precios de Elastic Load Balancing](https://aws.amazon.com/elasticloadbalancing/pricing/) y [precios de Amazon EKS](https://aws.amazon.com/eks/pricing/).
