import { render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import App from './App'

afterEach(() => {
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
})
