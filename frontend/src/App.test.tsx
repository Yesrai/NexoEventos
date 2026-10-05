import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import App from './App'

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
    is_demo: true,
  }

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
    expect(screen.getAllByText('S/ 10.00')).toHaveLength(2)

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

  it('selects a numbered seat and uses the server-defined price', async () => {
    const event = { ...baseEvent, id: 3, name: 'Teatro numerado', date: '2026-10-19', venue: 'Sala Central', category: 'Teatro', price: 30, capacity: 2, available_capacity: 2, ticket_mode: 'seats' as const }
    vi.stubGlobal('fetch', vi.fn(async (input: string | URL | Request) => {
      const url = String(input)
      if (url.endsWith('/api/auth/session')) return { ok: false, status: 401, json: async () => ({}) }
      if (url.endsWith('/api/events/3')) return { ok: true, status: 200, json: async () => ({ ...event, description: 'Obra ficticia', zones: [{ id: 8, name: 'Platea', price: 42, capacity: 2, available_capacity: 2 }], seats: [{ id: 41, zone_id: 8, zone_name: 'Platea', row: 'A', number: 1, price: 42, available: true }, { id: 42, zone_id: 8, zone_name: 'Platea', row: 'A', number: 2, price: 42, available: false }] }) }
      return { ok: true, status: 200, json: async () => [event] }
    }))

    render(<App />)
    fireEvent.click(await screen.findByRole('button', { name: 'Ver detalle' }))
    const available = await screen.findByRole('button', { name: 'Fila A, asiento 1, disponible' })
    const occupied = screen.getByRole('button', { name: 'Fila A, asiento 2, ocupado' })
    expect(occupied).toBeDisabled()
    fireEvent.click(available)
    expect(screen.getByText('Platea A-1')).toBeInTheDocument()
    expect(screen.getByText('S/ 42.00')).toBeInTheDocument()
  })
})
