import { FormEvent, KeyboardEvent as ReactKeyboardEvent, ReactNode, useEffect, useId, useMemo, useRef, useState } from 'react'
import QRCode from 'qrcode'
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

type Role = 'client' | 'organizer' | 'operator'
type User = { id: string; email: string; display_name: string; role: Role; session_expires_at: string }
type EventItem = {
  id: number; name: string; date: string; time: string | null; venue: string; city: string; category: string
  price: number; has_multiple_prices: boolean; capacity: number; available_capacity: number
  image_path: string | null; ticket_mode: 'general' | 'zones' | 'seats'; is_demo: boolean
}
type Zone = { id: number; name: string; price: number; capacity: number; available_capacity: number }
type Seat = { id: number; zone_id: number; zone_name: string; row: string; number: number; price: number; available: boolean }
type EventDetail = EventItem & { description: string; zones: Zone[]; seats: Seat[] }
type Reservation = { id: string; event_id: number; event_name: string; quantity: number; created_at: string }
type Ticket = {
  id: string; reservation_id: string; event_id: number; event_name: string
  event_date: string; event_time: string | null; event_venue: string; event_city: string; image_path: string | null
  ticket_type: 'general' | 'zones' | 'seats'; zone: string | null; row: string | null; seat: number | null; unit_price: number
  qr_token: string; used_at: string | null
}
type View = 'catalog' | 'auth' | 'account' | 'operator' | 'organizer'
type BarcodeResult = { rawValue: string }
type BarcodeDetectorInstance = { detect(source: HTMLVideoElement): Promise<BarcodeResult[]> }
type BarcodeDetectorConstructor = new (options: { formats: string[] }) => BarcodeDetectorInstance
type IconName = 'arrow' | 'art' | 'calendar' | 'check' | 'cinema' | 'clock' | 'close' | 'conference' | 'dance' | 'exhibition' | 'eye' | 'eyeOff' | 'fair' | 'festival' | 'food' | 'kids' | 'location' | 'minus' | 'music' | 'networking' | 'plus' | 'qr' | 'search' | 'sliders' | 'sport' | 'technology' | 'theater' | 'ticket' | 'user' | 'workshop'

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

function formatTime(value: string | null) {
  if (!value) return 'Horario no especificado'
  const [hours, minutes] = value.split(':').map(Number)
  return new Intl.DateTimeFormat('es-PE', { hour: 'numeric', minute: '2-digit', timeZone: 'America/Lima' }).format(new Date(Date.UTC(2026, 0, 1, hours + 5, minutes)))
}

function formatEventPrice(event: Pick<EventItem, 'price' | 'has_multiple_prices'>) {
  if (event.price === 0) return 'Gratis'
  return `${event.has_multiple_prices ? 'Desde ' : ''}S/ ${event.price.toFixed(2)}`
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

const categoryPresentation: Record<string, { label: string; Icon: IconType }> = {
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

const categoryOrder = Object.keys(categoryPresentation)

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
  const [quantity, setQuantity] = useState(1)
  const [zoneId, setZoneId] = useState<number | null>(null)
  const [selectedSeatIds, setSelectedSeatIds] = useState<number[]>([])
  const [confirmedTotal, setConfirmedTotal] = useState<number | null>(null)
  const [reservationMessage, setReservationMessage] = useState<string | null>(null)
  const [reservationError, setReservationError] = useState<string | null>(null)
  const [reserving, setReserving] = useState(false)
  const idempotencyKey = useRef<string | null>(null)
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
    setDetailLoading(true); setReservationMessage(null); setReservationError(null); idempotencyKey.current = null
    try {
      const response = await api(`/api/events/${eventId}`)
      if (!response.ok) throw new Error()
      setSelected(await response.json() as EventDetail)
      setQuantity(1)
      setZoneId(null)
      setSelectedSeatIds([])
      setConfirmedTotal(null)
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
      setSelectedSeatIds((ids) => {
        const availableIds = ids.filter((id) => current.seats.some((seat) => seat.id === id && seat.available))
        if (current.ticket_mode === 'seats') setQuantity(Math.max(1, availableIds.length))
        return availableIds
      })
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
      setReservationMessage(`Reserva confirmada. Se generaron ${String(body.ticket_count)} entrada(s).`)
      setConfirmedTotal(Number(body.total))
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

  const filtered = useMemo(() => {
    const today = new Intl.DateTimeFormat('en-CA', { timeZone: 'America/Lima' }).format(new Date())
    const current = new Date(`${today}T12:00:00`)
    const day = current.getDay()
    const saturday = new Date(current); saturday.setDate(current.getDate() + ((6 - day + 7) % 7))
    const sunday = new Date(saturday); sunday.setDate(saturday.getDate() + 1)
    const iso = (value: Date) => value.toISOString().slice(0, 10)
    const values = events.filter((item) => {
      const textMatch = `${item.name} ${item.venue} ${item.city} ${item.category}`.toLowerCase().includes(query.trim().toLowerCase())
      const dateMatch = dateFilter === 'all' || (dateFilter === 'today' && item.date === today) || (dateFilter === 'weekend' && item.date >= iso(saturday) && item.date <= iso(sunday)) || (dateFilter === 'range' && (!dateFrom || item.date >= dateFrom) && (!dateTo || item.date <= dateTo))
      return textMatch && (!category || item.category === category) && (!city || item.city === city) && dateMatch && (priceFilter === 'all' || (priceFilter === 'free' ? item.price === 0 : item.price > 0))
    })
    return [...values].sort((a, b) => sort === 'date' ? a.date.localeCompare(b.date) : sort === 'price-asc' ? a.price - b.price : b.price - a.price)
  }, [events, query, category, city, dateFilter, dateFrom, dateTo, priceFilter, sort])

  const categories = useMemo(() => [...new Set(events.map((item) => item.category))].sort((left, right) => {
    const leftIndex = categoryOrder.indexOf(left)
    const rightIndex = categoryOrder.indexOf(right)
    if (leftIndex < 0 || rightIndex < 0) return leftIndex < 0 ? rightIndex < 0 ? left.localeCompare(right, 'es') : 1 : -1
    return leftIndex - rightIndex
  }), [events])
  const cities = useMemo(() => [...new Set(events.map((item) => item.city))].sort(), [events])
  const activeFilterCount = [category, city, dateFilter !== 'all', priceFilter !== 'all'].filter(Boolean).length
  const curatedFeatured = [1002, 1004, 1010, 1013, 1016, 1003].flatMap((id) => {
    const item = events.find((event) => event.id === id)
    return item ? [item] : []
  })
  const featuredEvents = curatedFeatured.length ? curatedFeatured : events.slice(0, 6)
  const featured = featuredEvents[featuredIndex % Math.max(featuredEvents.length, 1)]
  const sideFeatured = featuredEvents.length > 1
    ? [...featuredEvents.slice(featuredIndex + 1), ...featuredEvents.slice(0, featuredIndex)].slice(0, 3)
    : []
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

  const activeZone = selected?.zones?.find((zone) => zone.id === zoneId) ?? null
  const quantityLimit = selected ? Math.min(10, activeZone?.available_capacity ?? selected.available_capacity) : 1
  const currentPrice = selected ? activeZone?.price ?? selected.price : 0
  const currentTotal = selected?.ticket_mode === 'seats'
    ? selected.seats.filter((seat) => selectedSeatIds.includes(seat.id)).reduce((sum, seat) => sum + seat.price, 0)
    : currentPrice * quantity

  function changeQuantity(next: number) {
    setQuantity(Math.max(1, Math.min(quantityLimit, next)))
    idempotencyKey.current = null
  }

  function toggleSeat(seat: Seat) {
    if (!seat.available) return
    setSelectedSeatIds((current) => {
      const next = current.includes(seat.id) ? current.filter((id) => id !== seat.id) : current.length < 10 ? [...current, seat.id] : current
      setQuantity(Math.max(1, next.length))
      return next
    })
    setReservationError(null); setReservationMessage(null); idempotencyKey.current = null
  }

  return (
    <main className="app-shell">
      <header className="site-header">
        <nav className="nav" aria-label="Navegación principal">
          <button className="brand link-button" onClick={() => setView('catalog')} aria-label="Ir al inicio de NexoEventos"><span className="brand-mark">N</span><span>Nexo<strong>Eventos</strong></span></button>
          <button className="nav-link link-button events-link" onClick={() => setView('catalog')}>Eventos</button>
          {view === 'catalog' && <form className="header-search" role="search" onSubmit={(event) => { event.preventDefault(); document.getElementById('catalogo')?.scrollIntoView({ behavior: 'smooth' }) }}><label className="sr-only" htmlFor="main-search">Buscar eventos</label><input id="main-search" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Buscar eventos" /><button type="submit" aria-label="Buscar"><Icon name="search" /></button></form>}
          <div className="nav-actions">
            {user?.role === 'client' && <button className="nav-link link-button" aria-label="Mis entradas" onClick={() => setView('account')}><Icon name="ticket" size={17} /><span>Mis entradas</span></button>}
            {user?.role === 'operator' && <button className="nav-link link-button" aria-label="Control de acceso" onClick={() => setView('operator')}><Icon name="qr" size={17} /><span>Control de acceso</span></button>}
            {user?.role === 'organizer' && <button className="nav-link link-button" aria-label="Mis eventos" onClick={() => setView('organizer')}><Icon name="calendar" size={17} /><span>Mis eventos</span></button>}
            {user ? <AccountMenu user={user} onLogout={logout} /> : <button className="button secondary compact-button" aria-label="Ingresar" onClick={() => setView('auth')}><Icon name="user" size={18} /><span>Ingresar</span></button>}
          </div>
        </nav>
      </header>
      <div className="demo-strip" role="note"><span>Demo académica</span><i aria-hidden="true">·</i><span>Eventos ficticios</span><i aria-hidden="true">·</i><span>Sin cobros reales</span></div>

      {sessionNotice && <div className="notice" role="status">{sessionNotice}<button aria-label="Cerrar aviso" onClick={() => setSessionNotice(null)}><Icon name="close" /></button></div>}
      {!sessionReady && <div className="status dark" role="status">Comprobando sesión…</div>}

      {view === 'auth' && <AuthPanel pendingReservation={selected ? { event: selected, quantity, total: currentTotal } : null} onBack={() => setView('catalog')} onAuthenticated={(value) => void authenticated(value)} />}
      {view === 'account' && user?.role === 'client' && <ClientAccount onExpired={() => { setUser(null); setSessionNotice('Tu sesión expiró. Vuelve a iniciar sesión.'); setView('auth') }} />}
      {view === 'operator' && user?.role === 'operator' && <OperatorPanel onExpired={() => { setUser(null); setSessionNotice('Tu sesión expiró. Vuelve a iniciar sesión.'); setView('auth') }} />}
      {view === 'organizer' && user?.role === 'organizer' && <OrganizerPanel />}

      {view === 'catalog' && <>
        <section className="home-intro" id="inicio" aria-labelledby="featured-title">
          <div className="home-section-title"><h1 id="featured-title">Destacados</h1></div>
          {loading && <div className="status" role="status">Cargando destacados…</div>}
          {!loading && featured && <div className="featured-layout">
            <article className="featured-main">
              <button className="featured-poster" onClick={() => void openDetail(featured.id)} aria-label={`Abrir evento destacado ${featured.name}`}>
                {featured.image_path ? <img src={featured.image_path} alt="" /> : <span className="image-fallback">{featured.category}</span>}
                <span className="poster-copy"><small>{featured.category}</small><strong>{featured.name}</strong><span>{formatDate(featured.date)} · {formatTime(featured.time)} · {featured.city}</span></span>
              </button>
              <button className="carousel-arrow previous" aria-label="Evento destacado anterior" onClick={() => moveFeatured(-1)}><Icon name="arrow" /></button>
              <button className="carousel-arrow next" aria-label="Siguiente evento destacado" onClick={() => moveFeatured(1)}><Icon name="arrow" /></button>
              <div className="carousel-dots" aria-label="Seleccionar evento destacado">{featuredEvents.map((item, index) => <button key={item.id} className={index === featuredIndex ? 'active' : ''} aria-label={`Mostrar ${item.name}`} aria-current={index === featuredIndex ? 'true' : undefined} onClick={() => setFeaturedIndex(index)} />)}</div>
            </article>
            <aside className="featured-side" aria-label="Más eventos destacados">{sideFeatured.map((item) => <button key={item.id} onClick={() => void openDetail(item.id)} aria-label={`Abrir ${item.name}`}>{item.image_path ? <img src={item.image_path} alt="" /> : <span className="image-fallback">{item.category}</span>}<span><small>{formatDate(item.date)} · {item.category}</small><strong>{item.name}</strong><em>{formatEventPrice(item)}</em></span></button>)}</aside>
          </div>}
          <section className="category-section" aria-labelledby="categories-title">
            <div className="home-section-title compact"><h2 id="categories-title">Categorías</h2><p>Explora por tipo de evento</p></div>
            <div className="category-carousel">
              <button type="button" className="category-arrow previous" aria-label="Ver categorías anteriores" onClick={() => moveCategories(-1)}><Icon name="arrow" size={19} /></button>
              <div className="category-links" aria-label="Categorías" ref={categoryListRef}>{categories.map((value) => {
                const presentation = categoryPresentation[value] ?? { label: value, Icon: GiClapperboard }
                return <button key={value} aria-pressed={category === value} className={category === value ? 'selected' : ''} onClick={() => setCategory(category === value ? '' : value)}><span className="category-icon"><presentation.Icon aria-hidden="true" /></span><span className="category-name">{presentation.label}</span></button>
              })}</div>
              <button type="button" className="category-arrow next" aria-label="Ver más categorías" onClick={() => moveCategories(1)}><Icon name="arrow" size={19} /></button>
            </div>
          </section>
        </section>
        <section className="catalog" id="catalogo" aria-labelledby="catalog-title">
          <div className="section-heading">
            <div><h2 id="catalog-title">Próximos eventos</h2></div>
            <div className="results-sort"><span>{filtered.length} resultado{filtered.length === 1 ? '' : 's'}</span><SelectMenu label="Ordenar" value={sort} align="end" onChange={(value) => setSort(value as typeof sort)} options={[{ value: 'date', label: 'Fecha próxima' }, { value: 'price-asc', label: 'Precio menor' }, { value: 'price-desc', label: 'Precio mayor' }]} /></div>
          </div>
          <div className="compact-filters" aria-label="Filtros del catálogo">
            <SelectMenu label="Ciudad" value={city} onChange={setCity} options={[{ value: '', label: 'Todas' }, ...cities.map((value) => ({ value, label: value }))]} />
            <SelectMenu label="Fecha" value={dateFilter} onChange={(value) => { setDateFilter(value as typeof dateFilter); if (value === 'range') setFiltersOpen(true) }} options={[{ value: 'all', label: 'Cualquier fecha' }, { value: 'today', label: 'Hoy' }, { value: 'weekend', label: 'Este fin de semana' }, { value: 'range', label: 'Rango personalizado' }]} />
            <SelectMenu label="Precio" value={priceFilter} align="end" onChange={(value) => setPriceFilter(value as typeof priceFilter)} options={[{ value: 'all', label: 'Todos' }, { value: 'free', label: 'Gratuitos' }, { value: 'paid', label: 'De pago' }]} />
            <button className="more-filters" onClick={() => setFiltersOpen((value) => !value)} aria-expanded={filtersOpen} aria-controls="more-filters-panel"><Icon name="sliders" />Más filtros{activeFilterCount > 0 && <b>{activeFilterCount}</b>}</button>
          </div>
          {filtersOpen && <div className="more-filters-panel" id="more-filters-panel"><DateRangePicker from={dateFrom} to={dateTo} onApply={(from, to) => { setDateFrom(from); setDateTo(to); setDateFilter('range') }} onClear={() => { setDateFrom(''); setDateTo(''); if (dateFilter === 'range') setDateFilter('all') }} /></div>}
          {(query || category || city || dateFilter !== 'all' || priceFilter !== 'all') && <div className="active-filters" aria-label="Filtros activos">{query && <button onClick={() => setQuery('')}>Búsqueda: {query}<Icon name="close" size={15} /></button>}{category && <button onClick={() => setCategory('')}>{categoryPresentation[category]?.label ?? category}<Icon name="close" size={15} /></button>}{city && <button onClick={() => setCity('')}>Ciudad: {city}<Icon name="close" size={15} /></button>}{dateFilter !== 'all' && <button onClick={() => { setDateFilter('all'); setDateFrom(''); setDateTo('') }}>Fecha: {dateFilter === 'today' ? 'Hoy' : dateFilter === 'weekend' ? 'Este fin de semana' : dateFrom && dateTo ? `${shortDate(dateFrom)} – ${shortDate(dateTo)}` : 'Rango'}<Icon name="close" size={15} /></button>}{priceFilter !== 'all' && <button onClick={() => setPriceFilter('all')}>{priceFilter === 'free' ? 'Gratuitos' : 'De pago'}<Icon name="close" size={15} /></button>}<button className="clear-active" onClick={clearFilters}>Limpiar todos</button></div>}
          {loading && <div className="status" role="status">Cargando experiencias…</div>}
          {error && <div className="status error" role="alert"><p>{error}</p><button onClick={() => void loadEvents()}>Reintentar</button></div>}
          {!loading && !error && filtered.length === 0 && <div className="empty-state"><span className="empty-icon"><Icon name="search" /></span><h3>No encontramos eventos</h3><p>Prueba otra fecha, categoría o rango de precio.</p><button className="button secondary" onClick={clearFilters}>Limpiar filtros</button></div>}
          {!loading && !error && filtered.length > 0 && <div className="grid">{filtered.map((item, index) => (
            <article className="card" key={item.id}>
              <button className={`card-art art-${index % 3}`} onClick={() => void openDetail(item.id)} aria-label={`Ver ${item.name}`}>{item.image_path ? <img src={item.image_path} alt="" loading="lazy" /> : <span className="image-fallback">{item.category}</span>}<span className="category-pill">{item.category}</span></button>
              <div className="card-body"><p className="date"><Icon name="calendar" size={16} />{formatDate(item.date)} · {formatTime(item.time)}</p><h3>{item.name}</h3><p className="venue"><Icon name="location" size={17} />{item.venue}, {item.city}</p>
                <div className="card-footer"><strong>{formatEventPrice(item)}</strong><span>{item.available_capacity} disponibles</span></div>
                <button className="button secondary detail-button" onClick={() => void openDetail(item.id)}>Ver detalle <Icon name="arrow" size={18} /></button>
              </div>
            </article>
          ))}</div>}
        </section>
        {(detailLoading || selected || reservationError) && <section className="event-detail" aria-live="polite">
          {detailLoading && <div className="status" role="status"><span className="spinner" />Cargando detalle…</div>}
          {selected && !detailLoading && <div className="detail-layout">
            <article className="event-story"><div className="detail-photo">{selected.image_path ? <img src={selected.image_path} alt={`Fotografía ilustrativa para ${selected.name}`} /> : <span>{selected.category}</span>}</div><div className="event-copy"><p className="eyebrow">Evento ficticio de demostración</p><h2>{selected.name}</h2><div className="event-meta"><span><Icon name="calendar" />{formatDate(selected.date)}</span><span><Icon name="clock" />{formatTime(selected.time)}</span><span><Icon name="location" />{selected.venue}, {selected.city}</span></div><p>{selected.description}</p><span className="availability">{selected.available_capacity} cupos disponibles de {selected.capacity}</span></div></article>
            <form className="booking-panel" onSubmit={(event) => void submitReservation(event)}>
              <div className="booking-heading"><div><p className="eyebrow">Tu reserva</p><h3>Selecciona tus entradas</h3></div><Icon name="ticket" size={26} /></div>
              {selected.ticket_mode === 'general' && <div className="ticket-option selected-option"><span className="selection-check"><Icon name="check" size={16} /></span><div><strong>Entrada general</strong><small>Acceso sin asiento asignado</small></div><b>{selected.price === 0 ? 'Gratis' : `S/ ${selected.price.toFixed(2)}`}</b></div>}
              {selected.ticket_mode === 'zones' && <fieldset className="zone-options"><legend>Elige una zona</legend>{selected.zones.map((zone) => <button type="button" key={zone.id} className={`ticket-option ${zoneId === zone.id ? 'selected-option' : ''}`} disabled={zone.available_capacity === 0} onClick={() => { setZoneId(zone.id); setQuantity(1); setReservationMessage(null); setReservationError(null); idempotencyKey.current = null }}><span className="selection-check">{zoneId === zone.id && <Icon name="check" size={16} />}</span><div><strong>{zone.name}</strong><small>{zone.available_capacity} disponibles</small></div><b>S/ {zone.price.toFixed(2)}</b></button>)}</fieldset>}
              {selected.ticket_mode === 'seats' && <div className="seat-selector"><div className="stage">Escenario</div><div className="seat-legend"><span><i className="seat-sample" />Disponible</span><span><i className="seat-sample selected" />Seleccionado</span><span><i className="seat-sample occupied">×</i>Ocupado</span></div><div className="seat-map" aria-label="Plano de asientos">{[...new Set(selected.seats.map((seat) => seat.row))].map((row) => <div className="seat-row" key={row}><strong>Fila {row}</strong><div>{selected.seats.filter((seat) => seat.row === row).map((seat) => <button type="button" key={seat.id} className={selectedSeatIds.includes(seat.id) ? 'selected' : ''} disabled={!seat.available} aria-label={`Fila ${seat.row}, asiento ${seat.number}, ${seat.available ? selectedSeatIds.includes(seat.id) ? 'seleccionado' : 'disponible' : 'ocupado'}`} aria-pressed={selectedSeatIds.includes(seat.id)} onClick={() => toggleSeat(seat)}>{seat.available ? seat.number : '×'}</button>)}</div></div>)}</div><details className="seat-list"><summary>Alternativa accesible por lista</summary>{selected.seats.map((seat) => <label key={seat.id}><input type="checkbox" checked={selectedSeatIds.includes(seat.id)} disabled={!seat.available} onChange={() => toggleSeat(seat)} /> Zona {seat.zone_name}, fila {seat.row}, asiento {seat.number} · S/ {seat.price.toFixed(2)} {seat.available ? '' : '(ocupado)'}</label>)}</details><small>La selección no retiene los asientos. El servidor los asigna al confirmar.</small></div>}
              <dl className="booking-facts"><div><dt>Evento</dt><dd>{selected.name}</dd></div><div><dt>Fecha</dt><dd>{formatDate(selected.date)} · {formatTime(selected.time)}</dd></div><div><dt>Lugar</dt><dd>{selected.venue}, {selected.city}</dd></div>{activeZone && <div><dt>Zona</dt><dd>{activeZone.name}</dd></div>}{selected.ticket_mode === 'seats' && selectedSeatIds.length > 0 && <div><dt>Asientos</dt><dd>{selected.seats.filter((seat) => selectedSeatIds.includes(seat.id)).map((seat) => `${seat.zone_name} ${seat.row}-${seat.number}`).join(', ')}</dd></div>}</dl>
              {selected.ticket_mode !== 'seats' && (selected.ticket_mode === 'general' || activeZone) && <div className="quantity-row"><div><strong>Cantidad</strong><small>Máximo {quantityLimit} por reserva</small></div><div className="stepper" aria-label="Cantidad de entradas"><button type="button" onClick={() => changeQuantity(quantity - 1)} disabled={quantity <= 1} aria-label="Restar una entrada"><Icon name="minus" /></button><output aria-live="polite">{quantity}</output><button type="button" onClick={() => changeQuantity(quantity + 1)} disabled={quantity >= quantityLimit} aria-label="Agregar una entrada"><Icon name="plus" /></button></div></div>}
              <div className="booking-summary"><span>Total simulado</span><strong>{selected.ticket_mode === 'seats' && selectedSeatIds.length === 0 ? 'Selecciona asientos' : currentTotal === 0 ? 'Gratis' : `S/ ${currentTotal.toFixed(2)}`}</strong></div>
              <button className="button primary reserve-button" disabled={reserving || selected.available_capacity === 0 || (selected.ticket_mode === 'zones' && !zoneId) || (selected.ticket_mode === 'seats' && selectedSeatIds.length === 0)} aria-busy={reserving}>{reserving && <span className="spinner" />}{reserving ? 'Confirmando reserva…' : user?.role === 'client' ? 'Confirmar reserva simulada' : 'Inicia sesión para reservar'}</button>
              <small>Compra simulada: no se procesa ni se cobra dinero real. La reserva queda vinculada a tu cuenta.</small>
              {reservationMessage && <div className="success reservation-confirmation" role="status"><span className="success-icon"><Icon name="check" /></span><div><strong>Reserva simulada confirmada</strong><p>{reservationMessage} Total simulado: {confirmedTotal === 0 ? 'Gratis' : `S/ ${(confirmedTotal ?? currentTotal).toFixed(2)}`}.</p><button type="button" className="button secondary" onClick={() => setView('account')}>Ir a Mis entradas <Icon name="arrow" size={18} /></button></div></div>}
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

  if (registeredUser) return <section className="workspace narrow auth-success" aria-live="polite"><span className="success-icon large"><Icon name="check" size={28} /></span><p className="eyebrow">Registro completado</p><h1 className="page-title">Tu cuenta está lista</h1><p>El servidor creó tu cuenta de cliente y abrió una sesión segura.</p>{pendingReservation && <div className="pending-summary"><strong>Tu selección sigue guardada</strong><span>{pendingReservation.event.name}</span><small>{pendingReservation.quantity} entrada(s) · {pendingReservation.total === 0 ? 'Gratis' : `S/ ${pendingReservation.total.toFixed(2)}`}</small></div>}<button className="button primary" onClick={() => onAuthenticated(registeredUser)}>{pendingReservation ? 'Continuar con mi reserva' : 'Ir a Mis entradas'} <Icon name="arrow" /></button></section>

  return <section className="workspace narrow auth-workspace">
    <button className="back-button" onClick={onBack}><Icon name="arrow" size={18} /> Volver {pendingReservation ? 'a la reserva' : 'a eventos'}</button>
    <p className="eyebrow">Cuenta segura</p><h1 className="page-title">{mode === 'login' ? 'Inicia sesión' : 'Crea tu cuenta'}</h1>
    <p className="muted">La sesión se protege con cookies HttpOnly y CSRF. No guardamos credenciales en el almacenamiento del navegador.</p>
    {pendingReservation && <div className="pending-summary"><strong>Tu reserva está en espera</strong><span>{pendingReservation.event.name}</span><small>{pendingReservation.quantity} entrada(s) · {pendingReservation.total === 0 ? 'Gratis' : `S/ ${pendingReservation.total.toFixed(2)}`}</small></div>}
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

  return <section className="workspace account-workspace"><div className="account-heading"><div><p className="eyebrow">Área personal</p><h1 className="page-title">Mis reservas y entradas</h1><p className="muted">Cada cupo confirmado tiene una entrada digital independiente y privada.</p></div><Icon name="ticket" size={42} /></div>
    {loading && <div className="status account-status" role="status"><span className="spinner" />Cargando tus reservas y entradas…</div>}
    {error && <div className="status error" role="alert"><div><strong>No pudimos mostrar tus entradas</strong><p>{error}</p><button onClick={() => void loadAccount()}>Reintentar</button></div></div>}
    {!loading && !error && reservations.length === 0 && <div className="empty-state"><span className="empty-icon"><Icon name="ticket" size={30} /></span><h2>Aún no tienes entradas</h2><p>Cuando confirmes una reserva simulada, tus entradas aparecerán aquí.</p></div>}
    {!loading && !error && reservations.length > 0 && <div className="account-sections"><div className="list-heading"><div><p className="eyebrow">Acceso personal</p><h2 className="subheading">Tus entradas digitales</h2></div><span>{tickets.length}</span></div>
      {reservationGroups.map(({ reservation, tickets: reservationTickets }) => <section className="reservation-group" key={reservation.id}>
        <div className="reservation-group-heading">
          {reservationTickets[0]?.image_path ? <img src={reservationTickets[0].image_path} alt="" /> : <span className="ticket-symbol"><Icon name="ticket" /></span>}
          <div><span className="reservation-kicker">Reserva simulada · {reservation.quantity} entrada(s)</span><h3>{reservation.event_name}</h3><small>Confirmada el {formatDate(reservation.created_at)}</small></div>
        </div>
        {reservationTickets.length === 0 ? <div className="empty-state compact"><p>La reserva existe, pero todavía no encontramos entradas asociadas.</p></div> : <div className="digital-tickets">{reservationTickets.map((ticket, index) => <button className="digital-ticket" key={ticket.id} onClick={(event) => { ticketTriggerRef.current = event.currentTarget; setSelected(ticket) }} aria-label={`Abrir entrada ${index + 1} para ${ticket.event_name}`}>
          {ticket.image_path && <span className="ticket-photo"><img src={ticket.image_path} alt="" /></span>}
          <span className="ticket-index">Entrada {index + 1} de {reservationTickets.length}</span>
          <div className="ticket-title"><Icon name="ticket" /><strong>{ticket.event_name}</strong></div>
          <strong className="ticket-kind">{ticketLabel(ticket)}</strong>
          <div className="ticket-details"><span><Icon name="calendar" size={17} />{formatDate(ticket.event_date)} · {formatTime(ticket.event_time)}</span><span><Icon name="location" size={17} />{ticket.event_venue}, {ticket.event_city}</span></div>
          <span className={ticket.used_at ? 'ticket-state used' : 'ticket-state available'}><Icon name={ticket.used_at ? 'close' : 'check'} size={16} />{ticket.used_at ? `Usada el ${formatDate(ticket.used_at)}` : 'Disponible para ingresar'}</span><span className="ticket-action"><Icon name="qr" /> Ver entrada QR <Icon name="arrow" size={17} /></span>
        </button>)}</div>}
      </section>)}
    </div>}
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
