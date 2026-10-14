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

Las vistas 3D son representaciones propias de recintos ficticios, generadas de
forma procedural (geometría, texturas en canvas y luces); no usan modelos,
texturas ni imágenes de terceros. Se cargan solo al activar la vista, no añaden
inventario vendible y su evidencia está en
[`evidencias/ui/recintos-3d/`](evidencias/ui/recintos-3d/) (generada con
`scripts/capture-venues.mjs`).

- **Estadio Nexo**: cancha, graderías escalonadas, accesos, barandas, cubiertas
  parciales y torres, más un entorno exterior con cielo, fachada con columnas y
  portales, avenida, estacionamiento, bloques de escaleras en las esquinas y
  horizonte. Solo son interactivos los asientos recibidos de la función activa.
- **Auditorio Nexo** (`venue3d-theatre.ts`): sala cerrada con techo artesonado,
  proscenio, telón, escenario con barras de luz, platea escalonada y butacas del
  inventario real coloreadas por zona de precio. La cámara permanece dentro de
  la sala.
- **Arena Parque Sur** (`venue3d-concert.ts`): escenario con truss, pantallas LED,
  línea de PA, foso con vallas, torre de sonido, carpas y acceso, de noche.
  Las zonas de pie son losas luminosas cuya profundidad es proporcional al
  aforo; la de mayor precio queda junto al escenario. No hay sillas decorativas.
- **Galería Central / Museo de la Ciudad** (`venue3d-museum.ts`): vestíbulo y tres
  salas conectadas con pisos, obras e iluminación propios y recorrido
  señalizado. La reserva continúa siendo por fecha, horario y cantidad.
- La **entrada general** sin distribución útil conserva el selector de cantidad
  y no carga Three.js.

Cada vista ofrece cámaras predefinidas, zoom y giro; conserva el plano 2D o la
lista como alternativa accesible (si WebGL falla se vuelve al plano sin perder
la selección), respeta `prefers-reduced-motion` y usa la misma selección,
precios e identificadores que el backend. Los estados ocupado/disponible nunca
se inventan en el cliente. En pantallas verticales la cámara se aleja para que
el recinto quepa a lo ancho y las sombras se desactivan en móvil.

Código compartido: `venue3d-kit.ts` (texturas procedurales, utilidades),
`venue3d-types.ts` (contrato de cada recinto) y `Venue3D.tsx` (cámara,
interacción, limpieza de memoria).
