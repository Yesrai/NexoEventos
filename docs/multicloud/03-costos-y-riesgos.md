# 3. Costos estimados y riesgos

**Todas las cifras son estimaciones por tarifa pública, sin impuestos; deben verificarse en el momento de crear cada recurso.**

## Costos
| Nube | Concepto | Estimación |
|---|---|---|
| AWS | Persistente con todo apagado (EBS, almacenamiento RDS, snapshots, S3, secretos, AMI, logs) | ≈ USD 0,21–0,22/día (≈ 6,5/mes) |
| AWS | Ventana V1 (EC2 + IPv4 + RDS) | ≈ USD 0,044/h |
| AWS | Ventana V2 (2 EC2 + ALB + IPv4 + RDS) | ≈ USD 0,11/h (3 h ≈ 0,33) |
| AWS | RDS Multi-AZ (opcional) | +USD 0,018/h y almacenamiento ×2 (≈ +USD 15/mes si queda 720 h; ventana de 2 h ≈ +0,04) |
| AWS | Transferencia de respaldos a OCI | despreciable (dump ≈ 80 KB; AWS cobra salida ≈ USD 0,09/GB tras 100 GB gratis) |
| OCI | Cuenta y recursos *Always Free* (VM E2.1.Micro, 20 GiB de Object Storage, VCN, NSG, Service Gateway, Bastion) | ≈ USD 0 (**verificar** región de origen, capacidad y tratamiento del NAT gateway) |
| OCI | Si no hay capacidad Always Free | crédito de prueba de OCI; coste de una VM pequeña por horas ≈ centavos |
| Azure | VM B2s ≈ USD 0,04/h solo en ventanas (p. ej. 40 h/mes ≈ 1,7) | ≈ USD 2/mes |
| Azure | Disco SSD estándar 64 GiB (persistente) + IP pública estática (si no se libera) | ≈ USD 5 + 3,6 /mes |
| Azure | Log Analytics (5 GB/mes gratis), pruebas de disponibilidad externas | ≈ USD 0–3/mes (**verificar**) |
| **Total mensual aprox.** | AWS ≈ 7–10 · OCI ≈ 0 · Azure ≈ 8–12 | **≈ USD 15–22/mes** (Azure dentro de los USD 100 informados si el crédito se confirma) |

Controles: presupuesto Azure con alertas al 50/80 %; VM de Azure desasignada fuera de ventanas; destruir la VM de OCI tras cada simulacro; ventanas AWS cortas con `stop` verificado; calendario real en `docs/operacion/calendario-credito-aws.md`.

## Riesgos
| Riesgo | Impacto | Mitigación |
|---|---|---|
| Lab AWS cancelado/credenciales denegadas (hoy) | sin acceso a AWS | Start Lab + renovar credenciales antes de la etapa AWS |
| RDS detenida se reinicia sola a los 7 días | consumo no previsto | `stop` tras cada ventana; revisar fecha límite |
| Cuenta OCI exige tarjeta o falla la verificación | bloquea OCI | decisión de la usuaria; alternativa: Azure Blob como destino de copia |
| Capacidad Always Free no disponible | sin VM de recuperación | otra AD/región de origen o crédito de prueba |
| Azure: crédito/vigencia sin confirmar, proveedores no registrados, cuota 0 en tamaños B | bloquea Azure | etapa 0 de verificación (solo lectura + registro de proveedores con autorización) |
| Clave de descifrado del respaldo | pérdida = respaldo inservible; exposición = datos | custodia offline; aportarla solo en simulacros |
| Abrir puertos de monitoreo | superficie de ataque | NSG por IP, TLS, agentes activos (sin entrada en AWS) |
| Certificado ACM importado vence el 1-ene-2027 | HTTPS de V2 | reimportar o dominio con validación DNS |
| Multi-AZ en el laboratorio sin probar | puede denegarse o cortar el servicio unos minutos | evaluar solo lectura primero; aplicar en ventana con respaldo |
| Secretos en Git/logs/capturas | fuga | gitleaks y Trivy ya en CI; capturas con revisión; credenciales fuera del repositorio |
