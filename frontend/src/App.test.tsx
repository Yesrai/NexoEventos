import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import App from './App'

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe('NexoEventos catalog', () => {
  it('renders events returned by the API', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: async () => [{
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
      if (url.endsWith('/api/events/1')) return { ok: true, status: 200, json: async () => ({ ...event, description: 'Descripción de prueba' }) }
      return { ok: true, status: 200, json: async () => [event] }
    }))

    render(<App />)
    fireEvent.click(await screen.findByRole('button', { name: 'Ver detalle' }))

    const minus = await screen.findByRole('button', { name: 'Restar una entrada' })
    const plus = screen.getByRole('button', { name: 'Agregar una entrada' })
    expect(minus).toBeDisabled()
    expect(screen.getAllByText('S/ 10.00')).toHaveLength(3)

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
    const event = { id: 1, name: 'Evento pendiente', date: '2026-10-17', venue: 'Lima', category: 'Prueba', price: 10, capacity: 5, available_capacity: 5 }
    vi.stubGlobal('fetch', vi.fn(async (input: string | URL | Request) => {
      const url = String(input)
      if (url.endsWith('/api/auth/session')) return { ok: false, status: 401, json: async () => ({}) }
      if (url.endsWith('/api/events/1')) return { ok: true, status: 200, json: async () => ({ ...event, description: 'Descripción suficiente' }) }
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
})
