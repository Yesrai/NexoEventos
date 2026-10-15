import { FormEvent, lazy, RefObject, Suspense, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api, EventDetail, formatDate, formatTime, Icon, messageFrom, Seat, SalesStatus, User, Zone, zoneColorMap } from './shared'

const Venue3D = lazy(() => import('./Venue3D'))
const Stadium3D = lazy(() => import('./Stadium3D'))

type StageMode = '3d' | 'plan' | 'list'
const money = (value: number) => value === 0 ? 'Gratis' : `S/ ${value.toFixed(2)}`
/** Qué recinto representa un evento. Los eventos con asientos numerados sobre planos genéricos (datos anteriores) usan la sala de butacas. */
type VenueKind = 'theatre' | 'stadium' | 'concert' | 'museum' | null
const venueKind = (event: EventDetail): VenueKind => {
  const kind = event.layout_kind ?? ''
  if (event.ticket_mode === 'seats') return kind === 'stadium' ? 'stadium' : 'theatre'
  if (kind === 'concert_zones' && event.ticket_mode === 'zones') return 'concert'
  if (kind === 'museum') return 'museum'
  return null
}
const supports3D = (event: EventDetail) => venueKind(event) !== null

/** Estado de la selección de compra. Lo usan la página del cliente y la vista previa del organizador. */
export function useSelection(event: EventDetail | null, onChange?: () => void) {
  const [quantity, setQuantity] = useState(1)
  const [zoneId, setZoneId] = useState<number | null>(null)
  const [selectedSeatIds, setSelectedSeatIds] = useState<number[]>([])
  const activeZone = event?.zones?.find((zone) => zone.id === zoneId) ?? null
  const quantityLimit = event ? Math.max(1, Math.min(10, activeZone?.available_capacity ?? event.available_capacity)) : 1
  const selectedSeats = event ? event.seats.filter((seat) => selectedSeatIds.includes(seat.id)) : []
  const unitPrice = event ? activeZone?.price ?? event.price : 0
  const total = event?.ticket_mode === 'seats' ? selectedSeats.reduce((sum, seat) => sum + seat.price, 0) : unitPrice * quantity
  const reset = () => { setQuantity(1); setZoneId(null); setSelectedSeatIds([]) }
  const changeQuantity = (next: number) => { setQuantity(Math.max(1, Math.min(quantityLimit, next))); onChange?.() }
  const selectZone = (id: number) => { setZoneId(id); setQuantity(1); onChange?.() }
  const toggleSeat = (seat: Seat) => {
    if (!seat.available) return
    setSelectedSeatIds((current) => {
      const next = current.includes(seat.id) ? current.filter((id) => id !== seat.id) : current.length < 10 ? [...current, seat.id] : current
      setQuantity(Math.max(1, next.length))
      return next
    })
    onChange?.()
  }
  const removeSeat = (id: number) => toggleSeat({ id, available: true } as Seat)
  return { quantity, setQuantity, zoneId, setZoneId, selectedSeatIds, setSelectedSeatIds, activeZone, quantityLimit, selectedSeats, unitPrice, total, reset, changeQuantity, selectZone, toggleSeat, removeSeat }
}
export type Selection = ReturnType<typeof useSelection>

/** Estado de ventas y fila virtual. La hora y la posición vienen siempre del servidor. */
function useSales(eventId: number, enabled: boolean) {
  const [sales, setSales] = useState<SalesStatus | null>(null)
  const [offset, setOffset] = useState(0)
  const [now, setNow] = useState(() => Date.now())
  const [error, setError] = useState<string | null>(null)
  const accept = useCallback((value: SalesStatus) => { setSales(value); setOffset(Date.parse(value.server_time) - Date.now()); setError(null) }, [])
  const refresh = useCallback(async () => {
    if (!enabled) return
    try {
      const response = await api(`/api/events/${eventId}/sales`)
      const body = response.ok ? await response.json() as SalesStatus : null
      if (body && typeof body.sales_open === 'boolean' && body.server_time) accept(body)
    } catch { /* se reintenta en el siguiente ciclo */ }
  }, [eventId, enabled, accept])
  useEffect(() => { void refresh() }, [refresh])
  const polling = Boolean(sales && (sales.queue_enabled || !sales.sales_open))
  useEffect(() => { if (!polling) return; const timer = window.setInterval(() => void refresh(), 5000); return () => window.clearInterval(timer) }, [polling, refresh])
  useEffect(() => { if (!polling) return; const timer = window.setInterval(() => setNow(Date.now()), 1000); return () => window.clearInterval(timer) }, [polling])
  const serverNow = now + offset
  const msToStart = sales?.sales_start_at ? Date.parse(sales.sales_start_at) - serverNow : 0
  const secondsLeft = sales?.queue?.status === 'admitted' && sales.queue.expires_at ? Math.max(0, Math.floor((Date.parse(sales.queue.expires_at) - serverNow) / 1000)) : null
  // Al cruzar el inicio o el vencimiento del turno se vuelve a preguntar al servidor.
  const boundary = sales && ((!sales.sales_open && msToStart <= 0) || (secondsLeft === 0))
  useEffect(() => { if (boundary) void refresh() }, [boundary, refresh])
  async function act(method: 'POST' | 'DELETE') {
    const response = await api(`/api/events/${eventId}/queue`, { method })
    if (response.ok) accept(await response.json() as SalesStatus)
    else setError(messageFrom(await response.json().catch(() => null), 'No se pudo actualizar tu lugar en la fila. Inténtalo de nuevo.'))
    return response.ok
  }
  return { sales, msToStart, secondsLeft, error, refresh, join: () => act('POST'), leave: () => act('DELETE') }
}

function clock(totalSeconds: number) {
  const days = Math.floor(totalSeconds / 86400)
  const hours = Math.floor((totalSeconds % 86400) / 3600)
  const minutes = Math.floor((totalSeconds % 3600) / 60)
  const seconds = totalSeconds % 60
  const pad = (value: number) => String(value).padStart(2, '0')
  return { days, text: `${days > 0 ? `${days} d ` : ''}${pad(hours)}:${pad(minutes)}:${pad(seconds)}` }
}

function startLabel(iso: string) {
  return new Intl.DateTimeFormat('es-PE', { dateStyle: 'full', timeStyle: 'short', timeZone: 'America/Lima' }).format(new Date(iso))
}

function SalesGate({ event, user, state, onLogin }: { event: EventDetail; user: User | null; state: ReturnType<typeof useSales>; onLogin: () => void }) {
  const { sales, msToStart, secondsLeft, error } = state
  const [busy, setBusy] = useState(false)
  if (!sales) return null
  const queue = sales.queue
  const countdown = !sales.sales_open && sales.sales_start_at ? clock(Math.max(0, Math.ceil(msToStart / 1000))) : null
  const run = async (action: () => Promise<boolean>) => { setBusy(true); try { await action() } finally { setBusy(false) } }
  const joinOrLogin = () => user?.role === 'client' ? void run(state.join) : onLogin()
  return <section className="ep-gate" aria-label="Sala de espera">
    {countdown && sales.sales_start_at && <div className="ep-countdown"><p className="ep-gate-kicker">Las ventas comienzan</p><p className="ep-gate-date">{startLabel(sales.sales_start_at)}</p><div className="ep-clock" role="timer" aria-label={`Faltan ${countdown.text}`}>{countdown.text}</div><p className="ep-gate-help">Hora oficial del servidor (Lima). Puedes recargar la página: tu lugar no se pierde.</p></div>}
    {sales.queue_enabled && !queue && <div className="ep-queue-card"><h2>{sales.sales_open ? 'Fila virtual por alta demanda' : 'Sala de espera'}</h2><p>{sales.sales_open ? `Solo ${sales.queue_max_active} personas compran a la vez. Entra a la fila y te avisaremos cuando sea tu turno.` : 'Entra a la sala de espera para guardar tu lugar por orden de llegada. Cuando abran las ventas se admite a las personas en ese orden.'}</p><button type="button" className="ep-button primary" disabled={busy} onClick={joinOrLogin}>{user?.role === 'client' ? sales.sales_open ? 'Entrar a la fila' : 'Entrar a la sala de espera' : 'Inicia sesión para entrar'}</button></div>}
    {queue?.status === 'waiting' && <div className="ep-queue-card" aria-live="polite"><h2>Estás en la {sales.sales_open ? 'fila' : 'sala de espera'}</h2>{queue.position !== null && <p className="ep-position"><strong>{queue.position}</strong><span>{queue.position === 1 ? 'Eres la siguiente persona' : `${queue.position - 1} personas delante de ti`} · {queue.waiting_total} en espera</span></p>}<p>{sales.sales_open ? 'Mantén esta página abierta. Tu lugar está guardado en el servidor, incluso si la recargas.' : 'Cuando comiencen las ventas se admitirá a las personas por orden de llegada.'}</p><button type="button" className="ep-button" disabled={busy} onClick={() => void run(state.leave)}>Salir de la fila</button></div>}
    {queue?.status === 'admitted' && secondsLeft !== null && <div className="ep-queue-card admitted" role="status"><h2>Es tu turno</h2><p>Tienes <strong>{clock(secondsLeft).text.replace(/^00:/, '')}</strong> para completar tu compra. Al reservar o vencer el tiempo, tu turno termina.</p><button type="button" className="ep-button" disabled={busy} onClick={() => void run(state.leave)}>Renunciar a mi turno</button></div>}
    {sales.queue_enabled && sales.sales_open && !queue && sales.queue_pass_minutes > 0 && event.available_capacity === 0 && <p className="ep-gate-help">No quedan entradas disponibles.</p>}
    {error && <p className="form-error" role="alert">{error}</p>}
  </section>
}

function Hero({ event, canBuy, onBuy, onBack, heroRef }: { event: EventDetail; canBuy: boolean; onBuy: () => void; onBack?: () => void; heroRef: RefObject<HTMLElement | null> }) {
  const soldOut = event.available_capacity === 0
  return <header className="ep-hero" ref={heroRef}>
    {event.image_path ? <img className="ep-hero-image" src={event.image_path} alt={`Fotografía ilustrativa para ${event.name}`} fetchPriority="high" /> : <div className="ep-hero-image fallback" aria-hidden="true" />}
    <div className="ep-hero-shade" aria-hidden="true" />
    <div className="ep-hero-inner">
      {onBack && <button type="button" className="ep-back" onClick={onBack}><Icon name="arrow" size={18} />Volver a eventos</button>}
      <div className="ep-hero-body">
        <span className="ep-chip">{event.category}</span>
        <h1>{event.name}</h1>
        <ul className="ep-meta"><li><Icon name="calendar" size={20} />{formatDate(event.date)}</li><li><Icon name="clock" size={20} />{formatTime(event.time)}</li><li><Icon name="location" size={20} />{event.venue}, {event.city}</li></ul>
        <p className="ep-lead">{event.description}</p>
        <div className="ep-hero-actions"><button type="button" className="ep-button primary large" disabled={!canBuy || soldOut} onClick={onBuy}>{soldOut ? 'Agotado' : 'Comprar entradas'}</button><span className="ep-availability" role="status">{soldOut ? 'Sin entradas disponibles' : `${event.available_capacity} entradas disponibles`}</span></div>
      </div>
    </div>
  </header>
}

function StickyBar({ event, heroRef, onBuy }: { event: EventDetail; heroRef: RefObject<HTMLElement | null>; onBuy: () => void }) {
  const [past, setPast] = useState(false)
  useEffect(() => {
    const element = heroRef.current
    if (!element || typeof IntersectionObserver === 'undefined') return
    const observer = new IntersectionObserver(([entry]) => setPast(!entry.isIntersecting), { rootMargin: '-90px 0px 0px 0px' })
    observer.observe(element)
    return () => observer.disconnect()
  }, [heroRef])
  const soldOut = event.available_capacity === 0
  return <div className={`ep-sticky ${past ? 'show' : ''}`} aria-hidden={!past}><div><strong>{event.name}</strong><span>{formatDate(event.date)} · {formatTime(event.time)}</span></div><button type="button" className="ep-button primary" tabIndex={past ? 0 : -1} disabled={soldOut} onClick={onBuy}>{soldOut ? 'Agotado' : 'Comprar entradas'}</button></div>
}

function Tiers({ event, selection, colors, interactive }: { event: EventDetail; selection: Selection; colors: Map<number, string>; interactive: boolean }) {
  if (!event.zones.length) return null
  return <ul className="ep-tiers" aria-label="Tipos de entrada">{event.zones.map((zone) => {
    const sold = zone.available_capacity === 0
    const few = !sold && zone.available_capacity <= Math.max(5, Math.ceil(zone.capacity * .1))
    const chosen = selection.zoneId === zone.id
    const body = <><i className="ep-swatch" style={{ background: colors.get(zone.id) }} aria-hidden="true" /><span className="ep-tier-copy"><strong>{zone.name}</strong><small>{sold ? 'Agotado' : `${zone.available_capacity} disponibles`}{few ? ' · ¡Últimas entradas!' : ''}</small></span><b>{money(zone.price)}</b></>
    return <li key={zone.id}>{interactive
      ? <button type="button" className={`ep-tier ${chosen ? 'selected' : ''}`} disabled={sold} aria-pressed={chosen} onClick={() => selection.selectZone(zone.id)}>{body}{chosen && <span className="ep-tier-check" aria-hidden="true"><Icon name="check" size={18} /></span>}</button>
      : <div className="ep-tier static">{body}</div>}</li>
  })}</ul>
}

function ZonePlan({ event, selection, colors }: { event: EventDetail; selection: Selection; colors: Map<number, string> }) {
  const zones = [...event.zones].sort((a, b) => b.price - a.price)
  const total = Math.max(1, zones.reduce((sum, zone) => sum + zone.capacity, 0))
  let cursor = 118
  return <svg className="ep-zone-plan" viewBox="0 0 800 560" role="group" aria-label="Plano de zonas frente al escenario">
    <defs><linearGradient id="ep-stage" x1="0" x2="1"><stop offset="0" stopColor="#1d2f3d" /><stop offset="1" stopColor="#0d1822" /></linearGradient></defs>
    <rect x="130" y="24" width="540" height="66" rx="14" fill="url(#ep-stage)" /><text x="400" y="66" textAnchor="middle" className="ep-plan-stage">ESCENARIO</text>
    <rect x="40" y="104" width="720" height="436" rx="22" className="ep-plan-floor" />
    {zones.map((zone) => {
      const height = Math.max(90, (404 - (zones.length - 1) * 12) * zone.capacity / total)
      const y = cursor; cursor += height + 12
      const chosen = selection.zoneId === zone.id
      const sold = zone.available_capacity === 0
      const color = sold ? '#9aa6ac' : colors.get(zone.id) ?? '#3a6ea5'
      return <g key={zone.id} className={`ep-plan-zone ${chosen ? 'selected' : ''} ${sold ? 'sold' : ''}`} role="button" tabIndex={sold ? -1 : 0} aria-disabled={sold} aria-pressed={chosen} aria-label={`${zone.name}, ${money(zone.price)}, ${sold ? 'agotada' : `${zone.available_capacity} disponibles`}`} onClick={() => !sold && selection.selectZone(zone.id)} onKeyDown={(e) => { if (!sold && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); selection.selectZone(zone.id) } }}>
        <rect x="60" y={y} width="680" height={height} rx="16" fill={color} fillOpacity={chosen ? .95 : .62} stroke={chosen ? '#fff' : color} strokeWidth={chosen ? 5 : 2} />
        <text x="400" y={y + height / 2 - 6} textAnchor="middle" className="ep-plan-zone-name">{zone.name}{chosen ? ' ✓' : ''}</text>
        <text x="400" y={y + height / 2 + 26} textAnchor="middle" className="ep-plan-zone-meta">{money(zone.price)} · {sold ? 'Agotada' : `${zone.available_capacity} disponibles`}</text>
      </g>
    })}
  </svg>
}

function SeatGrid({ seats, selection, colors }: { seats: Seat[]; selection: Selection; colors: Map<number, string> }) {
  const rows = [...new Set(seats.map((seat) => seat.row))]
  const columns = Math.max(0, ...seats.map((seat) => seat.number))
  const aisle = Math.floor(columns / 2) + 1
  return <div className="ep-seat-grid" role="group" aria-label="Asientos numerados">{rows.map((row) => <div className="ep-seat-row" key={row}><strong aria-hidden="true">{row}</strong><div>{seats.filter((seat) => seat.row === row).map((seat) => {
    const chosen = selection.selectedSeatIds.includes(seat.id)
    return <button type="button" key={seat.id} className={`ep-seat ${chosen ? 'selected' : ''} ${seat.number === aisle ? 'aisle' : ''}`} style={seat.available && !chosen ? { borderColor: colors.get(seat.zone_id), color: colors.get(seat.zone_id) } : undefined} disabled={!seat.available} aria-pressed={chosen} aria-label={`Zona ${seat.zone_name}, fila ${seat.row}, asiento ${seat.number}, ${seat.available ? chosen ? 'seleccionado' : 'disponible' : 'ocupado'}, ${money(seat.price)}`} onClick={() => selection.toggleSeat(seat)}>{chosen ? '✓' : seat.available ? seat.number : '×'}</button>
  })}</div><strong aria-hidden="true">{row}</strong></div>)}</div>
}

function TheatrePlan({ event, selection, colors }: { event: EventDetail; selection: Selection; colors: Map<number, string> }) {
  return <div className="ep-plan-scroll" tabIndex={0} aria-label="Plano de la sala. Desplázate para ver todas las filas."><div className="ep-theatre-stage">ESCENARIO</div><SeatGrid seats={event.seats} selection={selection} colors={colors} /></div>
}

function StadiumPlan({ event, selection, colors }: { event: EventDetail; selection: Selection; colors: Map<number, string> }) {
  const sectors = event.zones
  const [sectorId, setSectorId] = useState<number | null>(sectors[0]?.id ?? null)
  const geometry: Record<string, string> = {
    'Tribuna Norte': 'M170 34 H550 L520 118 H200 Z', 'Tribuna Sur': 'M170 366 H550 L520 282 H200 Z',
    'Tribuna Occidente': 'M44 90 L178 126 V274 L44 310 Z', 'Tribuna Oriente': 'M676 90 L542 126 V274 L676 310 Z',
  }
  const free = (id: number) => event.seats.filter((seat) => seat.zone_id === id && seat.available).length
  return <div className="ep-stadium-plan">
    <svg viewBox="0 0 720 400" role="group" aria-label="Tribunas alrededor de la cancha"><rect x="214" y="132" width="292" height="136" rx="8" className="ep-pitch" /><line x1="360" y1="132" x2="360" y2="268" className="ep-pitch-line" /><circle cx="360" cy="200" r="28" className="ep-pitch-line" fill="none" />
      {sectors.filter((zone) => geometry[zone.name]).map((zone) => {
        const chosenSector = sectorId === zone.id
        const picked = selection.selectedSeats.some((seat) => seat.zone_id === zone.id)
        const center = zone.name.endsWith('Norte') ? [360, 82] : zone.name.endsWith('Sur') ? [360, 330] : zone.name.endsWith('Occidente') ? [104, 200] : [616, 200]
        return <g key={zone.id} role="button" tabIndex={0} aria-pressed={chosenSector} aria-label={`${zone.name}, ${free(zone.id)} disponibles, ${money(zone.price)}`} className={`ep-sector ${chosenSector ? 'selected' : ''}`} onClick={() => setSectorId(zone.id)} onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setSectorId(zone.id) } }}>
          <path d={geometry[zone.name]} fill={colors.get(zone.id)} fillOpacity={chosenSector ? .95 : .6} stroke={chosenSector ? '#fff' : colors.get(zone.id)} strokeWidth={chosenSector ? 5 : 2} />
          <text x={center[0]} y={center[1] - 4} textAnchor="middle" className="ep-sector-name">{zone.name.replace('Tribuna ', '')}{picked ? ' ✓' : ''}</text><text x={center[0]} y={center[1] + 22} textAnchor="middle" className="ep-sector-meta">{free(zone.id)} libres</text>
        </g>
      })}
    </svg>
    {sectorId !== null && <><h3 className="ep-subtitle">{sectors.find((zone) => zone.id === sectorId)?.name} · elige tus asientos</h3><div className="ep-plan-scroll" tabIndex={0} aria-label="Asientos de la tribuna seleccionada"><SeatGrid seats={event.seats.filter((seat) => seat.zone_id === sectorId)} selection={selection} colors={colors} /></div></>}
  </div>
}

function MuseumPlan() {
  return <ol className="ep-museum-plan" aria-label="Recorrido por las salas">{['Ingreso', 'Sala 1', 'Sala 2', 'Sala 3', 'Salida'].map((name) => <li key={name}>{name}</li>)}</ol>
}

function SeatList({ event, selection, colors }: { event: EventDetail; selection: Selection; colors: Map<number, string> }) {
  const [query, setQuery] = useState('')
  const [open, setOpen] = useState<Record<string, boolean>>({})
  const term = query.trim().toLowerCase().replace(/^fila\s+/, '')
  const match = (seat: Seat) => !term || `${seat.row}${seat.number}`.toLowerCase() === term.replace(/[\s-]/g, '') || `${seat.row} ${seat.number}`.toLowerCase().includes(term) || seat.row.toLowerCase() === term
  return <div className="ep-seat-list-view">
    <div className="ep-seat-search"><label htmlFor="ep-seat-q">Buscar asiento</label><input id="ep-seat-q" type="search" inputMode="text" placeholder="Ej. B5 o fila C" value={query} onChange={(e) => setQuery(e.target.value)} /></div>
    {event.zones.map((zone) => {
      const seats = event.seats.filter((seat) => seat.zone_id === zone.id)
      const free = seats.filter((seat) => seat.available).length
      const picked = seats.filter((seat) => selection.selectedSeatIds.includes(seat.id)).length
      const rows = [...new Set(seats.map((seat) => seat.row))]
      return <section key={zone.id} className="ep-seat-section"><h3><i className="ep-swatch" style={{ background: colors.get(zone.id) }} aria-hidden="true" />{zone.name}<small>{free} libres · {money(zone.price)}{picked ? ` · ${picked} elegidos` : ''}</small></h3>
        {rows.map((row) => {
          const rowSeats = seats.filter((seat) => seat.row === row)
          const shown = rowSeats.filter(match)
          if (!shown.length) return null
          const key = `${zone.id}-${row}`
          const expanded = open[key] ?? (!!term || rowSeats.some((seat) => selection.selectedSeatIds.includes(seat.id)))
          return <div key={row} className="ep-seat-rowgroup"><button type="button" aria-expanded={expanded} aria-controls={`row-${key}`} onClick={() => setOpen({ ...open, [key]: !expanded })}><span>Fila {row}</span><small>{rowSeats.filter((seat) => seat.available).length} libres</small><Icon name={expanded ? 'minus' : 'plus'} size={16} /></button>
            {expanded && <div id={`row-${key}`} className="ep-seat-chips">{shown.map((seat) => { const chosen = selection.selectedSeatIds.includes(seat.id); return <button key={seat.id} type="button" className={`ep-seat ${chosen ? 'selected' : ''}`} disabled={!seat.available} aria-pressed={chosen} aria-label={`Zona ${zone.name}, fila ${seat.row}, asiento ${seat.number}, ${seat.available ? chosen ? 'seleccionado' : 'disponible' : 'ocupado'}`} onClick={() => selection.toggleSeat(seat)}>{chosen ? '✓' : seat.available ? seat.number : '×'}</button> })}</div>}
          </div>
        })}
      </section>
    })}
  </div>
}

function ListView({ event, selection, colors }: { event: EventDetail; selection: Selection; colors: Map<number, string> }) {
  if (event.ticket_mode === 'zones') return <fieldset className="ep-list"><legend>Elige una zona</legend>{event.zones.map((zone) => <label key={zone.id} className={zone.available_capacity === 0 ? 'disabled' : ''}><input type="radio" name="zone" checked={selection.zoneId === zone.id} disabled={zone.available_capacity === 0} onChange={() => selection.selectZone(zone.id)} /><i className="ep-swatch" style={{ background: colors.get(zone.id) }} aria-hidden="true" /><span>{zone.name}</span><small>{zone.available_capacity === 0 ? 'Agotada' : `${zone.available_capacity} disponibles`}</small><b>{money(zone.price)}</b></label>)}</fieldset>
  if (event.ticket_mode === 'seats') return <SeatList event={event} selection={selection} colors={colors} />
  return <p className="ep-note">Este evento no requiere elegir ubicación: indica la cantidad en tu compra.</p>
}

function Stage({ event, selection, colors }: { event: EventDetail; selection: Selection; colors: Map<number, string> }) {
  const has3D = supports3D(event)
  const kind = venueKind(event)
  const hasPlan = kind !== null
  const [mode, setMode] = useState<StageMode>(has3D ? '3d' : hasPlan ? 'plan' : 'list')
  const [unavailable, setUnavailable] = useState(false)
  const effective: StageMode = mode === '3d' && unavailable ? 'plan' : mode
  const modes: Array<{ id: StageMode; label: string }> = [...(has3D && !unavailable ? [{ id: '3d' as const, label: 'Mapa 3D' }] : []), ...(hasPlan ? [{ id: 'plan' as const, label: 'Plano' }] : []), ...(event.ticket_mode !== 'general' ? [{ id: 'list' as const, label: 'Lista' }] : [])]
  const loading = <div className="ep-stage-loading" role="status"><span className="spinner" />Cargando el recinto…</div>
  return <section className="ep-stage" aria-labelledby="ep-stage-title">
    <div className="ep-stage-head"><h2 id="ep-stage-title">{event.layout_kind === 'museum' ? 'Conoce el recinto' : 'Elige tu ubicación'}</h2>{modes.length > 1 && <div className="ep-segmented" role="group" aria-label="Forma de ver el recinto">{modes.map((item) => <button key={item.id} type="button" aria-pressed={effective === item.id} className={effective === item.id ? 'active' : ''} onClick={() => setMode(item.id)}>{item.label}</button>)}</div>}</div>
    {unavailable && <p className="ep-note" role="status">El mapa 3D no está disponible en este dispositivo. Usa el plano o la lista.</p>}
    <Tiers event={event} selection={selection} colors={colors} interactive={event.ticket_mode === 'zones'} />
    <div className="ep-stage-body">
      {effective === '3d' && kind === 'concert' && <Suspense fallback={loading}><Venue3D kind="concert" zones={event.zones} selectedZoneId={selection.zoneId} onSelectZone={selection.selectZone} onUnavailable={() => setUnavailable(true)} /></Suspense>}
      {effective === '3d' && kind === 'theatre' && <Suspense fallback={loading}><Venue3D kind="theatre" seats={event.seats} selectedSeatIds={selection.selectedSeatIds} onToggleSeat={selection.toggleSeat} onUnavailable={() => setUnavailable(true)} /></Suspense>}
      {effective === '3d' && kind === 'stadium' && <Suspense fallback={loading}><Stadium3D seats={event.seats} selectedSeatIds={selection.selectedSeatIds} onToggle={selection.toggleSeat} onSectorChange={() => undefined} onUnavailable={() => setUnavailable(true)} /></Suspense>}
      {effective === '3d' && kind === 'museum' && <Suspense fallback={loading}><Venue3D kind="museum" onUnavailable={() => setUnavailable(true)} /></Suspense>}
      {effective === 'plan' && kind === 'concert' && <ZonePlan event={event} selection={selection} colors={colors} />}
      {effective === 'plan' && kind === 'theatre' && <TheatrePlan event={event} selection={selection} colors={colors} />}
      {effective === 'plan' && kind === 'stadium' && <StadiumPlan event={event} selection={selection} colors={colors} />}
      {effective === 'plan' && kind === 'museum' && <MuseumPlan />}
      {effective === 'list' && <ListView event={event} selection={selection} colors={colors} />}
    </div>
    {event.ticket_mode === 'seats' && <ul className="ep-legend" aria-label="Leyenda"><li><i className="ep-dot free" />Disponible</li><li><i className="ep-dot chosen" />Seleccionado</li><li><i className="ep-dot taken" />Ocupado</li></ul>}
    {event.layout_kind === 'museum' && <p className="ep-note">En el museo se reserva por fecha, horario y cantidad: no hay asientos ni salas que elegir.</p>}
  </section>
}

function PurchasePanel({ event, selection, user, preview, gateBlocked, reserving, message, confirmedTotal, error, onSubmit, onGoTickets }: {
  event: EventDetail; selection: Selection; user: User | null; preview: boolean; gateBlocked: boolean; reserving: boolean
  message: string | null; confirmedTotal: number | null; error: string | null; onSubmit: () => void; onGoTickets: () => void
}) {
  const seatsMode = event.ticket_mode === 'seats'
  const needsZone = event.ticket_mode === 'zones' && !selection.activeZone
  const needsSeats = seatsMode && selection.selectedSeats.length === 0
  const showQuantity = !seatsMode && !needsZone
  const disabled = preview || gateBlocked || reserving || event.available_capacity === 0 || needsZone || needsSeats
  const label = preview ? 'Vista previa: no se puede comprar' : gateBlocked ? 'Compra no disponible todavía' : reserving ? 'Confirmando…' : needsZone ? 'Elige una zona' : needsSeats ? 'Elige tus asientos' : user?.role === 'client' ? 'Confirmar compra' : 'Inicia sesión para comprar'
  if (message) return <div className="ep-panel-body ep-done" role="status"><span className="success-icon large"><Icon name="check" size={28} /></span><h2>¡Compra confirmada!</h2><p>{message}</p><p className="ep-total-line"><span>Total simulado</span><strong>{money(confirmedTotal ?? selection.total)}</strong></p><button type="button" className="ep-button primary large" onClick={onGoTickets}>Ver mis entradas</button></div>
  return <form className="ep-panel-body" onSubmit={(e: FormEvent) => { e.preventDefault(); onSubmit() }}>
    <h2>Tu compra</h2>
    <p className="ep-panel-event"><strong>{event.name}</strong><span>{formatDate(event.date)} · {formatTime(event.time)}</span><span>{event.venue}</span></p>
    {event.ticket_mode === 'zones' && (selection.activeZone ? <p className="ep-line"><span>Zona</span><strong>{selection.activeZone.name}</strong></p> : <p className="ep-hint">Elige una zona en el mapa o en las tarjetas de precio.</p>)}
    {seatsMode && (selection.selectedSeats.length === 0 ? <p className="ep-hint">Toca los asientos que quieras en el mapa (hasta 10).</p> : <ul className="ep-seat-list" aria-label="Asientos elegidos">{selection.selectedSeats.map((seat) => <li key={seat.id}><span>{seat.zone_name} · Fila {seat.row} · Asiento {seat.number}</span><b>{money(seat.price)}</b><button type="button" aria-label={`Quitar asiento ${seat.row}-${seat.number}`} onClick={() => selection.removeSeat(seat.id)}><Icon name="close" size={16} /></button></li>)}</ul>)}
    {event.ticket_mode === 'general' && <p className="ep-line"><span>{event.layout_kind === 'museum' ? 'Ingreso por horario' : 'Entrada general'}</span><strong>{money(event.price)}</strong></p>}
    {showQuantity && <div className="ep-quantity"><div><strong>Cantidad</strong><small>Máximo {selection.quantityLimit} por compra · {selection.activeZone ? selection.activeZone.available_capacity : event.available_capacity} disponibles</small></div><div className="stepper" role="group" aria-label="Cantidad de entradas"><button type="button" onClick={() => selection.changeQuantity(selection.quantity - 1)} disabled={selection.quantity <= 1} aria-label="Restar una entrada"><Icon name="minus" /></button><output aria-live="polite">{selection.quantity}</output><button type="button" onClick={() => selection.changeQuantity(selection.quantity + 1)} disabled={selection.quantity >= selection.quantityLimit} aria-label="Agregar una entrada"><Icon name="plus" /></button></div></div>}
    <p className="ep-total-line"><span>Total simulado</span><strong>{needsZone || needsSeats ? '—' : money(selection.total)}</strong></p>
    <button className="ep-button primary large reserve-button" disabled={disabled} aria-busy={reserving}>{reserving && <span className="spinner" />}{label}</button>
    <p className="ep-fineprint">Compra simulada: no se cobra dinero real. Los precios y la disponibilidad los confirma el servidor al comprar.</p>
    {error && <p className="form-error" role="alert">{error}</p>}
  </form>
}

export function EventPage({ event, selection, user, preview = false, reserving = false, message = null, confirmedTotal = null, error = null, onBack, onSubmit, onRequireLogin, onGoTickets }: {
  event: EventDetail; selection: Selection; user: User | null; preview?: boolean; reserving?: boolean; message?: string | null; confirmedTotal?: number | null; error?: string | null
  onBack?: () => void; onSubmit?: () => Promise<void> | void; onRequireLogin?: () => void; onGoTickets?: () => void
}) {
  const colors = useMemo(() => zoneColorMap(event.zones, venueKind(event) === 'concert'), [event.zones, event.layout_kind, event.ticket_mode])
  const state = useSales(event.id, !preview && event.status === 'published')
  const buyRef = useRef<HTMLDivElement | null>(null)
  const heroRef = useRef<HTMLElement | null>(null)
  const [sheet, setSheet] = useState(false)
  const sales = state.sales
  const queue = sales?.queue ?? null
  const blocked = Boolean(sales && (!sales.sales_open || (sales.queue_enabled && queue?.status !== 'admitted')))
  const goBuy = () => { buyRef.current?.scrollIntoView?.({ behavior: 'smooth', block: 'start' }); setSheet(true) }
  const submit = async () => {
    if (!user || user.role !== 'client') { onRequireLogin?.(); return }
    await onSubmit?.()
    void state.refresh()
  }
  const summary = selection.selectedSeats.length ? `${selection.selectedSeats.length} asiento${selection.selectedSeats.length === 1 ? '' : 's'}` : selection.activeZone ? `${selection.quantity} × ${selection.activeZone.name}` : event.ticket_mode === 'general' ? `${selection.quantity} entrada${selection.quantity === 1 ? '' : 's'}` : 'Sin selección'
  useEffect(() => { if (message) setSheet(true) }, [message])
  return <article className="ep" aria-label={`Evento ${event.name}`}>
    <Hero event={event} canBuy onBuy={goBuy} onBack={onBack} heroRef={heroRef} />
    {!preview && <StickyBar event={event} heroRef={heroRef} onBuy={goBuy} />}
    <div className="ep-container">
    {preview && <p className="ep-preview-banner" role="note">Vista previa del organizador: así lo verán los clientes. Puedes probar la selección, pero no se compra nada.{event.status === 'draft' ? ' Está en borrador y no aparece en el catálogo.' : ''}</p>}
    <div className="ep-layout" id="comprar" ref={buyRef}>
      <div className="ep-main">
        {!preview && <SalesGate event={event} user={user} state={state} onLogin={() => onRequireLogin?.()} />}
        <Stage event={event} selection={selection} colors={colors} />
        <section className="ep-info" aria-labelledby="ep-info-title"><h2 id="ep-info-title">Información del evento</h2><div className="ep-info-grid"><div><h3>Acerca del evento</h3><p>{event.description}</p></div><div><h3>Lugar</h3><p>{event.venue}, {event.city}</p>{event.layout_name && <p className="ep-muted">{event.layout_name}</p>}</div><div><h3>Cómo comprar</h3><ol><li>Elige tu ubicación en el mapa.</li><li>Confirma la cantidad y el total.</li><li>Recibe tus entradas con código QR.</li></ol></div></div></section>
      </div>
      <aside className={`ep-panel ${sheet ? 'open' : ''}`} aria-label="Resumen de compra">
        <button type="button" className="ep-sheet-close" aria-label="Cerrar resumen" onClick={() => setSheet(false)}><Icon name="close" size={20} /></button>
        <PurchasePanel event={event} selection={selection} user={user} preview={preview} gateBlocked={blocked} reserving={reserving} message={message} confirmedTotal={confirmedTotal} error={error} onSubmit={() => void submit()} onGoTickets={() => onGoTickets?.()} />
      </aside>
    </div>
    </div>
    <div className="ep-bar" role="region" aria-label="Resumen rápido de compra"><div><strong>{event.ticket_mode === 'seats' && selection.selectedSeats.length === 0 ? 'Elige tus asientos' : event.ticket_mode === 'zones' && !selection.activeZone ? 'Elige una zona' : money(selection.total)}</strong><small>{summary}</small></div><button type="button" className="ep-button primary" onClick={() => setSheet(true)}>Ver compra</button></div>
    {sheet && <button type="button" className="ep-backdrop" aria-label="Cerrar resumen" onClick={() => setSheet(false)} />}
  </article>
}

export type { Zone }
