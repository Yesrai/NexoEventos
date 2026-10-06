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
    is_demo: bool


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
