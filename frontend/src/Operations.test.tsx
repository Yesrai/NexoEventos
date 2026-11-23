import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import axe from 'axe-core'
import { afterEach, describe, expect, it, vi } from 'vitest'

import Operations, { stateOf } from './Operations'
import OrganizerPanel from './Organizer'

const section = (extra: Record<string, unknown> = {}) => ({ estado: 'OK', origen: 'local', detalle: 'detalle', actualizado: '2026-11-17T15:00:00Z', ...extra })
const overview = {
  generado: '2026-11-17T15:00:00Z', solo_lectura: true,
  secciones: {
    servicios: section({ estado: 'ADVERTENCIA', detalle: 'solo la API y la base local están verificadas', servicios: { api: { estado: 'OK', origen: 'local' }, base_de_datos: { estado: 'OK', origen: 'local' }, rds_aws: { estado: 'No verificado', origen: 'sin_datos' } } }),
    respaldo: section({ detalle: 'último respaldo correcto hace 10 min', ultimo: { nombre: 'nexoeventos-rds-20261117T010203Z.cms', terminado: '2026-11-17T14:50:00Z' }, edad_min: 10, max_age_min: 90, rpo: 'dentro', objeto_en_el_destino: 'No verificado' }),
    lease: section({ estado: 'ADVERTENCIA', titular_local: false, epoca: 2, segundos_restantes: 0, perdido: true, almacen_remoto: 'No verificado' }),
    compuerta: section({ modo: 'enforce', rol: 'primary', bloqueos: { http: 3, sql: 1, commit: 0 } }),
    failover: section({ estado: 'ERROR', origen: 'simulado', registro: { estado: 'UNCERTAIN_DNS', epoca: 2 }, ultima_ejecucion: { resultado: 'ABORTED', estado_seguro: 'DNS INCIERTO', etapas: ['PRECHECK', 'DECIDE', 'FENCE_CHECK'], incidente: { clase: 'INSTANCE_DOWN', promovible: true }, vallado: { veredicto: 'FENCED', evidencia: [{ tipo: 'aws_instance', fuerza: 'verified' }] } }, modo: 'FAILOVER_AUTOMATICO', failover_real_validado: false }),
  },
}
const reply = (status: number, body: unknown = {}) => ({ ok: status >= 200 && status < 300, status, json: async () => body })

afterEach(() => { cleanup(); vi.unstubAllGlobals() })

describe('Panel de operación', () => {
  it('muestra estados, origen y última actualización con datos válidos', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => reply(200, overview)))
    render(<Operations />)
    const backup = await screen.findByRole('article', { name: 'Último respaldo y RPO' })
    expect(within(backup).getByText('Correcto')).toBeInTheDocument()
    expect(within(backup).getByText('Local')).toBeInTheDocument()
    expect(within(backup).getByText('nexoeventos-rds-20261117T010203Z.cms')).toBeInTheDocument()
    expect(within(backup).getByText('dentro')).toBeInTheDocument()
    expect(within(backup).getByText('Objeto en el destino').nextSibling).toHaveTextContent('No verificado')   // un registro local no prueba el destino
    expect(within(screen.getByRole('article', { name: 'Servicios' })).getByText('Base de datos')).toBeInTheDocument()              // etiqueta legible, no el identificador
    expect(within(screen.getByRole('article', { name: 'Servicios' })).getByText('RDS (AWS)')).toBeInTheDocument()
    expect(within(screen.getByRole('article', { name: 'Servicios' })).getByText('Advertencia')).toBeInTheDocument()
    expect(within(screen.getByRole('article', { name: 'Servicios' })).getAllByText('No verificado').length).toBeGreaterThan(0)
    expect(within(screen.getByRole('article', { name: 'Lease de escritura' })).getByText('Titular en este proceso').nextSibling).toHaveTextContent('No')
    const fo = screen.getByRole('article', { name: 'Failover' })
    expect(within(fo).getByText('Error')).toBeInTheDocument(); expect(within(fo).getByText('Simulado')).toBeInTheDocument()
    expect(within(fo).getByText('Failover real validado').nextSibling).toHaveTextContent('No')
    expect(screen.getByText(/Última actualización:/)).toBeInTheDocument()
    expect(screen.queryByText('Cloud verificado')).not.toBeInTheDocument()                        // nada aparece verificado en la nube sin evidencia
  })

  it('estados desconocidos, ausentes o inventados se muestran como «No verificado», nunca como sanos', async () => {
    expect(stateOf('OK').label).toBe('Correcto')
    for (const bad of [undefined, null, '', 'SANO', 'healthy', 'ok', 42]) expect(stateOf(bad).label).toBe('No verificado')
    vi.stubGlobal('fetch', vi.fn(async () => reply(200, { generado: 'x', solo_lectura: true, secciones: { servicios: { estado: 'healthy', origen: 'aws' }, respaldo: {}, lease: { estado: 'No verificado' } } })))
    render(<Operations />)
    const card = await screen.findByRole('article', { name: 'Servicios' })
    expect(within(card).getByText('No verificado', { selector: '.ops-badge' })).toBeInTheDocument()
    expect(within(card).getByText('Sin datos')).toBeInTheDocument()                                  // un origen desconocido no se presenta como cloud
    expect(screen.getAllByText('No verificado', { selector: '.ops-badge' }).length).toBe(5)         // incluidas las secciones ausentes (compuerta, failover)
    expect(screen.queryByText('Correcto')).not.toBeInTheDocument()
  })

  it('muestra la secuencia del incidente: modo, clasificación, vallado con su evidencia y que el failover real NO está validado', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => reply(200, overview)))
    render(<Operations />)
    expect(await screen.findByText('Failover automático')).toBeInTheDocument()
    expect(screen.getByText('INSTANCE_DOWN')).toBeInTheDocument()
    expect(screen.getByText('FENCED')).toBeInTheDocument()
    expect(screen.getByText('aws_instance (verificada)')).toBeInTheDocument()
    expect(screen.getByText('PRECHECK → DECIDE → FENCE_CHECK')).toBeInTheDocument()
  })

  it.each([[401, /no tiene permiso/], [403, /no tiene permiso/], [404, /desactivado/], [500, /No se pudo consultar/]])('muestra el error del API (%i) sin datos falsos', async (status, text) => {
    vi.stubGlobal('fetch', vi.fn(async () => reply(status)))
    render(<Operations />)
    expect(await screen.findByRole('alert')).toHaveTextContent(text)
    expect(screen.queryByRole('article')).not.toBeInTheDocument()
  })

  it('maneja fallos de red y respuestas con formato inválido', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => { throw new TypeError('network') }))
    const { unmount } = render(<Operations />)
    expect(await screen.findByRole('alert')).toHaveTextContent(/No se pudo consultar/); unmount()
    vi.stubGlobal('fetch', vi.fn(async () => reply(200, { otra: 'cosa' })))
    render(<Operations />)
    expect(await screen.findByRole('alert')).toHaveTextContent(/formato esperado/)
  })

  it('actualiza bajo demanda y es solo de lectura (sin controles destructivos ni de failover)', async () => {
    const fetchMock = vi.fn(async () => reply(200, overview)); vi.stubGlobal('fetch', fetchMock)
    render(<Operations />)
    await screen.findByRole('article', { name: 'Failover' })
    expect(fetchMock).toHaveBeenCalledTimes(1)
    fireEvent.click(screen.getByRole('button', { name: 'Actualizar' }))
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2))
    expect(screen.getAllByRole('button').map((b) => b.textContent)).toEqual(['Actualizar'])        // el único control es actualizar
    for (const call of fetchMock.mock.calls) expect((call as unknown as [string, RequestInit?])[1]?.method ?? 'GET').toBe('GET')
    expect(screen.queryByText(/ejecutar failover|promover|apagar|reiniciar|borrar/i)).not.toBeInTheDocument()
  })

  it('no presenta violaciones de accesibilidad automáticas', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => reply(200, overview)))
    const { container } = render(<Operations />)
    await screen.findByRole('article', { name: 'Failover' })
    const result = await axe.run(container, { rules: { 'color-contrast': { enabled: false } } })
    expect(result.violations.map((v) => v.id)).toEqual([])
  })
})

describe('Integración con el panel del organizador', () => {
  it('la pestaña «Operación» consulta /api/ops/overview y se puede volver a «Gestión»', async () => {
    const calls: string[] = []
    vi.stubGlobal('fetch', vi.fn(async (url: string) => {
      calls.push(String(url))
      if (String(url).endsWith('/api/ops/overview')) return reply(200, overview)
      return reply(200, [])
    }))
    render(<OrganizerPanel />)
    await screen.findByRole('group', { name: 'Sección del panel' })
    expect(calls.some((c) => c.endsWith('/api/ops/overview'))).toBe(false)                          // no se consulta hasta que se abre la pestaña
    fireEvent.click(screen.getByRole('button', { name: 'Operación' }))
    expect(await screen.findByRole('article', { name: 'Compuerta de escritura' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Operación' })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.queryByRole('button', { name: 'Nuevo evento' })).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Gestión' }))
    await waitFor(() => expect(screen.queryByRole('article', { name: 'Compuerta de escritura' })).not.toBeInTheDocument())
    expect(await screen.findByRole('button', { name: 'Nuevo evento' })).toBeInTheDocument()
  })
})
