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
})
