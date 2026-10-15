import type { ReactNode } from 'react'
import type { IconType } from 'react-icons'
import { LuBaby, LuClapperboard, LuCpu, LuDrama, LuFrame, LuHammer, LuMic, LuMusic, LuPalette, LuPresentation, LuStore, LuTent, LuTrophy, LuUsers, LuUtensilsCrossed } from 'react-icons/lu'

export type Role = 'client' | 'organizer' | 'operator'
export type User = { id: string; email: string; display_name: string; role: Role; session_expires_at: string }
export type EventItem = {
  id: number; name: string; date: string; time: string | null; venue: string; city: string; category: string
  price: number; has_multiple_prices: boolean; capacity: number; available_capacity: number
  image_path: string | null; ticket_mode: 'general' | 'zones' | 'seats'; is_demo: boolean
  venue_id: number | null; layout_id: number | null; layout_name: string | null
  layout_kind: 'theatre' | 'stadium' | 'concert_zones' | 'museum' | 'zones' | 'general' | null
  status: 'draft' | 'published'
  sales_start_at: string | null; queue_enabled: boolean; queue_max_active: number; queue_pass_minutes: number
}
export type Zone = { id: number; name: string; price: number; capacity: number; available_capacity: number }
export type Seat = { id: number; zone_id: number; zone_name: string; row: string; number: number; price: number; available: boolean }
export type EventDetail = EventItem & { description: string; zones: Zone[]; seats: Seat[] }
export type Reservation = { id: string; event_id: number; event_name: string; quantity: number; created_at: string }
export type Ticket = {
  id: string; reservation_id: string; event_id: number; event_name: string
  event_date: string; event_time: string | null; event_venue: string; event_city: string; image_path: string | null
  ticket_type: 'general' | 'zones' | 'seats'; zone: string | null; row: string | null; seat: number | null; unit_price: number
  qr_token: string; used_at: string | null
}
export type QueueState = { status: 'waiting' | 'admitted'; position: number | null; waiting_total: number; expires_at: string | null; seconds_left: number | null }
export type SalesStatus = { server_time: string; sales_start_at: string | null; sales_open: boolean; queue_enabled: boolean; queue_max_active: number; queue_pass_minutes: number; queue: QueueState | null }
export type View = 'catalog' | 'auth' | 'account' | 'operator' | 'organizer'
export type BarcodeResult = { rawValue: string }
export type BarcodeDetectorInstance = { detect(source: HTMLVideoElement): Promise<BarcodeResult[]> }
export type BarcodeDetectorConstructor = new (options: { formats: string[] }) => BarcodeDetectorInstance
export type IconName = 'arrow' | 'art' | 'calendar' | 'check' | 'cinema' | 'clock' | 'close' | 'conference' | 'dance' | 'exhibition' | 'eye' | 'eyeOff' | 'fair' | 'festival' | 'food' | 'kids' | 'location' | 'minus' | 'music' | 'networking' | 'plus' | 'qr' | 'search' | 'sliders' | 'sport' | 'technology' | 'theater' | 'ticket' | 'user' | 'workshop'

export const configuredApiUrl = import.meta.env.VITE_API_URL
export const apiUrl = configuredApiUrl ?? ''

export function cookie(name: string) {
  return document.cookie.split('; ').find((item) => item.startsWith(`${name}=`))?.split('=').slice(1).join('=') ?? ''
}

export async function api(path: string, init: RequestInit = {}) {
  const headers = new Headers(init.headers)
  if (init.body) headers.set('Content-Type', 'application/json')
  if (init.method && init.method !== 'GET') {
    const csrf = cookie('nexoeventos_csrf')
    if (csrf) headers.set('X-CSRF-Token', csrf)
  }
  return fetch(`${apiUrl}${path}`, { ...init, headers, credentials: 'include' })
}

export function formatDate(value: string) {
  return new Intl.DateTimeFormat('es-PE', { day: '2-digit', month: 'short', year: 'numeric' }).format(
    new Date(value.length === 10 ? `${value}T12:00:00` : value),
  )
}

export function formatTime(value: string | null) {
  if (!value) return 'Horario no especificado'
  const [hours, minutes] = value.split(':').map(Number)
  return new Intl.DateTimeFormat('es-PE', { hour: 'numeric', minute: '2-digit', timeZone: 'America/Lima' }).format(new Date(Date.UTC(2026, 0, 1, hours + 5, minutes)))
}

export function formatEventPrice(event: Pick<EventItem, 'price' | 'has_multiple_prices'>) {
  if (event.price === 0) return 'Gratis'
  return `${event.has_multiple_prices ? 'Desde ' : ''}S/ ${event.price.toFixed(2)}`
}

export function messageFrom(body: unknown, fallback: string) {
  if (typeof body === 'object' && body && 'detail' in body) {
    const detail = (body as { detail: unknown }).detail
    if (typeof detail === 'string') return detail
    if (typeof detail === 'object' && detail && 'message' in detail && typeof (detail as { message: unknown }).message === 'string') return (detail as { message: string }).message
  }
  return fallback
}

export function requestError(caught: unknown, fallback: string) {
  if (caught instanceof TypeError) return fallback
  return caught instanceof Error ? caught.message : fallback
}

export function Icon({ name, size = 20 }: { name: IconName; size?: number }) {
  const paths: Record<IconName, ReactNode> = {
    arrow: <><path d="M5 12h14" /><path d="m13 6 6 6-6 6" /></>,
    art: <><path d="M12 3a9 9 0 1 0 0 18h1.5a2 2 0 0 0 0-4H12a1.5 1.5 0 0 1 0-3h3a6 6 0 0 0 6-6c0-3-4-5-9-5Z" /><circle cx="7.5" cy="10" r=".8" fill="currentColor" /><circle cx="10" cy="6.8" r=".8" fill="currentColor" /><circle cx="15" cy="7" r=".8" fill="currentColor" /></>,
    calendar: <><path d="M7 2v3M17 2v3M3 9h18" /><rect x="3" y="4" width="18" height="17" rx="3" /></>,
    check: <path d="m5 12 4 4L19 6" />,
    cinema: <><rect x="3" y="7" width="18" height="13" rx="2" /><path d="m3 7 3-4h4L7 7m7 0 3-4h4l-3 4M8 12l6 3-6 3v-6Z" /></>,
    clock: <><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" /></>,
    close: <><path d="m6 6 12 12M18 6 6 18" /></>,
    conference: <><circle cx="12" cy="5" r="2" /><path d="M8 10c1-2 7-2 8 0M12 9v4" /><rect x="5" y="12" width="14" height="8" rx="2" /><path d="M9 16h6M12 12v8" /></>,
    dance: <><circle cx="13" cy="4" r="2" /><path d="m11 7-3 5 4 2 2 6M11 8l5 3 3-2M8 12l-4 4M12 14l-5 6" /></>,
    exhibition: <><rect x="3" y="4" width="18" height="16" rx="2" /><circle cx="9" cy="9" r="2" /><path d="m5 17 4-4 3 3 3-4 4 5" /></>,
    eye: <><path d="M2 12s3.5-6 10-6 10 6 10 6-3.5 6-10 6S2 12 2 12Z" /><circle cx="12" cy="12" r="2.5" /></>,
    eyeOff: <><path d="m3 3 18 18" /><path d="M10.6 6.2A10.7 10.7 0 0 1 12 6c6.5 0 10 6 10 6a17 17 0 0 1-2.1 2.9M6.6 6.6C3.6 8.4 2 12 2 12s3.5 6 10 6c1.3 0 2.5-.2 3.5-.6" /></>,
    fair: <><path d="M3 10h18l-3-5H6l-3 5Z" /><path d="M5 10v9h14v-9M8 19v-5h8v5" /><path d="M3 10c0 2 3 2 4.5 0 1.5 2 3 2 4.5 0 1.5 2 3 2 4.5 0 1.5 2 4.5 2 4.5 0" /></>,
    festival: <><path d="M4 5h16M6 5l2 4 2-4 2 4 2-4 2 4 2-4" /><path d="M7 14h.01M17 13h.01M12 17h.01" /><path d="m5 18 1 1m12-2 1-1m-7-4v-2" /></>,
    food: <><path d="M6 3v8M3.5 3v5a2.5 2.5 0 0 0 5 0V3M6 11v10" /><path d="M16 3c-2 2-3 5-3 8h4v10M17 3v8" /></>,
    kids: <><path d="m12 3 6 6-6 6-6-6 6-6Z" /><path d="m12 15 2 2-2 2 2 2M9 6l6 6M15 6 9 12" /></>,
    location: <><path d="M20 10c0 5-8 12-8 12S4 15 4 10a8 8 0 1 1 16 0Z" /><circle cx="12" cy="10" r="2.5" /></>,
    minus: <path d="M5 12h14" />,
    music: <><path d="M9 18V6l10-2v12" /><path d="M9 9l10-2" /><circle cx="6" cy="18" r="3" /><circle cx="16" cy="16" r="3" /></>,
    networking: <><circle cx="8" cy="8" r="3" /><circle cx="17" cy="7" r="2.5" /><path d="M3 20a5 5 0 0 1 10 0M13 14a4 4 0 0 1 8 3M11 10l3-1" /></>,
    plus: <><path d="M12 5v14M5 12h14" /></>,
    qr: <><rect x="3" y="3" width="7" height="7" rx="1" /><rect x="14" y="3" width="7" height="7" rx="1" /><rect x="3" y="14" width="7" height="7" rx="1" /><path d="M14 14h3v3h-3zM18 18h3v3h-3zM14 20h1M20 14h1" /></>,
    search: <><circle cx="11" cy="11" r="7" /><path d="m20 20-4-4" /></>,
    sliders: <><path d="M4 6h16M4 12h16M4 18h16" /><circle cx="8" cy="6" r="2" fill="white" /><circle cx="15" cy="12" r="2" fill="white" /><circle cx="10" cy="18" r="2" fill="white" /></>,
    sport: <><path d="M8 4h8v4a4 4 0 0 1-8 0V4Z" /><path d="M8 6H4v1a4 4 0 0 0 4 4M16 6h4v1a4 4 0 0 1-4 4M12 12v4M8 20h8M9 16h6" /></>,
    technology: <><rect x="6" y="6" width="12" height="12" rx="2" /><rect x="9" y="9" width="6" height="6" rx="1" /><path d="M9 2v4M15 2v4M9 18v4M15 18v4M2 9h4M2 15h4M18 9h4M18 15h4" /></>,
    theater: <><path d="M3 5c3-2 6-2 9 0v8c-2 4-7 4-9 0V5Z" /><path d="M6 8h.01M9 8h.01M6 12c1 .8 2 .8 3 0M13 6c3-1 6 0 8 2v7c-1 4-5 5-8 2" /><path d="M16 10h.01M19 11h.01M16 15c1-1 2-1 3 0" /></>,
    ticket: <><path d="M3 9a3 3 0 0 0 0 6v4h18v-4a3 3 0 0 0 0-6V5H3v4Z" /><path d="M13 7v2M13 13v4" /></>,
    user: <><circle cx="12" cy="8" r="4" /><path d="M4 21a8 8 0 0 1 16 0" /></>,
    workshop: <><path d="m14 6 4-4 4 4-4 4M15 9 5 19H2v-3L12 6" /><path d="M5 5h5M7.5 2.5v5" /></>,
  }
  return <svg className="icon" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{paths[name]}</svg>
}

export const categoryPresentation: Record<string, { label: string; Icon: IconType }> = {
  Conciertos: { label: 'Conciertos', Icon: LuMic },
  Festivales: { label: 'Festivales', Icon: LuTent },
  'Teatro y stand-up': { label: 'Teatro', Icon: LuDrama },
  Danza: { label: 'Danza', Icon: LuMusic },
  Cine: { label: 'Cine', Icon: LuClapperboard },
  Deportes: { label: 'Deportes', Icon: LuTrophy },
  Gastronomía: { label: 'Gastronomía', Icon: LuUtensilsCrossed },
  Ferias: { label: 'Ferias', Icon: LuStore },
  Exposiciones: { label: 'Exposiciones', Icon: LuFrame },
  'Arte y cultura': { label: 'Arte y cultura', Icon: LuPalette },
  Talleres: { label: 'Talleres', Icon: LuHammer },
  Infantil: { label: 'Infantil', Icon: LuBaby },
  Conferencias: { label: 'Conferencias', Icon: LuPresentation },
  Networking: { label: 'Networking', Icon: LuUsers },
  Tecnología: { label: 'Tecnología', Icon: LuCpu },
}

export const categoryOrder = Object.keys(categoryPresentation)

/** Colores por zona: iguales en la lista, el plano 2D y el recinto 3D. */
export const CONCERT_HUES = ['#c9892b', '#7a5aa6', '#4f8a6a', '#b5523f']
export const SEAT_HUES = ['#c9892b', '#4f8a6a', '#7a5aa6', '#b5523f']

export function zoneColorMap(zones: Array<{ id: number; price: number }>, concert: boolean) {
  const ordered = [...zones].sort((a, b) => concert ? b.price - a.price : a.price - b.price)
  const palette = concert ? CONCERT_HUES : SEAT_HUES
  return new Map(ordered.map((zone, index) => [zone.id, palette[index % palette.length]]))
}

export function apiOrigin() { return apiUrl }
