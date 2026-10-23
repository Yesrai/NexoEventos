# OCI — despliegue base (tenancy `nexoeventos`, sa-saopaulo-1) — 2026-10-23 UTC

Estado: **implementado y verificado por lectura independiente de la API** (sin VM, sin transferencia de respaldos, cuenta Free Trial sin actualizar).

## Aplicación
- Plan revisado: 10 a crear, 0 cambiar, 0 destruir; sin Compute, NAT, Internet Gateway ni IP públicas (comprobado sobre el JSON del plan).
- Estado separado `oci` (local, fuera de Git). Autenticación por clave API en `~/.oci` (fuera del repo).
- Primer `apply`: 9 recursos creados; el bucket falló (`namespace` vacío: el data source `oci_objectstorage_namespace` devolvía vacío al recibir el compartimento recién creado). No fue un error de permisos ni de costo.
- Corrección en `infra/oci/modules/storage/main.tf` (data source sin `compartment_id`; el namespace del tenancy se obtiene igual). Segundo plan: 1 a crear; `apply`: bucket creado. Total 10 recursos.
- Consulta temporal previa con `apply -auto-approve` (solo data sources): no creó recursos ni estado.

## Verificación (lectura de API, sin OCID)
- Bucket `nexoeventos-recovery`: `NoPublicAccess`, versionado `Enabled`, tier `Standard`.
- VCN `10.30.0.0/16` AVAILABLE; subred privada `10.30.1.0/24` con `prohibit_public_ip_on_vnic=true`.
- Rutas: tabla privada solo hacia `all-gru-services-in-oracle-services-network` (Service Gateway AVAILABLE); la tabla por defecto de la VCN no tiene reglas.
- Internet Gateways 0, NAT Gateways 0, instancias 0.
- NSG: INGRESS TCP solo desde `10.30.1.0/24`; EGRESS TCP solo hacia Oracle Services Network.
- Política: lectura de buckets y OBJECT_CREATE/READ/INSPECT solo sobre `nexoeventos-recovery`.

## Costos y límites
- Recursos de este despliegue sin cargo por diseño (VCN, subred, rutas, Service Gateway, NSG, compartimento, política). El bucket Standard solo cobraría por encima del almacenamiento gratuito; la cuota gratuita de Object Storage **no se pudo confirmar por API** y no se revisó en el panel de costos de OCI.
- Límites leídos: vcn-count 50, subnet-count 300, nat-gateway-count 1, bucket-count 10000.

## Pendiente (no hecho)
Grupo/usuario de carga `nexoeventos-backup-uploaders` (la política existe, el grupo no), VM de recuperación, transferencia de respaldos, simulacro de restauración.
