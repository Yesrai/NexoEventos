import { FormEvent, KeyboardEvent as ReactKeyboardEvent, lazy, ReactNode, Suspense, useEffect, useId, useMemo, useRef, useState } from 'react'
import QRCode from 'qrcode'
import { EventPage, useSelection } from './EventPage'
import { LuClapperboard } from 'react-icons/lu'
import { categoryOrder, categoryPresentation, type User, type EventItem, type Seat, type EventDetail, type Reservation, type Ticket, type View, type BarcodeDetectorConstructor, api, formatDate, formatTime, formatEventPrice, messageFrom, requestError, Icon } from './shared'

const OrganizerPanel = lazy(() => import('./Organizer'))

function AccountMenu({ user, onLogout }: { user: User; onLogout: () => Promise<void> }) {
  const [open, setOpen] = useState(false)
  const containerRef = useRef<HTMLDivElement>(null)
  const triggerRef = useRef<HTMLButtonElement>(null)
  const logoutRef = useRef<HTMLButtonElement>(null)
  const menuId = useId()
  const accountName = user.display_name?.trim() || user.email?.split('@')[0] || 'Usuario'
  const initial = accountName.charAt(0).toLocaleUpperCase('es-PE')

  useEffect(() => {
    if (!open) return
    const closeOutside = (event: PointerEvent) => {
      if (!containerRef.current?.contains(event.target as Node)) setOpen(false)
    }
    document.addEventListener('pointerdown', closeOutside)
    return () => document.removeEventListener('pointerdown', closeOutside)
  }, [open])

  function openWithKeyboard() {
    setOpen(true)
    window.requestAnimationFrame(() => logoutRef.current?.focus())
  }

  return <div className="account-menu" ref={containerRef}>
    <button
      ref={triggerRef}
      type="button"
      className="account-trigger"
      aria-label={`Abrir menú de ${accountName}`}
      aria-haspopup="menu"
      aria-expanded={open}
      aria-controls={open ? menuId : undefined}
      onClick={() => setOpen((value) => !value)}
      onKeyDown={(event) => {
        if (event.key === 'ArrowDown') { event.preventDefault(); openWithKeyboard() }
      }}
    >
      <span className="account-avatar" aria-hidden="true">{initial}</span>
    </button>
    {open && <div
      id={menuId}
      className="account-popover"
      role="menu"
      aria-label="Cuenta"
      onKeyDown={(event) => {
        if (event.key === 'Escape') { event.preventDefault(); setOpen(false); triggerRef.current?.focus() }
      }}
    >
      <div className="account-identity"><span>Sesión iniciada como</span><strong>{accountName}</strong></div>
      <button ref={logoutRef} type="button" role="menuitem" onClick={() => { setOpen(false); void onLogout() }}><Icon name="close" size={17} />Cerrar sesión</button>
    </div>}
  </div>
}


type SelectOption = { value: string; label: string }

function SelectMenu({ label, value, options, onChange, align = 'start' }: {
  label: string
  value: string
  options: readonly SelectOption[]
  onChange: (value: string) => void
  align?: 'start' | 'end'
}) {
  const id = useId()
  const rootRef = useRef<HTMLDivElement>(null)
  const triggerRef = useRef<HTMLButtonElement>(null)
  const listRef = useRef<HTMLUListElement>(null)
  const selectedIndex = Math.max(0, options.findIndex((option) => option.value === value))
  const [open, setOpen] = useState(false)
  const [activeIndex, setActiveIndex] = useState(selectedIndex)
  const selected = options[selectedIndex]

  useEffect(() => {
    if (!open) return
    setActiveIndex(selectedIndex)
    window.requestAnimationFrame(() => listRef.current?.focus())
    const closeOutside = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false)
    }
    document.addEventListener('pointerdown', closeOutside)
    return () => document.removeEventListener('pointerdown', closeOutside)
  }, [open, selectedIndex])

  function closeAndFocus() {
    setOpen(false)
    triggerRef.current?.focus()
  }

  function choose(index: number) {
    onChange(options[index].value)
    closeAndFocus()
  }

  function handleListKey(event: ReactKeyboardEvent<HTMLUListElement>) {
    if (event.key === 'Escape') {
      event.preventDefault()
      closeAndFocus()
    } else if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault()
      const offset = event.key === 'ArrowDown' ? 1 : -1
      setActiveIndex((current) => (current + offset + options.length) % options.length)
    } else if (event.key === 'Home' || event.key === 'End') {
      event.preventDefault()
      setActiveIndex(event.key === 'Home' ? 0 : options.length - 1)
    } else if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault()
      choose(activeIndex)
    } else if (event.key === 'Tab') {
      setOpen(false)
    } else if (event.key.length === 1) {
      const match = options.findIndex((option) => option.label.toLocaleLowerCase('es').startsWith(event.key.toLocaleLowerCase('es')))
      if (match >= 0) setActiveIndex(match)
    }
  }

  return <div className={`select-menu align-${align}`} ref={rootRef}>
    <span className="select-label" id={`${id}-label`}>{label}</span>
    <button
      ref={triggerRef}
      type="button"
      className="select-trigger"
      aria-haspopup="listbox"
      aria-expanded={open}
      aria-labelledby={`${id}-label ${id}-value`}
      aria-controls={`${id}-listbox`}
      onClick={() => setOpen((current) => !current)}
      onKeyDown={(event) => {
        if (!open && (event.key === 'ArrowDown' || event.key === 'ArrowUp')) {
          event.preventDefault()
          setOpen(true)
        }
      }}
    >
      <span id={`${id}-value`}>{selected.label}</span>
      <span className="select-chevron"><Icon name="arrow" size={16} /></span>
    </button>
    {open && <ul
      ref={listRef}
      id={`${id}-listbox`}
      className="select-popover"
      role="listbox"
      aria-labelledby={`${id}-label`}
      aria-activedescendant={`${id}-option-${activeIndex}`}
      tabIndex={-1}
      onKeyDown={handleListKey}
    >
      {options.map((option, index) => <li
        key={option.value}
        id={`${id}-option-${index}`}
        role="option"
        aria-selected={option.value === value}
        className={`${option.value === value ? 'selected' : ''} ${index === activeIndex ? 'active' : ''}`}
        onPointerMove={() => setActiveIndex(index)}
        onMouseDown={(event) => event.preventDefault()}
        onClick={() => choose(index)}
      >
        <span>{option.label}</span>
        {option.value === value && <Icon name="check" size={17} />}
      </li>)}
    </ul>}
  </div>
}

const weekDays = ['Lu', 'Ma', 'Mi', 'Ju', 'Vi', 'Sá', 'Do']

function limaToday() {
  return new Intl.DateTimeFormat('en-CA', { timeZone: 'America/Lima' }).format(new Date())
}

function dateParts(value: string) {
  const [year, month, day] = value.split('-').map(Number)
  return { year, month: month - 1, day }
}

function isoDate(year: number, month: number, day: number) {
  return new Date(Date.UTC(year, month, day)).toISOString().slice(0, 10)
}

function addDays(value: string, amount: number) {
  const { year, month, day } = dateParts(value)
  return isoDate(year, month, day + amount)
}

function addMonths(value: string, amount: number) {
  const { year, month, day } = dateParts(value)
  const target = new Date(Date.UTC(year, month + amount, 1))
  const lastDay = new Date(Date.UTC(target.getUTCFullYear(), target.getUTCMonth() + 1, 0)).getUTCDate()
  return isoDate(target.getUTCFullYear(), target.getUTCMonth(), Math.min(day, lastDay))
}

function calendarLabel(value: string) {
  const { year, month, day } = dateParts(value)
  return new Intl.DateTimeFormat('es-PE', { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric', timeZone: 'UTC' }).format(new Date(Date.UTC(year, month, day)))
}

function shortDate(value: string) {
  const { year, month, day } = dateParts(value)
  return new Intl.DateTimeFormat('es-PE', { day: '2-digit', month: 'short', year: 'numeric', timeZone: 'UTC' }).format(new Date(Date.UTC(year, month, day)))
}

function monthDays(monthValue: string) {
  const { year, month } = dateParts(monthValue)
  const mondayOffset = (new Date(Date.UTC(year, month, 1)).getUTCDay() + 6) % 7
  return Array.from({ length: 42 }, (_, index) => isoDate(year, month, index - mondayOffset + 1))
}

function DateRangePicker({ from, to, onApply, onClear }: {
  from: string
  to: string
  onApply: (from: string, to: string) => void
  onClear: () => void
}) {
  const id = useId()
  const rootRef = useRef<HTMLDivElement>(null)
  const triggerRef = useRef<HTMLButtonElement>(null)
  const panelRef = useRef<HTMLDivElement>(null)
  const [open, setOpen] = useState(false)
  const [draftFrom, setDraftFrom] = useState(from)
  const [draftTo, setDraftTo] = useState(to)
  const [visibleMonth, setVisibleMonth] = useState((from || limaToday()).slice(0, 7) + '-01')
  const today = limaToday()

  function closeAndFocus() {
    setOpen(false)
    triggerRef.current?.focus()
  }

  function focusDate(value: string) {
    window.requestAnimationFrame(() => {
      panelRef.current?.querySelector<HTMLButtonElement>(`button[data-date="${value}"]`)?.focus()
    })
  }

  useEffect(() => {
    if (!open) return
    setDraftFrom(from)
    setDraftTo(to)
    setVisibleMonth((from || today).slice(0, 7) + '-01')
    const focusValue = from || today
    focusDate(focusValue)
    const closeOutside = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false)
    }
    document.addEventListener('pointerdown', closeOutside)
    return () => document.removeEventListener('pointerdown', closeOutside)
  }, [open, from, to, today])

  function selectDate(value: string) {
    if (!draftFrom || draftTo || value < draftFrom) {
      setDraftFrom(value)
      setDraftTo('')
    } else {
      setDraftTo(value)
    }
  }

  function moveFocus(value: string, key: string) {
    const { year, month } = dateParts(value)
    const weekday = (new Date(Date.UTC(year, month, dateParts(value).day)).getUTCDay() + 6) % 7
    const target = key === 'ArrowLeft' ? addDays(value, -1)
      : key === 'ArrowRight' ? addDays(value, 1)
        : key === 'ArrowUp' ? addDays(value, -7)
          : key === 'ArrowDown' ? addDays(value, 7)
            : key === 'Home' ? addDays(value, -weekday)
              : key === 'End' ? addDays(value, 6 - weekday)
                : key === 'PageUp' ? addMonths(value, -1)
                  : addMonths(value, 1)
    const firstVisible = visibleMonth.slice(0, 7)
    const secondVisible = addMonths(visibleMonth, 1).slice(0, 7)
    if (target.slice(0, 7) < firstVisible || target.slice(0, 7) > secondVisible) setVisibleMonth(target.slice(0, 7) + '-01')
    focusDate(target)
  }

  function Month({ value, secondary = false }: { value: string; secondary?: boolean }) {
    const { year, month } = dateParts(value)
    const rawTitle = new Intl.DateTimeFormat('es-PE', { month: 'long', year: 'numeric', timeZone: 'UTC' }).format(new Date(Date.UTC(year, month, 1)))
    const title = rawTitle.charAt(0).toUpperCase() + rawTitle.slice(1)
    return <section className={`calendar-month ${secondary ? 'secondary-month' : ''}`} aria-label={title}>
      <h3>{title}</h3>
      <div className="calendar-weekdays" aria-hidden="true">{weekDays.map((day) => <span key={day}>{day}</span>)}</div>
      <div className="calendar-grid">
        {monthDays(value).map((date, index) => {
          const parts = dateParts(date)
          const outside = parts.month !== month
          const start = date === draftFrom
          const end = date === draftTo
          const inside = Boolean(draftFrom && draftTo && date > draftFrom && date < draftTo)
          return <button
            type="button"
            key={`${date}-${index}`}
            data-date={date}
            className={`${outside ? 'outside-month' : ''} ${inside ? 'in-range' : ''} ${start ? 'range-start' : ''} ${end ? 'range-end' : ''}`}
            aria-label={calendarLabel(date)}
            aria-current={date === today ? 'date' : undefined}
            aria-pressed={start || end}
            onClick={() => selectDate(date)}
            onKeyDown={(event) => {
              if (event.key === 'Escape') { event.preventDefault(); closeAndFocus(); return }
              if (['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown', 'Home', 'End', 'PageUp', 'PageDown'].includes(event.key)) {
                event.preventDefault(); moveFocus(date, event.key)
              }
            }}
          >{parts.day}</button>
        })}
      </div>
    </section>
  }

  const appliedLabel = from && to ? `${shortDate(from)} – ${shortDate(to)}` : 'Seleccionar rango'
  const draftLabel = draftFrom ? draftTo ? `${shortDate(draftFrom)} – ${shortDate(draftTo)}` : `${shortDate(draftFrom)} – selecciona el final` : 'Selecciona la fecha de inicio'

  return <div className="date-picker" ref={rootRef}>
    <span className="date-picker-label" id={`${id}-label`}>Rango de fechas</span>
    <button ref={triggerRef} type="button" className="date-picker-trigger" aria-haspopup="dialog" aria-expanded={open} aria-controls={`${id}-panel`} aria-labelledby={`${id}-label ${id}-value`} onClick={() => setOpen((value) => !value)}>
      <span id={`${id}-value`}><Icon name="calendar" size={18} />{appliedLabel}</span><span className="select-chevron"><Icon name="arrow" size={16} /></span>
    </button>
    {open && <div ref={panelRef} className="calendar-popover" id={`${id}-panel`} role="dialog" aria-modal="false" aria-label="Seleccionar rango de fechas" onKeyDown={(event) => { if (event.key === 'Escape') { event.preventDefault(); closeAndFocus() } }}>
      <div className="calendar-toolbar">
        <button type="button" aria-label="Mes anterior" onClick={() => setVisibleMonth(addMonths(visibleMonth, -1).slice(0, 7) + '-01')}><Icon name="arrow" size={17} /></button>
        <div><strong>Elige inicio y fin</strong><span aria-live="polite">{draftLabel}</span></div>
        <button type="button" aria-label="Mes siguiente" onClick={() => setVisibleMonth(addMonths(visibleMonth, 1).slice(0, 7) + '-01')}><Icon name="arrow" size={17} /></button>
      </div>
      <div className="calendar-months"><Month value={visibleMonth} /><Month value={addMonths(visibleMonth, 1).slice(0, 7) + '-01'} secondary /></div>
      <div className="calendar-actions">
        <button type="button" className="button secondary" onClick={() => { setDraftFrom(''); setDraftTo(''); onClear(); closeAndFocus() }}>Limpiar</button>
        <button type="button" className="button primary" disabled={!draftFrom || !draftTo} onClick={() => { onApply(draftFrom, draftTo); closeAndFocus() }}>Aplicar</button>
      </div>
    </div>}
  </div>
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
  const [category, setCategory] = useState('')
  const [city, setCity] = useState('')
  const [dateFilter, setDateFilter] = useState<'all' | 'today' | 'weekend' | 'range'>('all')
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')
  const [priceFilter, setPriceFilter] = useState<'all' | 'free' | 'paid'>('all')
  const [sort, setSort] = useState<'date' | 'price-asc' | 'price-desc'>('date')
  const [filtersOpen, setFiltersOpen] = useState(false)
  const [featuredIndex, setFeaturedIndex] = useState(0)
  const [selected, setSelected] = useState<EventDetail | null>(null)
  const [detailLoading, setDetailLoading] = useState(false)
  const [confirmedTotal, setConfirmedTotal] = useState<number | null>(null)
  const [reservationMessage, setReservationMessage] = useState<string | null>(null)
  const [reservationError, setReservationError] = useState<string | null>(null)
  const [reserving, setReserving] = useState(false)
  const [confirmation, setConfirmation] = useState<OrderSummary | null>(null)
  const idempotencyKey = useRef<string | null>(null)
  const selection = useSelection(selected, () => { idempotencyKey.current = null; setReservationError(null); setReservationMessage(null) })
  const { quantity, zoneId, selectedSeatIds, total: currentTotal } = selection
  const categoryListRef = useRef<HTMLDivElement>(null)

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
    setDetailLoading(true); setConfirmation(null); setReservationMessage(null); setReservationError(null); idempotencyKey.current = null
    try {
      const response = await api(`/api/events/${eventId}`)
      if (!response.ok) throw new Error()
      setSelected(await response.json() as EventDetail)
      selection.reset()
      setConfirmedTotal(null)
      window.scrollTo?.({ top: 0 })
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
      selection.setSelectedSeatIds((ids) => {
        const availableIds = ids.filter((id) => current.seats.some((seat) => seat.id === id && seat.available))
        if (current.ticket_mode === 'seats') selection.setQuantity(Math.max(1, availableIds.length))
        return availableIds
      })
      selection.setQuantity((value) => Math.max(1, Math.min(value, Math.min(10, current.available_capacity || 1))))
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
      return
    }
    setSessionNotice(null)
    setView(value.role === 'client' ? 'account' : value.role === 'operator' ? 'operator' : 'organizer')
  }

  async function submitReservation() {
    if (!selected) return
    if (!user || user.role !== 'client') { requireLogin(); return }
    setReserving(true); setReservationError(null); setReservationMessage(null)
    idempotencyKey.current ??= crypto.randomUUID()
    try {
      const seatIds = selected.ticket_mode === 'seats' ? selectedSeatIds : []
      const response = await api(`/api/events/${selected.id}/reservations`, {
        method: 'POST', headers: { 'Idempotency-Key': idempotencyKey.current }, body: JSON.stringify({ quantity, zone_id: selected.ticket_mode === 'zones' ? zoneId : null, seat_ids: seatIds }),
      })
      const body = await response.json() as Record<string, unknown>
      if (response.status === 401) { setUser(null); setSessionNotice('Tu sesión expiró. Vuelve a iniciar sesión.'); setView('auth'); return }
      if (!response.ok) {
        if (response.status === 409) await refreshSelected()
        throw new Error(messageFrom(body, 'No se pudo crear la reserva. Comprueba la disponibilidad e intenta de nuevo.'))
      }
      setConfirmedTotal(Number(body.total))
      setConfirmation({
        reservationId: String(body.reservation_id ?? ''), ticketCount: Number(body.ticket_count), total: Number(body.total),
        event: { name: selected.name, date: selected.date, time: selected.time, venue: selected.venue, city: selected.city, image_path: selected.image_path },
        lines: selected.ticket_mode === 'seats' ? selection.selectedSeats.map((seat) => ({ label: `${seat.zone_name} · Fila ${seat.row} · Asiento ${seat.number}`, amount: seat.price }))
          : selected.ticket_mode === 'zones' && selection.activeZone ? [{ label: `${quantity} × ${selection.activeZone.name}`, amount: selection.activeZone.price * quantity }]
          : [{ label: `${quantity} × Entrada general`, amount: selected.price * quantity }],
      })
      window.scrollTo?.({ top: 0 })
      setSelected((current) => current && { ...current, available_capacity: Number(body.available_capacity) })
      idempotencyKey.current = null
      await loadEvents()
      await refreshSelected()
    } catch (caught) {
      setReservationError(requestError(caught, 'No pudimos conectar con el servicio. Puedes reintentar sin duplicar la reserva.'))
    } finally { setReserving(false) }
  }

  async function logout() {
    await api('/api/auth/logout', { method: 'POST' })
    setUser(null); setView('catalog'); setSessionNotice('Sesión cerrada correctamente.')
  }

  const today = new Intl.DateTimeFormat('en-CA', { timeZone: 'America/Lima' }).format(new Date())
  const upcoming = useMemo(() => events.filter((item) => item.date >= today), [events, today])
  const filtered = useMemo(() => {
    const current = new Date(`${today}T12:00:00`)
    const day = current.getDay()
    const saturday = new Date(current); saturday.setDate(current.getDate() + ((6 - day + 7) % 7))
    const sunday = new Date(saturday); sunday.setDate(saturday.getDate() + 1)
    const iso = (value: Date) => value.toISOString().slice(0, 10)
    const values = upcoming.filter((item) => {
      const textMatch = `${item.name} ${item.venue} ${item.city} ${item.category}`.toLowerCase().includes(query.trim().toLowerCase())
      const dateMatch = dateFilter === 'all' || (dateFilter === 'today' && item.date === today) || (dateFilter === 'weekend' && item.date >= iso(saturday) && item.date <= iso(sunday)) || (dateFilter === 'range' && (!dateFrom || item.date >= dateFrom) && (!dateTo || item.date <= dateTo))
      return textMatch && (!category || item.category === category) && (!city || item.city === city) && dateMatch && (priceFilter === 'all' || (priceFilter === 'free' ? item.price === 0 : item.price > 0))
    })
    return [...values].sort((a, b) => sort === 'date' ? a.date.localeCompare(b.date) : sort === 'price-asc' ? a.price - b.price : b.price - a.price)
  }, [upcoming, today, query, category, city, dateFilter, dateFrom, dateTo, priceFilter, sort])
  const groups = useMemo(() => groupFunctions(filtered), [filtered])
  const [visibleCount, setVisibleCount] = useState(PAGE_SIZE)
  useEffect(() => { setVisibleCount(PAGE_SIZE) }, [query, category, city, dateFilter, dateFrom, dateTo, priceFilter, sort])

  const categories = useMemo(() => [...new Set(upcoming.map((item) => item.category))].sort((left, right) => {
    const leftIndex = categoryOrder.indexOf(left)
    const rightIndex = categoryOrder.indexOf(right)
    if (leftIndex < 0 || rightIndex < 0) return leftIndex < 0 ? rightIndex < 0 ? left.localeCompare(right, 'es') : 1 : -1
    return leftIndex - rightIndex
  }), [upcoming])
  const cities = useMemo(() => [...new Set(upcoming.map((item) => item.city))].sort(), [upcoming])
  const activeFilterCount = [category, city, dateFilter !== 'all', priceFilter !== 'all'].filter(Boolean).length
  const curatedFeatured = [1002, 1004, 1010, 1013, 1016, 1003].flatMap((id) => {
    const item = upcoming.find((event) => event.id === id)
    return item ? [item] : []
  })
  const featuredEvents = curatedFeatured.length ? curatedFeatured : upcoming.slice(0, 6)
  const featured = featuredEvents[featuredIndex % Math.max(featuredEvents.length, 1)]
  const sideFeatured = featuredEvents.length > 1
    ? [...featuredEvents.slice(featuredIndex + 1), ...featuredEvents.slice(0, featuredIndex)].slice(0, 3)
    : []
  const functionsOf = (current: EventDetail) => upcoming.filter((item) => functionKey(item) === functionKey(current)).sort((a, b) => `${a.date} ${a.time ?? ''}`.localeCompare(`${b.date} ${b.time ?? ''}`)).map(({ id, date, time, available_capacity }) => ({ id, date, time, available_capacity }))
  function goHome() {
    setQuery(''); setSelected(null); setConfirmation(null); setReservationError(null); setReservationMessage(null); setView('catalog'); window.scrollTo?.({ top: 0 })
  }
  function clearFilters() {
    setQuery(''); setCategory(''); setCity(''); setDateFilter('all'); setDateFrom(''); setDateTo(''); setPriceFilter('all'); setSort('date')
  }

  function moveFeatured(direction: number) {
    if (!featuredEvents.length) return
    setFeaturedIndex((value) => (value + direction + featuredEvents.length) % featuredEvents.length)
  }

  function moveCategories(direction: number) {
    categoryListRef.current?.scrollBy({ left: direction * 620, behavior: 'smooth' })
  }

  return (
    <main className="app-shell">
      <header className={`site-header view-${view}${selected || detailLoading ? ' has-event' : ''}`}>
        <nav className="nav" aria-label="Navegación principal">
          <button className="brand link-button" onClick={goHome} aria-label="Ir al inicio de NexoEventos"><span className="brand-mark">N</span><span>Nexo<strong>Eventos</strong></span></button>
          <button className="nav-link link-button events-link" onClick={goHome}>Eventos</button>
          <form className="header-search" role="search" onSubmit={(event) => { event.preventDefault(); if (view !== 'catalog') { setSelected(null); setView('catalog') } window.setTimeout(() => document.getElementById('catalogo')?.scrollIntoView({ behavior: 'smooth' }), 50) }}><label className="sr-only" htmlFor="main-search">Buscar eventos</label><input id="main-search" value={query} onChange={(event) => { setQuery(event.target.value); if (selected) setSelected(null); if (view !== 'catalog') setView('catalog') }} placeholder="Buscar eventos, artistas o lugares" /><button type="submit" aria-label="Buscar"><Icon name="search" /></button></form>
          <div className="nav-actions">
            {user?.role === 'client' && <button className="nav-link link-button" aria-label="Mis entradas" onClick={() => setView('account')}><Icon name="ticket" size={17} /><span>Mis entradas</span></button>}
            {user?.role === 'operator' && <button className="nav-link link-button" aria-label="Control de acceso" onClick={() => setView('operator')}><Icon name="qr" size={17} /><span>Control de acceso</span></button>}
            {user?.role === 'organizer' && <button className="nav-link link-button" aria-label="Mis eventos" onClick={() => setView('organizer')}><Icon name="calendar" size={17} /><span>Mis eventos</span></button>}
            {user ? <AccountMenu user={user} onLogout={logout} /> : <button className="button secondary compact-button" aria-label="Ingresar" onClick={() => setView('auth')}><Icon name="user" size={18} /><span>Ingresar</span></button>}
          </div>
        </nav>
      </header>

      {sessionNotice && <div className="notice" role="status">{sessionNotice}<button aria-label="Cerrar aviso" onClick={() => setSessionNotice(null)}><Icon name="close" /></button></div>}
      {!sessionReady && <div className="status dark" role="status">Comprobando sesión…</div>}

      {view === 'auth' && <AuthPanel pendingReservation={selected ? { event: selected, quantity, total: currentTotal } : null} onBack={() => setView('catalog')} onAuthenticated={(value) => void authenticated(value)} />}
      {view === 'account' && user?.role === 'client' && <ClientAccount onExpired={() => { setUser(null); setSessionNotice('Tu sesión expiró. Vuelve a iniciar sesión.'); setView('auth') }} />}
      {view === 'operator' && user?.role === 'operator' && <OperatorPanel onExpired={() => { setUser(null); setSessionNotice('Tu sesión expiró. Vuelve a iniciar sesión.'); setView('auth') }} />}
      {view === 'organizer' && user?.role === 'organizer' && <Suspense fallback={<div className="status dark" role="status">Cargando panel…</div>}><OrganizerPanel /></Suspense>}

      {view === 'catalog' && confirmation && <OrderConfirmation order={confirmation} onTickets={() => { setConfirmation(null); setSelected(null); setQuery(''); setView('account'); window.scrollTo?.({ top: 0 }) }} onExplore={goHome} />}
      {view === 'catalog' && !confirmation && (detailLoading || selected || reservationError) && <div className="ep-wrap" aria-live="polite">
        {detailLoading && <div className="status" role="status"><span className="spinner" />Cargando evento…</div>}
        {!detailLoading && !selected && reservationError && <div className="status error" role="alert"><p>{reservationError}</p><button type="button" onClick={() => { setReservationError(null) }}>Volver a eventos</button></div>}
        {selected && !detailLoading && <EventPage event={selected} selection={selection} user={user} reserving={reserving} functions={functionsOf(selected)} onSelectFunction={(id) => void openDetail(id)} message={reservationMessage} confirmedTotal={confirmedTotal} error={reservationError}
          onBack={() => { setSelected(null); setReservationError(null); setReservationMessage(null); window.scrollTo?.({ top: 0 }) }}
          onSubmit={submitReservation} onRequireLogin={requireLogin} onGoTickets={() => setView('account')} />}
      </div>}
      {view === 'catalog' && !confirmation && !(detailLoading || selected || reservationError) && <>
        <section className="home-intro" id="inicio" aria-labelledby="featured-title">
          <h1 id="featured-title" className="sr-only">Destacados</h1>
          {loading && <div className="status" role="status">Cargando destacados…</div>}
          {!loading && featured && <div className="nx-hero">
            <article className="nx-hero-stage" key={featured.id}>
              {featured.image_path ? <img className="nx-hero-photo" src={featured.image_path} alt="" fetchPriority="high" /> : <div className="nx-hero-photo fallback" aria-hidden="true" />}
              <div className="nx-hero-scrim" aria-hidden="true" />
              <div className="nx-hero-copy">
                <span className="nx-chip">{featured.category}</span>
                <p className="nx-hero-title">{featured.name}</p>
                <p className="nx-hero-meta"><span>{formatDate(featured.date)} · {formatTime(featured.time)}</span><span>{featured.venue}, {featured.city}</span></p>
                <div className="nx-hero-actions"><button className="nx-cta" onClick={() => void openDetail(featured.id)} aria-label={`Abrir evento destacado ${featured.name}`}>Ver entradas <Icon name="arrow" size={20} /></button><span className="nx-hero-price">{formatEventPrice(featured)}</span></div>
              </div>
              <div className="nx-hero-controls">
                <button className="carousel-arrow previous" aria-label="Evento destacado anterior" onClick={() => moveFeatured(-1)}><Icon name="arrow" /></button>
                <div className="carousel-dots" aria-label="Seleccionar evento destacado">{featuredEvents.map((item, index) => <button key={item.id} className={index === featuredIndex ? 'active' : ''} aria-label={`Mostrar ${item.name}`} aria-current={index === featuredIndex ? 'true' : undefined} onClick={() => setFeaturedIndex(index)} />)}</div>
                <button className="carousel-arrow next" aria-label="Siguiente evento destacado" onClick={() => moveFeatured(1)}><Icon name="arrow" /></button>
              </div>
            </article>
            <aside className="nx-rail" aria-label="Más eventos destacados">{sideFeatured.map((item) => <button key={item.id} onClick={() => void openDetail(item.id)} aria-label={`Abrir ${item.name}`}>{item.image_path ? <img src={item.image_path} alt="" loading="lazy" /> : <span className="image-fallback">{item.category}</span>}<span className="nx-rail-copy"><small>{formatDate(item.date)} · {item.category}</small><strong>{item.name}</strong><em>{formatEventPrice(item)}</em></span></button>)}</aside>
          </div>}
          <section className="category-section" aria-labelledby="categories-title">
            <div className="home-section-title compact"><h2 id="categories-title">Explora por categoría</h2></div>
            <div className="category-carousel">
              <button type="button" className="category-arrow previous" aria-label="Ver categorías anteriores" onClick={() => moveCategories(-1)}><Icon name="arrow" size={19} /></button>
              <div className="category-links" aria-label="Categorías" ref={categoryListRef}>{categories.map((value) => {
                const presentation = categoryPresentation[value] ?? { label: value, Icon: LuClapperboard }
                return <button key={value} aria-pressed={category === value} className={category === value ? 'selected' : ''} onClick={() => setCategory(category === value ? '' : value)}><span className="category-icon"><presentation.Icon aria-hidden="true" /></span><span className="category-name">{presentation.label}</span></button>
              })}</div>
              <button type="button" className="category-arrow next" aria-label="Ver más categorías" onClick={() => moveCategories(1)}><Icon name="arrow" size={19} /></button>
            </div>
          </section>
        </section>
        <section className="catalog" id="catalogo" aria-labelledby="catalog-title">
          <div className="section-heading">
            <div><h2 id="catalog-title">Próximos eventos</h2></div>
            <div className="results-sort"><span>{groups.length} resultado{groups.length === 1 ? '' : 's'}</span><SelectMenu label="Ordenar" value={sort} align="end" onChange={(value) => setSort(value as typeof sort)} options={[{ value: 'date', label: 'Fecha próxima' }, { value: 'price-asc', label: 'Precio menor' }, { value: 'price-desc', label: 'Precio mayor' }]} /></div>
          </div>
          <div className="compact-filters" aria-label="Filtros del catálogo">
            <SelectMenu label="Ciudad" value={city} onChange={setCity} options={[{ value: '', label: 'Todas' }, ...cities.map((value) => ({ value, label: value }))]} />
            <SelectMenu label="Fecha" value={dateFilter} onChange={(value) => { setDateFilter(value as typeof dateFilter); if (value === 'range') setFiltersOpen(true) }} options={[{ value: 'all', label: 'Cualquier fecha' }, { value: 'today', label: 'Hoy' }, { value: 'weekend', label: 'Este fin de semana' }, { value: 'range', label: 'Rango personalizado' }]} />
            <SelectMenu label="Precio" value={priceFilter} align="end" onChange={(value) => setPriceFilter(value as typeof priceFilter)} options={[{ value: 'all', label: 'Todos' }, { value: 'free', label: 'Gratuitos' }, { value: 'paid', label: 'De pago' }]} />
            <button className="more-filters" onClick={() => setFiltersOpen((value) => !value)} aria-expanded={filtersOpen} aria-controls="more-filters-panel"><Icon name="sliders" />Más filtros{activeFilterCount > 0 && <b>{activeFilterCount}</b>}</button>
          </div>
          {filtersOpen && <div className="more-filters-panel" id="more-filters-panel"><DateRangePicker from={dateFrom} to={dateTo} onApply={(from, to) => { setDateFrom(from); setDateTo(to); setDateFilter('range') }} onClear={() => { setDateFrom(''); setDateTo(''); if (dateFilter === 'range') setDateFilter('all') }} /></div>}
          {(query || category || city || dateFilter !== 'all' || priceFilter !== 'all') && <div className="active-filters" aria-label="Filtros activos">{query && <button onClick={() => setQuery('')}>Búsqueda: {query}<Icon name="close" size={15} /></button>}{category && <button onClick={() => setCategory('')}>{categoryPresentation[category]?.label ?? category}<Icon name="close" size={15} /></button>}{city && <button onClick={() => setCity('')}>Ciudad: {city}<Icon name="close" size={15} /></button>}{dateFilter !== 'all' && <button onClick={() => { setDateFilter('all'); setDateFrom(''); setDateTo('') }}>Fecha: {dateFilter === 'today' ? 'Hoy' : dateFilter === 'weekend' ? 'Este fin de semana' : dateFrom && dateTo ? `${shortDate(dateFrom)} – ${shortDate(dateTo)}` : 'Rango'}<Icon name="close" size={15} /></button>}{priceFilter !== 'all' && <button onClick={() => setPriceFilter('all')}>{priceFilter === 'free' ? 'Gratuitos' : 'De pago'}<Icon name="close" size={15} /></button>}{groups.length > 0 && <button className="clear-active" onClick={clearFilters}>Limpiar todos</button>}</div>}
          {loading && <div className="status" role="status">Cargando experiencias…</div>}
          {loading && <div className="nx-skeletons" aria-hidden="true">{[0, 1, 2, 3, 4, 5, 6, 7].map((n) => <div key={n} className="nx-skeleton"><i /><b /><b /></div>)}</div>}
          {error && <div className="status error" role="alert"><p>{error}</p><button onClick={() => void loadEvents()}>Reintentar</button></div>}
          {!loading && !error && groups.length === 0 && <div className="empty-state"><span className="empty-icon"><Icon name="search" /></span><h3>No encontramos eventos con esos filtros</h3><p>Prueba con otra ciudad, otra fecha o quita algún filtro.</p><button className="button secondary" onClick={clearFilters}>Limpiar filtros</button></div>}
          {!loading && !error && groups.length > 0 && <>
            <div className="grid">{groups.slice(0, visibleCount).map(({ item, count }) => (
              <article className="card nx-card" key={item.id}>
                <div className="card-art">{item.image_path ? <img src={item.image_path} alt="" loading="lazy" /> : <span className="image-fallback" aria-hidden="true">{(() => { const Glyph = (categoryPresentation[item.category] ?? { Icon: LuClapperboard }).Icon; return <Glyph size={40} /> })()}</span>}<span className="category-pill">{item.category}</span></div>
                <div className="card-body">
                  <p className="nx-when">{shortWhen(item.date, item.time)}{count > 1 && <b> · {count} funciones</b>}</p>
                  <h3><button type="button" className="card-link" aria-label={`Ver ${item.name}`} onClick={() => void openDetail(item.id)}>{item.name}</button></h3>
                  <p className="venue"><Icon name="location" size={18} /><span>{item.venue}, {item.city}</span></p>
                  <div className="card-footer"><strong>{formatEventPrice(item)}</strong>{item.available_capacity === 0 ? <em className="nx-few sold">Agotado</em> : item.available_capacity <= Math.max(10, Math.ceil(item.capacity * .1)) ? <em className="nx-few">Últimas entradas</em> : null}</div>
                </div>
              </article>
            ))}</div>
            {groups.length > visibleCount && <div className="more-results"><p role="status">Mostrando {Math.min(visibleCount, groups.length)} de {groups.length} eventos</p><button type="button" className="button secondary" onClick={() => setVisibleCount((value) => value + PAGE_SIZE)}>Mostrar más eventos</button></div>}
          </>}
        </section>
      </>}
      {!(detailLoading || selected || confirmation) && <nav className="nx-tabbar" aria-label="Navegación móvil">
        <button type="button" onClick={() => { setSelected(null); setView('catalog'); window.scrollTo?.({ top: 0 }) }} aria-current={view === 'catalog' ? 'page' : undefined}><Icon name="ticket" size={22} /><span>Inicio</span></button>
        <button type="button" onClick={() => { setSelected(null); setView('catalog'); window.setTimeout(() => document.getElementById('main-search')?.focus(), 60) }}><Icon name="search" size={22} /><span>Buscar</span></button>
        <button type="button" onClick={() => setView(!user ? 'auth' : user.role === 'client' ? 'account' : user.role === 'operator' ? 'operator' : 'organizer')} aria-current={view === 'account' || view === 'operator' || view === 'organizer' ? 'page' : undefined}><Icon name={user?.role === 'organizer' ? 'calendar' : user?.role === 'operator' ? 'qr' : 'ticket'} size={22} /><span>{user?.role === 'organizer' ? 'Eventos' : user?.role === 'operator' ? 'Acceso' : 'Entradas'}</span></button>
        <button type="button" onClick={() => { if (user) document.querySelector<HTMLButtonElement>('.account-trigger')?.click(); else setView('auth') }}><Icon name="user" size={22} /><span>Cuenta</span></button>
      </nav>}
      <footer><span>© 2026 NexoEventos</span></footer>
    </main>
  )
}

type OrderSummary = { reservationId: string; ticketCount: number; total: number; event: { name: string; date: string; time: string | null; venue: string; city: string; image_path: string | null }; lines: Array<{ label: string; amount: number }> }
const money = (value: number) => value === 0 ? 'Gratis' : `S/ ${value.toFixed(2)}`

function OrderConfirmation({ order, onTickets, onExplore }: { order: OrderSummary; onTickets: () => void; onExplore: () => void }) {
  return <section className="confirm" aria-labelledby="confirm-title">
    <div className="confirm-hero"><span className="confirm-check"><Icon name="check" size={30} /></span><h1 id="confirm-title">¡Compra confirmada!</h1><p>Tus entradas ya están en tu cuenta. Presenta el código QR de cada una para ingresar.</p></div>
    <div className="confirm-card">
      <div className="confirm-event">{order.event.image_path ? <img src={order.event.image_path} alt="" /> : <span className="confirm-noimg"><Icon name="ticket" size={26} /></span>}<div><strong>{order.event.name}</strong><span><Icon name="calendar" size={16} />{formatDate(order.event.date)} · {formatTime(order.event.time)}</span><span><Icon name="location" size={16} />{order.event.venue}, {order.event.city}</span></div></div>
      <ul className="confirm-lines" aria-label="Detalle de tu compra">{order.lines.map((line, index) => <li key={index}><span>{line.label}</span><b>{money(line.amount)}</b></li>)}</ul>
      <p className="confirm-total"><span>Total</span><strong>{money(order.total)}</strong></p>
      <dl className="confirm-ref">{order.reservationId && <div><dt>Número de reserva</dt><dd>{order.reservationId.slice(0, 8).toUpperCase()}</dd></div>}<div><dt>{order.ticketCount === 1 ? 'Entrada' : 'Entradas'}</dt><dd>{order.ticketCount}</dd></div></dl>
      <p className="confirm-note">Pago simulado: no se realizó ningún cobro.</p>
    </div>
    <div className="confirm-actions"><button type="button" className="button primary" onClick={onTickets}>Ver mis entradas</button><button type="button" className="button secondary" onClick={onExplore}>Seguir explorando eventos</button></div>
  </section>
}

const PAGE_SIZE = 12
/** Agrupa como funciones solo eventos del mismo nombre y recinto; no altera identificadores ni inventarios. */
const functionKey = (item: EventItem) => `${item.venue_id}|${item.name.trim().toLowerCase()}`
function groupFunctions(list: EventItem[]) {
  const groups = new Map<string, { item: EventItem; count: number }>()
  for (const item of list) {
    const key = functionKey(item)
    const found = groups.get(key)
    if (found) found.count += 1; else groups.set(key, { item, count: 1 })
  }
  return [...groups.values()]
}
const shortWhen = (date: string, time: string | null) => `${new Intl.DateTimeFormat('es-PE', { weekday: 'short', day: 'numeric', month: 'short' }).format(new Date(`${date}T12:00:00`)).replace(/\./g, '')} · ${formatTime(time)}`

function authErrorMessage(mode: 'login' | 'register', status: number, body: unknown) {
  const server = messageFrom(body, '')
  if (status === 409 && mode === 'register') return 'No se pudo crear la cuenta con este correo. Si ya te registraste antes, inicia sesión; si no recuerdas la contraseña, regístrate con otro correo (esta demo aún no tiene recuperación de contraseña).'
  if (status === 401 && mode === 'login') return 'Correo o contraseña incorrectos. Si nunca te registraste con este correo, crea una cuenta.'
  if (status === 429) return `${server || 'Demasiados intentos.'} Espera unos minutos antes de volver a intentarlo.`
  if (status === 403) return 'El servidor rechazó la solicitud por seguridad (origen o sesión no válidos). Abre la aplicación desde http://127.0.0.1:5173 o http://localhost:5173 y vuelve a intentarlo.'
  if (status === 422) return 'Algún dato no es válido: revisa el correo, el nombre y que la contraseña tenga entre 12 y 128 caracteres.'
  if (status >= 500) return `El servidor tuvo un problema (código ${status}). Inténtalo de nuevo; si continúa, revisa que el backend y la base de datos estén en marcha.`
  return server || (mode === 'login' ? `No pudimos iniciar sesión (código ${status}).` : `No pudimos completar el registro (código ${status}).`)
}

function AuthPanel({ pendingReservation, onBack, onAuthenticated }: {
  pendingReservation: { event: EventDetail; quantity: number; total: number } | null
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
  const [conflict, setConflict] = useState(false)

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
      const body = await response.json().catch(() => null) as unknown
      if (!response.ok) { setError(authErrorMessage(mode, response.status, body)); setConflict(mode === 'register' && response.status === 409); return }
      setConflict(false)
      setPassword('')
      if (mode === 'register') setRegisteredUser(body as User)
      else onAuthenticated(body as User)
    } catch (caught) {
      setError(caught instanceof TypeError ? 'No se pudo conectar con el servidor. Comprueba que el backend esté en marcha y que tengas conexión.' : requestError(caught, 'No pudimos completar la solicitud. Intenta nuevamente.'))
    }
    finally { setBusy(false) }
  }

  if (registeredUser) return <section className="workspace narrow auth-success" aria-live="polite"><span className="success-icon large"><Icon name="check" size={28} /></span><p className="eyebrow">Registro completado</p><h1 className="page-title">Tu cuenta está lista</h1><p>El servidor creó tu cuenta de cliente y abrió una sesión segura.</p>{pendingReservation && <div className="pending-summary"><strong>Tu selección sigue guardada</strong><span>{pendingReservation.event.name}</span><small>{pendingReservation.quantity} entrada(s) · {pendingReservation.total === 0 ? 'Gratis' : `S/ ${pendingReservation.total.toFixed(2)}`}</small></div>}<button className="button primary" onClick={() => onAuthenticated(registeredUser)}>{pendingReservation ? 'Continuar con mi reserva' : 'Ir a Mis entradas'} <Icon name="arrow" /></button></section>

  return <section className="workspace narrow auth-workspace">
    <button className="back-button" onClick={onBack}><Icon name="arrow" size={18} /> Volver {pendingReservation ? 'a la reserva' : 'a eventos'}</button>
    <h1 className="page-title">{mode === 'login' ? 'Inicia sesión' : 'Crea tu cuenta'}</h1>
    <p className="muted">{mode === 'login' ? 'Accede para comprar y ver tus entradas en un solo lugar.' : 'Guarda tus entradas y compra más rápido la próxima vez.'}</p>
    {pendingReservation && <div className="pending-summary"><strong>Tu reserva está en espera</strong><span>{pendingReservation.event.name}</span><small>{pendingReservation.quantity} entrada(s) · {pendingReservation.total === 0 ? 'Gratis' : `S/ ${pendingReservation.total.toFixed(2)}`}</small></div>}
    <div className="auth-tabs" role="tablist" aria-label="Acceso a la cuenta"><button type="button" role="tab" aria-selected={mode === 'login'} onClick={() => { setMode('login'); setError(null); setFieldErrors({}) }}>Ingresar</button><button type="button" role="tab" aria-selected={mode === 'register'} onClick={() => { setMode('register'); setError(null); setFieldErrors({}) }}>Registrarme</button></div>
    <form className="panel-form auth-form" noValidate onSubmit={(event) => void submit(event)}>
      {mode === 'register' && <div className="field-group"><label htmlFor="display-name">Nombre</label><input id="display-name" value={displayName} onChange={(event) => { setDisplayName(event.target.value); setFieldErrors((value) => ({ ...value, displayName: '' })) }} autoComplete="name" aria-invalid={Boolean(fieldErrors.displayName)} aria-describedby={fieldErrors.displayName ? 'display-name-error' : undefined} />{fieldErrors.displayName && <small className="field-error" id="display-name-error">{fieldErrors.displayName}</small>}</div>}
      <div className="field-group"><label htmlFor="auth-email">Correo</label><input id="auth-email" type="email" inputMode="email" value={email} onChange={(event) => { setEmail(event.target.value); setFieldErrors((value) => ({ ...value, email: '' })) }} autoComplete="email" aria-invalid={Boolean(fieldErrors.email)} aria-describedby={fieldErrors.email ? 'email-error' : undefined} />{fieldErrors.email && <small className="field-error" id="email-error">{fieldErrors.email}</small>}</div>
      <div className="field-group"><label htmlFor="auth-password">Contraseña</label><div className="password-field"><input id="auth-password" type={showPassword ? 'text' : 'password'} value={password} onChange={(event) => { setPassword(event.target.value); setFieldErrors((value) => ({ ...value, password: '' })) }} autoComplete={mode === 'register' ? 'new-password' : 'current-password'} aria-invalid={Boolean(fieldErrors.password)} aria-describedby={[mode === 'register' ? 'password-help' : '', fieldErrors.password ? 'password-error' : ''].filter(Boolean).join(' ') || undefined} /><button type="button" aria-label={showPassword ? 'Ocultar contraseña' : 'Mostrar contraseña'} aria-pressed={showPassword} onClick={() => setShowPassword((value) => !value)}><Icon name={showPassword ? 'eyeOff' : 'eye'} /></button></div>{mode === 'register' && <small className="field-help" id="password-help">Entre 12 y 128 caracteres. Puedes usar una frase larga y única.</small>}{fieldErrors.password && <small className="field-error" id="password-error">{fieldErrors.password}</small>}</div>
      <button className="button primary" disabled={busy} aria-busy={busy}>{busy && <span className="spinner" />}{busy ? 'Enviando…' : mode === 'login' ? 'Iniciar sesión' : 'Crear cuenta de cliente'}</button>
      {error && <p className="form-error" role="alert">{error}</p>}
      {conflict && <button type="button" className="button outline" onClick={() => { setMode('login'); setError(null); setConflict(false); setPassword('') }}>Ya tengo cuenta: iniciar sesión con este correo</button>}
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
  const ticketTriggerRef = useRef<HTMLButtonElement | null>(null)
  const modalCloseRef = useRef<HTMLButtonElement | null>(null)
  function closeTicket() {
    setSelected(null)
    window.requestAnimationFrame(() => ticketTriggerRef.current?.focus())
  }
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
    modalCloseRef.current?.focus()
    const close = (event: KeyboardEvent) => { if (event.key === 'Escape') closeTicket() }
    window.addEventListener('keydown', close)
    return () => window.removeEventListener('keydown', close)
  }, [selected])

  const reservationGroups = reservations.map((reservation) => ({
    reservation,
    tickets: tickets.filter((ticket) => ticket.reservation_id === reservation.id),
  }))

  function ticketLabel(ticket: Ticket) {
    if (ticket.ticket_type === 'seats') return `${ticket.zone ?? 'Zona'} · fila ${ticket.row ?? '—'}, asiento ${ticket.seat ?? '—'}`
    if (ticket.ticket_type === 'zones') return ticket.zone ?? 'Zona general'
    return 'Entrada general'
  }

  const today = new Intl.DateTimeFormat('en-CA', { timeZone: 'America/Lima' }).format(new Date())
  const [tab, setTab] = useState<'upcoming' | 'past'>('upcoming')
  const indexed = reservationGroups.flatMap(({ reservation, tickets: group }) => group.map((ticket, index) => ({ ticket, index, total: group.length, reservation })))
  const isPast = (ticket: Ticket) => ticket.event_date < today
  const upcomingTickets = indexed.filter(({ ticket }) => !isPast(ticket)).sort((x, y) => `${x.ticket.event_date}${x.ticket.event_time ?? ''}`.localeCompare(`${y.ticket.event_date}${y.ticket.event_time ?? ''}`))
  const pastTickets = indexed.filter(({ ticket }) => isPast(ticket)).sort((x, y) => `${y.ticket.event_date}${y.ticket.event_time ?? ''}`.localeCompare(`${x.ticket.event_date}${x.ticket.event_time ?? ''}`))
  const shown = tab === 'upcoming' ? upcomingTickets : pastTickets

  return <section className="workspace account-workspace wallet">
    <div className="wallet-head"><h1 className="page-title">Mis entradas</h1>
      {!loading && !error && reservations.length > 0 && <div className="wallet-tabs" role="tablist" aria-label="Filtrar entradas"><button type="button" role="tab" aria-selected={tab === 'upcoming'} onClick={() => setTab('upcoming')}>Próximas <span>{upcomingTickets.length}</span></button><button type="button" role="tab" aria-selected={tab === 'past'} onClick={() => setTab('past')}>Pasadas <span>{pastTickets.length}</span></button></div>}</div>
    {loading && <div className="status account-status" role="status"><span className="spinner" />Cargando tus entradas…</div>}
    {error && <div className="status error" role="alert"><div><strong>No pudimos mostrar tus entradas</strong><p>{error}</p><button onClick={() => void loadAccount()}>Reintentar</button></div></div>}
    {!loading && !error && reservations.length === 0 && <div className="empty-state"><span className="empty-icon"><Icon name="ticket" size={26} /></span><h2>Aún no tienes entradas</h2><p>Cuando compres entradas, aparecerán aquí con su código QR para ingresar.</p></div>}
    {!loading && !error && reservations.length > 0 && shown.length === 0 && <div className="empty-state"><span className="empty-icon"><Icon name="calendar" size={26} /></span><h2>{tab === 'upcoming' ? 'No tienes entradas próximas' : 'Aún no tienes entradas pasadas'}</h2><p>{tab === 'upcoming' ? 'Explora el catálogo y encuentra tu próximo evento.' : 'Aquí verás las entradas de eventos que ya ocurrieron.'}</p></div>}
    {!loading && !error && shown.length > 0 && <ul className="wallet-list">{shown.map(({ ticket, index, total }) => <li key={ticket.id}>
      <button className={`wallet-ticket ${ticket.used_at || isPast(ticket) ? 'muted' : ''}`} onClick={(event) => { ticketTriggerRef.current = event.currentTarget; setSelected(ticket) }} aria-label={`Abrir entrada ${index + 1} para ${ticket.event_name}`}>
        <span className="wt-photo">{ticket.image_path ? <img src={ticket.image_path} alt="" /> : <Icon name="ticket" size={28} />}</span>
        <span className="wt-body">
          <span className="wt-when">{formatDate(ticket.event_date)} · {formatTime(ticket.event_time)}</span>
          <strong className="wt-title">{ticket.event_name}</strong>
          <span className="wt-meta"><Icon name="location" size={16} />{ticket.event_venue}, {ticket.event_city}</span>
          <span className="wt-kind">{ticketLabel(ticket)}{total > 1 ? ` · ${index + 1} de ${total}` : ''}</span>
        </span>
        <span className="wt-stub">
          <span className={ticket.used_at ? 'wt-state used' : isPast(ticket) ? 'wt-state used' : 'wt-state ok'}>{ticket.used_at ? `Usada el ${formatDate(ticket.used_at)}` : isPast(ticket) ? 'Evento realizado' : 'Lista para ingresar'}</span>
          <span className="wt-qr"><Icon name="qr" size={20} />Ver entrada QR</span>
        </span>
      </button></li>)}</ul>}
    {selected && <div className="modal-backdrop" onClick={closeTicket}><section className="ticket-modal" role="dialog" aria-modal="true" aria-labelledby="ticket-dialog-title" aria-describedby="ticket-dialog-instruction" onClick={(event) => event.stopPropagation()}><button ref={modalCloseRef} className="modal-close" aria-label="Cerrar entrada" onClick={closeTicket}><Icon name="close" /></button><p className="eyebrow">Entrada digital privada</p><h2 id="ticket-dialog-title">{selected.event_name}</h2><strong className="modal-ticket-kind">{ticketLabel(selected)}</strong><div className="modal-event-meta"><span><Icon name="calendar" />{formatDate(selected.event_date)} · {formatTime(selected.event_time)}</span><span><Icon name="location" />{selected.event_venue}, {selected.event_city}</span></div><div className="qr-frame">{qrImage ? <img className="qr-image" src={qrImage} alt="Código QR de la entrada" /> : <div className="qr-loading" role="status"><span className="spinner" />Preparando QR…</div>}</div><p className={selected.used_at ? 'used-badge' : 'valid-badge'}><Icon name={selected.used_at ? 'close' : 'check'} size={16} />{selected.used_at ? 'Entrada utilizada' : 'Disponible para validar'}</p><p className="ticket-instruction" id="ticket-dialog-instruction">Presenta este QR completo y con buen brillo al operador en el ingreso. Abrirlo no consume la entrada. No compartas capturas.</p></section></div>}
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
      const accepted = body as { ticket_location?: string }
      setStatus(response.ok ? { kind: 'success', text: `Ingreso aceptado. ${accepted.ticket_location ?? 'Entrada general'}. La entrada quedó consumida.` } : { kind: 'error', text: messageFrom(body, 'No se pudo validar la entrada.') })
    } catch {
      setStatus({ kind: 'error', text: 'No pudimos conectar con el servicio de validación. Intenta nuevamente.' })
    } finally { setBusy(false) }
  }
  return <section className="workspace"><p className="eyebrow">Operación</p><h1 className="page-title">Control de acceso</h1><p className="muted">Solo aparecen eventos asignados a esta cuenta. Cada validación queda auditada sin guardar el token completo.</p>{events.length === 0 ? <div className="status dark">No tienes eventos asignados.</div> : <div className="operator-grid"><form className="panel-form" onSubmit={(event) => void validate(event)}><label>Evento asignado<select value={eventId} onChange={(event) => setEventId(Number(event.target.value))}>{events.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label><label>Código QR o token manual<textarea value={token} onChange={(event) => setToken(event.target.value)} minLength={20} required placeholder="nexo_…" /></label><button className="primary" disabled={busy}>{busy ? 'Validando…' : 'Validar ingreso'}</button>{status && <p className={status.kind === 'success' ? 'success' : 'form-error'} role="status">{status.text}</p>}</form><div className="camera-panel"><h2 className="subheading">Lector QR</h2>{stream ? <><video ref={videoRef} autoPlay playsInline muted /><div className="button-row"><button className="primary" onClick={() => void readFrame()}>Leer QR</button><button className="outline" onClick={stopCamera}>Cerrar cámara</button></div></> : <button className="outline" onClick={() => void startCamera()}>Permitir cámara</button>}{cameraError && <p className="form-error">{cameraError}</p>}<small>La cámara solo se solicita al pulsar el botón. La entrada se consume únicamente al confirmar “Validar ingreso”.</small></div></div>}</section>
}
