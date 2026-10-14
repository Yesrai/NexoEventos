"""Estado de ventas y fila virtual de un evento (lado cliente)."""
from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from app import queue as sales_queue
from app.auth import AuthContext, get_auth_context, require_csrf_role
from app.config import SESSION_COOKIE
from app.database import get_session
from app.models import Event, User
from app.schemas import SalesStatus

router = APIRouter(prefix="/api/events", tags=["sales"])


def _optional_user(session: Session, raw_token: str | None) -> User | None:
    if not raw_token:
        return None
    try:
        context = get_auth_context(session=session, raw_token=raw_token)
    except HTTPException:
        return None
    return context.user if context.user.role == "client" else None


@router.get("/{event_id}/sales", response_model=SalesStatus)
def sales_status(event_id: int, session: Session = Depends(get_session), raw_token: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None) -> SalesStatus:
    event = session.get(Event, event_id)
    if event is not None and event.status == "published" and event.queue_enabled:
        event = sales_queue.locked_event(session, event_id)  # solo la fila virtual serializa con las reservas
    if event is None or event.status != "published":
        session.rollback()
        raise HTTPException(status_code=404, detail="Evento no encontrado")
    user = _optional_user(session, raw_token)
    if event.queue_enabled:
        sales_queue.refresh(session, event, sales_queue.server_now(session))
    result = sales_queue.status_for(session, event, user)
    session.commit()
    return SalesStatus(**result)


@router.post("/{event_id}/queue", response_model=SalesStatus)
def join_queue(event_id: int, context: AuthContext = Depends(require_csrf_role("client")), session: Session = Depends(get_session)) -> SalesStatus:
    event = sales_queue.locked_event(session, event_id)
    if event is None:
        session.rollback()
        raise HTTPException(status_code=404, detail="Evento no encontrado")
    try:
        sales_queue.join(session, event, context.user)
    except sales_queue.QueueUnavailableError:
        session.rollback()
        raise HTTPException(status_code=409, detail="Este evento no usa fila virtual") from None
    result = sales_queue.status_for(session, event, context.user)
    session.commit()
    return SalesStatus(**result)


@router.delete("/{event_id}/queue", response_model=SalesStatus)
def leave_queue(event_id: int, context: AuthContext = Depends(require_csrf_role("client")), session: Session = Depends(get_session)) -> SalesStatus:
    event = sales_queue.locked_event(session, event_id)
    if event is None:
        session.rollback()
        raise HTTPException(status_code=404, detail="Evento no encontrado")
    sales_queue.leave(session, event, context.user)
    result = sales_queue.status_for(session, event, context.user)
    session.commit()
    return SalesStatus(**result)
