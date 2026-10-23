# Cierre del entorno temporal de recuperación de la aplicación en OCI — 2026-10-23 (UTC)

Estado: **ejecutado y verificado por API**. AWS (EC2 y RDS detenidas) y Azure no se tocaron.

## 1. Destrucción de la VM temporal y el Bastion
- Plan guardado `oci-app-teardown` (0 altas, 0 modificaciones, 2 destrucciones; el resto, sin cambios) comprobado inmediatamente antes de aplicar; `terraform apply` sin `-auto-approve`: VM E5.Flex destruida en 1 min 16 s, Bastion en 1 min 35 s; total 96 s (`Apply complete! 0 added, 0 changed, 2 destroyed`). Los túneles SSH locales se cerraron antes.
- API: instancias `TERMINATED`, Bastions `DELETED`, **volúmenes de arranque `TERMINATED`** (`preserve_boot_volume=false`; no queda ningún volumen disponible); sin volúmenes de bloque. Con ello desaparecen la copia de producción restaurada, el certificado/clave TLS efímeros y los hashes restablecidos de las dos cuentas; las claves de aplicación solo existían en la memoria (tmpfs) de la VM.

## 2. Retirada de las reglas HTTPS temporales
- Segundo plan: 0 altas, 1 modificación, 1 destrucción — eliminar la regla de entrada TCP/443 del NSG y quitar la salida TCP/443 de la lista de seguridad predeterminada; ningún otro recurso afectado. Aplicado: `0 added, 1 changed, 1 destroyed`.
- Estado final de reglas: NSG = entrada **TCP/22 desde la subred** (necesaria para futuras recuperaciones por Bastion) + salida TCP/443 solo hacia Oracle Services Network; lista de seguridad predeterminada = 0 reglas de entrada y única salida TCP/22 hacia la subred.

## 3. Conservado e intacto (API)
VCN y subred privada `10.30.1.0/24` (AVAILABLE), Service Gateway (AVAILABLE), compartimento, grupo `nexoeventos-backup-uploaders`, usuario de carga (ACTIVE, solo clave API) y política de mínimo privilegio; bucket `nexoeventos-recovery` (`NoPublicAccess`, versionado `Enabled`) con los 4 objetos: respaldo de datos cifrado y su manifiesto, y paquete cifrado de claves de aplicación y su manifiesto; SHA-256 de los dos paquetes cifrados verificados por descarga en streaming (coinciden con los manifiestos).

## 4. Costos
Recurso de pago de la ventana: solo la VM E5.Flex (≈ 0,049 USD/h; ≈ 1 h 10 min de existencia ⇒ ≈ 0,06 USD, precios de lista, no verificado con la facturación de OCI; con cargo a créditos del Free Trial). Tras el cierre quedan únicamente recursos sin cargo y ~93 KB en Object Storage. AWS: EC2/RDS detenidas.

## 5. Limitaciones que se mantienen
`already_used` (409) no equivale a una primera validación `accepted` (pendiente); las contraseñas de las dos cuentas de demostración se restablecieron solo en la copia de contingencia, ya destruida.
