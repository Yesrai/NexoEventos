# Informe de continuación — autenticación y entradas QR

Fecha de verificación: 1 de octubre de 2026
Ruta definitiva: `<project-root>`

La carpeta anterior `lleg-nuestro-cat-logo-hot-wheels` es únicamente un enlace simbólico de compatibilidad hacia esta ruta; no contiene un segundo proyecto. El repositorio está inicializado en `main`, pero todavía no tiene commits ni remoto y todos sus archivos permanecen sin seguimiento. No se publicó ni se creó ningún commit.

## Alcance terminado

- Registro público exclusivamente para clientes.
- Inicio y cierre de sesión con sesión opaca persistida en PostgreSQL, cookie `HttpOnly`, expiración de ocho horas y protección CSRF.
- Contraseñas procesadas con Argon2 mediante `pwdlib`.
- Autorización en backend por rol y propiedad para clientes, organizadores y operadores.
- Reservas vinculadas al cliente autenticado, conservando bloqueo transaccional e idempotencia por usuario.
- Una entrada por cupo, con token aleatorio sin datos personales, hash para validación y copia cifrada para el propietario.
- Consulta privada de reservas, entradas y QR.
- Validación de ingreso por operador asignado, con bloqueo de fila y exactamente una aceptación ante solicitudes simultáneas.
- Auditoría de fecha, operador y resultado con huella abreviada; no se guarda el token completo en el log.
- Pantallas de acceso, registro, área personal, entrada QR y control de acceso; lector por cámara bajo permiso explícito y alternativa manual.
- Procedimiento exclusivo de desarrollo para preparar organizador y operador, sin contraseñas predeterminadas.

## Migración

`0002_auth_tickets_and_access.py` agrega usuarios, sesiones, propiedad de eventos y reservas, asignaciones de operadores, entradas y auditoría. No modifica `0001` ni adjudica reservas antiguas a usuarios nuevos. Antes de aplicar la migración se comprobó que desarrollo y pruebas no contenían reservas de demostración; aun así, la columna de propietario queda nullable para preservar cualquier fila heredada.

El usuario de aplicación conserva permisos limitados. Las migraciones y el bootstrap de cuentas privilegiadas usan la conexión administrativa local separada.

## Pruebas ejecutadas

- Backend: `13 passed` contra `nexoeventos_test`.
- Frontend: `1 passed`.
- TypeScript + Vite: compilación correcta, 44 módulos transformados.
- Node efectivo durante prueba y compilación: `v24.21.0`.
- Alembic: base de pruebas en `head`.

La suite comprueba acceso anónimo rechazado, imposibilidad de elevar el rol al registrarse, aislamiento de entradas por cliente, propiedad del organizador, asignación del operador, persistencia tras reinicio, último cupo concurrente, reintentos idempotentes, conflicto de clave entre datos o propietarios, QR inexistente/usado, doble validación concurrente y revocación de sesión al cerrar.

## Probar los roles

1. Ejecutar migraciones: `cd backend && source .venv/bin/activate && alembic upgrade head`.
2. Ejecutar `../scripts/dev-bootstrap.py`. El script solicita contraseñas temporales sin mostrarlas ni guardarlas y prepara las cuentas ficticias cuyos correos imprime.
3. Iniciar el backend con `uvicorn app.main:app --reload --port 8000`.
4. En otra terminal: `cd frontend && PATH="/opt/homebrew/opt/node@24/bin:$PATH" npm run dev`.
5. Abrir `http://localhost:5173`.
6. Registrar un cliente desde la interfaz, reservar y abrir “Mis entradas”. Usar la cuenta de operador preparada para el control de acceso y la de organizador para “Mis eventos”.

No se incluyen contraseñas, tokens QR ni claves de cifrado en este informe.

## Verificación visual

Se revisaron en el navegador la pantalla de inicio de sesión, el panel del operador, la reserva de un cliente, su área privada y el cambio de una entrada de “Disponible” a “Usada”. La cámara no se autorizó durante la comprobación; la validación manual y la lógica concurrente sí quedaron probadas. La captura con el QR no se conserva como archivo porque el código contiene el token de acceso; se conservó únicamente una captura sin secretos del historial con la entrada ya usada en la tarea de Codex.

## Azure y AWS

Azure: el portal estaba autenticado y el propio menú de cuenta indicaba que el inicio usó MFA. La consulta de crédito, vencimiento y cuotas no se completó porque el control de Chrome cambió de pestaña durante la navegación. No se creó ni modificó ningún recurso. Para continuar, dejar abierta y en primer plano la ruta `Suscripciones > Azure for Students`; desde allí faltan `Resumen`, `Créditos` y `Uso + cuotas`.

AWS: no se pulsó “Start Lab”. Al revisar las pestañas se observó que Learner Lab ya figuraba activo, con temporizador cercano a cuatro horas y consumo visible de `Used $0.1 of $50`; esto demuestra presupuesto asignado y uso acumulado, no un saldo certificado. No se creó la VPC que aparecía preparada en otra pestaña ni se accionó ningún control de AWS.

## Limitaciones reales

- No está listo para producción: faltan HTTPS, cookies `Secure`, límites de tasa, recuperación de contraseña, MFA, rotación operativa de claves y revisión de seguridad.
- El lector de cámara depende de `getUserMedia` y `BarcodeDetector`; requiere prueba manual en el navegador/dispositivo objetivo. La alternativa manual funciona.
- No hay pagos reales, emisión fiscal ni integración cloud.
- La auditoría existe en base de datos, pero todavía no tiene interfaz administrativa.
- Queda pendiente terminar la revisión de crédito, vencimiento y cuotas de Azure.
- Antes de trabajo colaborativo o publicación, conviene revisar y crear el primer commit local; actualmente Git no aporta todavía historial recuperable.
