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
  event_date: string; event_venue: string
  qr_token: string; used_at: string | null
}
type View = 'catalog' | 'auth' | 'account' | 'operator' | 'organizer'
type BarcodeResult = { rawValue: string }
type BarcodeDetectorInstance = { detect(source: HTMLVideoElement): Promise<BarcodeResult[]> }
type BarcodeDetectorConstructor = new (options: { formats: string[] }) => BarcodeDetectorInstance
type IconName = 'arrow' | 'calendar' | 'check' | 'clock' | 'close' | 'eye' | 'eyeOff' | 'location' | 'minus' | 'plus' | 'qr' | 'search' | 'ticket' | 'user'

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

function requestError(caught: unknown, fallback: string) {
  if (caught instanceof TypeError) return fallback
  return caught instanceof Error ? caught.message : fallback
}

function Icon({ name, size = 20 }: { name: IconName; size?: number }) {
  const paths: Record<IconName, ReactNode> = {
    arrow: <><path d="M5 12h14" /><path d="m13 6 6 6-6 6" /></>,
    calendar: <><path d="M7 2v3M17 2v3M3 9h18" /><rect x="3" y="4" width="18" height="17" rx="3" /></>,
    check: <path d="m5 12 4 4L19 6" />,
    clock: <><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" /></>,
    close: <><path d="m6 6 12 12M18 6 6 18" /></>,
    eye: <><path d="M2 12s3.5-6 10-6 10 6 10 6-3.5 6-10 6S2 12 2 12Z" /><circle cx="12" cy="12" r="2.5" /></>,
    eyeOff: <><path d="m3 3 18 18" /><path d="M10.6 6.2A10.7 10.7 0 0 1 12 6c6.5 0 10 6 10 6a17 17 0 0 1-2.1 2.9M6.6 6.6C3.6 8.4 2 12 2 12s3.5 6 10 6c1.3 0 2.5-.2 3.5-.6" /></>,
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

  async function refreshSelected() {
    if (!selected) return
    try {
      const response = await api(`/api/events/${selected.id}`)
      if (!response.ok) throw new Error()
      const current = await response.json() as EventDetail
      setSelected(current)
      setQuantity((value) => Math.max(1, Math.min(value, Math.min(10, current.available_capacity || 1))))
    } catch {
      setReservationError('No pudimos volver a comprobar la disponibilidad. Intenta de nuevo antes de reservar.')
    }
  }

  function requireLogin() {
    setSessionNotice('Conservamos tu evento y la cantidad mientras accedes a tu cuenta.')
    setView('auth')
  }

  async function authenticated(value: User) {
    setUser(value)
    if (value.role === 'client' && selected) {
      setView('catalog')
      setSessionNotice('Sesión iniciada. Revisa la disponibilidad y confirma tu reserva simulada.')
      await refreshSelected()
      window.setTimeout(() => document.querySelector('.event-detail')?.scrollIntoView?.({ behavior: 'smooth', block: 'start' }), 0)
      return
    }
    setSessionNotice(null)
    setView(value.role === 'client' ? 'account' : value.role === 'operator' ? 'operator' : 'organizer')
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
      if (!response.ok) {
        if (response.status === 409) await refreshSelected()
        throw new Error(messageFrom(body, 'No se pudo crear la reserva. Comprueba la disponibilidad e intenta de nuevo.'))
      }
      setReservationMessage(`Reserva confirmada. Se generaron ${String(body.ticket_count)} entrada(s).`)
      setSelected((current) => current && { ...current, available_capacity: Number(body.available_capacity) })
      idempotencyKey.current = null
      await loadEvents()
    } catch (caught) {
      setReservationError(requestError(caught, 'No pudimos conectar con el servicio. Puedes reintentar sin duplicar la reserva.'))
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

      {view === 'auth' && <AuthPanel pendingReservation={selected ? { event: selected, quantity } : null} onBack={() => setView('catalog')} onAuthenticated={(value) => void authenticated(value)} />}
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
              <dl className="booking-facts"><div><dt>Evento</dt><dd>{selected.name}</dd></div><div><dt>Fecha</dt><dd>{formatDate(selected.date)}</dd></div><div><dt>Lugar</dt><dd>{selected.venue}</dd></div></dl>
              <div className="quantity-row"><div><strong>Cantidad</strong><small>Máximo {quantityLimit} por reserva</small></div><div className="stepper" aria-label="Cantidad de entradas"><button type="button" onClick={() => changeQuantity(quantity - 1)} disabled={quantity <= 1} aria-label="Restar una entrada"><Icon name="minus" /></button><output aria-live="polite">{quantity}</output><button type="button" onClick={() => changeQuantity(quantity + 1)} disabled={quantity >= quantityLimit} aria-label="Agregar una entrada"><Icon name="plus" /></button></div></div>
              <div className="booking-summary"><span>Total</span><strong>S/ {(selected.price * quantity).toFixed(2)}</strong></div>
              <button className="button primary reserve-button" disabled={reserving || selected.available_capacity === 0} aria-busy={reserving}>{reserving && <span className="spinner" />}{reserving ? 'Confirmando reserva…' : user?.role === 'client' ? 'Confirmar reserva' : 'Inicia sesión para reservar'}</button>
              <small>Compra simulada: no se procesa ni se cobra dinero real. La reserva queda vinculada a tu cuenta.</small>
              {reservationMessage && <div className="success reservation-confirmation" role="status"><span className="success-icon"><Icon name="check" /></span><div><strong>Reserva simulada confirmada</strong><p>{reservationMessage} Total simulado: S/ {(selected.price * quantity).toFixed(2)}.</p><button type="button" className="button secondary" onClick={() => setView('account')}>Ir a Mis entradas <Icon name="arrow" size={18} /></button></div></div>}
              {reservationError && <p className="form-error" role="alert">{reservationError}</p>}
            </form>
          </div>}
        </section>}
      </>}
      <footer>Proyecto académico · Datos y pagos simulados</footer>
    </main>
  )
}

function AuthPanel({ pendingReservation, onBack, onAuthenticated }: {
  pendingReservation: { event: EventDetail; quantity: number } | null
  onBack: () => void
  onAuthenticated: (user: User) => void
}) {
  const [mode, setMode] = useState<'login' | 'register'>('login')
  const [email, setEmail] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({})
  const [registeredUser, setRegisteredUser] = useState<User | null>(null)

  function validate() {
    const errors: Record<string, string> = {}
    if (mode === 'register' && displayName.trim().length < 2) errors.displayName = 'Escribe un nombre de al menos 2 caracteres.'
    if (!email.trim()) errors.email = 'El correo es obligatorio.'
    else if (!/^\S+@\S+\.\S+$/.test(email)) errors.email = 'Escribe un correo con formato válido.'
    if (!password) errors.password = 'La contraseña es obligatoria.'
    else if (mode === 'register' && password.length < 12) errors.password = 'Debe tener al menos 12 caracteres.'
    else if (password.length > 128) errors.password = 'No puede superar 128 caracteres.'
    setFieldErrors(errors)
    return Object.keys(errors).length === 0
  }

  async function submit(event: FormEvent) {
    event.preventDefault()
    if (busy || !validate()) return
    setBusy(true); setError(null)
    try {
      const response = await api(`/api/auth/${mode}`, { method: 'POST', body: JSON.stringify(mode === 'register' ? { email, display_name: displayName, password } : { email, password }) })
      const body = await response.json() as unknown
      if (!response.ok) {
        const fallback = mode === 'login'
          ? 'No pudimos iniciar sesión. Revisa tus datos e intenta de nuevo.'
          : 'No pudimos completar el registro. Revisa los datos o intenta iniciar sesión.'
        throw new Error(messageFrom(body, fallback))
      }
      setPassword('')
      if (mode === 'register') setRegisteredUser(body as User)
      else onAuthenticated(body as User)
    } catch (caught) {
      setError(requestError(caught, 'No pudimos conectar con el servicio. Intenta nuevamente.'))
    }
    finally { setBusy(false) }
  }

  if (registeredUser) return <section className="workspace narrow auth-success" aria-live="polite"><span className="success-icon large"><Icon name="check" size={28} /></span><p className="eyebrow">Registro completado</p><h1 className="page-title">Tu cuenta está lista</h1><p>El servidor creó tu cuenta de cliente y abrió una sesión segura.</p>{pendingReservation && <div className="pending-summary"><strong>Tu selección sigue guardada</strong><span>{pendingReservation.event.name}</span><small>{pendingReservation.quantity} entrada(s) · S/ {(pendingReservation.event.price * pendingReservation.quantity).toFixed(2)}</small></div>}<button className="button primary" onClick={() => onAuthenticated(registeredUser)}>{pendingReservation ? 'Continuar con mi reserva' : 'Ir a Mis entradas'} <Icon name="arrow" /></button></section>

  return <section className="workspace narrow auth-workspace">
    <button className="back-button" onClick={onBack}><Icon name="arrow" size={18} /> Volver {pendingReservation ? 'a la reserva' : 'a eventos'}</button>
    <p className="eyebrow">Cuenta segura</p><h1 className="page-title">{mode === 'login' ? 'Inicia sesión' : 'Crea tu cuenta'}</h1>
    <p className="muted">La sesión se protege con cookies HttpOnly y CSRF. No guardamos credenciales en el almacenamiento del navegador.</p>
    {pendingReservation && <div className="pending-summary"><strong>Tu reserva está en espera</strong><span>{pendingReservation.event.name}</span><small>{pendingReservation.quantity} entrada(s) · S/ {(pendingReservation.event.price * pendingReservation.quantity).toFixed(2)}</small></div>}
    <div className="auth-tabs" role="tablist" aria-label="Acceso a la cuenta"><button type="button" role="tab" aria-selected={mode === 'login'} onClick={() => { setMode('login'); setError(null); setFieldErrors({}) }}>Ingresar</button><button type="button" role="tab" aria-selected={mode === 'register'} onClick={() => { setMode('register'); setError(null); setFieldErrors({}) }}>Registrarme</button></div>
    <form className="panel-form auth-form" noValidate onSubmit={(event) => void submit(event)}>
      {mode === 'register' && <div className="field-group"><label htmlFor="display-name">Nombre</label><input id="display-name" value={displayName} onChange={(event) => { setDisplayName(event.target.value); setFieldErrors((value) => ({ ...value, displayName: '' })) }} autoComplete="name" aria-invalid={Boolean(fieldErrors.displayName)} aria-describedby={fieldErrors.displayName ? 'display-name-error' : undefined} />{fieldErrors.displayName && <small className="field-error" id="display-name-error">{fieldErrors.displayName}</small>}</div>}
      <div className="field-group"><label htmlFor="auth-email">Correo</label><input id="auth-email" type="email" inputMode="email" value={email} onChange={(event) => { setEmail(event.target.value); setFieldErrors((value) => ({ ...value, email: '' })) }} autoComplete="email" aria-invalid={Boolean(fieldErrors.email)} aria-describedby={fieldErrors.email ? 'email-error' : undefined} />{fieldErrors.email && <small className="field-error" id="email-error">{fieldErrors.email}</small>}</div>
      <div className="field-group"><label htmlFor="auth-password">Contraseña</label><div className="password-field"><input id="auth-password" type={showPassword ? 'text' : 'password'} value={password} onChange={(event) => { setPassword(event.target.value); setFieldErrors((value) => ({ ...value, password: '' })) }} autoComplete={mode === 'register' ? 'new-password' : 'current-password'} aria-invalid={Boolean(fieldErrors.password)} aria-describedby={[mode === 'register' ? 'password-help' : '', fieldErrors.password ? 'password-error' : ''].filter(Boolean).join(' ') || undefined} /><button type="button" aria-label={showPassword ? 'Ocultar contraseña' : 'Mostrar contraseña'} aria-pressed={showPassword} onClick={() => setShowPassword((value) => !value)}><Icon name={showPassword ? 'eyeOff' : 'eye'} /></button></div>{mode === 'register' && <small className="field-help" id="password-help">Entre 12 y 128 caracteres. Puedes usar una frase larga y única.</small>}{fieldErrors.password && <small className="field-error" id="password-error">{fieldErrors.password}</small>}</div>
      <button className="button primary" disabled={busy} aria-busy={busy}>{busy && <span className="spinner" />}{busy ? 'Enviando…' : mode === 'login' ? 'Iniciar sesión' : 'Crear cuenta de cliente'}</button>
      {error && <p className="form-error" role="alert">{error}</p>}
    </form>
  </section>
}

function ClientAccount({ onExpired }: { onExpired: () => void }) {
  const [reservations, setReservations] = useState<Reservation[]>([])
  const [tickets, setTickets] = useState<Ticket[]>([])
  const [selected, setSelected] = useState<Ticket | null>(null)
  const [qrImage, setQrImage] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  async function loadAccount() {
    setLoading(true); setError(null)
    try {
      const [res, tic] = await Promise.all([api('/api/me/reservations'), api('/api/me/tickets')])
      if (res.status === 401 || tic.status === 401) { onExpired(); return }
      if (!res.ok || !tic.ok) throw new Error()
      setReservations(await res.json() as Reservation[])
      setTickets(await tic.json() as Ticket[])
    } catch { setError('No pudimos cargar tus entradas. Comprueba la conexión y vuelve a intentarlo.') }
    finally { setLoading(false) }
  }
  useEffect(() => { void loadAccount() }, [])
  useEffect(() => {
    if (!selected) { setQrImage(''); return }
    void QRCode.toDataURL(selected.qr_token, { width: 360, margin: 4, errorCorrectionLevel: 'M' }).then(setQrImage).catch(() => setError('No pudimos generar la imagen QR.'))
  }, [selected])
  useEffect(() => {
    if (!selected) return
    const close = (event: KeyboardEvent) => { if (event.key === 'Escape') setSelected(null) }
    window.addEventListener('keydown', close)
    return () => window.removeEventListener('keydown', close)
  }, [selected])

  return <section className="workspace account-workspace"><div className="account-heading"><div><p className="eyebrow">Área personal</p><h1 className="page-title">Mis reservas y entradas</h1><p className="muted">Cada cupo confirmado tiene una entrada digital independiente y privada.</p></div><Icon name="ticket" size={42} /></div>
    {loading && <div className="status account-status" role="status"><span className="spinner" />Cargando tus reservas y entradas…</div>}
    {error && <div className="status error" role="alert"><div><strong>No pudimos mostrar tus entradas</strong><p>{error}</p><button onClick={() => void loadAccount()}>Reintentar</button></div></div>}
    {!loading && !error && reservations.length === 0 && <div className="empty-state"><span className="empty-icon"><Icon name="ticket" size={30} /></span><h2>Aún no tienes entradas</h2><p>Cuando confirmes una reserva simulada, tus entradas aparecerán aquí.</p></div>}
    {!loading && !error && reservations.length > 0 && <div className="account-sections"><section><div className="list-heading"><div><p className="eyebrow">Historial</p><h2 className="subheading">Reservas</h2></div><span>{reservations.length}</span></div><div className="reservation-list">{reservations.map((item) => <article className="reservation-card" key={item.id}><span className="ticket-symbol"><Icon name="ticket" /></span><div><strong>{item.event_name}</strong><small>{item.quantity} entrada(s) · reservada el {formatDate(item.created_at)}</small></div></article>)}</div></section>
      <section><div className="list-heading"><div><p className="eyebrow">Acceso personal</p><h2 className="subheading">Entradas digitales</h2></div><span>{tickets.length}</span></div>{tickets.length === 0 ? <div className="empty-state compact"><p>La reserva existe, pero todavía no encontramos entradas asociadas.</p></div> : <div className="digital-tickets">{tickets.map((ticket, index) => <button className="digital-ticket" key={ticket.id} onClick={() => setSelected(ticket)} aria-label={`Abrir entrada ${index + 1} para ${ticket.event_name}`}><span className="ticket-index">Entrada {index + 1}</span><div className="ticket-title"><Icon name="ticket" /><strong>{ticket.event_name}</strong></div><div className="ticket-details"><span><Icon name="calendar" size={17} />{formatDate(ticket.event_date)}</span><span><Icon name="clock" size={17} />Horario no especificado</span><span><Icon name="location" size={17} />{ticket.event_venue}</span></div><span className={ticket.used_at ? 'ticket-state used' : 'ticket-state available'}><Icon name={ticket.used_at ? 'close' : 'check'} size={16} />{ticket.used_at ? `Usada el ${formatDate(ticket.used_at)}` : 'Disponible para ingresar'}</span><span className="ticket-action"><Icon name="qr" /> Ver entrada QR</span></button>)}</div>}</section>
    </div>}
    {selected && <div className="modal-backdrop" onClick={() => setSelected(null)}><section className="ticket-modal" role="dialog" aria-modal="true" aria-labelledby="ticket-dialog-title" onClick={(event) => event.stopPropagation()}><button className="modal-close" aria-label="Cerrar entrada" onClick={() => setSelected(null)}><Icon name="close" /></button><p className="eyebrow">Entrada digital privada</p><h2 id="ticket-dialog-title">{selected.event_name}</h2><div className="modal-event-meta"><span><Icon name="calendar" />{formatDate(selected.event_date)}</span><span><Icon name="clock" />Horario no especificado</span><span><Icon name="location" />{selected.event_venue}</span></div><div className="qr-frame">{qrImage ? <img className="qr-image" src={qrImage} alt="Código QR de la entrada" /> : <div className="qr-loading" role="status"><span className="spinner" />Preparando QR…</div>}</div><p className={selected.used_at ? 'used-badge' : 'valid-badge'}><Icon name={selected.used_at ? 'close' : 'check'} size={16} />{selected.used_at ? 'Entrada utilizada' : 'Disponible para validar'}</p><p className="ticket-instruction">Presenta este QR completo y con buen brillo al operador en el ingreso. Abrirlo no consume la entrada.</p></section></div>}
  </section>
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
  async function validate(event: FormEvent) {
    event.preventDefault()
    if (busy) return
    setBusy(true); setStatus(null)
    try {
      const response = await api('/api/operator/validate', { method: 'POST', body: JSON.stringify({ event_id: eventId, qr_token: token.trim() }) })
      const body = await response.json() as unknown
      if (response.status === 401) { onExpired(); return }
      setStatus(response.ok ? { kind: 'success', text: 'Ingreso aceptado. La entrada quedó consumida.' } : { kind: 'error', text: messageFrom(body, 'No se pudo validar la entrada.') })
    } catch {
      setStatus({ kind: 'error', text: 'No pudimos conectar con el servicio de validación. Intenta nuevamente.' })
    } finally { setBusy(false) }
  }
  return <section className="workspace"><p className="eyebrow">Operación</p><h1 className="page-title">Control de acceso</h1><p className="muted">Solo aparecen eventos asignados a esta cuenta. Cada validación queda auditada sin guardar el token completo.</p>{events.length === 0 ? <div className="status dark">No tienes eventos asignados.</div> : <div className="operator-grid"><form className="panel-form" onSubmit={(event) => void validate(event)}><label>Evento asignado<select value={eventId} onChange={(event) => setEventId(Number(event.target.value))}>{events.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label><label>Código QR o token manual<textarea value={token} onChange={(event) => setToken(event.target.value)} minLength={20} required placeholder="nexo_…" /></label><button className="primary" disabled={busy}>{busy ? 'Validando…' : 'Validar ingreso'}</button>{status && <p className={status.kind === 'success' ? 'success' : 'form-error'} role="status">{status.text}</p>}</form><div className="camera-panel"><h2 className="subheading">Lector QR</h2>{stream ? <><video ref={videoRef} autoPlay playsInline muted /><div className="button-row"><button className="primary" onClick={() => void readFrame()}>Leer QR</button><button className="outline" onClick={stopCamera}>Cerrar cámara</button></div></> : <button className="outline" onClick={() => void startCamera()}>Permitir cámara</button>}{cameraError && <p className="form-error">{cameraError}</p>}<small>La cámara solo se solicita al pulsar el botón. La entrada se consume únicamente al confirmar “Validar ingreso”.</small></div></div>}</section>
}

function OrganizerPanel() {
  const [events, setEvents] = useState<EventItem[]>([])
  const [loading, setLoading] = useState(true)
  useEffect(() => { void api('/api/organizer/events').then(async (response) => { if (response.ok) setEvents(await response.json() as EventItem[]) }).finally(() => setLoading(false)) }, [])
  return <section className="workspace"><p className="eyebrow">Organización</p><h1 className="page-title">Mis eventos</h1><p className="muted">El backend limita esta lista y las actualizaciones a los eventos propiedad del organizador.</p>{loading && <div className="status dark">Cargando eventos…</div>}{!loading && events.length === 0 && <div className="status dark">No tienes eventos asignados.</div>}<div className="grid compact">{events.map((item) => <article className="row-card" key={item.id}><strong>{item.name}</strong><span>{item.available_capacity} cupos disponibles · {formatDate(item.date)}</span></article>)}</div></section>
}
