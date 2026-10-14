import uuid
from datetime import date, datetime, time, timezone
from decimal import Decimal

from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("role IN ('client', 'organizer', 'operator')", name="ck_users_role"),
        UniqueConstraint("email", name="uq_users_email"),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(254))
    display_name: Mapped[str] = mapped_column(String(100))
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AuthSession(Base):
    __tablename__ = "auth_sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    csrf_hash: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AuthRateLimit(Base):
    __tablename__ = "auth_rate_limits"
    key_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    failed_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    window_started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    blocked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Event(Base):
    __tablename__ = "events"
    __table_args__ = (
        CheckConstraint("capacity >= 0", name="ck_events_capacity_nonnegative"),
        CheckConstraint("reserved_count >= 0", name="ck_events_reserved_nonnegative"),
        CheckConstraint("reserved_count <= capacity", name="ck_events_reserved_within_capacity"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    name: Mapped[str] = mapped_column(String(160))
    event_date: Mapped[date] = mapped_column(Date)
    event_time: Mapped[time | None] = mapped_column(nullable=True)
    venue: Mapped[str] = mapped_column(String(180))
    city: Mapped[str] = mapped_column(String(80), default="Lima", server_default="Lima")
    category: Mapped[str] = mapped_column(String(80))
    description: Mapped[str] = mapped_column(Text)
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    capacity: Mapped[int] = mapped_column(Integer)
    reserved_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    image_path: Mapped[str | None] = mapped_column(String(240), nullable=True)
    ticket_mode: Mapped[str] = mapped_column(String(20), default="general", server_default="general")
    is_demo: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    status: Mapped[str] = mapped_column(String(12), default="published", server_default="published")
    sales_start_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    queue_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    queue_max_active: Mapped[int] = mapped_column(Integer, default=50, server_default="50")
    queue_pass_minutes: Mapped[int] = mapped_column(Integer, default=10, server_default="10")
    organizer_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    venue_id: Mapped[int | None] = mapped_column(ForeignKey("venues.id", ondelete="RESTRICT"), nullable=True)
    layout_id: Mapped[int | None] = mapped_column(ForeignKey("venue_layouts.id", ondelete="RESTRICT"), nullable=True)


class Venue(Base):
    __tablename__ = "venues"
    __table_args__ = (UniqueConstraint("code", name="uq_venues_code"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(80))
    name: Mapped[str] = mapped_column(String(180))
    city: Mapped[str] = mapped_column(String(80))


class VenueLayout(Base):
    __tablename__ = "venue_layouts"
    __table_args__ = (
        UniqueConstraint("venue_id", "code", name="uq_venue_layouts_venue_code"),
        CheckConstraint(
            "layout_kind IN ('theatre', 'stadium', 'concert_zones', 'museum', 'zones', 'general')",
            name="ck_venue_layouts_kind",
        ),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    venue_id: Mapped[int] = mapped_column(ForeignKey("venues.id", ondelete="RESTRICT"), index=True)
    code: Mapped[str] = mapped_column(String(80))
    name: Mapped[str] = mapped_column(String(120))
    layout_kind: Mapped[str] = mapped_column(String(24))


class Reservation(Base):
    __tablename__ = "reservations"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_reservations_quantity_positive"),
        UniqueConstraint("idempotency_key", name="uq_reservations_idempotency_key"),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id", ondelete="RESTRICT"), index=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), index=True, nullable=True)
    quantity: Mapped[int] = mapped_column(Integer)
    buyer_alias: Mapped[str] = mapped_column(String(80))
    idempotency_key: Mapped[str] = mapped_column(String(128))
    request_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class OperatorEventAssignment(Base):
    __tablename__ = "operator_event_assignments"
    operator_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class EventZone(Base):
    __tablename__ = "event_zones"
    __table_args__ = (
        CheckConstraint("price >= 0", name="ck_event_zones_price_nonnegative"),
        CheckConstraint("capacity >= 0", name="ck_event_zones_capacity_nonnegative"),
        CheckConstraint("reserved_count BETWEEN 0 AND capacity", name="ck_event_zones_reserved_within_capacity"),
        UniqueConstraint("event_id", "name", name="uq_event_zones_event_name"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(80))
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    capacity: Mapped[int] = mapped_column(Integer)
    reserved_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")


class EventSeat(Base):
    __tablename__ = "event_seats"
    __table_args__ = (
        CheckConstraint("seat_number > 0", name="ck_event_seats_number_positive"),
        UniqueConstraint("event_id", "zone_id", "row_label", "seat_number", name="uq_event_seats_position"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"), index=True)
    zone_id: Mapped[int] = mapped_column(ForeignKey("event_zones.id", ondelete="CASCADE"))
    row_label: Mapped[str] = mapped_column(String(12))
    seat_number: Mapped[int] = mapped_column(Integer)
    reservation_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("reservations.id", ondelete="RESTRICT"), index=True, nullable=True)


class Ticket(Base):
    __tablename__ = "tickets"
    __table_args__ = (UniqueConstraint("token_hash", name="uq_tickets_token_hash"),)
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    reservation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("reservations.id", ondelete="RESTRICT"), index=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id", ondelete="RESTRICT"))
    owner_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64))
    token_ciphertext: Mapped[str] = mapped_column(Text)
    ticket_type: Mapped[str] = mapped_column(String(20), default="general", server_default="general")
    zone_id: Mapped[int | None] = mapped_column(ForeignKey("event_zones.id", ondelete="RESTRICT"), nullable=True)
    seat_id: Mapped[int | None] = mapped_column(ForeignKey("event_seats.id", ondelete="RESTRICT"), nullable=True, unique=True)
    unit_price: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    used_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=True)


class AccessLog(Base):
    __tablename__ = "access_logs"
    __table_args__ = (
        CheckConstraint("result IN ('accepted', 'already_used', 'invalid_token', 'wrong_event')", name="ck_access_logs_result"),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id", ondelete="RESTRICT"))
    ticket_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tickets.id", ondelete="RESTRICT"), nullable=True)
    operator_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    result: Mapped[str] = mapped_column(String(30))
    token_fingerprint: Mapped[str] = mapped_column(String(16))
    # The application supplies the timestamp so INSERT does not need SELECT
    # permission for a server-generated RETURNING value on this write-only table.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), server_default=func.now()
    )


class QueueEntry(Base):
    __tablename__ = "queue_entries"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"))
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(String(12))
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    admitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
