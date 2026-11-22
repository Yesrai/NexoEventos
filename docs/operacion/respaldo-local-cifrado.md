# Respaldo local cifrado para reconstruir NexoEventos (AWS V2) en otra sesión, cuenta o laboratorio

Preparado el 22-nov-2026. **Es una copia LOCAL: no se ha subido ni compartido en ningún servicio.** Mientras solo exista en este Mac, **no protege** contra la pérdida del equipo: falta la copia externa segura (§7). Esta guía no contiene contraseñas, claves ni valores de secretos.

## 1. Qué es y cómo se crea
`scripts/ops/respaldo-reconstruccion.sh create` genera `work/respaldo-cifrado/nexoeventos-reconstruccion-<fecha>.tar.cms` (CMS, AES-256-CBC) cifrado con la **clave PÚBLICA** de recuperación del proyecto (`work/recovery-keys/<corrida>/recovery-public.crt`). No pide ni imprime contraseñas. Junto al archivo quedan: su SHA-256 (`.tar.cms.sha256`), el SHA-256 del paquete sin cifrar (`.paquete.sha256`, solo para comprobar el descifrado) y un inventario saneado (`.inventario.md`: contadores y tamaños, sin nombres sensibles). Todo con permisos 0600 en un directorio 0700 ignorado por Git.

## 2. Qué contiene (dentro del paquete cifrado)
| Parte | Contenido | Para qué sirve |
|---|---|---|
| `repositorio.bundle` | `git bundle --all`: todas las ramas y etiquetas con sus commits (incluidos los **locales sin publicar**) | Reconstruir el repositorio completo (Terraform, scripts, Ansible, migraciones de Alembic, backend, frontend, docs y evidencias ya versionadas) sin depender de GitHub |
| `sin-publicar.tar.gz` | Archivos **modificados o nuevos sin commit** (p. ej. `rds-window.sh`, `review-plan.py`, las guías de operación) | No perder trabajo no versionado |
| `work-esencial.tar.gz` | De `work/`: `terraform-envs` (tfvars locales), `terraform-state` (estado de Terraform), `ansible` y `ansible-secrets`, `backups` y `portable-backups` (respaldos cifrados de la BD), `restauracion`, `evidencias`, `observability`, `failover-lab`, `oci-transfer`, `cloud-readonly`, `carga`, `obs-lab`, `c04`, los archivos sueltos de `work/operacion` (registros, IDs de AMI y certificado) y **solo el certificado público** de recuperación | Rehacer tfvars, estado, secretos de Ansible y registros de operación |
| `MANIFIESTO.sha256`, `PARTES.sha256`, `LEEME-RESTAURAR.txt` | SHA-256 por archivo y por parte; instrucciones | Comprobar la integridad al restaurar |

## 3. Qué NO contiene (a propósito)
- **La clave privada de recuperación** (`recovery-private.pem`) ni otras claves privadas (`*.pem`, `*.key`, claves de OCI y SSH): cifrar la clave dentro de su propio paquete lo haría irrecuperable justo cuando hace falta. **Debe guardarse aparte** (§7).
- **Credenciales de AWS Academy** (perfil `nexoeventos-lab`, `/tmp/nexoeventos-aws-current`): son temporales y caducan; se renuevan en cada sesión.
- Planes de Terraform (`*.tfplan`; contienen valores sensibles y se regeneran), cachés de proveedores (`.terraform`, 2,9 GB), entornos virtuales, `node_modules`, builds, paquetes de release regenerables (`work/releases`, `scripts/build-release.sh`), el respaldo previo de reescritura de historia, `work/ia-s14` y las **capturas originales sin redactar** (`~/Pictures/Capturas`; en el repositorio solo están las copias redactadas).
- Los **datos de PostgreSQL**: no se exportan aquí; viven en la RDS, sus instantáneas y los `.cms` de la BD (que sí van en `work/backups` y `work/portable-backups`).

## 4. Materiales sensibles (dónde están y cómo se protegen)
`work/` está ignorado por Git (`.gitignore`): tfvars (ID de cuenta, ARN), estado de Terraform, secretos de Ansible, claves de recuperación y respaldos. Ningún archivo de `work/` se versiona ni se cita con su contenido en documentación pública. Los documentos del repositorio (incluida esta guía) solo enumeran **categorías y nombres de variables**, nunca valores.

## 5. Verificar el respaldo (sin escribir nada fuera de un temporal 0700 que se borra)
```bash
scripts/ops/respaldo-reconstruccion.sh verify --key work/recovery-keys/<corrida>/recovery-private.pem
```
Comprueba, por este orden: SHA-256 del archivo cifrado; **descifrado real** con la clave privada; SHA-256 del paquete descifrado igual al original; integridad de las tres partes; `git bundle verify`; **todos** los archivos extraídos contra el manifiesto; ausencia por nombre de claves privadas, credenciales y planes; y que `work/` no contiene por patrón claves privadas ni credenciales de AWS. Resultado del 22-nov-2026: **verificación completa** (paquete de 399 MB; repositorio con 8 referencias; 1144 archivos coinciden con su SHA-256; 13 archivos de estado de Terraform; 0 claves privadas por nombre). La clave se usa solo como ruta; no se imprime.

## 6. Restaurar en otro equipo o sesión
1. Tener el `.tar.cms` y **la clave privada de recuperación** (guardada aparte).
2. `openssl cms -decrypt -binary -inform DER -in <paquete>.tar.cms -inkey <clave-privada> -out paquete.tar`
3. `tar xf paquete.tar && shasum -a 256 -c PARTES.sha256`
4. `git clone repositorio.bundle NexoEventos` (todas las ramas y commits locales).
5. `tar xzf sin-publicar.tar.gz -C NexoEventos` y `tar xzf work-esencial.tar.gz -C NexoEventos` (reaplicar encima del clon; permisos 0600/0700).
6. `cd` a las extracciones y `shasum -a 256 -c MANIFIESTO.sha256` (rutas relativas a `sin-publicar/` y `work-esencial/`).
7. Reinstalar herramientas (`terraform`, `aws`, `jq`, `python3`, `ansible`), regenerar el entorno (`npm ci`, `pip`), inicializar Terraform (`terraform init` en `infra/aws-v2`) y renovar las credenciales de Academy (guía de reconstrucción §4).
No sustituye ni borra los originales.

## 7. Qué falta para una copia externa segura (pendiente; requiere decisión de la propietaria)
1. **Copiar el `.tar.cms` a un soporte o servicio FUERA de este Mac y de la cuenta de AWS** (disco externo, nube personal, etc.); el archivo ya está cifrado, así que es seguro de mover. Comprobar su SHA-256 en el destino.
2. **Guardar la clave privada de recuperación por separado** (gestor de contraseñas o soporte cifrado distinto del paquete). Hoy está en este mismo Mac sin contraseña: quien tenga el Mac puede descifrar el paquete; y si el Mac se pierde, **sin esa clave el paquete es irrecuperable**. Recomendable protegerla con una frase de paso.
3. Guardar también (por separado) las **claves de OCI** (`~/.oci/`), las claves SSH y las capturas originales, que este paquete no incluye.
4. Probar la restauración **desde la copia externa** una vez, en otro directorio.
Hasta que existan 1 y 2, el respaldo **no debe presentarse como recuperable ante la pérdida del equipo**.

## 8. Qué NO se traslada a otra cuenta o laboratorio al ejecutar Terraform
Terraform solo crea recursos nuevos en la cuenta activa; **no copia** nada que ya exista en la cuenta anterior. Con una cuenta o un laboratorio nuevos hay que rehacer por separado:
| Recurso de AWS | Por qué no se traslada | Qué hacer |
|---|---|---|
| **AMI dorada** y sus instantáneas EBS | Son de la cuenta de origen (las AMI no cruzan cuentas sin compartirlas explícitamente, que no se ha hecho) | Reconstruir: `v2-prepare.sh builder-*` + `scripts/ansible-aws.sh bake` (≈ 45 min) |
| **RDS** y sus instantáneas | Datos y copias de la cuenta anterior | Restaurar desde un `.cms` descifrado (o compartir/copiar una instantánea manualmente; cifrada con clave de la cuenta de origen) |
| **Secretos** (Secrets Manager) | Los valores no viajan | Recrearlos desde el `backend.env` original o el paquete de recuperación; sin la `TICKET_ENCRYPTION_KEY` original los QR no se descifran |
| **Certificado de ACM** (importado) | Es de la cuenta | Volver a importarlo o emitir otro; actualizar `certificate_arn` |
| **Buckets S3** y objetos (respaldos `.cms`, `deployment-source`) | Contenido de la cuenta | Re-subir desde `work/backups` / OCI |
| **Roles e instance profile** (`LabRole`, `LabInstanceProfile`) | Los define Academy en cada cuenta | Comprobar nombres y permisos; ajustar `instance_profile_name` |
| **Estado y tfvars de Terraform** | `expected_account_id` y los IDs son de la cuenta anterior | Crear un entorno nuevo (`work/terraform-envs/<nuevo>.tfvars`, estado propio) según `migracion-entre-cuentas.md`; **no reutilizar** el estado de la cuenta antigua |
| **Cuotas, regiones y SCP** | Cada cuenta/laboratorio tiene las suyas | Verificar tamaños y regiones permitidos antes de planificar |
Ver también [migracion-entre-cuentas.md](migracion-entre-cuentas.md) y [aws-v2-reconstruccion.md](aws-v2-reconstruccion.md).
