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
