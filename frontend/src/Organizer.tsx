import { FormEvent, KeyboardEvent, useCallback, useEffect, useMemo, useState } from 'react'
import { api, AuditoriumSeatPicker, categoryOrder, EventDetail, EventItem, formatDate, formatTime, MuseumVisitGuide, StadiumSeatPicker, ZoneLayoutPicker } from './shared'

type LayoutKind = NonNullable<EventItem['layout_kind']>
type LayoutOption = { layout_id: number; name: string; layout_kind: LayoutKind; ticket_mode: 'general' | 'zones' | 'seats' }
type VenueOption = { venue_id: number; name: string; city: string; layouts: LayoutOption[] }
type EventState = { has_sales: boolean; can_edit_inventory: boolean; can_publish: boolean; can_unpublish: boolean; can_delete: boolean; publish_problems: string[] }
type Operator = { user_id: string; email: string; display_name: string }
type Stats = {
  event_id: number; name: string; ticket_mode: 'general' | 'zones' | 'seats'; capacity: number; sold: number; available: number
  occupancy_percent: number; revenue: number; checked_in: number; pending_entry: number
  zones: Array<{ zone_id: number; name: string; price: number; capacity: number; sold: number; available: number; revenue: number }>
}
type ZoneDraft = { name: string; price: string; capacity: string }
type SectionDraft = { name: string; price: string; rows: string; seats_per_row: string }
type Inventory = { layoutId: number | null; price: string; capacity: string; zones: ZoneDraft[]; sections: SectionDraft[] }
type Feedback = { kind: 'success' | 'error'; text: string } | null
type TabId = 'summary' | 'data' | 'inventory' | 'preview' | 'operators'

const IMAGES = ['concert-live', 'concert-stage', 'concert-energy', 'festival-stage', 'theater-performance', 'open-theater', 'standup-stage', 'dance-stage', 'football-stadium', 'running-race', 'art-exhibition', 'culture-museum', 'conference-speaker', 'technology-exhibition', 'cinema-room', 'pottery-hands', 'cooking-workshop', 'food-fair', 'children-workshop', 'networking-professionals']
const STADIUM_SIDES = ['Tribuna Norte', 'Tribuna Sur', 'Tribuna Oriente', 'Tribuna Occidente']
const TABS: Array<{ id: TabId; label: string }> = [{ id: 'summary', label: 'Resumen' }, { id: 'data', label: 'Datos' }, { id: 'inventory', label: 'Recinto y entradas' }, { id: 'preview', label: 'Vista previa' }, { id: 'operators', label: 'Operadores' }]

const emptyInventory: Inventory = { layoutId: null, price: '', capacity: '', zones: [], sections: [] }
const today = () => new Date().toISOString().slice(0, 10)

function errorText(payload: unknown, fallback: string) {
  const detail = typeof payload === 'object' && payload && 'detail' in payload ? (payload as { detail: unknown }).detail : null
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail) && detail.length) return 'Revisa los campos del formulario: hay valores fuera de rango o incompletos.'
  return fallback
}

function defaultsFor(layout: LayoutOption): Inventory {
  if (layout.ticket_mode === 'general') return { ...emptyInventory, layoutId: layout.layout_id, price: layout.layout_kind === 'museum' ? '18' : '20', capacity: '60' }
  if (layout.ticket_mode === 'zones') return { ...emptyInventory, layoutId: layout.layout_id, zones: layout.layout_kind === 'concert_zones' ? [{ name: 'Campo', price: '45', capacity: '120' }, { name: 'Preferencial', price: '75', capacity: '60' }] : [{ name: 'General', price: '30', capacity: '100' }] }
  if (layout.layout_kind === 'stadium') return { ...emptyInventory, layoutId: layout.layout_id, sections: [{ name: 'Tribuna Norte', price: '40', rows: '2', seats_per_row: '12' }, { name: 'Tribuna Oriente', price: '55', rows: '2', seats_per_row: '12' }] }
  return { ...emptyInventory, layoutId: layout.layout_id, sections: [{ name: 'General', price: '35', rows: '4', seats_per_row: '12' }, { name: 'Preferencial', price: '55', rows: '4', seats_per_row: '12' }] }
}

function inventoryFromDetail(detail: EventDetail): Inventory {
  const base = { ...emptyInventory, layoutId: detail.layout_id }
  if (detail.ticket_mode === 'general') return { ...base, price: String(detail.price), capacity: String(detail.capacity) }
  if (detail.ticket_mode === 'zones') return { ...base, zones: detail.zones.map((zone) => ({ name: zone.name, price: String(zone.price), capacity: String(zone.capacity) })) }
  return {
    ...base,
    sections: detail.zones.map((zone) => {
      const own = detail.seats.filter((seat) => seat.zone_id === zone.id)
      const rows = new Set(own.map((seat) => seat.row)).size
      return { name: zone.name, price: String(zone.price), rows: String(rows), seats_per_row: String(rows ? Math.round(own.length / rows) : 0) }
    }),
  }
}

function inventoryBody(inventory: Inventory, kind: LayoutKind | null) {
  const body: Record<string, unknown> = { layout_id: inventory.layoutId }
  if (kind === 'museum' || kind === 'general') { body.price = Number(inventory.price); body.capacity = Number(inventory.capacity) }
  else if (kind === 'zones' || kind === 'concert_zones') body.zones = inventory.zones.map((zone) => ({ name: zone.name.trim(), price: Number(zone.price), capacity: Number(zone.capacity) }))
  else body.sections = inventory.sections.map((section) => ({ name: section.name.trim(), price: Number(section.price), rows: Number(section.rows), seats_per_row: Number(section.seats_per_row) }))
  return body
}

function InventoryEditor({ venues, value, onChange, disabled }: { venues: VenueOption[]; value: Inventory; onChange: (value: Inventory) => void; disabled: boolean }) {
  const layouts = useMemo(() => venues.flatMap((venue) => venue.layouts.map((layout) => ({ ...layout, venue }))), [venues])
  const current = layouts.find((layout) => layout.layout_id === value.layoutId) ?? null
  const venueId = current?.venue.venue_id ?? ''
  const kind = current?.layout_kind ?? null
  const venue = venues.find((item) => item.venue_id === venueId)
  const totalSeats = value.sections.reduce((sum, section) => sum + (Number(section.rows) || 0) * (Number(section.seats_per_row) || 0), 0)
  const totalRows = value.sections.reduce((sum, section) => sum + (Number(section.rows) || 0), 0)
  const chooseVenue = (id: number) => { const target = venues.find((item) => item.venue_id === id); if (target?.layouts[0]) onChange(defaultsFor(target.layouts[0])) }
  const chooseLayout = (id: number) => { const layout = layouts.find((item) => item.layout_id === id); if (layout) onChange(defaultsFor(layout)) }
  const setZone = (index: number, patch: Partial<ZoneDraft>) => onChange({ ...value, zones: value.zones.map((zone, at) => at === index ? { ...zone, ...patch } : zone) })
  const setSection = (index: number, patch: Partial<SectionDraft>) => onChange({ ...value, sections: value.sections.map((section, at) => at === index ? { ...section, ...patch } : section) })

  return <fieldset className="organizer-fieldset" disabled={disabled}>
    <legend>Recinto y entradas</legend>
    <div className="organizer-form-row">
      <label>Recinto<select value={venueId} onChange={(event) => chooseVenue(Number(event.target.value))} required><option value="" disabled>Selecciona un recinto</option>{venues.map((item) => <option key={item.venue_id} value={item.venue_id}>{item.name} · {item.city}</option>)}</select></label>
      <label>Plano del recinto<select value={value.layoutId ?? ''} onChange={(event) => chooseLayout(Number(event.target.value))} disabled={!venue} required><option value="" disabled>Selecciona un plano</option>{venue?.layouts.map((layout) => <option key={layout.layout_id} value={layout.layout_id}>{layout.name}</option>)}</select></label>
    </div>
    {current && <p className="organizer-hint">{kind === 'theatre' && 'Asientos numerados en una sala con escenario frontal: define secciones con filas y asientos por fila.'}{kind === 'stadium' && 'Asientos numerados por tribuna alrededor de la cancha: elige tribunas (Norte, Sur, Oriente, Occidente).'}{(kind === 'concert_zones' || kind === 'zones') && 'Zonas con aforo y precio propio, sin asientos numerados.'}{kind === 'museum' && 'Cupo por horario: los visitantes reservan fecha, hora y cantidad, no salas ni asientos. La hora es obligatoria.'}{kind === 'general' && 'Entrada general con cupo único, sin ubicación asignada.'}</p>}
    {(kind === 'museum' || kind === 'general') && <div className="organizer-form-row"><label>{kind === 'museum' ? 'Precio por visitante (S/)' : 'Precio (S/)'}<input type="number" min="0" step="0.01" value={value.price} onChange={(event) => onChange({ ...value, price: event.target.value })} required /></label><label>{kind === 'museum' ? 'Cupo por horario' : 'Aforo'}<input type="number" min="1" max="5000" step="1" value={value.capacity} onChange={(event) => onChange({ ...value, capacity: event.target.value })} required /></label></div>}
    {(kind === 'zones' || kind === 'concert_zones') && <div className="organizer-rows">{value.zones.map((zone, index) => <div className="organizer-line" key={index} role="group" aria-label={`Zona ${index + 1}`}>
      <label>Nombre de zona<input value={zone.name} onChange={(event) => setZone(index, { name: event.target.value })} minLength={2} maxLength={80} required /></label>
      <label>Precio (S/)<input type="number" min="0" step="0.01" value={zone.price} onChange={(event) => setZone(index, { price: event.target.value })} required /></label>
      <label>Aforo<input type="number" min="1" max="5000" step="1" value={zone.capacity} onChange={(event) => setZone(index, { capacity: event.target.value })} required /></label>
      <button type="button" className="outline" disabled={value.zones.length <= 1} onClick={() => onChange({ ...value, zones: value.zones.filter((_, at) => at !== index) })} aria-label={`Quitar zona ${index + 1}`}>Quitar</button>
    </div>)}
    <button type="button" className="outline" disabled={value.zones.length >= 6} onClick={() => onChange({ ...value, zones: [...value.zones, { name: `Zona ${value.zones.length + 1}`, price: '30', capacity: '50' }] })}>Agregar zona</button></div>}
    {(kind === 'theatre' || kind === 'stadium') && <div className="organizer-rows">{value.sections.map((section, index) => <div className="organizer-line organizer-line-seats" key={index} role="group" aria-label={`Sección ${index + 1}`}>
      <label>{kind === 'stadium' ? 'Tribuna' : 'Nombre de sección'}{kind === 'stadium'
        ? <select value={section.name} onChange={(event) => setSection(index, { name: event.target.value })}>{STADIUM_SIDES.map((side) => <option key={side} value={side} disabled={value.sections.some((other, at) => at !== index && other.name === side)}>{side}</option>)}</select>
        : <input value={section.name} onChange={(event) => setSection(index, { name: event.target.value })} minLength={2} maxLength={80} required />}</label>
      <label>Precio (S/)<input type="number" min="0" step="0.01" value={section.price} onChange={(event) => setSection(index, { price: event.target.value })} required /></label>
      <label>Filas<input type="number" min="1" max="8" step="1" value={section.rows} onChange={(event) => setSection(index, { rows: event.target.value })} required /></label>
      <label>Asientos por fila<input type="number" min="1" max="12" step="1" value={section.seats_per_row} onChange={(event) => setSection(index, { seats_per_row: event.target.value })} required /></label>
      <button type="button" className="outline" disabled={value.sections.length <= 1} onClick={() => onChange({ ...value, sections: value.sections.filter((_, at) => at !== index) })} aria-label={`Quitar sección ${index + 1}`}>Quitar</button>
    </div>)}
    <button type="button" className="outline" disabled={value.sections.length >= 4} onClick={() => onChange({ ...value, sections: [...value.sections, { name: kind === 'stadium' ? STADIUM_SIDES.find((side) => !value.sections.some((section) => section.name === side)) ?? 'Tribuna Sur' : `Sección ${value.sections.length + 1}`, price: '40', rows: '2', seats_per_row: '12' }] })}>Agregar {kind === 'stadium' ? 'tribuna' : 'sección'}</button>
    <p className="organizer-hint" role="status">Total: {totalSeats} asientos en {totalRows} filas. Las filas se rotulan A, B, C… en orden y las secciones más cercanas al escenario o la cancha van primero.</p></div>}
    {disabled && <p className="organizer-hint">Hay reservas o entradas emitidas: el recinto, el plano y el inventario ya no se pueden modificar.</p>}
  </fieldset>
}

function Preview({ detail }: { detail: EventDetail }) {
  const [seatIds, setSeatIds] = useState<number[]>([])
  const [zoneId, setZoneId] = useState<number | null>(null)
  const toggle = (seat: { id: number }) => setSeatIds((current) => current.includes(seat.id) ? current.filter((id) => id !== seat.id) : [...current, seat.id].slice(0, 10))
  useEffect(() => { setSeatIds([]); setZoneId(null) }, [detail.id, detail.zones.length, detail.seats.length, detail.layout_id])
  const kind = detail.layout_kind
  return <div className="organizer-preview">
    <p className="organizer-banner" role="note">Vista previa: así verán este evento los clientes. Puedes probar la selección, pero aquí no se reserva nada.{detail.status === 'draft' ? ' Está en borrador y no aparece en el catálogo.' : ''}</p>
    <article className="event-story"><div className="detail-photo">{detail.image_path ? <img src={detail.image_path} alt={`Fotografía ilustrativa para ${detail.name}`} /> : <span>{detail.category}</span>}</div><div className="event-copy"><p className="eyebrow">Evento ficticio de demostración</p><h3>{detail.name}</h3><div className="event-meta"><span>{formatDate(detail.date)}</span><span>{formatTime(detail.time)}</span><span>{detail.venue}, {detail.city}</span></div><p>{detail.description}</p><span className="availability">{detail.available_capacity} cupos disponibles de {detail.capacity}</span></div></article>
    {detail.ticket_mode === 'general' && <><div className="ticket-option selected-option"><div><strong>{kind === 'museum' ? 'Ingreso por horario' : 'Entrada general'}</strong><small>{kind === 'museum' ? 'Elige cantidad de visitantes; las salas no se reservan' : 'Acceso sin asiento ni ubicación asignados'}</small></div><b>{detail.price === 0 ? 'Gratis' : `S/ ${detail.price.toFixed(2)}`}</b></div>{kind === 'museum' && <MuseumVisitGuide />}</>}
    {detail.ticket_mode === 'zones' && <ZoneLayoutPicker zones={detail.zones} selectedZoneId={zoneId} concert={kind === 'concert_zones'} onSelect={setZoneId} />}
    {detail.ticket_mode === 'seats' && (kind === 'stadium' ? <StadiumSeatPicker seats={detail.seats} selectedSeatIds={seatIds} onToggle={toggle} /> : kind === 'theatre' ? <AuditoriumSeatPicker seats={detail.seats} selectedSeatIds={seatIds} onToggle={toggle} /> : <div className="form-error" role="alert">Este evento usa asientos numerados pero su plano no admite asientos.</div>)}
  </div>
}

function StatsView({ stats }: { stats: Stats }) {
  return <>
    <dl className="organizer-kpis" aria-label="Indicadores del evento">
      <div><dt>Entradas vendidas</dt><dd>{stats.sold} de {stats.capacity}</dd></div>
      <div><dt>Ocupación</dt><dd>{stats.occupancy_percent.toFixed(1)} %</dd></div>
      <div><dt>Disponibles</dt><dd>{stats.available}</dd></div>
      <div><dt>Ingresos simulados</dt><dd>S/ {stats.revenue.toFixed(2)}</dd></div>
      <div><dt>Ya ingresaron</dt><dd>{stats.checked_in}</dd></div>
      <div><dt>Pendientes de ingreso</dt><dd>{stats.pending_entry}</dd></div>
    </dl>
    {stats.zones.length > 0 && <table className="organizer-zones"><caption>Ventas por zona</caption><thead><tr><th scope="col">Zona</th><th scope="col">Precio</th><th scope="col">Vendidas</th><th scope="col">Disponibles</th><th scope="col">Ingresos</th></tr></thead><tbody>{stats.zones.map((zone) => <tr key={zone.zone_id}><th scope="row">{zone.name}</th><td>S/ {zone.price.toFixed(2)}</td><td>{zone.sold} de {zone.capacity}</td><td>{zone.available}</td><td>S/ {zone.revenue.toFixed(2)}</td></tr>)}</tbody></table>}
  </>
}

type DataForm = { name: string; date: string; time: string; category: string; description: string; image: string }
const emptyData: DataForm = { name: '', date: '', time: '19:30', category: categoryOrder[0], description: '', image: '' }

function DataFields({ value, onChange, locked }: { value: DataForm; onChange: (value: DataForm) => void; locked: boolean }) {
  return <fieldset className="organizer-fieldset"><legend>Datos del evento</legend>
    <label>Nombre<input value={value.name} onChange={(event) => onChange({ ...value, name: event.target.value })} minLength={2} maxLength={160} required /></label>
    <div className="organizer-form-row">
      <label>Fecha<input type="date" min={locked ? undefined : today()} value={value.date} onChange={(event) => onChange({ ...value, date: event.target.value })} disabled={locked} required /></label>
      <label>Hora<input type="time" value={value.time} onChange={(event) => onChange({ ...value, time: event.target.value })} disabled={locked} /></label>
    </div>
    {locked && <p className="organizer-hint">La fecha y la hora no se pueden cambiar porque ya hay reservas o entradas emitidas. Crea una nueva función para otro día.</p>}
    <div className="organizer-form-row">
      <label>Categoría<select value={value.category} onChange={(event) => onChange({ ...value, category: event.target.value })}>{[...new Set([...categoryOrder, value.category])].map((category) => <option key={category} value={category}>{category}</option>)}</select></label>
      <label>Imagen ilustrativa<select value={value.image} onChange={(event) => onChange({ ...value, image: event.target.value })}><option value="">Sin imagen</option>{[...new Set([...IMAGES, ...(value.image ? [value.image.replace('/events/', '').replace('.jpg', '')] : [])])].map((name) => <option key={name} value={name}>{name.replace(/-/g, ' ')}</option>)}</select></label>
    </div>
    <label>Descripción<textarea value={value.description} onChange={(event) => onChange({ ...value, description: event.target.value })} minLength={10} maxLength={4000} required /></label>
  </fieldset>
}

function EventWorkspace({ eventId, venues, onChanged, onGone, onSelect }: { eventId: number; venues: VenueOption[]; onChanged: (detail: EventDetail) => void; onGone: (id: number) => void; onSelect: (id: number) => void }) {
  const [tab, setTab] = useState<TabId>('summary')
  const [detail, setDetail] = useState<EventDetail | null>(null)
  const [state, setState] = useState<EventState | null>(null)
  const [stats, setStats] = useState<Stats | null>(null)
  const [operators, setOperators] = useState<Operator[]>([])
  const [data, setData] = useState<DataForm>(emptyData)
  const [inventory, setInventory] = useState<Inventory>(emptyInventory)
  const [feedback, setFeedback] = useState<Feedback>(null)
  const [busy, setBusy] = useState(false)
  const [operatorEmail, setOperatorEmail] = useState('')
  const [functionForm, setFunctionForm] = useState<{ date: string; time: string } | null>(null)
  const [confirmDelete, setConfirmDelete] = useState(false)

  const loadAll = useCallback(async () => {
    const [detailResponse, stateResponse, statsResponse, operatorsResponse] = await Promise.all([api(`/api/organizer/events/${eventId}`), api(`/api/organizer/events/${eventId}/state`), api(`/api/organizer/events/${eventId}/stats`), api(`/api/organizer/events/${eventId}/operators`)])
    if (!detailResponse.ok) return
    const loaded = await detailResponse.json() as EventDetail
    setDetail(loaded)
    setData({ name: loaded.name, date: loaded.date, time: loaded.time?.slice(0, 5) ?? '', category: loaded.category, description: loaded.description, image: loaded.image_path?.replace('/events/', '').replace('.jpg', '') ?? '' })
    setInventory(inventoryFromDetail(loaded))
    if (stateResponse.ok) setState(await stateResponse.json() as EventState)
    if (statsResponse.ok) setStats(await statsResponse.json() as Stats)
    if (operatorsResponse.ok) setOperators(await operatorsResponse.json() as Operator[])
  }, [eventId])

  useEffect(() => { setDetail(null); setState(null); setStats(null); setFeedback(null); setTab('summary'); setFunctionForm(null); setConfirmDelete(false); void loadAll() }, [loadAll])

  const kind = venues.flatMap((venue) => venue.layouts).find((layout) => layout.layout_id === inventory.layoutId)?.layout_kind ?? null

  async function mutate(request: () => Promise<Response>, success: string, after?: (response: Response) => Promise<void>) {
    setBusy(true); setFeedback(null)
    try {
      const response = await request()
      if (!response.ok && response.status !== 204) { setFeedback({ kind: 'error', text: errorText(await response.json().catch(() => ({})), 'No se pudo completar la acción. Inténtalo de nuevo.') }); return false }
      if (after) await after(response)
      else if (response.status !== 204) onChanged(await response.json() as EventDetail)
      setFeedback({ kind: 'success', text: success })
      return true
    } catch { setFeedback({ kind: 'error', text: 'No se pudo conectar con el servidor. Revisa tu conexión.' }); return false } finally { setBusy(false) }
  }

  async function saveData(event: FormEvent) {
    event.preventDefault()
    const body: Record<string, unknown> = { name: data.name.trim(), category: data.category, description: data.description.trim() }
    if (!state?.has_sales) { body.date = data.date; if (data.time) body.time = `${data.time}:00` }
    if (await mutate(() => api(`/api/organizer/events/${eventId}`, { method: 'PATCH', body: JSON.stringify(body) }), 'Datos guardados.')) await loadAll()
  }
  async function saveInventory(event: FormEvent) {
    event.preventDefault()
    if (await mutate(() => api(`/api/organizer/events/${eventId}/inventory`, { method: 'PUT', body: JSON.stringify(inventoryBody(inventory, kind)) }), 'Recinto e inventario guardados. Revisa la vista previa.')) { await loadAll(); setTab('preview') }
  }
  const publish = async (path: 'publish' | 'unpublish', success: string) => { if (await mutate(() => api(`/api/organizer/events/${eventId}/${path}`, { method: 'POST' }), success)) await loadAll() }
  async function addOperator(event: FormEvent) {
    event.preventDefault()
    await mutate(() => api(`/api/organizer/events/${eventId}/operators`, { method: 'POST', body: JSON.stringify({ email: operatorEmail.trim() }) }), 'Operador asignado: ya puede validar entradas de este evento.', async (response) => { setOperators(await response.json() as Operator[]); setOperatorEmail('') })
  }
  const removeOperator = (operator: Operator) => mutate(() => api(`/api/organizer/events/${eventId}/operators/${operator.user_id}`, { method: 'DELETE' }), 'Operador retirado.', async (response) => setOperators(await response.json() as Operator[]))
  async function createFunction(event: FormEvent) {
    event.preventDefault()
    if (!functionForm) return
    await mutate(() => api(`/api/organizer/events/${eventId}/functions`, { method: 'POST', body: JSON.stringify({ date: functionForm.date, time: functionForm.time ? `${functionForm.time}:00` : null }) }), 'Nueva función creada como borrador.', async (response) => { const created = await response.json() as EventDetail; onChanged(created); onSelect(created.id) })
  }
  async function deleteDraft() {
    const ok = await mutate(() => api(`/api/organizer/events/${eventId}`, { method: 'DELETE' }), 'Borrador eliminado.', async () => undefined)
    if (ok) onGone(eventId)
  }
  const onTabKey = (event: KeyboardEvent<HTMLButtonElement>) => {
    const index = TABS.findIndex((item) => item.id === tab)
    const next = event.key === 'ArrowRight' ? (index + 1) % TABS.length : event.key === 'ArrowLeft' ? (index + TABS.length - 1) % TABS.length : -1
    if (next >= 0) { event.preventDefault(); setTab(TABS[next].id); document.getElementById(`organizer-tab-${TABS[next].id}`)?.focus() }
  }

  if (!detail || !state) return <div className="status dark" role="status">Cargando evento…</div>
  const published = detail.status === 'published'
  return <div className="organizer-workspace">
    <header className="organizer-head"><div><h2 className="subheading">{detail.name}</h2><p className="muted">{formatDate(detail.date)} · {formatTime(detail.time)} · {detail.venue}</p></div><span className={`organizer-badge ${published ? 'published' : 'draft'}`}>{published ? 'Publicado' : 'Borrador'}</span></header>
    <div className="organizer-tabs" role="tablist" aria-label="Secciones del evento">{TABS.map((item) => <button key={item.id} id={`organizer-tab-${item.id}`} role="tab" type="button" aria-selected={tab === item.id} aria-controls={`organizer-panel-${item.id}`} tabIndex={tab === item.id ? 0 : -1} className={tab === item.id ? 'active' : ''} onClick={() => setTab(item.id)} onKeyDown={onTabKey}>{item.label}</button>)}</div>
    {feedback && <p className={feedback.kind === 'success' ? 'success' : 'form-error'} role={feedback.kind === 'error' ? 'alert' : 'status'}>{feedback.text}</p>}
    <div role="tabpanel" id={`organizer-panel-${tab}`} aria-labelledby={`organizer-tab-${tab}`} className="organizer-panel">
      {tab === 'summary' && <>
        <section aria-label="Estado de publicación" className="organizer-actions">
          {!published && state.publish_problems.length > 0 && <div className="status dark" role="status"><strong>Falta para publicar:</strong><ul>{state.publish_problems.map((problem) => <li key={problem}>{problem}</li>)}</ul></div>}
          {!published && state.publish_problems.length === 0 && <p className="muted">Todo listo: revisa la vista previa y publica cuando quieras. Hasta entonces el evento no aparece en el catálogo ni admite reservas.</p>}
          {published && <p className="muted">El evento está visible en el catálogo y admite reservas.{state.has_sales ? ' Como ya tiene reservas, no se puede despublicar ni cambiar su recinto, inventario, fecha u hora.' : ''}</p>}
          <div className="button-row">
            {!published && <button type="button" className="primary" disabled={busy || !state.can_publish} onClick={() => void publish('publish', 'Evento publicado: ya aparece en el catálogo.')}>Publicar evento</button>}
            {published && <button type="button" className="outline" disabled={busy || !state.can_unpublish} onClick={() => void publish('unpublish', 'Evento devuelto a borrador.')}>Despublicar</button>}
            <button type="button" className="outline" disabled={busy} onClick={() => setFunctionForm({ date: '', time: detail.time?.slice(0, 5) ?? '' })}>Nueva función</button>
            {state.can_delete && !confirmDelete && <button type="button" className="outline danger" disabled={busy} onClick={() => setConfirmDelete(true)}>Eliminar borrador</button>}
          </div>
          {confirmDelete && <div className="status dark" role="alertdialog" aria-label="Confirmar eliminación"><p>¿Eliminar este borrador y su configuración? No se puede deshacer.</p><div className="button-row"><button type="button" className="outline danger" disabled={busy} onClick={() => void deleteDraft()}>Sí, eliminar</button><button type="button" className="outline" onClick={() => setConfirmDelete(false)}>Cancelar</button></div></div>}
          {functionForm && <form className="panel-form organizer-inline" onSubmit={(event) => void createFunction(event)}><h3 className="subheading">Nueva función</h3><p className="muted">Copia el recinto, el plano y la configuración de entradas. El inventario y las reservas serán independientes.</p><div className="organizer-form-row"><label>Fecha<input type="date" min={today()} value={functionForm.date} onChange={(event) => setFunctionForm({ ...functionForm, date: event.target.value })} required /></label><label>Hora<input type="time" value={functionForm.time} onChange={(event) => setFunctionForm({ ...functionForm, time: event.target.value })} /></label></div><div className="button-row"><button className="primary" disabled={busy}>Crear función</button><button type="button" className="outline" onClick={() => setFunctionForm(null)}>Cancelar</button></div></form>}
        </section>
        <h3 className="subheading">Estadísticas</h3>
        {stats ? <StatsView stats={stats} /> : <div className="status dark" role="status">Cargando estadísticas…</div>}
      </>}
      {tab === 'data' && <form className="panel-form organizer-form" onSubmit={(event) => void saveData(event)}><DataFields value={data} onChange={setData} locked={state.has_sales} /><button className="primary" disabled={busy}>{busy ? 'Guardando…' : 'Guardar datos'}</button></form>}
      {tab === 'inventory' && <form className="panel-form organizer-form" onSubmit={(event) => void saveInventory(event)}><InventoryEditor venues={venues} value={inventory} onChange={setInventory} disabled={!state.can_edit_inventory} />{state.can_edit_inventory && <button className="primary" disabled={busy || !inventory.layoutId}>{busy ? 'Guardando…' : 'Guardar recinto e inventario'}</button>}</form>}
      {tab === 'preview' && <Preview detail={detail} />}
      {tab === 'operators' && <section aria-label="Operadores de ingreso"><p className="muted">Solo los operadores asignados pueden validar los QR de este evento.</p>{operators.length === 0 ? <div className="status dark">Aún no hay operadores asignados.</div> : <ul className="organizer-operators">{operators.map((operator) => <li key={operator.user_id}><span><strong>{operator.display_name}</strong><small>{operator.email}</small></span><button type="button" className="outline" disabled={busy} aria-label={`Retirar a ${operator.display_name}`} onClick={() => void removeOperator(operator)}>Retirar</button></li>)}</ul>}<form className="panel-form organizer-inline" onSubmit={(event) => void addOperator(event)}><label>Correo del operador<input type="email" value={operatorEmail} onChange={(event) => setOperatorEmail(event.target.value)} required /></label><button className="primary" disabled={busy}>Asignar operador</button></form></section>}
    </div>
  </div>
}

function NewEvent({ venues, onCreated }: { venues: VenueOption[]; onCreated: (detail: EventDetail) => void }) {
  const [data, setData] = useState<DataForm>({ ...emptyData, date: '' })
  const [inventory, setInventory] = useState<Inventory>(emptyInventory)
  const [feedback, setFeedback] = useState<Feedback>(null)
  const [busy, setBusy] = useState(false)
  const kind = venues.flatMap((venue) => venue.layouts).find((layout) => layout.layout_id === inventory.layoutId)?.layout_kind ?? null
  async function submit(event: FormEvent) {
    event.preventDefault()
    if (!inventory.layoutId) { setFeedback({ kind: 'error', text: 'Selecciona un recinto y un plano.' }); return }
    setBusy(true); setFeedback(null)
    try {
      const body = { name: data.name.trim(), date: data.date, time: data.time ? `${data.time}:00` : null, category: data.category, description: data.description.trim(), image_path: data.image ? `/events/${data.image}.jpg` : null, ...inventoryBody(inventory, kind) }
      const response = await api('/api/organizer/events', { method: 'POST', body: JSON.stringify(body) })
      if (response.ok) onCreated(await response.json() as EventDetail)
      else setFeedback({ kind: 'error', text: errorText(await response.json().catch(() => ({})), 'No se pudo crear el evento.') })
    } catch { setFeedback({ kind: 'error', text: 'No se pudo conectar con el servidor. Revisa tu conexión.' }) } finally { setBusy(false) }
  }
  return <form className="panel-form organizer-form" onSubmit={(event) => void submit(event)}>
    <h2 className="subheading">Nuevo evento</h2>
    <p className="muted">Se crea como borrador: no aparece en el catálogo hasta que lo publiques.</p>
    <DataFields value={data} onChange={setData} locked={false} />
    <InventoryEditor venues={venues} value={inventory} onChange={setInventory} disabled={false} />
    {feedback && <p className={feedback.kind === 'success' ? 'success' : 'form-error'} role={feedback.kind === 'error' ? 'alert' : 'status'}>{feedback.text}</p>}
    <button className="primary" disabled={busy}>{busy ? 'Creando…' : 'Crear borrador'}</button>
  </form>
}

export default function OrganizerPanel() {
  const [events, setEvents] = useState<EventItem[]>([])
  const [venues, setVenues] = useState<VenueOption[]>([])
  const [loading, setLoading] = useState(true)
  const [selectedId, setSelectedId] = useState<number | 'new' | null>(null)

  const reload = useCallback(async () => {
    const [eventsResponse, venuesResponse] = await Promise.all([api('/api/organizer/events'), api('/api/organizer/venues')])
    if (eventsResponse.ok) setEvents(await eventsResponse.json() as EventItem[])
    if (venuesResponse.ok) setVenues(await venuesResponse.json() as VenueOption[])
  }, [])
  useEffect(() => { void reload().finally(() => setLoading(false)) }, [reload])
  useEffect(() => { if (selectedId === null && events.length) setSelectedId(events[0].id) }, [events, selectedId])

  const afterChange = async (detail: EventDetail) => { await reload(); if (selectedId === 'new') setSelectedId(detail.id) }
  return <section className="workspace"><p className="eyebrow">Organización</p><h1 className="page-title">Mis eventos</h1><p className="muted">Crea eventos y funciones, elige recinto y plano, configura entradas y publica. El backend limita todo a los eventos propiedad del organizador.</p>
    {loading && <div className="status dark" role="status">Cargando eventos…</div>}
    {!loading && <div className="organizer-layout">
      <div className="organizer-sidebar">
        <button type="button" className="primary organizer-new" onClick={() => setSelectedId('new')}>Nuevo evento</button>
        {events.length === 0 && <div className="status dark">Aún no tienes eventos. Crea el primero.</div>}
        <div className="organizer-list" role="group" aria-label="Eventos del organizador">{events.map((item) => <button type="button" key={item.id} className={`row-card organizer-item ${item.id === selectedId ? 'active' : ''}`} aria-pressed={item.id === selectedId} onClick={() => setSelectedId(item.id)}><strong>{item.name}</strong><span>{formatDate(item.date)} · {formatTime(item.time)}</span><small><span className={`organizer-badge ${item.status === 'published' ? 'published' : 'draft'}`}>{item.status === 'published' ? 'Publicado' : 'Borrador'}</span> {item.available_capacity} de {item.capacity} cupos · {item.layout_name ?? 'Sin plano'}</small></button>)}</div>
      </div>
      <div className="organizer-detail">
        {selectedId === 'new' && <NewEvent venues={venues} onCreated={(detail) => { void reload().then(() => setSelectedId(detail.id)) }} />}
        {typeof selectedId === 'number' && <EventWorkspace key={selectedId} eventId={selectedId} venues={venues} onChanged={(detail) => void afterChange(detail)} onGone={(id) => { setEvents((current) => current.filter((item) => item.id !== id)); setSelectedId(null); void reload() }} onSelect={(id) => { void reload().then(() => setSelectedId(id)) }} />}
      </div>
    </div>}
  </section>
}
