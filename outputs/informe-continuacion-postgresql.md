# Continuación de NexoEventos — PostgreSQL y reservas

Fecha: 1 de octubre de 2026.

## Ruta definitiva

`<project-root>`

La carpeta anterior tenía un nombre generado por la tarea. No contenía otro proyecto ni historial Git previo: estaba vacía al comenzar y todos los archivos eran identificables como NexoEventos. Se renombró completa, preservando `.git`, dependencias y archivos.

## Azure

La suscripción observada continúa siendo Azure for Students, activa, con rol Propietario y sin recursos. La comprobación de crédito, vencimiento, políticas y cuotas sigue pendiente porque la pestaña oficial permanece en `Selección de la cuenta`; no se seleccionó una identidad ni se introdujo MFA. No se crearon recursos ni se registraron proveedores.

## Node.js

El proyecto fija Node.js 24.21.0 mediante `.nvmrc`, `.node-version`, `engines`, `.npmrc` y configuración de terminal de VS Code. La compilación y las pruebas registraron `Node efectivo: v24.21.0`. Node 26 no fue desinstalado ni cambiado globalmente.

## PostgreSQL

- PostgreSQL local: 14.18.
- Base de desarrollo: `nexoeventos`.
- Base de pruebas: `nexoeventos_test`.
- Propietario de objetos: `nexoeventos_owner`, sin inicio de sesión.
- Usuario de aplicación: `nexoeventos_app`, sin privilegios administrativos.
- No se modificó ninguna base ajena ni contraseña global.

Permisos efectivos del usuario de aplicación:

- Puede conectarse y leer eventos.
- Puede actualizar únicamente la columna `reserved_count`.
- Puede leer e insertar reservas para idempotencia y creación.
- No puede crear tablas, insertar eventos ni borrar reservas.

## Funciones implementadas

- Migración Alembic reproducible con tablas, restricciones y tres eventos ficticios.
- Catálogo y detalle consultan PostgreSQL.
- Reservas simuladas mediante transacción y bloqueo de fila.
- Control de cupos también protegido por restricción de base.
- Idempotencia con clave única y hash de la solicitud.
- Un reintento idéntico devuelve la misma reserva sin descontar otra vez.
- Una clave reutilizada con otros datos devuelve HTTP 409.
- No existe endpoint público GET de reservas.
- Frontend con detalle, formulario de compra simulada y aviso explícito de que no hay pagos reales, autenticación ni QR.

## Pruebas

- Backend/PostgreSQL: 6 aprobadas.
- Frontend/Vitest: 1 aprobada.
- Build TypeScript/Vite: correcto.
- Terraform validate: correcto en AWS, Azure y GCP.
- QA visual: escritorio y móvil; catálogo, detalle y formulario responsive.

Las pruebas PostgreSQL comprobaron:

1. Eventos y reserva permanecen al cerrar una instancia de backend, disponer su pool y crear otra instancia.
2. Dos solicitudes simultáneas por el último cupo producen exactamente una reserva y una respuesta 409.
3. Repetir clave y cuerpo devuelve la misma reserva y no consume más cupos.
4. Reutilizar la clave con una cantidad diferente devuelve un conflicto controlado.
5. `/api/reservations` no existe como endpoint público.

## Pendientes reales

- Completar selección de cuenta/MFA de Azure para consultar crédito, vencimiento, políticas y cuotas.
- Autenticación y autorización de usuarios.
- Roles de cliente, organizador y operador.
- Generación y validación de QR.
- Endpoints privados para que una identidad autenticada consulte sus reservas.
- AWS Learner Lab no fue iniciado.
