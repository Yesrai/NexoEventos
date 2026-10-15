#!/usr/bin/env python3
"""Upsert the demo catalog without deleting reservations or tickets."""
from __future__ import annotations

import argparse
from datetime import date, time, timedelta

from sqlalchemy import create_engine, text

EVENTS = [
    (1001, "Ritmos del Malecón", "Conciertos", 5, time(20, 0), "Anfiteatro del Parque", "Lima", "Una noche de música en vivo al aire libre en el Anfiteatro del Parque. Entrada general.", 45, 180, "general", "concert-live"),
    (1002, "Sesiones del Centro", "Conciertos", 12, time(19, 30), "Centro Cultural Metropolitano", "Lima", "Sesiones de música en vivo en el Centro Cultural Metropolitano. Elige tu zona y asegura tu lugar.", 55, 240, "zones", "concert-stage"),
    (1003, "Pulso Eléctrico", "Conciertos", 19, time(21, 0), "Teatro Urbano", "Lima", "Concierto de rock alternativo en el Teatro Urbano, con asientos numerados. Elige tus butacas en el recinto.", 70, 48, "zones", "concert-energy"),
    (1004, "Movimiento en Escena", "Danza", 8, time(19, 0), "Sala Miraflores", "Lima", "Una función de danza contemporánea en la Sala Miraflores. Elige tus asientos y disfruta del espectáculo.", 52, 48, "zones", "dance-stage"),
    (1005, "Historias del Barranco", "Teatro y stand-up", 15, time(20, 0), "Teatro del Puente", "Lima", "Tres historias breves sobre encuentros y despedidas en la ciudad, en el Teatro del Puente. Elige tu zona.", 38, 160, "zones", "open-theater"),
    (1006, "Impro sin Guion", "Teatro y stand-up", 22, time(20, 30), "Casa Escénica", "Lima", "Una función de improvisación teatral en Casa Escénica. Entrada general.", 32, 120, "general", "theater-performance"),
    (1007, "Comedia de Oficina", "Teatro y stand-up", 10, time(21, 0), "Sala Central", "Callao", "Stand-up sobre reuniones, correos y vida laboral en la Sala Central. Elige tus asientos.", 40, 48, "zones", "standup-stage"),
    (1008, "Micrófono Abierto Lima", "Teatro y stand-up", 17, time(19, 30), "Patio Cultural", "Lima", "Una noche de micrófono abierto en el Patio Cultural para escuchar nuevas voces de la comedia. Entrada general.", 20, 90, "general", "standup-microphone"),
    (1009, "Risas de Barrio", "Teatro y stand-up", 24, time(20, 0), "Auditorio Vecinal", "Lima", "Monólogos y humor cotidiano en el Auditorio Vecinal. Elige tu zona.", 28, 150, "zones", "standup-room"),
    (1010, "Cerámica para Empezar", "Talleres", 6, time(10, 0), "Taller Artesano", "Lima", "Sesión introductoria de modelado manual en cerámica, en el Taller Artesano. Materiales incluidos.", 60, 30, "general", "pottery-hands"),
    (1011, "Mesa Creativa", "Talleres", 13, time(11, 0), "Laboratorio de Oficios", "Lima", "Taller de técnicas mixtas y trabajo colaborativo en el Laboratorio de Oficios. Elige tu zona.", 48, 60, "zones", "pottery-table"),
    (1012, "Diseño en Arcilla", "Talleres", 20, time(16, 0), "Estudio Norte", "Callao", "Experiencia guiada para diseñar una pieza pequeña en arcilla, en el Estudio Norte. Elige tu asiento.", 72, 48, "zones", "pottery-detail"),
    (1013, "Feria de Sabores Locales", "Ferias", 7, time(10, 0), "Parque de la Exposición", "Lima", "Feria de productores, demostraciones y cocina local en el Parque de la Exposición. Entrada gratuita: reserva la tuya.", 0, 400, "general", "food-local-fair"),
    (1014, "Mercado Creativo", "Ferias", 14, time(11, 0), "Plaza Cultural", "Lima", "Diseño independiente, gastronomía y actividades para toda la familia en la Plaza Cultural. Elige tu zona.", 15, 300, "zones", "food-fair"),
    (1015, "Festival Huerta Urbana", "Ferias", 21, time(9, 30), "Jardín Comunitario", "Callao", "Encuentro sobre cultivo urbano, alimentos y sostenibilidad en el Jardín Comunitario. Entrada general.", 12, 220, "general", "food-organic"),
    (1016, "5K Costa Verde", "Deportes", 9, time(7, 0), "Circuito Costa Verde", "Lima", "Carrera recreativa por el Circuito Costa Verde. Entrada gratuita: reserva tu cupo.", 0, 500, "general", "running-field"),
    (1017, "Circuito Activo", "Deportes", 16, time(8, 0), "Complejo Deportivo Municipal", "Lima", "Jornada de retos físicos por niveles de participación en el Complejo Deportivo Municipal. Elige tu zona.", 25, 240, "zones", "running-race"),
    (1018, "Encuentro de Atletismo", "Deportes", 23, time(9, 0), "Estadio Regional", "Callao", "Competencia de atletismo en el Estadio Regional. Elige tu tribuna y tus asientos.", 35, 48, "zones", "running-road"),
    (1019, "Ideas que Conectan", "Conferencias", 11, time(18, 30), "Auditorio Innovación", "Lima", "Charlas sobre creatividad, ciudad y nuevas formas de colaboración en el Auditorio Innovación. Entrada general.", 30, 180, "general", "conference-panel"),
    (1020, "Festival Ciudad Abierta", "Festivales", 18, time(16, 0), "Parque Metropolitano", "Lima", "Festival con música, actividades culturales y propuestas independientes en el Parque Metropolitano. Elige tu zona.", 45, 320, "zones", "festival-stage"),
    (1021, "Miradas Contemporáneas", "Exposiciones", 4, time(11, 0), "Galería Central", "Lima", "Exposición de fotografía, ilustración y arte contemporáneo en la Galería Central. Reserva tu ingreso por horario.", 18, 140, "general", "art-exhibition"),
    (1022, "Conexiones Creativas", "Networking", 13, time(19, 0), "Centro Empresarial", "Lima", "Encuentro para compartir proyectos y crear conexiones profesionales en el Centro Empresarial. Entrada general.", 25, 120, "general", "networking-professionals"),
    (1023, "Cocina Peruana en Vivo", "Gastronomía", 17, time(12, 0), "Mercado Cultural", "Callao", "Demostración gastronómica con técnicas e ingredientes de la cocina peruana, en el Mercado Cultural. Elige tu zona.", 50, 80, "zones", "cooking-workshop"),
    (1024, "Pequeños Inventores", "Infantil", 6, time(10, 30), "Biblioteca Comunitaria", "Lima", "Actividad familiar con retos creativos y experimentos para niñas y niños, en la Biblioteca Comunitaria. Entrada general.", 15, 70, "general", "kids-electronics"),
    (1025, "Cine Bajo las Estrellas", "Cine", 20, time(19, 30), "Patio Audiovisual", "Lima", "Proyección de cortometrajes con conversación posterior, en el Patio Audiovisual. Entrada general.", 20, 150, "general", "cinema-room"),
    (1026, "Foro Futuro Digital", "Tecnología", 10, time(9, 30), "Hub Tecnológico", "Lima", "Foro sobre productos digitales, infraestructura y experiencias tecnológicas en el Hub Tecnológico. Elige tu zona.", 65, 220, "zones", "technology-exhibition"),
    (1027, "Rutas del Arte", "Arte y cultura", 22, time(11, 30), "Museo de la Ciudad", "Callao", "Recorrido cultural por piezas, relatos y expresiones artísticas contemporáneas en el Museo de la Ciudad. Reserva tu ingreso por horario.", 22, 100, "general", "culture-museum"),
    (1028, "Voces en el Auditorio", "Teatro y stand-up", 26, time(20, 0), "Auditorio Nexo", "Lima", "Una función con escenario frontal en el Auditorio Nexo. Elige tus asientos numerados en la sala.", 35, 96, "seats", "auditorium-seats"),
    (1029, "Clásico Metropolitano", "Deportes", 27, time(16, 0), "Estadio Nexo", "Lima", "Partido en el Estadio Nexo con tribunas y localidades numeradas. Elige tu tribuna y tus asientos.", 40, 72, "seats", "football-stadium"),
    (1030, "Copa Ciudad", "Deportes", 29, time(18, 0), "Estadio Nexo", "Lima", "Encuentro deportivo en el Estadio Nexo con tribunas y localidades numeradas. Elige tus asientos.", 38, 72, "seats", "stadium-match"),
    (1031, "Noche del Parque", "Conciertos", 28, time(20, 30), "Arena Parque Sur", "Lima", "Concierto de pie en Arena Parque Sur con zonas Campo y Preferencial. Elige tu zona.", 45, 180, "zones", "concert-arena-lights"),
]

# La asignación es deliberadamente por función, no se infiere por categoría.
# El plano describe el recinto; cada Event conserva su propio inventario.
LAYOUT_KIND_BY_EVENT = {
    1001: "general", 1002: "concert_zones", 1003: "concert_zones", 1004: "zones",
    1005: "zones", 1006: "general", 1007: "zones", 1008: "general", 1009: "zones",
    1010: "general", 1011: "zones", 1012: "zones", 1013: "general", 1014: "zones",
    1015: "general", 1016: "general", 1017: "zones", 1018: "stadium", 1019: "general",
    1020: "concert_zones", 1021: "museum", 1022: "general", 1023: "zones", 1024: "general",
    1025: "general", 1026: "zones", 1027: "museum", 1028: "theatre", 1029: "stadium",
    1030: "stadium", 1031: "concert_zones",
}

LAYOUT_NAMES = {
    "theatre": "Sala frontal con pasillo central",
    "stadium": "Cancha central y tribunas",
    "concert_zones": "Escenario y zonas de pie",
    "museum": "Recorrido orientativo de salas",
    "zones": "Sectores con aforo",
    "general": "Acceso general sin ubicación asignada",
}

CUSTOM_ZONES = {
    1029: [("Tribuna Norte", 40, 24), ("Tribuna Oriente", 55, 24), ("Tribuna Occidente", 65, 24)],
    1030: [("Tribuna Norte", 38, 24), ("Tribuna Oriente", 50, 24), ("Tribuna Occidente", 60, 24)],
    1031: [("Campo", 45, 120), ("Preferencial", 75, 60)],
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database-url", default="postgresql+psycopg:///nexoeventos")
    args = parser.parse_args()
    engine = create_engine(args.database_url)
    start = date.today() + timedelta(days=3)
    with engine.begin() as connection:
        for event_id, name, category, offset, event_time, venue, city, description, price, capacity, mode, image in EVENTS:
            inserted_event_id = connection.scalar(text("""
                INSERT INTO events (id, name, event_date, event_time, venue, city, category, description, price, capacity, reserved_count, image_path, ticket_mode, is_demo)
                VALUES (:id, :name, :event_date, :event_time, :venue, :city, :category, :description, :price, :capacity, 0, :image_path, :ticket_mode, true)
                ON CONFLICT (id) DO NOTHING
                RETURNING id
            """), {
                "id": event_id, "name": name, "event_date": start + timedelta(days=offset), "event_time": event_time,
                "venue": venue, "city": city, "category": category, "description": description, "price": price,
                "capacity": capacity, "image_path": f"/events/{image}.jpg", "ticket_mode": mode,
            })
            # Un ID existente puede tener cupos, reservas, propietario u otra
            # configuración operativa. No se modifica ni se le agregan zonas.
            if inserted_event_id is None:
                continue
            if mode in {"zones", "seats"}:
                definitions = CUSTOM_ZONES.get(event_id, [("Preferencial", price + 20, capacity // 2), ("General", price, capacity - capacity // 2)])
                zone_ids: list[int] = []
                for zone_name, zone_price, zone_capacity in definitions:
                    zone_id = connection.scalar(text("""
                        INSERT INTO event_zones (event_id, name, price, capacity, reserved_count)
                        VALUES (:event_id, :name, :price, :capacity, 0)
                        RETURNING id
                    """), {"event_id": event_id, "name": zone_name, "price": zone_price, "capacity": zone_capacity})
                    zone_ids.append(zone_id)
                if mode == "seats":
                    rows = ("A", "B", "C", "D", "E", "F", "G", "H") if event_id == 1028 else ("A", "B", "C", "D", "E", "F")
                    for row_index, row_label in enumerate(rows):
                        zone_id = zone_ids[0] if event_id == 1028 and row_index < 4 else zone_ids[1] if event_id == 1028 else zone_ids[row_index // 2]
                        for seat_number in range(1, 13):
                            connection.execute(text("""
                                INSERT INTO event_seats (event_id, zone_id, row_label, seat_number)
                                VALUES (:event_id, :zone_id, :row_label, :seat_number)
                                ON CONFLICT (event_id, zone_id, row_label, seat_number) DO NOTHING
                            """), {"event_id": event_id, "zone_id": zone_id, "row_label": row_label, "seat_number": seat_number})

        # Vincula cada función a un recinto y a una distribución explícitos.
        # Solo se completan estos metadatos; cupos, reservas, zonas y asientos
        # de funciones existentes no se actualizan ni se regeneran.
        for event in EVENTS:
            event_id, _, _, _, _, venue_name, city, *_ = event
            kind = LAYOUT_KIND_BY_EVENT[event_id]
            shared_stadium = event_id in {1029, 1030}
            venue_code = "estadio-nexo" if shared_stadium else f"recinto-{event_id}"
            layout_code = "cancha-y-tribunas" if shared_stadium else f"plano-{event_id}"
            venue_id = connection.scalar(text("""
                INSERT INTO venues (code, name, city)
                VALUES (:code, :name, :city)
                ON CONFLICT (code) DO UPDATE SET name = EXCLUDED.name, city = EXCLUDED.city
                RETURNING id
            """), {"code": venue_code, "name": venue_name, "city": city})
            layout_id = connection.scalar(text("""
                INSERT INTO venue_layouts (venue_id, code, name, layout_kind)
                VALUES (:venue_id, :code, :name, :kind)
                ON CONFLICT (venue_id, code) DO UPDATE SET name = EXCLUDED.name, layout_kind = EXCLUDED.layout_kind
                RETURNING id
            """), {"venue_id": venue_id, "code": layout_code, "name": LAYOUT_NAMES[kind], "kind": kind})
            connection.execute(text("""
                UPDATE events
                SET venue_id = :venue_id, layout_id = :layout_id
                WHERE id = :event_id AND is_demo = true AND venue = :venue_name
                  AND (venue_id IS NULL OR venue_id = :venue_id)
                  AND (layout_id IS NULL OR layout_id = :layout_id)
            """), {"event_id": event_id, "venue_name": venue_name, "venue_id": venue_id, "layout_id": layout_id})

        # Corrección visual acotada: no altera cupos, reservas, propietarios,
        # zonas ni asientos de la función existente.
        connection.execute(text("""
            UPDATE events SET image_path = '/events/football-stadium.jpg'
            WHERE id = 1029 AND is_demo = true AND venue = 'Estadio Nexo'
        """))
    engine.dispose()
    print(f"Catálogo demo actualizado: {len(EVENTS)} eventos; no se eliminaron reservas.")


if __name__ == "__main__":
    main()
