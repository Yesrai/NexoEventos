# Recintos, planos y funciones

El modelo local separa cuatro conceptos:

- `venues`: recinto físico ficticio.
- `venue_layouts`: distribución reutilizable de un recinto.
- `events`: función con fecha, hora e inventario propio.
- `events.ticket_mode`: modalidad de ingreso (`general`, `zones` o `seats`).

La asignación se define por ID de función en `scripts/seed-demo-catalog.py`; no se infiere por categoría. Dos funciones pueden compartir `layout_id`, pero zonas, asientos, cupos y reservas siempre llevan `event_id`. El backend rechaza zonas o asientos que no pertenezcan a la función solicitada.

## Ejemplos comprobables

| Evento | Recinto | Modalidad | Plano |
|---|---|---|---|
| Voces en el Auditorio | Auditorio Nexo | Asientos numerados | Sala frontal con pasillo central |
| Clásico Metropolitano | Estadio Nexo | Sectores, filas y asientos | Cancha central y tribunas |
| Copa Ciudad | Estadio Nexo | Sectores, filas y asientos | El mismo plano anterior, con inventario independiente |
| Noche del Parque | Arena Parque Sur | Zonas con aforo, de pie | Escenario y zonas Campo/Preferencial |
| Miradas Contemporáneas | Galería Central | Entrada general por horario | Recorrido orientativo de salas, no reservable |
| Ritmos del Malecón | Anfiteatro del Parque | Entrada general | Sin mapa de asientos |

Los eventos sin localidades numeradas nunca reciben un auditorio de respaldo. Si una función declara asientos pero carece de plano explícito, la interfaz bloquea el mapa genérico y muestra un error de configuración.

## Ambientes 3D locales

Las vistas 3D son aproximaciones propias de recintos ficticios; no representan
réplicas exactas de lugares reales. Se cargan solo al activar la vista y no
añaden inventario vendible:

- **Estadio Nexo**: terreno exterior, cancha, perímetro, graderías escalonadas,
  accesos, barandas, cubiertas parciales y torres. Solo son interactivos los
  asientos recibidos desde la función activa.
- **Auditorio Nexo**: sala de corte abierto con escenario, telón, luces,
  pendiente, pasillo y butacas del inventario real.
- **Arena Parque Sur**: escenario, pantalla de contenido propio, estructura,
  accesos, barreras y superficies de Campo/Preferencial. Son zonas de pie, sin
  sillas decorativas.
- **Galería Central / Museo de la Ciudad**: salas conectadas, piezas geométricas
  propias e iluminación de galería. Es una guía espacial; la reserva continúa
  siendo por fecha, horario y cantidad.
- La **entrada general** sin distribución útil conserva el selector de cantidad
  y no carga Three.js.

Cada vista conserva el plano 2D o la lista como alternativa accesible, respeta
`prefers-reduced-motion` y usa la misma selección, precios e identificadores que
el backend. Los estados ocupado/disponible nunca se inventan en el cliente.
