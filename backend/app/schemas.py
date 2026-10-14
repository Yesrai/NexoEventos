from datetime import date as DateValue, datetime, time as TimeValue
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class HealthResponse(BaseModel):
    status: Literal["ok"]
    service: str


class UserView(BaseModel):
    id: UUID
    email: EmailStr
    display_name: str
    role: Literal["client", "organizer", "operator"]
    session_expires_at: datetime


class RegisterRequest(StrictModel):
    email: EmailStr
    display_name: str = Field(min_length=2, max_length=100)
    password: str = Field(min_length=12, max_length=128)


class LoginRequest(StrictModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class EventSummary(BaseModel):
    id: int
    name: str
    date: DateValue
    time: TimeValue | None
    venue: str
    city: str
    category: str
    price: float
    has_multiple_prices: bool
    capacity: int
    available_capacity: int
    image_path: str | None
    ticket_mode: Literal["general", "zones", "seats"]
    venue_id: int | None = None
    layout_id: int | None = None
    layout_name: str | None = None
    layout_kind: Literal["theatre", "stadium", "concert_zones", "museum", "zones", "general"] | None = None
    is_demo: bool
    status: Literal["draft", "published"] = "published"


class ZoneView(BaseModel):
    id: int
    name: str
    price: float
    capacity: int
    available_capacity: int


class SeatView(BaseModel):
    id: int
    zone_id: int
    zone_name: str
    row: str
    number: int
    price: float
    available: bool


class EventDetail(EventSummary):
    description: str
    zones: list[ZoneView] = Field(default_factory=list)
    seats: list[SeatView] = Field(default_factory=list)


class EventUpdate(StrictModel):
    name: str | None = Field(default=None, min_length=2, max_length=160)
    date: DateValue | None = None
    venue: str | None = Field(default=None, min_length=2, max_length=180)
    category: str | None = Field(default=None, min_length=2, max_length=80)
    description: str | None = Field(default=None, min_length=10)
    price: float | None = Field(default=None, ge=0)
    capacity: int | None = Field(default=None, ge=0)
    time: TimeValue | None = None


class ReservationCreate(StrictModel):
    quantity: int = Field(ge=1, le=10)
    zone_id: int | None = None
    seat_ids: list[int] = Field(default_factory=list, max_length=10)


class ReservationCreated(BaseModel):
    reservation_id: UUID
    event_id: int
    quantity: int
    available_capacity: int
    ticket_count: int
    replayed: bool
    total: float
    ticket_mode: Literal["general", "zones", "seats"]


class MyReservation(BaseModel):
    id: UUID
    event_id: int
    event_name: str
    quantity: int
    created_at: datetime


class TicketView(BaseModel):
    id: UUID
    reservation_id: UUID
    event_id: int
    event_name: str
    event_date: DateValue
    event_venue: str
    event_city: str
    event_time: TimeValue | None
    image_path: str | None
    ticket_type: Literal["general", "zones", "seats"]
    zone: str | None
    row: str | None
    seat: int | None
    unit_price: float
    qr_token: str
    used_at: datetime | None


class ValidationRequest(StrictModel):
    event_id: int
    qr_token: str = Field(min_length=20, max_length=256)


class ValidationResult(BaseModel):
    result: Literal["accepted"]
    ticket_id: UUID
    event_id: int
    used_at: datetime
    ticket_location: str


class ZoneStats(BaseModel):
    zone_id: int
    name: str
    price: float
    capacity: int
    sold: int
    available: int
    revenue: float


class OrganizerEventStats(BaseModel):
    event_id: int
    name: str
    ticket_mode: Literal["general", "zones", "seats"]
    capacity: int
    sold: int
    available: int
    occupancy_percent: float
    revenue: float
    checked_in: int
    pending_entry: int
    zones: list[ZoneStats]


class ZoneInput(StrictModel):
    name: str = Field(min_length=2, max_length=80)
    price: float = Field(ge=0, le=100000)
    capacity: int = Field(ge=1, le=5000)


class SectionInput(StrictModel):
    name: str = Field(min_length=2, max_length=80)
    price: float = Field(ge=0, le=100000)
    rows: int = Field(ge=1, le=8)
    seats_per_row: int = Field(ge=1, le=12)


class InventoryInput(StrictModel):
    """Configuración de entradas; qué campos aplican depende del tipo del plano elegido."""

    layout_id: int
    price: float | None = Field(default=None, ge=0, le=100000)
    capacity: int | None = Field(default=None, ge=1, le=5000)
    zones: list[ZoneInput] = Field(default_factory=list, max_length=6)
    sections: list[SectionInput] = Field(default_factory=list, max_length=4)


class EventCreate(InventoryInput):
    name: str = Field(min_length=2, max_length=160)
    date: DateValue
    time: TimeValue | None = None
    category: str = Field(min_length=2, max_length=80)
    description: str = Field(min_length=10, max_length=4000)
    image_path: str | None = Field(default=None, pattern=r"^/events/[a-z0-9-]{1,60}\.jpg$")


class FunctionCreate(StrictModel):
    date: DateValue
    time: TimeValue | None = None


class LayoutOption(BaseModel):
    layout_id: int
    name: str
    layout_kind: Literal["theatre", "stadium", "concert_zones", "museum", "zones", "general"]
    ticket_mode: Literal["general", "zones", "seats"]


class VenueOption(BaseModel):
    venue_id: int
    name: str
    city: str
    layouts: list[LayoutOption]


class OperatorAssign(StrictModel):
    email: EmailStr


class OperatorView(BaseModel):
    user_id: UUID
    email: str
    display_name: str


class EventState(BaseModel):
    """Qué puede cambiarse todavía; la interfaz lo usa para bloquear controles."""

    has_sales: bool
    can_edit_inventory: bool
    can_publish: bool
    can_unpublish: bool
    can_delete: bool
    publish_problems: list[str]
