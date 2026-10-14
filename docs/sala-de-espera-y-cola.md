# Sala de espera y cola virtual

Diseño proporcional al proyecto académico. Todo el control vive en el backend y
PostgreSQL; la interfaz solo muestra lo que el servidor informa.

## Qué se implementa

| Capacidad | Decisión |
|---|---|
| Inicio de ventas por evento | `events.sales_start_at` (nulo = ventas abiertas, como hasta ahora). Antes de esa hora el backend rechaza reservas (`403 sales_not_open`). |
| Cuenta regresiva | Sale de `GET /api/events/{id}/sales`, que devuelve la hora **del servidor** (reloj de PostgreSQL). El navegador calcula solo el desfase y nunca decide si las ventas están abiertas. |
| Cola virtual opcional | El organizador la activa por evento (`queue_enabled`) y define cuántas personas pueden comprar a la vez (`queue_max_active`) y cuántos minutos dura su turno (`queue_pass_minutes`). |
| Turnos | Tabla `queue_entries` (`waiting` → `admitted` → `completed`/`expired`/`left`). Un cliente tiene como máximo una entrada viva por evento (índice único parcial). |
| Orden | Llegada (`joined_at`, `id`). Se puede entrar a la fila antes del inicio; las admisiones solo ocurren después de `sales_start_at`. |
| Admisión | Perezosa y transaccional: cada consulta o unión bloquea la fila del evento, expira turnos vencidos y admite en orden hasta llenar `queue_max_active`. No hay procesos en segundo plano. |
| Reserva | `POST /reservations` exige turno vigente cuando la cola está activa; al reservar con éxito el turno pasa a `completed` y libera su lugar. La repetición idempotente de una reserva ya hecha no exige turno. |
| Refrescar la página | No salta la cola: el turno está en la base, asociado a la sesión autenticada. |
| Posición | Real: personas en espera con llegada anterior + 1. **No se inventa tiempo estimado**; solo se muestra «personas delante» y el total en espera. |
| Accesibilidad | Región `aria-live` educada para cambios de estado, cuenta regresiva legible, sin animaciones que informen algo que el servidor no dijo. |

## Qué no se implementa (y por qué)

- **Sin Redis, SQS ni WebSockets:** exigirían nuevos servicios cloud y costo; el sondeo cada 5 s es suficiente para la escala del laboratorio.
- **Sin sorteo ni protección frente a bots:** entrar antes del inicio premia la velocidad de clic; requiere sesión de cliente autenticada, pero no hay CAPTCHA.
- **Sin estimación de minutos:** no hay histórico de ritmo de compra fiable.
- **Una sola reserva por turno:** al completar, la persona debe volver a la fila.

## Costos operativos

- **Base de datos:** cada persona en espera genera una consulta corta cada 5 s (`GET /sales`) que toma un bloqueo de fila del evento. Estimación de orden de magnitud con 200 personas esperando: ≈ 40 transacciones/s sobre un único evento; es viable en la `t3.small` + RDS del diseño actual, pero **no se midió** en la nube. La carga de la fila se mide en pruebas locales (ver `PROJECT_STATUS.md`).
- **Escalado:** con miles de personas esperando habría que sacar la cola de PostgreSQL (por ejemplo, un contador en memoria compartida o una cola gestionada) y servir la sala de espera como página estática; eso sí es un cambio de arquitectura y no se hace aquí.
- **Costo cloud adicional:** ninguno nuevo (sin servicios nuevos); solo más tráfico de lectura y escritura sobre las instancias existentes.
- **Datos:** `queue_entries` crece una fila por persona y evento; se pueden purgar entradas `completed/expired/left` antiguas sin afectar reservas.

## Consistencia y concurrencia

- Toda admisión, unión y expiración se hace con `SELECT … FOR UPDATE` sobre la fila de `events`, la misma que serializa las reservas: dos clientes no pueden ocupar el mismo lugar ni exceder `queue_max_active`.
- El aforo sigue controlándose como antes; la cola solo limita cuántas personas intentan comprar a la vez.
- Un turno expirado deja de autorizar reservas de inmediato (la validación usa `expires_at > now()` en el servidor).

## API

| Método y ruta | Rol | Función |
|---|---|---|
| `GET /api/events/{id}/sales` | público | Hora del servidor, `sales_start_at`, estado y, si hay sesión de cliente, su turno |
| `POST /api/events/{id}/queue` | cliente | Entrar a la fila (idempotente) |
| `DELETE /api/events/{id}/queue` | cliente | Salir de la fila |
| `PUT /api/organizer/events/{id}/sales` | organizador | Inicio de ventas y parámetros de la cola |
