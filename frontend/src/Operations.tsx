import { useCallback, useEffect, useState } from 'react'
import { api } from './shared'

type Section = { estado?: string; origen?: string; detalle?: string; actualizado?: string; [key: string]: unknown }
type Overview = { generado: string; solo_lectura: boolean; secciones: Record<'servicios' | 'respaldo' | 'lease' | 'compuerta' | 'failover', Section> }
const SERVICE_LABELS: Record<string, string> = { api: 'API', base_de_datos: 'Base de datos', balanceador_aws: 'Balanceador (AWS)', rds_aws: 'RDS (AWS)', oci_recuperacion: 'Recuperación (OCI)', azure_monitoreo: 'Monitoreo (Azure)' }
type Load = { kind: 'loading' } | { kind: 'ok'; data: Overview; at: Date } | { kind: 'error'; text: string }

const ORIGINS: Record<string, string> = { local: 'Local', simulado: 'Simulado', cloud_verificado: 'Cloud verificado', sin_datos: 'Sin datos' }
const STATES: Record<string, { label: string; cls: string }> = {
  OK: { label: 'Correcto', cls: 'ops-ok' }, ADVERTENCIA: { label: 'Advertencia', cls: 'ops-warn' }, ERROR: { label: 'Error', cls: 'ops-err' },
}
const TITLES: Array<[keyof Overview['secciones'], string]> = [['servicios', 'Servicios'], ['respaldo', 'Último respaldo y RPO'], ['lease', 'Lease de escritura'], ['compuerta', 'Compuerta de escritura'], ['failover', 'Failover']]

// Todo lo que no sea un estado conocido se muestra como «No verificado»: nunca se asume sano.
export const stateOf = (value: unknown) => STATES[String(value)] ?? { label: 'No verificado', cls: 'ops-unk' }
const originOf = (value: unknown) => ORIGINS[String(value)] ?? 'Sin datos'
const show = (value: unknown) => value === null || value === undefined || value === '' ? 'No verificado' : typeof value === 'boolean' ? (value ? 'Sí' : 'No') : String(value)
const time = (iso?: string) => { const d = iso ? new Date(iso) : null; return d && !Number.isNaN(d.getTime()) ? d.toLocaleString('es-PE', { timeZone: 'America/Lima', dateStyle: 'short', timeStyle: 'medium' }) : 'No verificado' }
const obj = (value: unknown): Record<string, unknown> => (typeof value === 'object' && value !== null && !Array.isArray(value) ? value as Record<string, unknown> : {})

function Badge({ estado }: { estado?: string }) { const s = stateOf(estado); return <span className={`ops-badge ${s.cls}`}>{s.label}</span> }
function Rows({ rows }: { rows: Array<[string, unknown]> }) { return <dl className="ops-rows">{rows.map(([k, v]) => <div key={k}><dt>{k}</dt><dd>{show(v)}</dd></div>)}</dl> }

function Details({ id, s }: { id: keyof Overview['secciones']; s: Section }) {
  if (id === 'servicios') {
    const items = obj(s.servicios)
    return <ul className="ops-services">{Object.entries(items).map(([name, v]) => { const it = obj(v); return <li key={name}><span>{SERVICE_LABELS[name] ?? name.replace(/_/g, ' ')}</span><Badge estado={String(it.estado)} /><small>{originOf(it.origen)}</small></li> })}</ul>
  }
  if (id === 'respaldo') {
    const last = obj(s.ultimo)
    return <Rows rows={[['Último respaldo', last.nombre], ['Terminó', last.terminado ? time(String(last.terminado)) : null], ['Edad (min)', s.edad_min], ['Umbral RPO (min)', s.max_age_min], ['Estado de RPO', s.rpo], ['Objeto en el destino', s.objeto_en_el_destino]]} />
  }
  if (id === 'lease') return <Rows rows={[['Titular en este proceso', s.titular_local], ['Época', s.epoca], ['Segundos restantes', s.segundos_restantes], ['Perdido', s.perdido], ['Almacén remoto', s.almacen_remoto]]} />
  if (id === 'compuerta') { const b = obj(s.bloqueos); const vb = obj(s.vallado_en_base); return <Rows rows={[['Modo', s.modo], ['Rol', s.rol], ['Bloqueos HTTP', b.http], ['Bloqueos SQL', b.sql], ['Commits abortados', b.commit], ['Vallado en la base', vb.activo === true ? 'activo' : 'inactivo'], ['Última sincronización con la base', vb.ultima_sincronizacion_ok], ['Errores de sincronización', vb.errores_de_sincronizacion]]} /> }
  const reg = obj(s.registro), run = obj(s.ultima_ejecucion), inc = obj(run.incidente), fen = obj(run.vallado)
  const MODOS: Record<string, string> = { RECUPERACION_DESDE_RESPALDO: 'Recuperación desde respaldo', STANDBY_PREPARADO: 'Standby preparado', FAILOVER_AUTOMATICO: 'Failover automático', FAILBACK: 'Failback' }
  const ev = Array.isArray(fen.evidencia) ? (fen.evidencia as Array<Record<string, unknown>>).map(e => `${String(e.tipo)} (${e.fuerza === 'verified' ? 'verificada' : 'inferida'})`).join(', ') : null
  const etapas = Array.isArray(run.etapas) ? (run.etapas as unknown[]).join(' → ') : null
  return <Rows rows={[['Modo', MODOS[String(s.modo)] ?? 'Recuperación desde respaldo'], ['Registro de promoción', reg.estado], ['Época', reg.epoca], ['Última ejecución', run.resultado], ['Estado seguro', run.estado_seguro],
    ['Clasificación del incidente', inc.clase], ['Promovible', inc.promovible], ['Vallado del primario', fen.veredicto], ['Evidencia de vallado', ev], ['Secuencia', etapas], ['Failover real validado', s.failover_real_validado ?? false]]} />
}

export default function Operations() {
  const [load, setLoad] = useState<Load>({ kind: 'loading' })
  const refresh = useCallback(async () => {
    setLoad({ kind: 'loading' })
    try {
      const response = await api('/api/ops/overview')
      if (response.status === 401 || response.status === 403) return setLoad({ kind: 'error', text: 'Tu cuenta no tiene permiso para ver el estado operativo.' })
      if (response.status === 404) return setLoad({ kind: 'error', text: 'El panel de operación está desactivado en este servidor.' })
      if (!response.ok) return setLoad({ kind: 'error', text: 'No se pudo consultar el estado operativo. Inténtalo de nuevo.' })
      const data = await response.json() as Overview
      if (!data || typeof data !== 'object' || !data.secciones) return setLoad({ kind: 'error', text: 'La respuesta del servidor no tiene el formato esperado.' })
      setLoad({ kind: 'ok', data, at: new Date() })
    } catch { setLoad({ kind: 'error', text: 'No se pudo consultar el estado operativo. Inténtalo de nuevo.' }) }
  }, [])
  useEffect(() => { void refresh() }, [refresh])

  return <section className="ops" aria-label="Operación">
    <div className="ops-head">
      <div><h2>Operación</h2><p className="muted">Solo lectura. «Local» es lo que este servidor comprueba por sí mismo; «Simulado» viene de pruebas; nada se marca como «Cloud verificado» sin evidencia real.</p></div>
      <div className="ops-actions"><button type="button" className="outline" onClick={() => void refresh()} disabled={load.kind === 'loading'}>{load.kind === 'loading' ? 'Actualizando…' : 'Actualizar'}</button>{load.kind === 'ok' && <small className="muted">Última actualización: {time(load.at.toISOString())}</small>}</div>
    </div>
    {load.kind === 'loading' && <div className="status" role="status"><span className="spinner" />Consultando el estado operativo…</div>}
    {load.kind === 'error' && <div className="status dark" role="alert">{load.text}</div>}
    {load.kind === 'ok' && <div className="ops-grid">{TITLES.map(([id, title]) => { const s = load.data.secciones[id] ?? {}; return <article key={id} className="ops-card" aria-label={title}>
      <header><h3>{title}</h3><Badge estado={s.estado} /></header>
      <p className="ops-origin"><span className="ops-chip">{originOf(s.origen)}</span>{s.actualizado ? <small>Actualizado: {time(s.actualizado)}</small> : <small>Actualizado: No verificado</small>}</p>
      <p>{s.detalle ?? 'No verificado'}</p>
      <Details id={id} s={s} />
    </article> })}</div>}
  </section>
}
