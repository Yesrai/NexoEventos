import { FormEvent, ReactNode, useEffect, useMemo, useRef, useState } from 'react'
import QRCode from 'qrcode'

type Role = 'client' | 'organizer' | 'operator'
type User = { id: string; email: string; display_name: string; role: Role; session_expires_at: string }
type EventItem = {
  id: number; name: string; date: string; venue: string; category: string
  price: number; capacity: number; available_capacity: number
}
type EventDetail = EventItem & { description: string }
type Reservation = { id: string; event_id: number; event_name: string; quantity: number; created_at: string }
type Ticket = {
  id: string; reservation_id: string; event_id: number; event_name: string
  qr_token: string; used_at: string | null
}
type View = 'catalog' | 'auth' | 'account' | 'operator' | 'organizer'
type BarcodeResult = { rawValue: string }
type BarcodeDetectorInstance = { detect(source: HTMLVideoElement): Promise<BarcodeResult[]> }
type BarcodeDetectorConstructor = new (options: { formats: string[] }) => BarcodeDetectorInstance
type IconName = 'arrow' | 'calendar' | 'check' | 'close' | 'location' | 'minus' | 'plus' | 'qr' | 'search' | 'ticket' | 'user'

const configuredApiUrl = import.meta.env.VITE_API_URL
const apiUrl = configuredApiUrl !== undefined
  ? configuredApiUrl
  : import.meta.env.PROD
    ? ''
    : `${window.location.protocol}//${window.location.hostname}:8000`

function cookie(name: string) {
  return document.cookie.split('; ').find((item) => item.startsWith(`${name}=`))?.split('=').slice(1).join('=') ?? ''
}

async function api(path: string, init: RequestInit = {}) {
  const headers = new Headers(init.headers)
  if (init.body) headers.set('Content-Type', 'application/json')
  if (init.method && init.method !== 'GET') {
    const csrf = cookie('nexoeventos_csrf')
    if (csrf) headers.set('X-CSRF-Token', csrf)
  }
  return fetch(`${apiUrl}${path}`, { ...init, headers, credentials: 'include' })
}

function formatDate(value: string) {
  return new Intl.DateTimeFormat('es-PE', { day: '2-digit', month: 'short', year: 'numeric' }).format(
    new Date(value.length === 10 ? `${value}T12:00:00` : value),
  )
}

function messageFrom(body: unknown, fallback: string) {
  if (typeof body === 'object' && body && 'detail' in body && typeof body.detail === 'string') return body.detail
  return fallback
}

function Icon({ name, size = 20 }: { name: IconName; size?: number }) {
  const paths: Record<IconName, ReactNode> = {
    arrow: <><path d="M5 12h14" /><path d="m13 6 6 6-6 6" /></>,
    calendar: <><path d="M7 2v3M17 2v3M3 9h18" /><rect x="3" y="4" width="18" height="17" rx="3" /></>,
    check: <path d="m5 12 4 4L19 6" />,
    close: <><path d="m6 6 12 12M18 6 6 18" /></>,
    location: <><path d="M20 10c0 5-8 12-8 12S4 15 4 10a8 8 0 1 1 16 0Z" /><circle cx="12" cy="10" r="2.5" /></>,
    minus: <path d="M5 12h14" />,
    plus: <><path d="M12 5v14M5 12h14" /></>,
    qr: <><rect x="3" y="3" width="7" height="7" rx="1" /><rect x="14" y="3" width="7" height="7" rx="1" /><rect x="3" y="14" width="7" height="7" rx="1" /><path d="M14 14h3v3h-3zM18 18h3v3h-3zM14 20h1M20 14h1" /></>,
    search: <><circle cx="11" cy="11" r="7" /><path d="m20 20-4-4" /></>,
    ticket: <><path d="M3 9a3 3 0 0 0 0 6v4h18v-4a3 3 0 0 0 0-6V5H3v4Z" /><path d="M13 7v2M13 13v4" /></>,
    user: <><circle cx="12" cy="8" r="4" /><path d="M4 21a8 8 0 0 1 16 0" /></>,
  }
  return <svg className="icon" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{paths[name]}</svg>
}

export default function App() {
  const [view, setView] = useState<View>('catalog')
  const [user, setUser] = useState<User | null>(null)
  const [sessionReady, setSessionReady] = useState(false)
  const [sessionNotice, setSessionNotice] = useState<string | null>(null)
  const [events, setEvents] = useState<EventItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [query, setQuery] = useState('')
  const [selected, setSelected] = useState<EventDetail | null>(null)
  const [detailLoading, setDetailLoading] = useState(false)
  const [quantity, setQuantity] = useState(1)
  const [reservationMessage, setReservationMessage] = useState<string | null>(null)
  const [reservationError, setReservationError] = useState<string | null>(null)
  const [reserving, setReserving] = useState(false)
  const idempotencyKey = useRef<string | null>(null)

  async function loadEvents() {
    setLoading(true)
    setError(null)
    try {
      const response = await api('/api/events')
      if (!response.ok) throw new Error()
      setEvents(await response.json() as EventItem[])
    } catch {
      setError('No pudimos cargar los eventos. Verifica que el backend esté activo.')
    } finally {
      setLoading(false)
    }
  }

  async function checkSession() {
    try {
      const response = await api('/api/auth/session')
      if (response.ok) setUser(await response.json() as User)
      else if (response.status === 401) setUser(null)
    } finally {
      setSessionReady(true)
    }
  }

  useEffect(() => { void loadEvents(); void checkSession() }, [])

  async function openDetail(eventId: number) {
    setDetailLoading(true); setReservationMessage(null); setReservationError(null); idempotencyKey.current = null
    try {
      const response = await api(`/api/events/${eventId}`)
      if (!response.ok) throw new Error()
      setSelected(await response.json() as EventDetail)
      setQuantity(1)
      window.setTimeout(() => document.querySelector('.event-detail')?.scrollIntoView?.({ behavior: 'smooth', block: 'start' }), 0)
    } catch {
      setReservationError('No pudimos cargar el detalle del evento.')
    } finally { setDetailLoading(false) }
  }

  function requireLogin() {
    setSessionNotice('Inicia sesión como cliente para reservar.')
    setView('auth')
  }

  async function submitReservation(event: FormEvent) {
    event.preventDefault()
    if (!selected) return
    if (!user || user.role !== 'client') { requireLogin(); return }
    setReserving(true); setReservationError(null); setReservationMessage(null)
    idempotencyKey.current ??= crypto.randomUUID()
    try {
      const response = await api(`/api/events/${selected.id}/reservations`, {
        method: 'POST', headers: { 'Idempotency-Key': idempotencyKey.current }, body: JSON.stringify({ quantity }),
      })
      const body = await response.json() as Record<string, unknown>
      if (response.status === 401) { setUser(null); setSessionNotice('Tu sesión expiró. Vuelve a iniciar sesión.'); setView('auth'); return }
      if (!response.ok) throw new Error(messageFrom(body, 'No se pudo crear la reserva'))
      setReservationMessage(`Reserva confirmada. Se generaron ${String(body.ticket_count)} entrada(s).`)
      setSelected((current) => current && { ...current, available_capacity: Number(body.available_capacity) })
      idempotencyKey.current = null
      await loadEvents()
    } catch (caught) {
      setReservationError(caught instanceof Error ? caught.message : 'No se pudo crear la reserva')
    } finally { setReserving(false) }
  }

  async function logout() {
    await api('/api/auth/logout', { method: 'POST' })
    setUser(null); setView('catalog'); setSessionNotice('Sesión cerrada correctamente.')
  }

  const filtered = useMemo(
    () => events.filter((item) => `${item.name} ${item.venue} ${item.category}`.toLowerCase().includes(query.toLowerCase())),
    [events, query],
  )

  const quantityLimit = selected ? Math.min(10, selected.available_capacity) : 1

  function changeQuantity(next: number) {
    setQuantity(Math.max(1, Math.min(quantityLimit, next)))
    idempotencyKey.current = null
  }

  return (
    <main className="app-shell">
      <header className="site-header">
        <nav className="nav" aria-label="Navegación principal">
          <button className="brand link-button" onClick={() => setView('catalog')} aria-label="Ir al inicio de NexoEventos"><span className="brand-mark">N</span><span>Nexo<strong>Eventos</strong></span></button>
          {view === 'catalog' && <label className="header-search"><span className="sr-only">Buscar eventos</span><Icon name="search" /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Buscar eventos, lugares o categorías" /></label>}
          <div className="nav-actions">
            <button className="nav-link link-button" onClick={() => setView('catalog')}>Eventos</button>
            {user?.role === 'client' && <button className="nav-link link-button" onClick={() => setView('account')}>Mis entradas</button>}
            {user?.role === 'operator' && <button className="nav-link link-button" onClick={() => setView('operator')}>Control de acceso</button>}
            {user?.role === 'organizer' && <button className="nav-link link-button" onClick={() => setView('organizer')}>Mis eventos</button>}
            {user ? <button className="button secondary compact-button" onClick={() => void logout()}>Cerrar sesión</button> : <button className="button secondary compact-button" onClick={() => setView('auth')}><Icon name="user" size={18} /> Ingresar</button>}
          </div>
        </nav>
      </header>

      {sessionNotice && <div className="notice" role="status">{sessionNotice}<button aria-label="Cerrar aviso" onClick={() => setSessionNotice(null)}><Icon name="close" /></button></div>}
      {!sessionReady && <div className="status dark" role="status">Comprobando sesión…</div>}

      {view === 'auth' && <AuthPanel onAuthenticated={(value) => { setUser(value); setSessionNotice(null); setView(value.role === 'client' ? 'account' : value.role === 'operator' ? 'operator' : 'organizer') }} />}
      {view === 'account' && user?.role === 'client' && <ClientAccount onExpired={() => { setUser(null); setSessionNotice('Tu sesión expiró. Vuelve a iniciar sesión.'); setView('auth') }} />}
      {view === 'operator' && user?.role === 'operator' && <OperatorPanel onExpired={() => { setUser(null); setSessionNotice('Tu sesión expiró. Vuelve a iniciar sesión.'); setView('auth') }} />}
      {view === 'organizer' && user?.role === 'organizer' && <OrganizerPanel />}

      {view === 'catalog' && <>
        <header className="hero" id="inicio">
          <div className="hero-copy"><p className="eyebrow">Eventos para recordar</p><h1>Tu próxima experiencia empieza aquí.</h1><p>Descubre eventos, reserva tus entradas y lleva tu QR contigo, todo desde una experiencia simple y segura.</p><a className="button primary" href="#catalogo">Explorar eventos <Icon name="arrow" /></a></div>
          <div className="hero-poster" aria-hidden="true"><span>NexoEventos</span><strong>Momentos que conectan.</strong><small>Reserva · disfruta · comparte</small></div>
        </header>
        <section className="catalog" id="catalogo" aria-labelledby="catalog-title">
          <div className="section-heading">
            <div><p className="eyebrow">Cartelera</p><h2 id="catalog-title">Encuentra tu próximo evento</h2><p>Experiencias disponibles para reservar ahora.</p></div>
            <label className="search"><Icon name="search" /><span className="sr-only">Buscar eventos</span><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Buscar por nombre o lugar" /></label>
          </div>
          {loading && <div className="status" role="status">Cargando experiencias…</div>}
          {error && <div className="status error" role="alert"><p>{error}</p><button onClick={() => void loadEvents()}>Reintentar</button></div>}
          {!loading && !error && filtered.length === 0 && <div className="status">No encontramos eventos con ese criterio.</div>}
          {!loading && !error && filtered.length > 0 && <div className="grid">{filtered.map((item, index) => (
            <article className="card" key={item.id}>
              <button className={`card-art art-${index % 3}`} onClick={() => void openDetail(item.id)} aria-label={`Ver ${item.name}`}><span className="poster-brand">NexoEventos</span><strong>{item.category}</strong><span className="category-pill">{item.category}</span></button>
              <div className="card-body"><p className="date"><Icon name="calendar" size={16} />{formatDate(item.date)}</p><h3>{item.name}</h3><p className="venue"><Icon name="location" size={17} />{item.venue}</p>
                <div className="card-footer"><strong>S/ {item.price.toFixed(2)}</strong><span>{item.available_capacity} disponibles</span></div>
                <button className="button secondary detail-button" onClick={() => void openDetail(item.id)}>Ver detalle <Icon name="arrow" size={18} /></button>
              </div>
            </article>
          ))}</div>}
        </section>
        {(detailLoading || selected || reservationError) && <section className="event-detail" aria-live="polite">
          {detailLoading && <div className="status" role="status"><span className="spinner" />Cargando detalle…</div>}
          {selected && !detailLoading && <div className="detail-layout">
            <article className="event-story"><div className="detail-poster"><span>NexoEventos presenta</span><strong>{selected.name}</strong><small>{selected.category}</small></div><div className="event-copy"><p className="eyebrow">Detalle del evento</p><h2>{selected.name}</h2><div className="event-meta"><span><Icon name="calendar" />{formatDate(selected.date)}</span><span><Icon name="location" />{selected.venue}</span></div><p>{selected.description}</p><span className="availability">{selected.available_capacity} cupos disponibles de {selected.capacity}</span></div></article>
            <form className="booking-panel" onSubmit={(event) => void submitReservation(event)}>
              <div className="booking-heading"><div><p className="eyebrow">Tu reserva</p><h3>Selecciona tus entradas</h3></div><Icon name="ticket" size={26} /></div>
              <div className="ticket-option selected-option"><span className="selection-check"><Icon name="check" size={16} /></span><div><strong>Entrada general</strong><small>Acceso al evento</small></div><b>S/ {selected.price.toFixed(2)}</b></div>
              <div className="quantity-row"><div><strong>Cantidad</strong><small>Máximo {quantityLimit} por reserva</small></div><div className="stepper" aria-label="Cantidad de entradas"><button type="button" onClick={() => changeQuantity(quantity - 1)} disabled={quantity <= 1} aria-label="Restar una entrada"><Icon name="minus" /></button><output aria-live="polite">{quantity}</output><button type="button" onClick={() => changeQuantity(quantity + 1)} disabled={quantity >= quantityLimit} aria-label="Agregar una entrada"><Icon name="plus" /></button></div></div>
              <div className="booking-summary"><span>Total</span><strong>S/ {(selected.price * quantity).toFixed(2)}</strong></div>
              <button className="button primary reserve-button" disabled={reserving || selected.available_capacity === 0} aria-busy={reserving}>{reserving && <span className="spinner" />}{reserving ? 'Confirmando reserva…' : user?.role === 'client' ? 'Confirmar reserva' : 'Inicia sesión para reservar'}</button>
              <small>No se procesa dinero real. La reserva queda vinculada a tu cuenta.</small>
              {reservationMessage && <p className="success confirmation" role="status"><Icon name="check" /> <span>{reservationMessage} <button type="button" className="inline-link" onClick={() => setView('account')}>Ver mis entradas</button></span></p>}
              {reservationError && <p className="form-error" role="alert">{reservationError}</p>}
            </form>
          </div>}
        </section>}
      </>}
      <footer>Proyecto académico · Datos y pagos simulados</footer>
    </main>
  )
}

function AuthPanel({ onAuthenticated }: { onAuthenticated: (user: User) => void }) {
  const [mode, setMode] = useState<'login' | 'register'>('login')
  const [email, setEmail] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  async function submit(event: FormEvent) {
    event.preventDefault(); setBusy(true); setError(null)
    try {
      const response = await api(`/api/auth/${mode}`, { method: 'POST', body: JSON.stringify(mode === 'register' ? { email, display_name: displayName, password } : { email, password }) })
      const body = await response.json() as unknown
      if (!response.ok) throw new Error(messageFrom(body, mode === 'login' ? 'No se pudo iniciar sesión' : 'No se pudo crear la cuenta'))
      onAuthenticated(body as User)
    } catch (caught) { setError(caught instanceof Error ? caught.message : 'No se pudo completar la solicitud') }
    finally { setBusy(false) }
  }
  return <section className="workspace narrow"><p className="eyebrow">Cuenta segura</p><h1 className="page-title">{mode === 'login' ? 'Inicia sesión' : 'Crea tu cuenta'}</h1><p className="muted">La sesión se guarda en una cookie HttpOnly; la interfaz no conserva credenciales en localStorage.</p><form className="panel-form" onSubmit={(event) => void submit(event)}>{mode === 'register' && <label>Nombre<input value={displayName} onChange={(event) => setDisplayName(event.target.value)} minLength={2} required /></label>}<label>Correo<input type="email" value={email} onChange={(event) => setEmail(event.target.value)} required /></label><label>Contraseña<input type="password" value={password} onChange={(event) => setPassword(event.target.value)} minLength={mode === 'register' ? 12 : 1} required /></label><button className="primary" disabled={busy}>{busy ? 'Procesando…' : mode === 'login' ? 'Ingresar' : 'Registrarme como cliente'}</button>{error && <p className="form-error" role="alert">{error}</p>}</form><button className="inline-link auth-switch" onClick={() => { setMode(mode === 'login' ? 'register' : 'login'); setError(null) }}>{mode === 'login' ? 'Crear una cuenta de cliente' : 'Ya tengo una cuenta'}</button></section>
}

function ClientAccount({ onExpired }: { onExpired: () => void }) {
  const [reservations, setReservations] = useState<Reservation[]>([])
  const [tickets, setTickets] = useState<Ticket[]>([])
  const [selected, setSelected] = useState<Ticket | null>(null)
  const [qrImage, setQrImage] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => { void (async () => { try { const [res, tic] = await Promise.all([api('/api/me/reservations'), api('/api/me/tickets')]); if (res.status === 401 || tic.status === 401) { onExpired(); return } if (!res.ok || !tic.ok) throw new Error(); setReservations(await res.json() as Reservation[]); setTickets(await tic.json() as Ticket[]) } catch { setError('No pudimos cargar tus reservas y entradas.') } finally { setLoading(false) } })() }, [])
  useEffect(() => { if (!selected) { setQrImage(''); return } void QRCode.toDataURL(selected.qr_token, { width: 300, margin: 2 }).then(setQrImage) }, [selected])
  return <section className="workspace"><p className="eyebrow">Área personal</p><h1 className="page-title">Mis reservas y entradas</h1>{loading && <div className="status dark">Cargando tus entradas…</div>}{error && <div className="status error">{error}</div>}{!loading && !error && reservations.length === 0 && <div className="status dark">Aún no tienes reservas.</div>}{reservations.length > 0 && <div className="account-grid"><div><h2 className="subheading">Reservas</h2>{reservations.map((item) => <article className="row-card" key={item.id}><strong>{item.event_name}</strong><span>{item.quantity} entrada(s) · {formatDate(item.created_at)}</span></article>)}</div><div><h2 className="subheading">Entradas</h2>{tickets.map((ticket) => <button className="ticket-row" key={ticket.id} onClick={() => setSelected(ticket)}><span><strong>{ticket.event_name}</strong><small>{ticket.used_at ? `Usada: ${formatDate(ticket.used_at)}` : 'Disponible'}</small></span><b>{ticket.used_at ? 'Usada' : 'Ver QR'}</b></button>)}</div></div>}{selected && <div className="modal-backdrop" onClick={() => setSelected(null)}><section className="ticket-modal" role="dialog" aria-modal="true" aria-label="Entrada QR" onClick={(event) => event.stopPropagation()}><button className="modal-close" onClick={() => setSelected(null)}>×</button><p className="eyebrow">Entrada personal</p><h2>{selected.event_name}</h2>{qrImage ? <img className="qr-image" src={qrImage} alt="Código QR de la entrada" /> : <p>Cargando QR…</p>}<p className={selected.used_at ? 'used-badge' : 'valid-badge'}>{selected.used_at ? 'Entrada utilizada' : 'Lista para validar'}</p><small>Mostrar este QR no consume la entrada. Solo un operador asignado puede validarla.</small></section></div>}</section>
}

function OperatorPanel({ onExpired }: { onExpired: () => void }) {
  const [events, setEvents] = useState<EventItem[]>([])
  const [eventId, setEventId] = useState(0)
  const [token, setToken] = useState('')
  const [status, setStatus] = useState<{ kind: 'success' | 'error'; text: string } | null>(null)
  const [busy, setBusy] = useState(false)
  const [cameraError, setCameraError] = useState<string | null>(null)
  const [stream, setStream] = useState<MediaStream | null>(null)
  const videoRef = useRef<HTMLVideoElement>(null)
  useEffect(() => { void (async () => { const response = await api('/api/operator/events'); if (response.status === 401) { onExpired(); return } if (response.ok) { const values = await response.json() as EventItem[]; setEvents(values); setEventId(values[0]?.id ?? 0) } })() }, [])
  useEffect(() => () => stream?.getTracks().forEach((track) => track.stop()), [stream])
  useEffect(() => { if (videoRef.current && stream) videoRef.current.srcObject = stream }, [stream])
  async function startCamera() { setCameraError(null); try { const value = await navigator.mediaDevices.getUserMedia({ video: { facingMode: 'environment' } }); setStream(value) } catch { setCameraError('No se pudo abrir la cámara. Usa la alternativa manual.') } }
  function stopCamera() { stream?.getTracks().forEach((track) => track.stop()); setStream(null) }
  async function readFrame() { const Detector = (window as unknown as { BarcodeDetector?: BarcodeDetectorConstructor }).BarcodeDetector; if (!Detector || !videoRef.current) { setCameraError('Este navegador no ofrece lectura QR directa. Copia el código en el campo manual.'); return } const results = await new Detector({ formats: ['qr_code'] }).detect(videoRef.current); if (results[0]) { setToken(results[0].rawValue); stopCamera() } else setCameraError('No se detectó un QR en la imagen. Intenta de nuevo.') }
  async function validate(event: FormEvent) { event.preventDefault(); setBusy(true); setStatus(null); const response = await api('/api/operator/validate', { method: 'POST', body: JSON.stringify({ event_id: eventId, qr_token: token.trim() }) }); const body = await response.json() as unknown; if (response.status === 401) { onExpired(); return } setStatus(response.ok ? { kind: 'success', text: 'Ingreso aceptado. La entrada quedó consumida.' } : { kind: 'error', text: messageFrom(body, 'No se pudo validar la entrada.') }); setBusy(false) }
  return <section className="workspace"><p className="eyebrow">Operación</p><h1 className="page-title">Control de acceso</h1><p className="muted">Solo aparecen eventos asignados a esta cuenta. Cada validación queda auditada sin guardar el token completo.</p>{events.length === 0 ? <div className="status dark">No tienes eventos asignados.</div> : <div className="operator-grid"><form className="panel-form" onSubmit={(event) => void validate(event)}><label>Evento asignado<select value={eventId} onChange={(event) => setEventId(Number(event.target.value))}>{events.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label><label>Código QR o token manual<textarea value={token} onChange={(event) => setToken(event.target.value)} minLength={20} required placeholder="nexo_…" /></label><button className="primary" disabled={busy}>{busy ? 'Validando…' : 'Validar ingreso'}</button>{status && <p className={status.kind === 'success' ? 'success' : 'form-error'} role="status">{status.text}</p>}</form><div className="camera-panel"><h2 className="subheading">Lector QR</h2>{stream ? <><video ref={videoRef} autoPlay playsInline muted /><div className="button-row"><button className="primary" onClick={() => void readFrame()}>Leer QR</button><button className="outline" onClick={stopCamera}>Cerrar cámara</button></div></> : <button className="outline" onClick={() => void startCamera()}>Permitir cámara</button>}{cameraError && <p className="form-error">{cameraError}</p>}<small>La cámara solo se solicita al pulsar el botón. La entrada se consume únicamente al confirmar “Validar ingreso”.</small></div></div>}</section>
}

function OrganizerPanel() {
  const [events, setEvents] = useState<EventItem[]>([])
  const [loading, setLoading] = useState(true)
  useEffect(() => { void api('/api/organizer/events').then(async (response) => { if (response.ok) setEvents(await response.json() as EventItem[]) }).finally(() => setLoading(false)) }, [])
  return <section className="workspace"><p className="eyebrow">Organización</p><h1 className="page-title">Mis eventos</h1><p className="muted">El backend limita esta lista y las actualizaciones a los eventos propiedad del organizador.</p>{loading && <div className="status dark">Cargando eventos…</div>}{!loading && events.length === 0 && <div className="status dark">No tienes eventos asignados.</div>}<div className="grid compact">{events.map((item) => <article className="row-card" key={item.id}><strong>{item.name}</strong><span>{item.available_capacity} cupos disponibles · {formatDate(item.date)}</span></article>)}</div></section>
}
