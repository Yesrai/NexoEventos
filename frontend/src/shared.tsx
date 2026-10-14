import { lazy, ReactNode, Suspense, useState } from 'react'
import type { IconType } from 'react-icons'
import {
  GiBallerinaShoes,
  GiBearFace,
  GiCampingTent,
  GiClapperboard,
  GiDramaMasks,
  GiHammerNails,
  GiKnifeFork,
  GiMeshNetwork,
  GiMicrochip,
  GiMicrophone,
  GiPalette,
  GiPublicSpeaker,
  GiShop,
  GiSoccerBall,
  GiWoodFrame,
} from 'react-icons/gi'

export type Role = 'client' | 'organizer' | 'operator'
export type User = { id: string; email: string; display_name: string; role: Role; session_expires_at: string }
export type EventItem = {
  id: number; name: string; date: string; time: string | null; venue: string; city: string; category: string
  price: number; has_multiple_prices: boolean; capacity: number; available_capacity: number
  image_path: string | null; ticket_mode: 'general' | 'zones' | 'seats'; is_demo: boolean
  venue_id: number | null; layout_id: number | null; layout_name: string | null
  layout_kind: 'theatre' | 'stadium' | 'concert_zones' | 'museum' | 'zones' | 'general' | null
  status: 'draft' | 'published'
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
export type View = 'catalog' | 'auth' | 'account' | 'operator' | 'organizer'
export type BarcodeResult = { rawValue: string }
export type BarcodeDetectorInstance = { detect(source: HTMLVideoElement): Promise<BarcodeResult[]> }
export type BarcodeDetectorConstructor = new (options: { formats: string[] }) => BarcodeDetectorInstance
export type IconName = 'arrow' | 'art' | 'calendar' | 'check' | 'cinema' | 'clock' | 'close' | 'conference' | 'dance' | 'exhibition' | 'eye' | 'eyeOff' | 'fair' | 'festival' | 'food' | 'kids' | 'location' | 'minus' | 'music' | 'networking' | 'plus' | 'qr' | 'search' | 'sliders' | 'sport' | 'technology' | 'theater' | 'ticket' | 'user' | 'workshop'

export const Stadium3D = lazy(() => import('./Stadium3D'))
export const Venue3D = lazy(() => import('./Venue3D'))

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
  if (typeof body === 'object' && body && 'detail' in body && typeof body.detail === 'string') return body.detail
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

export function AuditoriumSeatPicker({ seats, selectedSeatIds, onToggle }: {
  seats: Seat[]
  selectedSeatIds: number[]
  onToggle: (seat: Seat) => void
}) {
  const [zoom, setZoom] = useState(1)
  const [viewMode, setViewMode] = useState<'2d' | '3d'>('2d')
  const [threeUnavailable, setThreeUnavailable] = useState(false)
  const rows = [...new Set(seats.map((seat) => seat.row))]
  const maximumNumber = Math.max(0, ...seats.map((seat) => seat.number))
  const aisleStart = Math.floor(maximumNumber / 2) + 1
  const selectedSeats = seats.filter((seat) => selectedSeatIds.includes(seat.id))
  const changeZoom = (next: number) => setZoom(Math.max(.8, Math.min(1.4, Number(next.toFixed(1)))))

  return <div className="auditorium-selector">
    <div className="auditorium-heading">
      <div><strong>Plano del auditorio</strong><span>Escenario al frente · pasillo central</span></div>
      <div className="stadium-heading-actions"><div className="stadium-view-toggle" role="group" aria-label="Vista del auditorio"><button type="button" className={viewMode === '2d' ? 'active' : ''} aria-pressed={viewMode === '2d'} onClick={() => setViewMode('2d')}>Plano 2D</button><button type="button" className={viewMode === '3d' ? 'active' : ''} aria-pressed={viewMode === '3d'} disabled={threeUnavailable} onClick={() => setViewMode('3d')}>Sala 3D</button></div>{viewMode === '2d' && <div className="zoom-controls" role="group" aria-label="Zoom del plano">
        <button type="button" onClick={() => changeZoom(zoom - .1)} disabled={zoom <= .8} aria-label="Alejar plano"><Icon name="minus" size={16} /></button>
        <output aria-live="polite" aria-label="Nivel de zoom">{Math.round(zoom * 100)}%</output>
        <button type="button" onClick={() => changeZoom(zoom + .1)} disabled={zoom >= 1.4} aria-label="Acercar plano"><Icon name="plus" size={16} /></button>
        <button type="button" className="zoom-reset" onClick={() => setZoom(1)} disabled={zoom === 1}>Restablecer</button>
      </div>}</div>
    </div>
    {threeUnavailable && <p className="stadium-3d-fallback" role="status">La sala 3D no está disponible en este dispositivo. El plano 2D y la lista siguen activos.</p>}
    <div className="seat-legend" aria-label="Leyenda del plano">
      <span><i className="seat-sample" />Disponible</span>
      <span><i className="seat-sample selected">✓</i>Seleccionado</span>
      <span><i className="seat-sample occupied">×</i>Ocupado</span>
    </div>
    {viewMode === '3d' ? <Suspense fallback={<div className="venue-3d-loading" role="status"><span className="spinner" />Cargando sala 3D…</div>}><Venue3D kind="theatre" seats={seats} selectedSeatIds={selectedSeatIds} onToggleSeat={onToggle} onUnavailable={() => { setThreeUnavailable(true); setViewMode('2d') }} /></Suspense> : <div className="auditorium-viewport" tabIndex={0} aria-label="Plano desplazable del auditorio. Usa los controles de zoom o desplázate horizontalmente.">
      <div className="auditorium-plan" style={{ zoom }}>
        <div className="auditorium-stage"><span>Escenario</span></div>
        <div className="stage-direction" aria-hidden="true">Vista hacia el escenario</div>
        <div className="seat-map" role="group" aria-label="Asientos numerados">
          {rows.map((row) => {
            const rowSeats = seats.filter((seat) => seat.row === row)
            return <div className="seat-row" key={row}>
              <strong aria-hidden="true">{row}</strong>
              <div className="seat-bank">
                {rowSeats.map((seat) => <button
                  type="button"
                  key={seat.id}
                  className={`${selectedSeatIds.includes(seat.id) ? 'selected' : ''} ${seat.number === aisleStart ? 'aisle-before' : ''}`}
                  disabled={!seat.available}
                  aria-label={`Zona ${seat.zone_name}, fila ${seat.row}, asiento ${seat.number}, ${seat.available ? selectedSeatIds.includes(seat.id) ? 'seleccionado' : 'disponible' : 'ocupado'}`}
                  aria-pressed={selectedSeatIds.includes(seat.id)}
                  onClick={() => onToggle(seat)}
                >{seat.number}</button>)}
              </div>
              <strong aria-hidden="true">{row}</strong>
              <span className="row-zone">{rowSeats[0]?.zone_name}</span>
            </div>
          })}
        </div>
      </div>
    </div>}
    <div className="seat-selection-status" role="status" aria-live="polite">
      <strong>{selectedSeats.length ? `${selectedSeats.length} asiento${selectedSeats.length === 1 ? '' : 's'} seleccionado${selectedSeats.length === 1 ? '' : 's'}` : 'Ningún asiento seleccionado'}</strong>
      <span>{selectedSeats.length ? selectedSeats.map((seat) => `${seat.row}-${seat.number}`).join(', ') : 'Elige hasta 10 asientos disponibles.'}</span>
    </div>
    <details className="seat-list">
      <summary>Alternativa accesible por lista</summary>
      <div>{rows.map((row) => <fieldset key={row}><legend>Fila {row}</legend>{seats.filter((seat) => seat.row === row).map((seat) => <label key={seat.id}><input type="checkbox" checked={selectedSeatIds.includes(seat.id)} disabled={!seat.available} onChange={() => onToggle(seat)} /> {seat.zone_name}, asiento {seat.number} · S/ {seat.price.toFixed(2)} {seat.available ? '' : '(ocupado)'}</label>)}</fieldset>)}</div>
    </details>
    <small>La selección se confirma en el servidor. Si otra persona reserva primero, actualizaremos el plano sin duplicar el asiento.</small>
  </div>
}

export function StadiumSeatPicker({ seats, selectedSeatIds, onToggle }: {
  seats: Seat[]
  selectedSeatIds: number[]
  onToggle: (seat: Seat) => void
}) {
  const sectors = [...new Map(seats.map((seat) => [seat.zone_id, { id: seat.zone_id, name: seat.zone_name }])).values()]
  const [sectorId, setSectorId] = useState<number | null>(null)
  const [threeSectorId, setThreeSectorId] = useState<number | null>(null)
  const [viewMode, setViewMode] = useState<'2d' | '3d'>('2d')
  const [threeUnavailable, setThreeUnavailable] = useState(false)
  const [zoom, setZoom] = useState(1)
  const sector = sectors.find((item) => item.id === sectorId) ?? null
  const summarySector = sectors.find((item) => item.id === (viewMode === '3d' ? threeSectorId : sectorId)) ?? null
  const visible = sector ? seats.filter((seat) => seat.zone_id === sector.id) : []
  const rows = [...new Set(visible.map((seat) => seat.row))]
  const selected = seats.filter((seat) => selectedSeatIds.includes(seat.id))
  const sectorSeats = summarySector ? seats.filter((seat) => seat.zone_id === summarySector.id) : []
  const sectorPrice = sectorSeats[0]?.price ?? 0
  const sectorAvailable = sectorSeats.filter((seat) => seat.available).length
  const maximumNumber = Math.max(0, ...visible.map((seat) => seat.number))
  const aisleStart = Math.floor(maximumNumber / 2) + 1
  const total = selected.reduce((sum, seat) => sum + seat.price, 0)
  const changeZoom = (next: number) => setZoom(Math.max(.8, Math.min(1.4, Number(next.toFixed(1)))))
  const geometry: Record<string, { path: string; x: number; y: number; orientation: string }> = {
    'Tribuna Norte': { path: 'M165 38 H555 L525 125 H195 Z', x: 360, y: 82, orientation: 'Norte' },
    'Tribuna Occidente': { path: 'M92 100 L180 135 V325 L92 360 L50 310 V150 Z', x: 116, y: 232, orientation: 'Occidente' },
    'Tribuna Oriente': { path: 'M628 100 L540 135 V325 L628 360 L670 310 V150 Z', x: 604, y: 232, orientation: 'Oriente' },
    'Tribuna Sur': { path: 'M165 422 H555 L525 335 H195 Z', x: 360, y: 382, orientation: 'Sur' },
  }
  const configuredSectors = sectors.flatMap((item) => geometry[item.name] ? [{ ...item, ...geometry[item.name] }] : [])
  const chooseSector = (id: number) => { setSectorId(id); setZoom(1) }
  const returnToStadium = () => { setSectorId(null); setZoom(1) }
  return <div className="stadium-selector">
    <div className="stadium-heading"><div><p className="eyebrow">Plano del estadio</p>{viewMode === '2d' && sector && <button type="button" className="stadium-back" onClick={returnToStadium}><Icon name="arrow" size={16} /> Volver al estadio</button>}<strong>{summarySector ? `${summarySector.name} · Sector ${summarySector.name.replace('Tribuna ', '')}` : 'Selecciona una tribuna'}</strong><span>{summarySector ? 'Elige una fila y un asiento orientados hacia la cancha' : 'Norte arriba · Oriente derecha · Occidente izquierda'}</span></div><div className="stadium-heading-actions"><div className="stadium-view-toggle" role="group" aria-label="Vista del estadio"><button type="button" className={viewMode === '2d' ? 'active' : ''} aria-pressed={viewMode === '2d'} onClick={() => setViewMode('2d')}>Plano 2D</button><button type="button" className={viewMode === '3d' ? 'active' : ''} aria-pressed={viewMode === '3d'} disabled={threeUnavailable} onClick={() => setViewMode('3d')}>Vista 3D</button></div>{viewMode === '2d' && <div className="zoom-controls" role="group" aria-label="Zoom del plano del estadio"><button type="button" onClick={() => changeZoom(zoom - .1)} disabled={zoom <= .8} aria-label="Alejar plano"><Icon name="minus" size={16} /></button><output aria-live="polite" aria-label="Nivel de zoom">{Math.round(zoom * 100)}%</output><button type="button" onClick={() => changeZoom(zoom + .1)} disabled={zoom >= 1.4} aria-label="Acercar plano"><Icon name="plus" size={16} /></button><button type="button" className="zoom-reset" onClick={() => setZoom(1)} disabled={zoom === 1}>Ajustar</button></div>}</div></div>
    {threeUnavailable && <p className="stadium-3d-fallback" role="status">El visor 3D no está disponible en este dispositivo. El plano 2D y la lista accesible siguen activos.</p>}
    <div className="stadium-workspace">
      <div className="stadium-map-area">
        {viewMode === '3d' ? <Suspense fallback={<div className="stadium-3d-module-loading" role="status"><span className="spinner" />Cargando módulo 3D…</div>}><Stadium3D seats={seats} selectedSeatIds={selectedSeatIds} onToggle={onToggle} onSectorChange={setThreeSectorId} onUnavailable={() => { setThreeUnavailable(true); setViewMode('2d') }} /></Suspense> : !sector ? <div className="stadium-viewport" tabIndex={0} aria-label="Mapa desplazable del estadio"><svg className="stadium-svg" style={{ transform: `scale(${zoom})` }} viewBox="0 0 720 460" role="group" aria-label="Tribunas alrededor de la cancha">
          <rect className="stadium-outline" x="28" y="20" width="664" height="420" rx="62" />
          <rect className="football-field" x="205" y="132" width="310" height="196" rx="5" />
          <line className="field-line" x1="360" y1="132" x2="360" y2="328" /><circle className="field-line" cx="360" cy="230" r="33" /><circle className="field-dot" cx="360" cy="230" r="3" />
          <rect className="field-line" x="205" y="174" width="48" height="112" /><rect className="field-line" x="467" y="174" width="48" height="112" /><rect className="field-goal" x="195" y="204" width="10" height="52" /><rect className="field-goal" x="515" y="204" width="10" height="52" />
          {configuredSectors.map((item) => <g key={item.id} className={`stadium-map-sector ${selected.some((seat) => seat.zone_id === item.id) ? 'has-selection' : ''}`} role="button" tabIndex={0} aria-label={`${item.name}, ${seats.filter((seat) => seat.zone_id === item.id && seat.available).length} disponibles, S/ ${(seats.find((seat) => seat.zone_id === item.id)?.price ?? 0).toFixed(2)}`} onClick={() => chooseSector(item.id)} onKeyDown={(event) => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); chooseSector(item.id) } }}><path className="stadium-sector-shape" d={item.path} /><text className="stadium-sector-label" x={item.x} y={item.y} textAnchor="middle">{item.name.replace('Tribuna ', '')}</text><text className="stadium-sector-count" x={item.x} y={item.y + 18} textAnchor="middle">{seats.filter((seat) => seat.zone_id === item.id && seat.available).length} disp.</text></g>)}
          <text className="stadium-compass" x="360" y="18" textAnchor="middle">N</text>
        </svg></div> : <div className="sector-viewport" tabIndex={0} aria-label={`Plano ampliado de ${sector.name}`}><div className="sector-plan" style={{ transform: `scale(${zoom})` }}><div className="field-orientation"><span>Hacia la cancha</span><i aria-hidden="true">↓</i></div><div className="stadium-seats" role="group" aria-label={`Localidades de ${sector.name}`}>{rows.map((row) => <div className="stadium-seat-row" key={row}><strong aria-hidden="true">{row}</strong><div>{visible.filter((seat) => seat.row === row).map((seat) => <button type="button" key={seat.id} className={`${selectedSeatIds.includes(seat.id) ? 'selected' : ''} ${seat.number === aisleStart ? 'aisle-before' : ''}`} disabled={!seat.available} aria-pressed={selectedSeatIds.includes(seat.id)} aria-label={`${seat.zone_name}, fila ${seat.row}, asiento ${seat.number}, ${seat.available ? selectedSeatIds.includes(seat.id) ? 'seleccionado' : 'disponible' : 'ocupado'}, S/ ${seat.price.toFixed(2)}`} onClick={() => onToggle(seat)}>{!seat.available ? '×' : seat.number}</button>)}</div><strong aria-hidden="true">{row}</strong></div>)}</div></div></div>}
      </div>
      <details className="stadium-summary" open aria-live="polite"><summary>Resumen de selección</summary><div className="stadium-summary-content"><p className="eyebrow">Selección actual</p>{summarySector ? <><h4>{summarySector.name}</h4><dl><div><dt>Sector</dt><dd>{summarySector.name.replace('Tribuna ', '')}</dd></div><div><dt>Precio</dt><dd>S/ {sectorPrice.toFixed(2)}</dd></div><div><dt>Disponibles</dt><dd>{sectorAvailable} de {sectorSeats.length}</dd></div></dl></> : <><h4>Elige en el mapa</h4><p>Selecciona una superficie de tribuna para ver sus filas y localidades reales.</p></>}<div className="seat-selection-status" role="status"><strong>{selected.length ? `${selected.length} localidad${selected.length === 1 ? '' : 'es'} seleccionada${selected.length === 1 ? '' : 's'}` : 'Ninguna localidad seleccionada'}</strong><span>{selected.length ? selected.map((seat) => `${seat.zone_name} ${seat.row}-${seat.number}`).join(', ') : 'Puedes conservar asientos al volver al estadio.'}</span>{selected.length > 0 && <b>Total: S/ {total.toFixed(2)}</b>}</div></div></details>
    </div>
    <div className="seat-legend" aria-label="Leyenda del plano"><span><i className="seat-sample" />Disponible</span><span><i className="seat-sample selected">✓</i>Seleccionado</span><span><i className="seat-sample occupied">×</i>Ocupado</span></div>
    <details className="seat-list"><summary>Alternativa accesible por lista</summary><div>{sectors.map((sector) => <fieldset key={sector.id}><legend>{sector.name}</legend>{seats.filter((seat) => seat.zone_id === sector.id).map((seat) => <label key={seat.id}><input type="checkbox" checked={selectedSeatIds.includes(seat.id)} disabled={!seat.available} onChange={() => onToggle(seat)} /> Fila {seat.row}, asiento {seat.number} · S/ {seat.price.toFixed(2)} {seat.available ? '' : '(ocupado)'}</label>)}</fieldset>)}</div></details>
  </div>
}

export function ZoneLayoutPicker({ zones, selectedZoneId, onSelect, concert }: { zones: Zone[]; selectedZoneId: number | null; onSelect: (id: number) => void; concert: boolean }) {
  const [viewMode, setViewMode] = useState<'2d' | '3d'>('2d')
  const [threeUnavailable, setThreeUnavailable] = useState(false)
  return <fieldset className={`zone-options ${concert ? 'concert-zone-picker' : ''}`}><legend>{concert ? 'Elige una zona de pie' : 'Elige una zona'}</legend>{concert && <><div className="venue-view-heading"><span>Plano de Arena Parque Sur</span><div className="stadium-view-toggle" role="group" aria-label="Vista del concierto"><button type="button" className={viewMode === '2d' ? 'active' : ''} aria-pressed={viewMode === '2d'} onClick={() => setViewMode('2d')}>Plano 2D</button><button type="button" className={viewMode === '3d' ? 'active' : ''} aria-pressed={viewMode === '3d'} disabled={threeUnavailable} onClick={() => setViewMode('3d')}>Recinto 3D</button></div></div>{viewMode === '3d' ? <Suspense fallback={<div className="venue-3d-loading" role="status"><span className="spinner" />Cargando recinto 3D…</div>}><Venue3D kind="concert" zones={zones} selectedZoneId={selectedZoneId} onSelectZone={onSelect} onUnavailable={() => { setThreeUnavailable(true); setViewMode('2d') }} /></Suspense> : <div className="concert-plan" aria-label="Plano del concierto"><div className="concert-stage">Escenario</div><div className="concert-floor">Zonas sin asientos numerados</div></div>}</>}<div className={concert ? 'concert-zone-grid' : ''}>{zones.map((zone) => <button type="button" key={zone.id} className={`ticket-option ${selectedZoneId === zone.id ? 'selected-option' : ''}`} disabled={zone.available_capacity === 0} aria-pressed={selectedZoneId === zone.id} onClick={() => onSelect(zone.id)}><span className="selection-check">{selectedZoneId === zone.id && <Icon name="check" size={16} />}</span><div><strong>{zone.name}</strong><small>{zone.available_capacity} de {zone.capacity} disponibles{concert ? ' · de pie' : ''}</small></div><b>S/ {zone.price.toFixed(2)}</b></button>)}</div></fieldset>
}

export function MuseumVisitGuide() {
  const [viewMode, setViewMode] = useState<'2d' | '3d'>('2d')
  const [threeUnavailable, setThreeUnavailable] = useState(false)
  return <aside className="museum-guide" aria-label="Plano orientativo del museo"><div className="museum-guide-heading"><div><strong>Recorrido orientativo</strong><span>La reserva es por horario y cantidad, no por sala.</span></div><div className="stadium-view-toggle" role="group" aria-label="Vista del museo"><button type="button" className={viewMode === '2d' ? 'active' : ''} aria-pressed={viewMode === '2d'} onClick={() => setViewMode('2d')}>Plano</button><button type="button" className={viewMode === '3d' ? 'active' : ''} aria-pressed={viewMode === '3d'} disabled={threeUnavailable} onClick={() => setViewMode('3d')}>Recorrido 3D</button></div></div>{viewMode === '3d' ? <Suspense fallback={<div className="venue-3d-loading" role="status"><span className="spinner" />Cargando recorrido 3D…</div>}><Venue3D kind="museum" onUnavailable={() => { setThreeUnavailable(true); setViewMode('2d') }} /></Suspense> : <div className="museum-rooms" aria-hidden="true"><span>Ingreso</span><span>Sala 1</span><span>Sala 2</span><span>Sala 3</span><span>Salida</span></div>}</aside>
}


export const categoryPresentation: Record<string, { label: string; Icon: IconType }> = {
  Conciertos: { label: 'Conciertos', Icon: GiMicrophone },
  Festivales: { label: 'Festivales', Icon: GiCampingTent },
  'Teatro y stand-up': { label: 'Teatro', Icon: GiDramaMasks },
  Danza: { label: 'Danza', Icon: GiBallerinaShoes },
  Cine: { label: 'Cine', Icon: GiClapperboard },
  Deportes: { label: 'Deportes', Icon: GiSoccerBall },
  Gastronomía: { label: 'Gastronomía', Icon: GiKnifeFork },
  Ferias: { label: 'Ferias', Icon: GiShop },
  Exposiciones: { label: 'Exposiciones', Icon: GiWoodFrame },
  'Arte y cultura': { label: 'Arte y cultura', Icon: GiPalette },
  Talleres: { label: 'Talleres', Icon: GiHammerNails },
  Infantil: { label: 'Infantil', Icon: GiBearFace },
  Conferencias: { label: 'Conferencias', Icon: GiPublicSpeaker },
  Networking: { label: 'Networking', Icon: GiMeshNetwork },
  Tecnología: { label: 'Tecnología', Icon: GiMicrochip },
}

export const categoryOrder = Object.keys(categoryPresentation)
