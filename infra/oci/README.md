# OCI — recuperación (preparación local; NADA desplegado)

Raíz Terraform con **estado propio**, módulos `iam`, `network`, `storage` y `recovery`. Valida con `terraform fmt -check` y `terraform validate`; no se ha ejecutado `plan`/`apply` ni existe cuenta OCI.

| Módulo | Recursos | Seguridad |
|---|---|---|
| `iam` | compartment `nexoeventos`, política del grupo de subida | solo `OBJECT_CREATE/READ/INSPECT` en un bucket; sin borrar ni administrar |
| `network` | VCN `10.30.0.0/16`, subred privada `10.30.1.0/24`, Service Gateway, NSG, NAT (opcional) | sin Internet Gateway ni IP pública; entrada solo SSH desde la propia subred (Bastion); salida 443 a servicios de Oracle |
| `storage` | bucket Standard, `NoPublicAccess`, versionado | privado; cifrado por defecto de Oracle + CMS propio de la copia |
| `recovery` | VM temporal (`create=false`), OCI Bastion | sin IP pública; clave SSH pública; se destruye tras cada simulacro |

Uso futuro (con autorización): `terraform init -backend-config="path=$PWD/../../work/terraform-state/oci/terraform.tfstate"`, copiar `terraform.tfvars.example` a `work/terraform-envs/oci.tfvars` y revisar `plan` antes de cualquier `apply`. Autenticación por `~/.oci/config` (clave API fuera del repositorio).

## Costos estimados (por tarifa; **verificar** al crear la cuenta y la región de origen)
| Recurso | Estimación |
|---|---|
| Compartment, VCN, subred, NSG, Service Gateway, Bastion | USD 0 (sin cargo en OCI) |
| NAT gateway (solo simulacro) | sin cargo por el gateway; verificar |
| Object Storage 20 GiB (*Always Free*); la copia pesa ≈ 80 KB | USD 0 |
| VM `VM.Standard.E2.1.Micro` (*Always Free*) si hay capacidad | USD 0 |
| Sin capacidad Always Free → VM pequeña de pago | centavos por hora (crédito de prueba) |

Decisión pendiente de la usuaria: región de origen y tarjeta de verificación. Plan alterno si OCI no es viable: Azure Blob como destino de copia.

## Identidad de carga (IAM)

Terraform crea el grupo `nexoeventos-backup-uploaders` y el usuario de servicio `nexoeventos-backup-uploader` en el dominio *Default*, con la capacidad de usar solo clave API (sin contraseña de consola, tokens, SMTP ni claves de secreto). La política limita el grupo a leer el bucket `nexoeventos-recovery` y a OBJECT_CREATE/READ/INSPECT sobre sus objetos: sin OBJECT_DELETE ni OBJECT_OVERWRITE, sin administración de buckets. **La clave API del usuario no se crea con Terraform**: la genera la operadora fuera del repositorio (clave independiente de la de administración) y la registra en la consola; la clave privada nunca entra en Git ni en el estado.
