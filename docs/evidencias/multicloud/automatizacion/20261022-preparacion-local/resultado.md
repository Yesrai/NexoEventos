# Preparación local multicloud · 22-oct-2026 (sin nubes, sin recursos, sin secretos)

Validaciones ejecutadas **solo en local**; los archivos `*.txt` de esta carpeta son su salida original.

| Validación | Resultado | Archivo |
|---|---|---|
| Coherencia de `docs/multicloud` con Terraform y estado real de AWS (CIDR, subredes, sin solape entre nubes, raíces citadas, etapas 0–11, región de Azure permitida) | 28/28 OK | `coherencia.txt` |
| Terraform OCI: `fmt -check` y `validate` (proveedor `oracle/oci` 9.11.0, 4 módulos) | correcto | `terraform-oci.txt` |
| Terraform Azure: `fmt -check` y `validate` (`azurerm` 5.10.0, 4 módulos) | correcto | `terraform-azure.txt` |
| Seguridad estática de la IaC (bucket privado, sin IP pública ni Internet Gateway, NSG por IP, VM y NAT desactivados por defecto, mínimo privilegio, sin secretos) | 13/13 OK | `seguridad-iac.txt` |
| Transferencia cifrada y restauración aislada con **claves desechables** (base local con reservas de ensayo → CMS «AWS» → re-cifrado con clave «OCI» independiente → SHA-256 → restauración en PostgreSQL 18 → huella idéntica) + 7 casos negativos | 16/16 OK (restauración de ensayo en 7 s) | `restauracion-local.txt` |
| Búsqueda de patrones de secretos/OCID en lo nuevo | ninguno | `secretos.txt` |

Limitaciones: no se ejecutó `plan` (requiere credenciales); los costos son estimaciones por tarifa pública; la restauración probada es local (Docker) y no equivale a la VM de OCI; las claves y el volcado de la prueba eran desechables y se destruyeron; el RTO de 7 s corresponde a una base de ensayo, no a OCI.
