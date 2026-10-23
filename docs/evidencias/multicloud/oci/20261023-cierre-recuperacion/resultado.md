# Cierre de la recuperación OCI — retirada de la VM temporal y Bastion — 2026-10-23 (UTC)

Estado: **ejecutado y verificado por API**. Sin cambios en AWS ni Azure.

## Destrucción
- Commit `9dfa0da` publicado antes (CI: 4 de 4 jobs correctos).
- Plan regenerado con el estado actual: 0 altas, 0 modificaciones, 2 destrucciones (VM `nexoeventos-recovery-drill` y Bastion `nexorecovery`); 15 recursos restantes sin cambios; `preserve_boot_volume=false`.
- `terraform apply` del plan guardado, sin `-auto-approve`: VM destruida en 1 min 15 s, Bastion en 1 min 30 s; total 91 s. `Apply complete! 0 added, 0 changed, 2 destroyed`.

## Estado final (API)
- VM: `TERMINATED`. Bastion: `DELETED`. Volumen de arranque de 50 GB: `TERMINATED` (no conservado; los datos restaurados en `drill` desaparecen con él).
- Intactos: VCN y subred privada (AVAILABLE), Service Gateway, NSG (2 reglas), lista de seguridad predeterminada (0 reglas de entrada; única salida TCP/22 hacia la subred), grupo `nexoeventos-backup-uploaders`, usuario de carga ACTIVE y política de privilegio mínimo.
- Bucket `nexoeventos-recovery`: `NoPublicAccess`, versionado `Enabled`, con los dos objetos del respaldo: `.oci.cms` (92.060 bytes, SHA-256 `ae87bb87…` igual al manifiesto) y `.manifest.json` (628 bytes, SHA-256 `8c737fae…`), verificados por descarga en streaming.
- Claves: la clave de recuperación privada permanece solo en la estación de la propietaria; no se tocó la clave API del usuario de carga.

## Costos
Recursos remanentes sin cargo previsto (VCN, subred, Service Gateway, NSG, IAM) y ~92 KB en Object Storage; estimado USD 0, no verificado en el panel de costos de OCI.
