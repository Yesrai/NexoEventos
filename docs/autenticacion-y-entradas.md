# Autenticación, permisos y entradas

## Sesión

El backend usa sesiones opacas almacenadas en PostgreSQL. El navegador recibe un identificador aleatorio en una cookie `HttpOnly`, `SameSite=Lax`; el valor persistido en la base es únicamente su hash SHA-256. La sesión dura ocho horas por defecto y el cierre de sesión elimina el registro del servidor, por lo que reutilizar la cookie anterior no concede acceso.

Las operaciones con cambios requieren un token CSRF independiente mediante cookie y cabecera, además de validar el origen permitido. En un despliegue HTTPS se debe activar `SESSION_COOKIE_SECURE=true`. No se usa `localStorage` para autorización. Las contraseñas se procesan con Argon2 mediante `pwdlib`; nunca se guardan en texto claro.

Los intentos de inicio de sesión se limitan en PostgreSQL por una derivación HMAC de correo y dirección origen: cinco fallos dentro de 15 minutos bloquean durante 15 minutos. No se guarda correo o IP en claro en esa tabla. No se ha implementado recuperación de contraseña, MFA ni gestión remota de sesiones. Antes de producción hacen falta rotación operativa de claves, TLS efectivamente emitido/probado y una revisión de seguridad.

## Roles y propiedad

- El registro público rechaza campos adicionales y siempre crea un `client`.
- El cliente solo ve reservas y entradas cuyo propietario coincide con su sesión.
- El organizador lista y actualiza únicamente eventos asociados a su usuario.
- El operador lista eventos asignados y solo valida entradas dentro de ellos.
- Las cuentas ficticias privilegiadas se crean únicamente con `scripts/dev-bootstrap.py`, que solicita contraseñas en el terminal y no las imprime ni las incorpora al código.

## Entradas e ingreso

Cada cupo reservado genera una entrada dentro de la misma transacción que descuenta la capacidad. El QR contiene un token aleatorio sin datos personales. PostgreSQL conserva su hash para validar y una copia cifrada para mostrárselo al propietario; la clave de cifrado vive en `backend/.env`, ignorado por Git.

Mostrar una entrada no cambia su estado. La validación bloquea la fila de la entrada (`SELECT ... FOR UPDATE`), comprueba asignación, evento y uso previo, y registra el resultado. Dos validaciones simultáneas dejan exactamente una aceptación. La auditoría conserva fecha, operador, resultado y solo una huella abreviada del token.
