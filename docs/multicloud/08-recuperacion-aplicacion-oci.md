# 08 — Recuperación de la aplicación NexoEventos en OCI (diseño para revisión)

Estado: **diseñado y con plan de Terraform revisable; nada creado ni aplicado**. Complementa la recuperación de datos ([07](07-simulacro-oci.md)).

## Objetivo y alcance
Demostrar que NexoEventos (PostgreSQL 18 + FastAPI + Nginx + frontend React/Vite) se ejecuta desde OCI con el respaldo restaurado de AWS. Entorno **temporal** (se destruye al terminar), sin tocar el DNS de producción ni AWS. El acceso es solo por túnel de OCI Bastion.

## Arquitectura
Una VM Oracle Linux 9 en la subred privada existente (`10.30.1.0/24`, sin IP pública, sin Internet Gateway ni NAT):
- **PostgreSQL 18.6** (RPM PGDG ya verificados), solo socket Unix; base `nexoeventos` restaurada del respaldo cifrado (descifrado en la Mac de la propietaria, como en el simulacro); rol de aplicación sin superusuario con contraseña aleatoria generada en la VM y guardada solo en tmpfs.
- **FastAPI/uvicorn** (Python 3.12 de los repositorios de Oracle) en `127.0.0.1:8000`, unidad systemd existente (`deploy/systemd/nexoeventos-api.service`), `APP_ENV=production`, cookies seguras.
- **Nginx** (repositorios de Oracle) sirve `frontend/dist` y hace proxy de `/api/` (plantilla de `deploy/nginx`, variante con certificado autofirmado para el origen de la demostración).
- **Acceso:** sesión de reenvío de puerto de OCI Bastion al `443` de la VM (IP /32 de la propietaria) → `https://localhost:8443` en su Mac; `FRONTEND_ORIGINS=https://localhost:8443`. No hay IP pública ni cambio de DNS. Administración: Bastion → SSH/22.
- **Sin Internet:** paquetes del sistema (Python, Nginx) por el espejo de Oracle vía Service Gateway (TCP 443); ruedas Python, `frontend/dist` y RPM de PostgreSQL se construyen/verifican en la Mac y se copian por scp.

## Forma de la VM, capacidad y cuotas (São Paulo, AD-1, consultado el 2026-10-23)
| Opción | Estado | Nota |
|---|---|---|
| `VM.Standard.A1.Flex` 1/2/4 OCPU (6/12/24 GB), Always Free | **OUT_OF_HOST_CAPACITY** en las tres configuraciones | Preferida; reintentar el informe de capacidad antes de aplicar |
| `VM.Standard.E4.Flex` 1 OCPU / 8 GB | OUT_OF_HOST_CAPACITY | — |
| `VM.Standard.E5.Flex` 1 OCPU / 8 GB (x86_64) | **AVAILABLE** | No es Always Free; se paga con créditos del Free Trial |
| `VM.Standard.E2.1.Micro` (Always Free) | Disponible | 498 MB de RAM útiles: insuficiente para PostgreSQL + API + Nginx con holgura |
Cuotas (Free Trial): A1 41 núcleos / 277 GB, E5 13 núcleos. Always Free real: 4 OCPU / 24 GB A1 y 200 GB de bloque; el volumen de 50 GB cabe. **Propuesta:** intentar A1 (2 OCPU/12 GB) y, si sigue sin capacidad, **E5.Flex 1 OCPU/8 GB con `allow_trial_paid_shape=true`**. Requiere aprobación explícita; no se actualiza la cuenta a Pay As You Go.

## Compatibilidad ARM64 / x86_64
- Backend: las 33 dependencias de `requirements-production.lock` tienen rueda binaria para CPython 3.12 en `manylinux_2_28` **aarch64 y x86_64** (verificado con `pip install --dry-run --platform …`), incluidas `argon2-cffi-bindings`, `cryptography`, `psycopg[binary]` y `pydantic-core`. Python 3.12 es el de CI y del Dockerfile.
- PostgreSQL 18.6 PGDG `rhel9.8` existe para **aarch64** y x86_64 (los x86_64 ya se verificaron por firma y se instalaron en el simulacro; los aarch64 deben verificarse igual antes de usar A1).
- Frontend: `dist` es estático (se construye con Node 24 en la Mac, 11 MB); sin dependencia de arquitectura.
- Imagen: Oracle Linux 9.8 oficial (`aarch64` y x86_64, 2026-10-16). El backend ya corre en arm64 en la Mac de desarrollo; no se probó aún en una A1 de OCI.

## Secretos de la aplicación (dependencia crítica)
`TICKET_ENCRYPTION_KEY` y `SECURITY_HASH_KEY` no están en el respaldo de la base. Sin ellas, los tickets existentes no se pueden descifrar/validar. Opciones: **(A, recomendada)** leer esas dos claves de AWS Secrets Manager con el laboratorio activo (solo lectura), cifrarlas en tubería con el certificado de recuperación de OCI y subirlas como objeto adicional; se descifran en la Mac y llegan por SSH a un archivo en tmpfs (0600) de la VM; **(B)** claves nuevas: la aplicación arranca, pero los tickets previos no validan (no demuestra continuidad real). Se elegirá con la propietaria. Otras variables: `FRONTEND_ORIGINS`, `SESSION_COOKIE_SECURE=true`, `DATABASE_URL` local. El certificado TLS autofirmado requiere una clave privada efímera generada en la VM (se destruye con ella): necesita aprobación explícita.

## Pruebas (sin ventas reales ni cambios permanentes)
La base de OCI es una copia desechable; se toma la huella (10 comprobaciones) **antes** de las pruebas.
1. Arranque: `systemctl is-active` de postgresql/API/nginx; `GET /healthz` = 200 (verifica BD).
2. Inicio de sesión con una cuenta de demostración existente (la contraseña la introduce la propietaria en la terminal; no se guarda): `POST /api/auth/login`, cookie segura, `GET /api/me`.
3. Catálogo: `GET /api/events` devuelve los eventos publicados (35 en total en la base).
4. Reservas: consulta de las reservas del usuario de demostración (solo lectura; 135 en total).
5. Tickets: validación de un ticket **existente** con la ruta de operador (escribe una fila en `access_logs` de la copia; se documenta el delta esperado y se verifica que reservas/tickets/inventario no cambian). Requiere la opción A de secretos.
6. Restricciones: puerto 5432 sin TCP, Nginx solo accesible por el túnel, sin IP pública, `x-forwarded` correcto, cabeceras de seguridad de Nginx presentes.

## Medición del tiempo de recuperación integral (RTO del servicio)
`T0` = orden de recuperación (inicio de `terraform apply` de la VM); `T1` = primer `/healthz` 200 sobre datos restaurados; `T2` = prueba funcional completa correcta. Fases registradas con marca de tiempo UTC: aprovisionamiento (apply), preparación del SO (swap/paquetes), instalación de PostgreSQL, restauración (descifrado local + transmisión + `pg_restore`), secretos, arranque de la API y Nginx, humo funcional. Se informan **por separado**: RTO de datos (hasta huella verificada), RTO del servicio (T1) y RTO funcional (T2), y los desvíos/fallos. Dos mediciones si el tiempo lo permite: fría (todo desde cero) y caliente (artefactos ya copiados). Objetivo propuesto (a validar): RTO del servicio ≤ 60 min. RPO: el del último respaldo (hoy 0 min respecto al estado de producción: los datos no cambiaron desde el respaldo).

## Costos estimados (no verificados con facturación de OCI)
- E5.Flex 1 OCPU/8 GB: del orden de USD 0,05/h (lista pública aproximada); una sesión de 3–4 h ≈ USD 0,2, con cargo a créditos del Free Trial. Con A1 Always Free: USD 0. Volumen de 50 GB dentro de Always Free/créditos; Bastion y Service Gateway sin cargo; sin IP pública, NAT ni balanceador.
- Riesgo: dejar la VM encendida; se destruye con plan revisado y `preserve_boot_volume=false`.

## Riesgos
Capacidad A1 intermitente; 8 GB/E5 consumen créditos; secretos de producción en tránsito (cifrados en tubería, nunca en disco ni Git); instalación de paquetes lenta en VMs pequeñas (se usa swap); certificado autofirmado (aviso del navegador); datos de producción en la copia (se destruyen con el volumen); el RTO medido dependerá de la forma elegida.

## Evidencias para la rúbrica
Plan Terraform (resumen y no-op de lo demás), capacidades consultadas, tabla de compatibilidad, `tiempos.txt` por fase, salidas de las 6 pruebas (códigos HTTP, conteos, hashes; sin cookies ni tokens), huella antes/después, captura del navegador sobre `https://localhost:8443` sin datos personales, verificación de eliminación y estado final, y registro de fallos.

## Plan Terraform (para revisión; no aplicado)
`work/terraform-plans/oci-app-demo.tfplan` (fuera de Git): **3 a crear, 1 a modificar, 0 a destruir**: VM `E5.Flex` 1 OCPU/8 GB con volumen de 50 GB y sin IP pública; OCI Bastion (solo tu /32, sesiones de 1 h); regla NSG de entrada TCP/443 desde la subred; regla de salida TCP/443 hacia la subred en la lista de seguridad predeterminada (modificación en el sitio). Variables nuevas: `app_https_enabled` y `allow_trial_paid_shape` (ambas `false` por defecto).

## Decisiones aprobadas (2026-10-23) y preparación
- Secretos: **opción A** (claves originales `TICKET_ENCRYPTION_KEY` y `SECURITY_HASH_KEY`), solo en el entorno temporal. Forma: `VM.Standard.E5.Flex` 1 OCPU / 8 GB con créditos del Free Trial. Certificado TLS y clave privada efímeros generados en la VM (`/etc/nginx/demo-tls`, se destruyen con ella). Arquitectura privada aprobada.
- **Costos confirmados con la lista de precios pública de Oracle (USD):** E5 OCPU 0,03/h; E5 memoria 0,002/GB·h; bloque 0,0255/GB·mes; unidades de rendimiento 0,0017/GB·mes por VPU. VM 1 OCPU + 8 GB = 0,046/h; volumen de 50 GB (10 VPU/GB) ≈ 0,0029/h; **total ≈ 0,049/h: ~0,20 USD en una ventana de 4 h y ~1,17 USD si queda 24 h**. Bastion y Service Gateway sin cargo; sin IP pública, NAT, balanceador ni salida a Internet. La API de uso no muestra consumo en octubre (todo ha sido gratuito hasta ahora). **El estado Free Trial y el saldo de créditos no se pueden leer con este perfil**: se confirman en la consola (Facturación → Suscripción).
- Variables mínimas de la aplicación (inspección del código): `APP_ENV`, `DATABASE_URL`, `FRONTEND_ORIGINS`, `SESSION_COOKIE_SECURE`, `SESSION_HOURS`, `LOGIN_*`, `ARGON2_MAX_CONCURRENT`, `DB_POOL_SIZE`, `DB_MAX_OVERFLOW`, `TICKET_ENCRYPTION_KEY`, `SECURITY_HASH_KEY`. Solo las dos últimas son secretos de aplicación; la contraseña de BD se genera en la VM y no sale de ella.

## Recuperación de secretos (cifrada, separada del código y de los datos)
1. `scripts/multicloud/oci-drill/app-secrets-export.sh` (con el laboratorio AWS activo, solo lectura): lee `nexoeventos/academy/backend-env`, **filtra con lista blanca las dos claves** y las cifra en tubería (CMS AES-256) con el certificado público de recuperación; los valores no tocan disco, pantalla ni registros. Genera un paquete y un manifiesto (nombres de claves y SHA-256) en `work/`.
2. Se sube con el perfil de carga a `secrets/` del bucket (objeto distinto del respaldo de datos).
3. En la recuperación, `app-recovery.sh` descifra **en la Mac de la propietaria** (segunda frase de paso) y entrega las claves por SSH a `/run/nexoeventos/secrets.env` (tmpfs, 0600) mediante `install-app-secrets.sh`; el servicio las lee por `EnvironmentFile`. Nunca se registran, imprimen ni suben a Git; se pierden al reiniciar o destruir la VM.
Prueba local con datos **ficticios** y el certificado real (sin descifrar): ninguna cadena en claro dentro del CMS, destinatario = serial del certificado, solo las dos claves admitidas, falla (código 3) si falta una.

## Scripts preparados (sin ejecutar contra la nube)
`app-secrets-export.sh`, `install-app-secrets.sh`, `install-app.sh` (etapas 1 y 2), `app-recovery.sh` (orquestador con marcas T0/T_datos/T_servicio/T_funcional) y `app-smoke.py` (pruebas funcionales por el túnel HTTPS; contraseñas por `getpass`, sin ventas; la validación de un ticket escribe una fila en `access_logs` de la copia desechable). Solo se validaron sintaxis y la transformación de la plantilla de Nginx con la plantilla real.

## Ventana de despliegue propuesta (una sola)
Antes: confirmar créditos, AWS lab activo (lectura del secreto), `app-secrets-export.sh` + subida, A1 sin capacidad (reintento del informe). Durante: `apply` del plan (3 altas, 1 modificación), dos sesiones de Bastion (SSH y 443), `app-recovery.sh`, evidencias. Después: plan de destrucción revisado.
**Riesgos específicos:** SELinux en Oracle Linux (se aplican `httpd_can_network_connect` y etiquetas del frontend); `pip download` en la Mac necesita Internet; la cuenta de demostración debe tener tickets con QR para probar la validación; la IP /32 del Bastion puede cambiar.
