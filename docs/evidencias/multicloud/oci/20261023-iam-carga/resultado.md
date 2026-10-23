# OCI — IAM de la identidad de carga (dominio Default) — 2026-10-23 UTC

Estado: **implementado y verificado por lectura de la API**. Sin claves API generadas, sin transferencia, sin VM.

## Aplicación (estado Terraform `oci`)
- Primer `apply`: creó el grupo `nexoeventos-backup-uploaders` y estrechó la política; el usuario falló: el dominio de identidad exige correo principal (`primaryEmailNotSpecified`).
- Variable `uploader_user_email` (sensible, sin valor por defecto) definida solo en el tfvars local fuera de Git. Plan: 3 a crear, 0 cambiar, 0 destruir → `apply` del plan guardado, sin `-auto-approve`: usuario `nexoeventos-backup-uploader`, capacidades y membresía.

## Verificación (API)
- Usuario ACTIVE; capacidades: solo `can_use_api_keys=true`; consola, auth tokens, SMTP y claves de secreto en `false`.
- Pertenece únicamente a `nexoeventos-backup-uploaders` (no a `Administrators`). La única política del tenancy es `Tenant Admin Policy`, sin relación con este grupo.
- Política del compartimento: lectura de buckets limitada a `nexoeventos-recovery`; objetos solo OBJECT_CREATE/READ/INSPECT en ese bucket. Sin OBJECT_DELETE, OBJECT_OVERWRITE ni administración de buckets.

## Pendiente
Clave API independiente del usuario de carga (se genera fuera del repo y se registra manualmente), transferencia de respaldos, VM de recuperación.
