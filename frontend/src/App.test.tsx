import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import axe from 'axe-core'
import { afterEach, describe, expect, it, vi } from 'vitest'

import App from './App'

vi.mock('qrcode', () => ({ default: { toDataURL: vi.fn().mockResolvedValue('data:image/png;base64,dGVzdA==') } }))
vi.mock('./Stadium3D', () => ({
  default: ({ selectedSeatIds }: { selectedSeatIds: number[] }) => <div data-testid="stadium-3d-test">Visor 3D · {selectedSeatIds.length} selección</div>,
}))

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe('NexoEventos catalog', () => {
  const baseEvent = {
    time: '19:30:00',
    city: 'Lima',
    image_path: null,
    ticket_mode: 'general' as const,
    venue_id: null,
    layout_id: null,
    layout_name: null,
    layout_kind: 'general' as const,
    is_demo: true,
    has_multiple_prices: false,
  }

  async function expectNoAccessibilityViolations() {
    // JSDOM has no layout engine; contrast is checked against the rendered palette separately.
    const results = await axe.run(document.body, { rules: { 'color-contrast': { enabled: false } } })
    const report = results.violations.map((violation) => `${violation.id}: ${violation.help}`).join('\n')
    expect(results.violations, report).toEqual([])
  }

  it('passes automated accessibility checks on catalog, date dialog and authentication', async () => {
    const event = { ...baseEvent, id: 1, name: 'Evento accesible', date: '2026-10-17', venue: 'Sala Uno', category: 'Conciertos', price: 20, has_multiple_prices: false, capacity: 10, available_capacity: 10 }
    vi.stubGlobal('fetch', vi.fn(async (input: string | URL | Request) => String(input).endsWith('/api/auth/session')
      ? { ok: false, status: 401, json: async () => ({}) }
      : { ok: true, status: 200, json: async () => [event] }))

    render(<App />)
    await screen.findByRole('heading', { name: 'Evento accesible' })
    await expectNoAccessibilityViolations()

    fireEvent.click(screen.getByRole('button', { name: /Más filtros/ }))
    fireEvent.click(screen.getByRole('button', { name: 'Rango de fechas Seleccionar rango' }))
    await screen.findByRole('dialog', { name: 'Seleccionar rango de fechas' })
    await expectNoAccessibilityViolations()
    fireEvent.keyDown(screen.getByRole('dialog', { name: 'Seleccionar rango de fechas' }), { key: 'Escape' })

    fireEvent.click(screen.getByRole('button', { name: 'Ingresar' }))
    await screen.findByRole('heading', { name: 'Inicia sesión' })
    await expectNoAccessibilityViolations()
  })

  it('renders events returned by the API', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: async () => [{
        ...baseEvent,
        id: 1,
        name: 'Evento persistente',
        date: '2026-10-17',
        venue: 'Laboratorio local',
        category: 'Prueba',
        price: 10,
        capacity: 20,
        available_capacity: 19,
      }],
    }))

    render(<App />)

    expect(await screen.findByRole('heading', { name: 'Evento persistente' })).toBeInTheDocument()
    expect(screen.getByText('19 disponibles')).toBeInTheDocument()
  })

  it('uses Desde only when the API confirms multiple real prices', async () => {
    const events = [
      { ...baseEvent, id: 1, name: 'Precio único', date: '2026-10-17', venue: 'Sala Uno', category: 'Conciertos', price: 20, has_multiple_prices: false, capacity: 10, available_capacity: 10 },
      { ...baseEvent, id: 2, name: 'Varias zonas', date: '2026-10-18', venue: 'Sala Dos', category: 'Teatro', price: 25, has_multiple_prices: true, capacity: 10, available_capacity: 10 },
    ]
    vi.stubGlobal('fetch', vi.fn(async (input: string | URL | Request) => String(input).endsWith('/api/auth/session')
      ? { ok: false, status: 401, json: async () => ({}) }
      : { ok: true, status: 200, json: async () => events }))

    render(<App />)
    await screen.findByRole('heading', { name: 'Precio único' })
    expect(screen.queryByText('Desde S/ 20.00')).not.toBeInTheDocument()
    expect(screen.getAllByText('S/ 20.00').length).toBeGreaterThan(0)
    expect(screen.getAllByText('Desde S/ 25.00').length).toBeGreaterThan(0)
  })

  it('updates quantity and total while respecting the minimum', async () => {
    const event = {
      ...baseEvent,
      id: 1,
      name: 'Evento persistente',
      date: '2026-10-17',
      venue: 'Laboratorio local',
      category: 'Prueba',
      price: 10,
      capacity: 20,
      available_capacity: 3,
    }
    vi.stubGlobal('fetch', vi.fn(async (input: string | URL | Request) => {
      const url = String(input)
      if (url.endsWith('/api/auth/session')) return { ok: false, status: 401, json: async () => ({}) }
      if (url.endsWith('/api/events/1')) return { ok: true, status: 200, json: async () => ({ ...event, description: 'Descripción de prueba', zones: [], seats: [] }) }
      return { ok: true, status: 200, json: async () => [event] }
    }))

    render(<App />)
    fireEvent.click(await screen.findByRole('button', { name: 'Ver detalle' }))

    const minus = await screen.findByRole('button', { name: 'Restar una entrada' })
    const plus = screen.getByRole('button', { name: 'Agregar una entrada' })
    expect(minus).toBeDisabled()
    const booking = screen.getByRole('heading', { name: 'Selecciona tus entradas' }).closest('form')
    expect(booking).not.toBeNull()
    expect(within(booking as HTMLFormElement).getAllByText('S/ 10.00')).toHaveLength(2)

    fireEvent.click(plus)
    expect(minus).toBeEnabled()
    expect(screen.getByText('S/ 20.00')).toBeInTheDocument()
  })

  it('shows specific registration errors and can reveal the password', async () => {
    vi.stubGlobal('fetch', vi.fn(async (input: string | URL | Request) => {
      if (String(input).endsWith('/api/auth/session')) return { ok: false, status: 401, json: async () => ({}) }
      return { ok: true, status: 200, json: async () => [] }
    }))

    render(<App />)
    fireEvent.click(screen.getByRole('button', { name: 'Ingresar' }))
    fireEvent.click(await screen.findByRole('tab', { name: 'Registrarme' }))
    fireEvent.click(screen.getByRole('button', { name: 'Crear cuenta de cliente' }))

    expect(screen.getByText('Escribe un nombre de al menos 2 caracteres.')).toBeInTheDocument()
    expect(screen.getByText('El correo es obligatorio.')).toBeInTheDocument()
    expect(screen.getByText('La contraseña es obligatoria.')).toBeInTheDocument()
    const password = screen.getByLabelText('Contraseña')
    expect(password).toHaveAttribute('type', 'password')
    fireEvent.click(screen.getByRole('button', { name: 'Mostrar contraseña' }))
    expect(password).toHaveAttribute('type', 'text')
  })

  it('prevents a duplicate login submission while the request is pending', async () => {
    const fetchMock = vi.fn(async (input: string | URL | Request) => {
      const url = String(input)
      if (url.endsWith('/api/auth/login')) return await new Promise<never>(() => undefined)
      if (url.endsWith('/api/auth/session')) return { ok: false, status: 401, json: async () => ({}) }
      return { ok: true, status: 200, json: async () => [] }
    })
    vi.stubGlobal('fetch', fetchMock)

    render(<App />)
    fireEvent.click(screen.getByRole('button', { name: 'Ingresar' }))
    fireEvent.change(await screen.findByLabelText('Correo'), { target: { value: 'cliente@example.com' } })
    fireEvent.change(screen.getByLabelText('Contraseña'), { target: { value: 'una-frase-segura' } })
    const submit = screen.getByRole('button', { name: 'Iniciar sesión' })
    fireEvent.click(submit)
    fireEvent.click(submit)

    expect(fetchMock.mock.calls.filter(([input]) => String(input).endsWith('/api/auth/login'))).toHaveLength(1)
    expect(screen.getByRole('button', { name: 'Enviando…' })).toBeDisabled()
  })

  it('preserves the pending event and quantity when authentication is required', async () => {
    const event = { ...baseEvent, id: 1, name: 'Evento pendiente', date: '2026-10-17', venue: 'Lima', category: 'Prueba', price: 10, capacity: 5, available_capacity: 5 }
    vi.stubGlobal('fetch', vi.fn(async (input: string | URL | Request) => {
      const url = String(input)
      if (url.endsWith('/api/auth/session')) return { ok: false, status: 401, json: async () => ({}) }
      if (url.endsWith('/api/events/1')) return { ok: true, status: 200, json: async () => ({ ...event, description: 'Descripción suficiente', zones: [], seats: [] }) }
      return { ok: true, status: 200, json: async () => [event] }
    }))

    render(<App />)
    fireEvent.click(await screen.findByRole('button', { name: 'Ver detalle' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Agregar una entrada' }))
    fireEvent.click(screen.getByRole('button', { name: 'Inicia sesión para reservar' }))

    expect(await screen.findByText('Tu reserva está en espera')).toBeInTheDocument()
    expect(screen.getByText('Evento pendiente')).toBeInTheDocument()
    expect(screen.getByText('2 entrada(s) · S/ 20.00')).toBeInTheDocument()
  })

  it('returns to login with a clear notice when a private request is unauthorized', async () => {
    vi.stubGlobal('fetch', vi.fn(async (input: string | URL | Request) => {
      const url = String(input)
      if (url.endsWith('/api/auth/session')) return { ok: true, status: 200, json: async () => ({ id: '1', email: 'client@example.com', display_name: 'Cliente', role: 'client', session_expires_at: '2026-10-05T00:00:00Z' }) }
      if (url.includes('/api/me/')) return { ok: false, status: 401, json: async () => ({ detail: 'Sesión expirada' }) }
      return { ok: true, status: 200, json: async () => [] }
    }))

    render(<App />)
    fireEvent.click(await screen.findByRole('button', { name: 'Mis entradas' }))

    expect(await screen.findByRole('heading', { name: 'Inicia sesión' })).toBeInTheDocument()
    expect(screen.getByText('Tu sesión expiró. Vuelve a iniciar sesión.')).toBeInTheDocument()
  })

  it('opens the accessible account menu and performs the real logout action', async () => {
    const fetchMock = vi.fn(async (input: string | URL | Request) => {
      const url = String(input)
      if (url.endsWith('/api/auth/session')) return { ok: true, status: 200, json: async () => ({ id: '1', email: 'client@example.com', display_name: 'Cliente Demo', role: 'client', session_expires_at: '2026-10-05T00:00:00Z' }) }
      if (url.endsWith('/api/auth/logout')) return { ok: true, status: 204, json: async () => ({}) }
      return { ok: true, status: 200, json: async () => [] }
    })
    vi.stubGlobal('fetch', fetchMock)

    render(<App />)
    const trigger = await screen.findByRole('button', { name: 'Abrir menú de Cliente Demo' })
    fireEvent.keyDown(trigger, { key: 'ArrowDown' })
    expect(screen.getByText('Cliente Demo')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('menuitem', { name: 'Cerrar sesión' }))

    await waitFor(() => expect(fetchMock.mock.calls.some(([input]) => String(input).endsWith('/api/auth/logout'))).toBe(true))
    expect(screen.getByText('Sesión cerrada correctamente.')).toBeInTheDocument()
  })

  it('moves focus into the private ticket dialog and restores it on Escape', async () => {
    const reservation = { id: 'reservation-1', event_id: 1, event_name: 'Evento QR', quantity: 1, created_at: '2026-10-06T10:00:00Z' }
    const ticket = { id: 'ticket-1', reservation_id: 'reservation-1', event_id: 1, event_name: 'Evento QR', event_date: '2026-10-20', event_time: '19:30:00', event_venue: 'Sala Uno', event_city: 'Lima', image_path: null, ticket_type: 'general', zone: null, row: null, seat: null, unit_price: 20, qr_token: 'nexo_token_ficticio_para_prueba', used_at: null }
    vi.stubGlobal('fetch', vi.fn(async (input: string | URL | Request) => {
      const url = String(input)
      if (url.endsWith('/api/auth/session')) return { ok: true, status: 200, json: async () => ({ id: '1', email: 'client@example.com', display_name: 'Cliente Demo', role: 'client', session_expires_at: '2026-10-06T18:00:00Z' }) }
      if (url.endsWith('/api/me/reservations')) return { ok: true, status: 200, json: async () => [reservation] }
      if (url.endsWith('/api/me/tickets')) return { ok: true, status: 200, json: async () => [ticket] }
      return { ok: true, status: 200, json: async () => [] }
    }))

    render(<App />)
    fireEvent.click(await screen.findByRole('button', { name: 'Mis entradas' }))
    const trigger = await screen.findByRole('button', { name: 'Abrir entrada 1 para Evento QR' })
    trigger.focus()
    fireEvent.click(trigger)
    const close = await screen.findByRole('button', { name: 'Cerrar entrada' })
    await waitFor(() => expect(close).toHaveFocus())
    await expectNoAccessibilityViolations()
    fireEvent.keyDown(window, { key: 'Escape' })
    await waitFor(() => expect(trigger).toHaveFocus())
  })

  it('combines category and city filters and can clear them', async () => {
    const events = [
      { ...baseEvent, id: 1, name: 'Concierto Lima', date: '2026-10-17', venue: 'Teatro Uno', category: 'Conciertos', price: 20, capacity: 10, available_capacity: 10 },
      { ...baseEvent, id: 2, name: 'Taller Callao', date: '2026-10-18', venue: 'Centro Dos', city: 'Callao', category: 'Talleres', price: 0, capacity: 10, available_capacity: 10 },
    ]
    vi.stubGlobal('fetch', vi.fn(async (input: string | URL | Request) => String(input).endsWith('/api/auth/session')
      ? { ok: false, status: 401, json: async () => ({}) }
      : { ok: true, status: 200, json: async () => events }))

    render(<App />)
    expect(await screen.findByRole('heading', { name: 'Concierto Lima' })).toBeInTheDocument()
    expect(screen.getAllByRole('textbox', { name: 'Buscar eventos' })).toHaveLength(1)
    fireEvent.click(screen.getByRole('button', { name: 'Siguiente evento destacado' }))
    expect(screen.getByRole('button', { name: 'Abrir evento destacado Taller Callao' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Talleres' }))
    fireEvent.click(screen.getByRole('button', { name: 'Ciudad Todas' }))
    fireEvent.click(screen.getByRole('option', { name: 'Callao' }))
    expect(screen.queryByRole('heading', { name: 'Concierto Lima' })).not.toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Taller Callao' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Ciudad: Callao' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Limpiar todos' }))
    expect(screen.getByRole('heading', { name: 'Concierto Lima' })).toBeInTheDocument()
  })

  it('renders the expanded category set with icons and keeps selection functional', async () => {
    const events = [
      { ...baseEvent, id: 1, name: 'Foro digital', date: '2026-10-17', venue: 'Hub Uno', category: 'Tecnología', price: 20, capacity: 10, available_capacity: 10 },
      { ...baseEvent, id: 2, name: 'Encuentro profesional', date: '2026-10-18', venue: 'Centro Dos', category: 'Networking', price: 0, capacity: 10, available_capacity: 10 },
      { ...baseEvent, id: 3, name: 'Muestra visual', date: '2026-10-19', venue: 'Galería Tres', category: 'Exposiciones', price: 15, capacity: 10, available_capacity: 10 },
    ]
    vi.stubGlobal('fetch', vi.fn(async (input: string | URL | Request) => String(input).endsWith('/api/auth/session')
      ? { ok: false, status: 401, json: async () => ({}) }
      : { ok: true, status: 200, json: async () => events }))

    render(<App />)
    await screen.findByRole('heading', { name: 'Foro digital' })
    const technology = screen.getByRole('button', { name: 'Tecnología' })
    expect(technology.querySelector('svg')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Networking' }).querySelector('svg')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Exposiciones' }).querySelector('svg')).toBeInTheDocument()
    fireEvent.click(technology)
    expect(technology).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByRole('heading', { name: 'Foro digital' })).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Encuentro profesional' })).not.toBeInTheDocument()
  })

  it('operates the custom filters with keyboard and restores focus', async () => {
    const events = [
      { ...baseEvent, id: 1, name: 'Evento Lima', date: '2026-10-17', venue: 'Sala Uno', category: 'Conciertos', price: 20, capacity: 10, available_capacity: 10 },
      { ...baseEvent, id: 2, name: 'Evento Callao', date: '2026-10-18', venue: 'Sala Dos', city: 'Callao', category: 'Talleres', price: 0, capacity: 10, available_capacity: 10 },
    ]
    vi.stubGlobal('fetch', vi.fn(async (input: string | URL | Request) => String(input).endsWith('/api/auth/session')
      ? { ok: false, status: 401, json: async () => ({}) }
      : { ok: true, status: 200, json: async () => events }))

    render(<App />)
    await screen.findByRole('heading', { name: 'Evento Lima' })
    const city = screen.getByRole('button', { name: 'Ciudad Todas' })
    city.focus()
    fireEvent.keyDown(city, { key: 'ArrowDown' })
    const listbox = await screen.findByRole('listbox', { name: 'Ciudad' })
    fireEvent.keyDown(listbox, { key: 'ArrowDown' })
    fireEvent.keyDown(listbox, { key: 'Enter' })

    expect(screen.getByRole('button', { name: 'Ciudad Callao' })).toHaveFocus()
    expect(screen.getByRole('button', { name: 'Ciudad: Callao' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Fecha Cualquier fecha' }))
    const dateListbox = screen.getByRole('listbox', { name: 'Fecha' })
    fireEvent.keyDown(dateListbox, { key: 'Escape' })
    expect(screen.queryByRole('listbox', { name: 'Fecha' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Fecha Cualquier fecha' })).toHaveFocus()
    fireEvent.click(screen.getByRole('button', { name: 'Precio Todos' }))
    expect(screen.getByRole('listbox', { name: 'Precio' })).toBeInTheDocument()
    fireEvent.pointerDown(document.body)
    expect(screen.queryByRole('listbox', { name: 'Precio' })).not.toBeInTheDocument()
  })

  it('selects and applies an accessible date range without native date inputs', async () => {
    const events = [
      { ...baseEvent, id: 1, name: 'Dentro del rango', date: '2026-10-12', venue: 'Sala Uno', category: 'Conciertos', price: 20, capacity: 10, available_capacity: 10 },
      { ...baseEvent, id: 2, name: 'Fuera del rango', date: '2026-10-25', venue: 'Sala Dos', category: 'Talleres', price: 0, capacity: 10, available_capacity: 10 },
    ]
    vi.stubGlobal('fetch', vi.fn(async (input: string | URL | Request) => String(input).endsWith('/api/auth/session')
      ? { ok: false, status: 401, json: async () => ({}) }
      : { ok: true, status: 200, json: async () => events }))

    render(<App />)
    await screen.findByRole('heading', { name: 'Dentro del rango' })
    fireEvent.click(screen.getByRole('button', { name: /Más filtros/ }))
    const trigger = screen.getByRole('button', { name: 'Rango de fechas Seleccionar rango' })
    fireEvent.click(trigger)
    expect(screen.getByRole('dialog', { name: 'Seleccionar rango de fechas' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'martes, 20 de octubre de 2026' }))
    fireEvent.click(screen.getByRole('button', { name: 'miércoles, 7 de octubre de 2026' }))
    expect(screen.getByText(/07 oct.*selecciona el final/i)).toBeInTheDocument()
    const start = screen.getByRole('button', { name: 'miércoles, 7 de octubre de 2026' })
    fireEvent.keyDown(start, { key: 'ArrowRight' })
    await waitFor(() => expect(screen.getByRole('button', { name: 'jueves, 8 de octubre de 2026' })).toHaveFocus())
    fireEvent.click(screen.getByRole('button', { name: 'martes, 20 de octubre de 2026' }))
    expect(screen.getByText(/07 oct.*20 oct/i)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Aplicar' }))

    expect(screen.getByRole('button', { name: /Rango de fechas 07 oct.*20 oct/i })).toHaveFocus()
    expect(screen.getByRole('heading', { name: 'Dentro del rango' })).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Fuera del rango' })).not.toBeInTheDocument()
    expect(document.querySelector('input[type="date"]')).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /Rango de fechas 07 oct.*20 oct/i }))
    fireEvent.keyDown(screen.getByRole('dialog', { name: 'Seleccionar rango de fechas' }), { key: 'Escape' })
    expect(screen.queryByRole('dialog', { name: 'Seleccionar rango de fechas' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Rango de fechas 07 oct.*20 oct/i })).toHaveFocus()
  })

  it('selects a numbered seat and uses the server-defined price', async () => {
    const event = { ...baseEvent, id: 3, name: 'Teatro numerado', date: '2026-10-19', venue: 'Sala Central', category: 'Teatro', price: 30, capacity: 2, available_capacity: 2, ticket_mode: 'seats' as const, layout_kind: 'theatre' as const }
    vi.stubGlobal('fetch', vi.fn(async (input: string | URL | Request) => {
      const url = String(input)
      if (url.endsWith('/api/auth/session')) return { ok: false, status: 401, json: async () => ({}) }
      if (url.endsWith('/api/events/3')) return { ok: true, status: 200, json: async () => ({ ...event, description: 'Obra ficticia', zones: [{ id: 8, name: 'Platea', price: 42, capacity: 2, available_capacity: 2 }], seats: [{ id: 41, zone_id: 8, zone_name: 'Platea', row: 'A', number: 1, price: 42, available: true }, { id: 42, zone_id: 8, zone_name: 'Platea', row: 'A', number: 2, price: 42, available: false }] }) }
      return { ok: true, status: 200, json: async () => [event] }
    }))

    render(<App />)
    fireEvent.click(await screen.findByRole('button', { name: 'Ver detalle' }))
    const available = await screen.findByRole('button', { name: 'Zona Platea, fila A, asiento 1, disponible' })
    const occupied = screen.getByRole('button', { name: 'Zona Platea, fila A, asiento 2, ocupado' })
    expect(occupied).toBeDisabled()
    expect(screen.getByRole('group', { name: 'Zoom del plano' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Acercar plano' }))
    expect(screen.getByText('Ningún asiento seleccionado')).toBeInTheDocument()
    fireEvent.click(available)
    expect(screen.getByText('Platea A-1')).toBeInTheDocument()
    expect(screen.getByText('S/ 42.00')).toBeInTheDocument()
    expect(screen.getByText('1 asiento seleccionado')).toBeInTheDocument()
    await expectNoAccessibilityViolations()
  })

  it('keeps the accessible 2D plan and selection when WebGL is unavailable for a 3D venue', async () => {
    const theatre = { ...baseEvent, id: 31, name: 'Sala sin WebGL', date: '2026-11-10', venue: 'Auditorio', category: 'Teatro', price: 30, capacity: 2, available_capacity: 2, ticket_mode: 'seats' as const, layout_kind: 'theatre' as const }
    const concert = { ...baseEvent, id: 32, name: 'Arena sin WebGL', date: '2026-11-11', venue: 'Arena', category: 'Conciertos', price: 45, capacity: 20, available_capacity: 20, ticket_mode: 'zones' as const, layout_kind: 'concert_zones' as const }
    const details: Record<number, unknown> = {
      31: { ...theatre, description: 'Teatro', zones: [{ id: 1, name: 'Platea', price: 30, capacity: 2, available_capacity: 2 }], seats: [{ id: 1, zone_id: 1, zone_name: 'Platea', row: 'A', number: 1, price: 30, available: true }] },
      32: { ...concert, description: 'Concierto', zones: [{ id: 3, name: 'Campo', price: 45, capacity: 20, available_capacity: 20 }], seats: [] },
    }
    vi.stubGlobal('fetch', vi.fn(async (input: string | URL | Request) => {
      const url = String(input)
      if (url.endsWith('/api/auth/session')) return { ok: false, status: 401, json: async () => ({}) }
      const match = url.match(/\/api\/events\/(\d+)$/)
      return { ok: true, status: 200, json: async () => match ? details[Number(match[1])] : [theatre, concert] }
    }))
    render(<App />)
    await screen.findByRole('heading', { name: 'Sala sin WebGL' })
    fireEvent.click(screen.getByRole('button', { name: 'Ver Sala sin WebGL' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Zona Platea, fila A, asiento 1, disponible' }))
    fireEvent.click(screen.getByRole('button', { name: 'Sala 3D' }))
    expect(await screen.findByText(/La sala 3D no está disponible en este dispositivo/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Sala 3D' })).toBeDisabled()
    expect(screen.getByText('1 asiento seleccionado')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Zona Platea, fila A, asiento 1, seleccionado' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Ver Arena sin WebGL' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Recinto 3D' }))
    await waitFor(() => expect(screen.getByRole('button', { name: 'Recinto 3D' })).toBeDisabled())
    expect(screen.getByLabelText('Plano del concierto')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /Campo/ }))
    expect(screen.getByRole('button', { name: /Campo/ })).toHaveAttribute('aria-pressed', 'true')
  })

  it('renders the configured plan instead of a universal auditorium fallback', async () => {
    const cases = [
      { ...baseEvent, id: 21, name: 'Teatro explícito', date: '2026-11-01', venue: 'Auditorio', category: 'Teatro', price: 30, capacity: 2, available_capacity: 2, ticket_mode: 'seats' as const, layout_kind: 'theatre' as const },
      { ...baseEvent, id: 22, name: 'Estadio explícito', date: '2026-11-02', venue: 'Estadio', category: 'Deportes', price: 40, capacity: 2, available_capacity: 2, ticket_mode: 'seats' as const, layout_kind: 'stadium' as const },
      { ...baseEvent, id: 23, name: 'Concierto por zonas', date: '2026-11-03', venue: 'Arena', category: 'Conciertos', price: 45, capacity: 20, available_capacity: 20, ticket_mode: 'zones' as const, layout_kind: 'concert_zones' as const },
      { ...baseEvent, id: 24, name: 'Museo por horario', date: '2026-11-04', venue: 'Museo', category: 'Exposiciones', price: 18, capacity: 20, available_capacity: 20, layout_kind: 'museum' as const },
      { ...baseEvent, id: 25, name: 'Ingreso general', date: '2026-11-05', venue: 'Parque', category: 'Ferias', price: 0, capacity: 20, available_capacity: 20, layout_kind: 'general' as const },
    ]
    const details: Record<number, unknown> = {
      21: { ...cases[0], description: 'Teatro', zones: [{ id: 1, name: 'Platea', price: 30, capacity: 2, available_capacity: 2 }], seats: [{ id: 1, zone_id: 1, zone_name: 'Platea', row: 'A', number: 1, price: 30, available: true }] },
      22: { ...cases[1], description: 'Estadio', zones: [{ id: 2, name: 'Tribuna Norte', price: 40, capacity: 2, available_capacity: 2 }], seats: [{ id: 2, zone_id: 2, zone_name: 'Tribuna Norte', row: 'A', number: 1, price: 40, available: true }] },
      23: { ...cases[2], description: 'Concierto', zones: [{ id: 3, name: 'Campo', price: 45, capacity: 20, available_capacity: 20 }], seats: [] },
      24: { ...cases[3], description: 'Museo', zones: [], seats: [] },
      25: { ...cases[4], description: 'General', zones: [], seats: [] },
    }
    vi.stubGlobal('fetch', vi.fn(async (input: string | URL | Request) => {
      const url = String(input)
      if (url.endsWith('/api/auth/session')) return { ok: false, status: 401, json: async () => ({}) }
      const match = url.match(/\/api\/events\/(\d+)$/)
      return { ok: true, status: 200, json: async () => match ? details[Number(match[1])] : cases }
    }))
    render(<App />)
    await screen.findByRole('heading', { name: 'Teatro explícito' })
    fireEvent.click(screen.getByRole('button', { name: 'Ver Teatro explícito' }))
    expect(await screen.findByText('Plano del auditorio')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Ver Estadio explícito' }))
    expect(await screen.findByText('Plano del estadio')).toBeInTheDocument()
    expect(screen.getByRole('group', { name: 'Tribunas alrededor de la cancha' })).toBeInTheDocument()
    const north = screen.getByRole('button', { name: /Tribuna Norte, 1 disponibles, S\/ 40.00/ })
    fireEvent.keyDown(north, { key: 'Enter' })
    expect(await screen.findByText('Tribuna Norte · Sector Norte')).toBeInTheDocument()
    const stadiumSeat = screen.getByRole('button', { name: /Tribuna Norte, fila A, asiento 1, disponible, S\/ 40.00/ })
    fireEvent.click(stadiumSeat)
    expect(screen.getByText('1 localidad seleccionada')).toBeInTheDocument()
    expect(screen.getByText('Total: S/ 40.00')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Volver al estadio' }))
    expect(screen.getByText('1 localidad seleccionada')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Vista 3D' }))
    expect(await screen.findByText('Visor 3D · 1 selección')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Plano 2D' }))
    expect(screen.getByText('1 localidad seleccionada')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Ver Concierto por zonas' }))
    expect(await screen.findByLabelText('Plano del concierto')).toBeInTheDocument()
    expect(screen.queryByText('Plano del auditorio')).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Ver Museo por horario' }))
    expect(await screen.findByLabelText('Plano orientativo del museo')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Ver Ingreso general' }))
    expect(await screen.findByText('Acceso sin asiento ni ubicación asignados')).toBeInTheDocument()
    expect(screen.queryByText('Plano del auditorio')).not.toBeInTheDocument()
  })
})
