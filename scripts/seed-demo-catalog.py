#!/usr/bin/env python3
"""Upsert the academic demo catalog without deleting reservations or tickets."""
from __future__ import annotations

import argparse
from datetime import date, time, timedelta

from sqlalchemy import create_engine, text

EVENTS = [
    (1001, "Ritmos del Malecón", "Conciertos", 5, time(20, 0), "Anfiteatro del Parque", "Lima", "Una noche de bandas independientes junto al mar.", 45, 180, "general", "concert-live"),
    (1002, "Sesiones del Centro", "Conciertos", 12, time(19, 30), "Centro Cultural Metropolitano", "Lima", "Encuentro acústico con proyectos musicales ficticios de la ciudad.", 55, 240, "zones", "concert-stage"),
    (1003, "Pulso Eléctrico", "Conciertos", 19, time(21, 0), "Teatro Urbano", "Lima", "Concierto demo de rock alternativo con zonas de ingreso.", 70, 48, "zones", "concert-energy"),
    (1004, "Movimiento en Escena", "Danza", 8, time(19, 0), "Sala Miraflores", "Lima", "Obra de danza contemporánea creada para el catálogo académico.", 52, 48, "zones", "dance-stage"),
    (1005, "Historias del Barranco", "Teatro y stand-up", 15, time(20, 0), "Teatro del Puente", "Lima", "Tres historias breves sobre encuentros y despedidas en la ciudad.", 38, 160, "zones", "open-theater"),
    (1006, "Impro sin Guion", "Teatro y stand-up", 22, time(20, 30), "Casa Escénica", "Lima", "Función ficticia de improvisación construida con ideas del público.", 32, 120, "general", "theater-performance"),
    (1007, "Comedia de Oficina", "Teatro y stand-up", 10, time(21, 0), "Sala Central", "Callao", "Stand-up académico sobre reuniones, correos y vida laboral.", 40, 48, "zones", "standup-stage"),
    (1008, "Micrófono Abierto Lima", "Teatro y stand-up", 17, time(19, 30), "Patio Cultural", "Lima", "Noche demo para nuevas voces de la comedia local.", 20, 90, "general", "standup-microphone"),
    (1009, "Risas de Barrio", "Teatro y stand-up", 24, time(20, 0), "Auditorio Vecinal", "Lima", "Espectáculo ficticio de monólogos y humor cotidiano.", 28, 150, "zones", "standup-room"),
    (1010, "Cerámica para Empezar", "Talleres", 6, time(10, 0), "Taller Artesano", "Lima", "Sesión introductoria de modelado manual con materiales incluidos.", 60, 30, "general", "pottery-hands"),
    (1011, "Mesa Creativa", "Talleres", 13, time(11, 0), "Laboratorio de Oficios", "Lima", "Taller ficticio de técnicas mixtas y trabajo colaborativo.", 48, 60, "zones", "pottery-table"),
    (1012, "Diseño en Arcilla", "Talleres", 20, time(16, 0), "Estudio Norte", "Callao", "Experiencia guiada para diseñar una pieza pequeña en arcilla.", 72, 48, "zones", "pottery-detail"),
    (1013, "Feria de Sabores Locales", "Ferias", 7, time(10, 0), "Parque de la Exposición", "Lima", "Feria académica de productores, demostraciones y cocina local.", 0, 400, "general", "food-local-fair"),
    (1014, "Mercado Creativo", "Ferias", 14, time(11, 0), "Plaza Cultural", "Lima", "Diseño independiente, gastronomía y actividades para toda la familia.", 15, 300, "zones", "food-fair"),
    (1015, "Festival Huerta Urbana", "Ferias", 21, time(9, 30), "Jardín Comunitario", "Callao", "Encuentro ficticio sobre cultivo urbano, alimentos y sostenibilidad.", 12, 220, "general", "food-organic"),
    (1016, "5K Costa Verde", "Deportes", 9, time(7, 0), "Circuito Costa Verde", "Lima", "Carrera recreativa demo con punto de encuentro y control de ingreso.", 0, 500, "general", "running-field"),
    (1017, "Circuito Activo", "Deportes", 16, time(8, 0), "Complejo Deportivo Municipal", "Lima", "Jornada ficticia de retos físicos por niveles de participación.", 25, 240, "zones", "running-race"),
    (1018, "Encuentro de Atletismo", "Deportes", 23, time(9, 0), "Estadio Regional", "Callao", "Competencia académica de pista con zonas de tribuna.", 35, 48, "zones", "running-road"),
    (1019, "Ideas que Conectan", "Conferencias", 11, time(18, 30), "Auditorio Innovación", "Lima", "Charlas ficticias sobre creatividad, ciudad y nuevas formas de colaboración.", 30, 180, "general", "conference-speaker"),
    (1020, "Festival Ciudad Abierta", "Festivales", 18, time(16, 0), "Parque Metropolitano", "Lima", "Festival académico con música, actividades culturales y propuestas independientes.", 45, 320, "zones", "festival-stage"),
    (1021, "Miradas Contemporáneas", "Exposiciones", 4, time(11, 0), "Galería Central", "Lima", "Exposición ficticia de fotografía, ilustración y arte contemporáneo.", 18, 140, "general", "art-exhibition"),
    (1022, "Conexiones Creativas", "Networking", 13, time(19, 0), "Centro Empresarial", "Lima", "Encuentro demo para compartir proyectos y crear conexiones profesionales.", 25, 120, "general", "networking-professionals"),
    (1023, "Cocina Peruana en Vivo", "Gastronomía", 17, time(12, 0), "Mercado Cultural", "Callao", "Demostración gastronómica ficticia con técnicas, ingredientes y degustación simulada.", 50, 80, "zones", "cooking-workshop"),
    (1024, "Pequeños Inventores", "Infantil", 6, time(10, 30), "Biblioteca Comunitaria", "Lima", "Actividad familiar demo con retos creativos y experimentos seguros para niñas y niños.", 15, 70, "general", "children-workshop"),
    (1025, "Cine Bajo las Estrellas", "Cine", 20, time(19, 30), "Patio Audiovisual", "Lima", "Proyección académica de cortometrajes ficticios con conversación posterior.", 20, 150, "general", "cinema-room"),
    (1026, "Foro Futuro Digital", "Tecnología", 10, time(9, 30), "Hub Tecnológico", "Lima", "Foro demo sobre productos digitales, infraestructura y experiencias tecnológicas.", 65, 220, "zones", "technology-exhibition"),
    (1027, "Rutas del Arte", "Arte y cultura", 22, time(11, 30), "Museo de la Ciudad", "Callao", "Recorrido cultural ficticio por piezas, relatos y expresiones artísticas contemporáneas.", 22, 100, "general", "culture-museum"),
    (1028, "Voces en el Auditorio", "Teatro y stand-up", 26, time(20, 0), "Auditorio Nexo", "Lima", "Función ficticia con escenario frontal y asientos numerados para probar el recorrido completo de reserva.", 35, 96, "seats", "theater-performance"),
]


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
                definitions = [("Preferencial", price + 20, capacity // 2), ("General", price, capacity - capacity // 2)]
                zone_ids: list[int] = []
                for zone_name, zone_price, zone_capacity in definitions:
                    zone_id = connection.scalar(text("""
                        INSERT INTO event_zones (event_id, name, price, capacity, reserved_count)
                        VALUES (:event_id, :name, :price, :capacity, 0)
                        RETURNING id
                    """), {"event_id": event_id, "name": zone_name, "price": zone_price, "capacity": zone_capacity})
                    zone_ids.append(zone_id)
                if mode == "seats":
                    for row_index, row_label in enumerate(("A", "B", "C", "D", "E", "F", "G", "H")):
                        zone_id = zone_ids[0] if row_index < 4 else zone_ids[1]
                        for seat_number in range(1, 13):
                            connection.execute(text("""
                                INSERT INTO event_seats (event_id, zone_id, row_label, seat_number)
                                VALUES (:event_id, :zone_id, :row_label, :seat_number)
                                ON CONFLICT (event_id, zone_id, row_label, seat_number) DO NOTHING
                            """), {"event_id": event_id, "zone_id": zone_id, "row_label": row_label, "seat_number": seat_number})
    engine.dispose()
    print(f"Catálogo demo actualizado: {len(EVENTS)} eventos; no se eliminaron reservas.")


if __name__ == "__main__":
    main()
