# Paso 0 — respaldo y prueba de compatibilidad del disco de la VM de Azure (4-nov-2026, saneado)

**Estado: COMPLETADO sin cambios en la VM ni en el disco original.** Horas UTC; Perú = UTC−5. Solo recursos nuevos: 1 instantánea, 1 disco de prueba y 3 bloqueos.

## Antes
VM `vm-nexoeventos-obs` `deallocated`. Disco de SO original (`disco-original-antes.json`): **64 GiB**, `StandardSSD_LRS`, `centralus`, Linux, **Gen2 / Trusted Launch**, cifrado con clave de plataforma, creado el 28-oct, adjunto a la VM (`Reserved`), sin zonas, etiquetas `managed_by=Terraform`.

## Qué se creó
| Recurso | Detalle |
|---|---|
| Instantánea `snap-vm-nexoeventos-obs-os-20261104` (01:14:43 UTC) | **incremental**, `Standard_LRS`, 64 GiB, `provisioningState = Succeeded`, **conserva `TrustedLaunch`**, Gen2, cifrado de plataforma; su fuente es el disco original y su `sourceUniqueId` **coincide** con el `uniqueId` del disco original (`instantanea.json`) |
| Disco de prueba / de reversión `disk-prueba-vm-nexoeventos-obs-os-20261104` (01:15:21 UTC) | creado desde la instantánea: 64 GiB, `StandardSSD_LRS`, Gen2, **`TrustedLaunch` heredado**, cifrado de plataforma, `Unattached`, `Succeeded` (`disco-prueba.json`) |
| Bloqueos `CanNotDelete` | en la instantánea, en el disco de prueba y en el **disco original** (solo impiden borrar; no impiden desacoplar/cambiar el disco de una VM ni arrancar/parar) |

## Hallazgo de compatibilidad
- Azure **sí** permite una copia compatible: el tipo de seguridad `TrustedLaunch` **se hereda** de la instantánea al disco.
- El primer intento con `--security-type TrustedLaunch` falló con `BadRequest`: **«Security Type 'TrustedLaunch' is not supported for CreateOption 'Copy'»**; no dejó ningún recurso a medias. Sin ese flag la creación funcionó (resultado verificado con `az disk show`).
- **Sigue sin demostrarse** que ese disco se pueda **adjuntar como disco de datos** a otra VM Trusted Launch (Paso 1) ni que el **cambio de disco** de la VM original funcione: eso solo se comprueba en los pasos siguientes.

## Comprobaciones posteriores
Disco original: **0 propiedades distintas** entre antes y después (comparación completa salvo `etag`). VM: **0 propiedades distintas**, `osDisk` igual, sigue `deallocated`. NSG `admin-https` igual a la original. Recursos del grupo: 14 (12 + instantánea + disco de prueba); grupos de la suscripción: 2. No se tocó UFW, SSH, NSG, Terraform, AWS ni OCI.

## Coste de conservarlos (estimaciones con tarifas públicas, sin verificar con facturación)
- Disco de prueba E6: **4,80 USD/mes ≈ 0,16 USD/día** (se factura por el tamaño del disco aunque no se use).
- Instantánea incremental: se factura por datos usados (supuesto 0,05 USD/GiB·mes; el precio no se pudo consultar en la API pública); cota máxima 64 GiB ≈ 0,11 USD/día, esperado ≈ 0,01–0,02 USD/día.
- **Total ≈ 0,17–0,27 USD/día**; costó crearlos centavos. Recomendación: conservarlos solo durante la operación y borrarlos al terminar (requiere quitar los bloqueos y tu autorización).

## Nota sobre bloqueos y Terraform
El bloqueo `CanNotDelete` del disco original hará fallar un borrado accidental, **incluido el de un `terraform destroy` de la VM/disco**: antes de destruir en el futuro hay que quitar los bloqueos con autorización. No afecta a `az vm start/deallocate` ni a un cambio de disco.
