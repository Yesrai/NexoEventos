import hashlib
import logging
from contextlib import asynccontextmanager
from decimal import Decimal
from uuid import UUID

from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError, InterfaceError, OperationalError
from sqlalchemy.exc import TimeoutError as PoolTimeoutError
from sqlalchemy.orm import Session

from app.access_control import (
    EventNotAssignedError,
    TicketAlreadyUsedError,
    TicketNotFoundError,
    TicketWrongEventError,
    validate_ticket,
)
from app.auth import (
    AuthContext,
    clear_session_cookies,
    get_auth_context,
    hash_password,
    issue_session,
    normalize_email,
    require_csrf,
    require_csrf_role,
    require_role,
    set_session_cookies,
    verify_login,
    verify_public_origin,
)
from app.queue import QueueRequiredError, SalesNotOpenError
from app.sales import router as sales_router
from app.catalog import event_detail, event_summary, zone_pricing
from app.organizer import router as organizer_router
from app.config import ALLOWED_ORIGINS, validate_production_config
from app.database import build_engine, build_session_factory, get_session
from app.models import AuthSession, Event, EventSeat, EventZone, OperatorEventAssignment, Reservation, Ticket, User, VenueLayout
from app.reservations import (
    CapacityExceededError,
    EventNotFoundError,
    IdempotencyConflictError,
    InvalidSelectionError,
    SelectionConflictError,
    create_reservation,
)
from app.rate_limit import (
    LoginRateLimitedError,
    check_login_allowed,
    clear_login_failures,
    login_rate_key,
    record_login_failure,
)
from app.schemas import (
    EventDetail,
    EventSummary,
    EventUpdate,
    HealthResponse,
    LoginRequest,
    MyReservation,
    OrganizerEventStats,
    RegisterRequest,
    ReservationCreate,
    ReservationCreated,
    TicketView,
    SeatView,
    ZoneStats,
    ZoneView,
    UserView,
    ValidationRequest,
    ValidationResult,
)
from app.ticket_tokens import reveal_ticket_secret


def _user_view(context: AuthContext) -> UserView:
    return UserView(
        id=context.user.id,
        email=context.user.email,
        display_name=context.user.display_name,
        role=context.user.role,
        session_expires_at=context.auth_session.expires_at,
    )


logger = logging.getLogger("nexoeventos.api")


def create_app(database_url: str | None = None) -> FastAPI:
    validate_production_config()
    engine = build_engine(database_url)

    # Apagado ordenado (reemplazo de instancias, reinicio del servicio): se cierran las conexiones del pool para no dejar sesiones colgadas en RDS.
    @asynccontextmanager
    async def lifespan(_: FastAPI):
        yield
        engine.dispose()

    application = FastAPI(title="NexoEventos API", version="0.3.0", lifespan=lifespan)
    application.state.engine = engine
    application.state.session_factory = build_session_factory(engine)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=sorted(ALLOWED_ORIGINS - {"http://testserver"}),
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE"],
        allow_headers=["Content-Type", "Idempotency-Key", "X-CSRF-Token"],
    )

    # Base de datos caída o saturada (failover de RDS, red, pool agotado): respuesta 503 reintentable en lugar de un 500 opaco.
    # Solo se registra el tipo de excepción: el mensaje puede contener la URL o parámetros de la consulta.
    @application.exception_handler(OperationalError)
    @application.exception_handler(InterfaceError)
    @application.exception_handler(PoolTimeoutError)
    async def database_unavailable(request: Request, exc: Exception) -> JSONResponse:
        logger.warning("Base de datos no disponible (%s) en %s", type(exc).__name__, request.url.path)
        return JSONResponse(status_code=503, content={"detail": "Servicio no disponible temporalmente"}, headers={"Retry-After": "5"})

    # LIVENESS: el proceso está vivo y responde. NO toca PostgreSQL a propósito: el health check del ALB (y con él el reemplazo de
    # instancias por el Auto Scaling) no debe depender de la base de datos; si ésta falla, cambiar de instancia no la arregla.
    # `async def` a propósito: se ejecuta en el bucle de eventos y no consume un hilo del pool (los endpoints `def` usan un pool de hilos
    # que una base de datos bloqueada puede agotar); así la liveness responde aunque todas las peticiones esperen a PostgreSQL.
    @application.get("/health", response_model=HealthResponse)
    async def health() -> HealthResponse:
        return HealthResponse(status="ok", service="nexoeventos-api")

    # READINESS: puede atender operaciones que requieren PostgreSQL. Es para monitoreo externo (Zabbix, `/healthz`), no para
    # decidir el reemplazo de instancias.
    @application.get("/ready")
    def ready(session: Session = Depends(get_session)) -> dict[str, str]:
        try:
            session.execute(text("SELECT 1"))
        except Exception:
            raise HTTPException(status_code=503, detail="Servicio no disponible") from None
        return {"status": "ready"}

    @application.post("/api/auth/register", response_model=UserView, status_code=201)
    def register(payload: RegisterRequest, request: Request, response: Response, session: Session = Depends(get_session)) -> UserView:
        verify_public_origin(request)
        user = User(
            email=normalize_email(str(payload.email)),
            display_name=payload.display_name.strip(),
            password_hash=hash_password(payload.password),
            role="client",
        )
        try:
            with session.begin():
                session.add(user)
                session.flush()
                raw_token, csrf_token, _ = issue_session(session, user)
        except IntegrityError:
            raise HTTPException(
                status_code=409,
                detail="No se pudo completar el registro. Revisa los datos o intenta iniciar sesión.",
            ) from None
        auth_session = session.get(AuthSession, hashlib.sha256(raw_token.encode()).hexdigest())
        assert auth_session is not None
        set_session_cookies(response, raw_token, csrf_token)
        return _user_view(AuthContext(user, auth_session))

    @application.post("/api/auth/login", response_model=UserView)
    def login(payload: LoginRequest, request: Request, response: Response, session: Session = Depends(get_session)) -> UserView:
        verify_public_origin(request)
        source_address = request.client.host if request.client else "unknown"
        rate_key = login_rate_key(str(payload.email), source_address)
        try:
            check_login_allowed(session, rate_key)
        except LoginRateLimitedError as error:
            raise HTTPException(
                status_code=429,
                detail="Demasiados intentos. Intenta nuevamente más tarde.",
                headers={"Retry-After": str(error.retry_after_seconds)},
            ) from None
        user = verify_login(session, str(payload.email), payload.password)
        if user is None:
            try:
                record_login_failure(session, rate_key)
            except LoginRateLimitedError as error:
                raise HTTPException(
                    status_code=429,
                    detail="Demasiados intentos. Intenta nuevamente más tarde.",
                    headers={"Retry-After": str(error.retry_after_seconds)},
                ) from None
            raise HTTPException(status_code=401, detail="Credenciales inválidas") from None
        clear_login_failures(session, rate_key)
        raw_token, csrf_token, _ = issue_session(session, user)
        session.commit()
        auth_session = session.get(AuthSession, hashlib.sha256(raw_token.encode()).hexdigest())
        assert auth_session is not None
        set_session_cookies(response, raw_token, csrf_token)
        return _user_view(AuthContext(user, auth_session))

    @application.get("/api/auth/session", response_model=UserView)
    def current_session(context: AuthContext = Depends(get_auth_context)) -> UserView:
        return _user_view(context)

    @application.post("/api/auth/logout", status_code=204)
    def logout(response: Response, context: AuthContext = Depends(require_csrf), session: Session = Depends(get_session)) -> Response:
        session.delete(context.auth_session)
        session.commit()
        clear_session_cookies(response)
        response.status_code = 204
        return response

    @application.get("/api/events", response_model=list[EventSummary])
    def list_events(session: Session = Depends(get_session)) -> list[EventSummary]:
        events = session.scalars(select(Event).where(Event.is_demo.is_(True), Event.status == "published").order_by(Event.event_date, Event.id)).all()
        pricing = zone_pricing(session, [event.id for event in events])
        layouts = {layout.id: layout for layout in session.scalars(select(VenueLayout).where(VenueLayout.id.in_([event.layout_id for event in events if event.layout_id]))).all()}
        return [event_summary(event, pricing.get(event.id), layouts.get(event.layout_id)) for event in events]

    @application.get("/api/events/{event_id}", response_model=EventDetail)
    def public_event_detail(event_id: int, session: Session = Depends(get_session)) -> EventDetail:
        event = session.get(Event, event_id)
        if event is None or event.status != "published":
            raise HTTPException(status_code=404, detail="Evento no encontrado")
        return event_detail(event, session)

    @application.post("/api/events/{event_id}/reservations", response_model=ReservationCreated)
    def reserve(
        event_id: int,
        payload: ReservationCreate,
        response: Response,
        idempotency_key: str = Header(min_length=8, max_length=128, alias="Idempotency-Key"),
        context: AuthContext = Depends(require_csrf_role("client")),
        session: Session = Depends(get_session),
    ) -> ReservationCreated:
        try:
            result = create_reservation(session, event_id, context.user, payload, idempotency_key)
        except EventNotFoundError:
            raise HTTPException(status_code=404, detail="Evento no encontrado") from None
        except SalesNotOpenError:
            session.rollback()
            raise HTTPException(status_code=403, detail={"code": "sales_not_open", "message": "Las ventas de este evento todavía no han comenzado."}) from None
        except QueueRequiredError:
            session.rollback()
            raise HTTPException(status_code=403, detail={"code": "queue_required", "message": "Este evento tiene fila virtual: entra a la fila y espera tu turno para comprar."}) from None
        except CapacityExceededError:
            raise HTTPException(status_code=409, detail="No hay cupos suficientes") from None
        except SelectionConflictError:
            raise HTTPException(status_code=409, detail="Una o más entradas seleccionadas ya no están disponibles") from None
        except InvalidSelectionError as error:
            raise HTTPException(status_code=422, detail=str(error)) from None
        except IdempotencyConflictError:
            raise HTTPException(status_code=409, detail="La clave de idempotencia ya fue usada por otra solicitud") from None
        response.status_code = status.HTTP_200_OK if result.replayed else status.HTTP_201_CREATED
        return ReservationCreated(
            reservation_id=result.reservation.id,
            event_id=result.reservation.event_id,
            quantity=result.reservation.quantity,
            available_capacity=result.available_capacity,
            ticket_count=result.ticket_count,
            replayed=result.replayed,
            total=float(result.total),
            ticket_mode=result.ticket_mode,
        )

    @application.get("/api/me/reservations", response_model=list[MyReservation])
    def my_reservations(context: AuthContext = Depends(require_role("client")), session: Session = Depends(get_session)) -> list[MyReservation]:
        rows = session.execute(
            select(Reservation, Event.name)
            .join(Event, Event.id == Reservation.event_id)
            .where(Reservation.user_id == context.user.id)
            .order_by(Reservation.created_at.desc())
        ).all()
        return [MyReservation(id=item.id, event_id=item.event_id, event_name=name, quantity=item.quantity, created_at=item.created_at) for item, name in rows]

    def owned_ticket(ticket_id: UUID, owner_id: UUID, session: Session) -> TicketView:
        row = session.execute(
            select(Ticket, Event)
            .join(Event, Event.id == Ticket.event_id)
            .where(Ticket.id == ticket_id, Ticket.owner_user_id == owner_id)
        ).one_or_none()
        if row is None:
            raise HTTPException(status_code=404, detail="Entrada no encontrada")
        ticket, event = row
        zone = session.get(EventZone, ticket.zone_id) if ticket.zone_id else None
        seat = session.get(EventSeat, ticket.seat_id) if ticket.seat_id else None
        return TicketView(
            id=ticket.id,
            reservation_id=ticket.reservation_id,
            event_id=ticket.event_id,
            event_name=event.name,
            event_date=event.event_date,
            event_venue=event.venue,
            event_city=event.city,
            event_time=event.event_time,
            image_path=event.image_path,
            ticket_type=ticket.ticket_type,
            zone=zone.name if zone else None,
            row=seat.row_label if seat else None,
            seat=seat.seat_number if seat else None,
            unit_price=float(ticket.unit_price if ticket.unit_price is not None else event.price),
            qr_token=reveal_ticket_secret(ticket.token_ciphertext),
            used_at=ticket.used_at,
        )

    @application.get("/api/me/tickets", response_model=list[TicketView])
    def my_tickets(context: AuthContext = Depends(require_role("client")), session: Session = Depends(get_session)) -> list[TicketView]:
        ticket_ids = session.scalars(select(Ticket.id).where(Ticket.owner_user_id == context.user.id).order_by(Ticket.created_at.desc())).all()
        return [owned_ticket(ticket_id, context.user.id, session) for ticket_id in ticket_ids]

    @application.get("/api/me/tickets/{ticket_id}", response_model=TicketView)
    def my_ticket(ticket_id: UUID, context: AuthContext = Depends(require_role("client")), session: Session = Depends(get_session)) -> TicketView:
        return owned_ticket(ticket_id, context.user.id, session)

    @application.get("/api/operator/events", response_model=list[EventSummary])
    def operator_events(context: AuthContext = Depends(require_role("operator")), session: Session = Depends(get_session)) -> list[EventSummary]:
        events = session.scalars(
            select(Event).join(OperatorEventAssignment).where(OperatorEventAssignment.operator_user_id == context.user.id)
        ).all()
        pricing = zone_pricing(session, [event.id for event in events])
        layouts = {layout.id: layout for layout in session.scalars(select(VenueLayout).where(VenueLayout.id.in_([event.layout_id for event in events if event.layout_id]))).all()}
        return [event_summary(event, pricing.get(event.id), layouts.get(event.layout_id)) for event in events]

    @application.post("/api/operator/validate", response_model=ValidationResult)
    def validate_entry(
        payload: ValidationRequest,
        context: AuthContext = Depends(require_csrf_role("operator")),
        session: Session = Depends(get_session),
    ) -> ValidationResult:
        try:
            result = validate_ticket(session, context.user.id, payload.event_id, payload.qr_token)
        except EventNotAssignedError:
            raise HTTPException(status_code=403, detail="Operador no asignado a este evento") from None
        except TicketNotFoundError:
            raise HTTPException(status_code=404, detail="Código QR inexistente") from None
        except TicketWrongEventError:
            raise HTTPException(status_code=409, detail="La entrada corresponde a otro evento") from None
        except TicketAlreadyUsedError:
            raise HTTPException(status_code=409, detail="Entrada ya utilizada") from None
        ticket = session.get(Ticket, result.ticket_id)
        zone = session.get(EventZone, ticket.zone_id) if ticket and ticket.zone_id else None
        seat = session.get(EventSeat, ticket.seat_id) if ticket and ticket.seat_id else None
        location = (
            f"{zone.name} · fila {seat.row_label}, asiento {seat.seat_number}"
            if zone and seat else zone.name if zone else "Entrada general"
        )
        return ValidationResult(result="accepted", ticket_id=result.ticket_id, event_id=result.event_id, used_at=result.used_at, ticket_location=location)

    application.include_router(organizer_router)
    application.include_router(sales_router)
    return application


app = create_app()
