import { FormEvent, useEffect, useRef, useState } from 'react'
import { api, BarcodeDetectorConstructor, EventItem, formatDate, formatTime, Icon, messageFrom } from './shared'

type Tone = 'ok' | 'warn' | 'error'
type Result = { tone: Tone; title: string; detail: string; note?: string }

const limaTime = (iso: string) => new Intl.DateTimeFormat('es-PE', { hour: 'numeric', minute: '2-digit', timeZone: 'America/Lima' }).format(new Date(iso))

/** Traduce la respuesta del servidor (reglas intactas) a un resultado claro para la puerta. */
export function classify(status: number, body: unknown): Result {
  if (status === 200) {
    const accepted = body as { ticket_location?: string; used_at?: string }
    return { tone: 'ok', title: 'Ingreso aceptado', detail: accepted.ticket_location ?? 'Entrada general', note: `La entrada quedó consumida${accepted.used_at ? ` · ${limaTime(accepted.used_at)}` : ''}.` }
  }
  const message = messageFrom(body, '')
  if (status === 409 && /ya utilizada/i.test(message)) return { tone: 'warn', title: 'Entrada ya utilizada', detail: 'Esta entrada ya registró su ingreso. No permitas el paso sin revisar con el organizador.' }
  if (status === 409) return { tone: 'error', title: 'Entrada de otro evento', detail: message || 'La entrada corresponde a otro evento.' }
  if (status === 404) return { tone: 'error', title: 'Código no válido', detail: 'No existe una entrada con ese código. Revisa el QR e inténtalo de nuevo.' }
  if (status === 403) return { tone: 'error', title: 'Sin autorización', detail: 'Tu cuenta no está asignada a este evento.' }
  return { tone: 'error', title: 'No se pudo validar', detail: message || 'Inténtalo nuevamente.' }
}

export default function OperatorPanel({ onExpired }: { onExpired: () => void }) {
  const [events, setEvents] = useState<EventItem[]>([])
  const [loaded, setLoaded] = useState(false)
  const [eventId, setEventId] = useState(0)
  const [token, setToken] = useState('')
  const [result, setResult] = useState<Result | null>(null)
  const [busy, setBusy] = useState(false)
  const [cameraError, setCameraError] = useState<string | null>(null)
  const [stream, setStream] = useState<MediaStream | null>(null)
  const videoRef = useRef<HTMLVideoElement>(null)
  const fieldRef = useRef<HTMLTextAreaElement>(null)
  const resultRef = useRef<HTMLDivElement>(null)
  const current = events.find((item) => item.id === eventId)
  const detectorSupported = typeof window !== 'undefined' && 'BarcodeDetector' in window

  useEffect(() => { void (async () => {
    const response = await api('/api/operator/events')
    if (response.status === 401) { onExpired(); return }
    if (response.ok) { const values = await response.json() as EventItem[]; setEvents(values); setEventId(values[0]?.id ?? 0) }
    setLoaded(true)
  })() }, [])
  useEffect(() => () => stream?.getTracks().forEach((track) => track.stop()), [stream])
  useEffect(() => { if (videoRef.current && stream) videoRef.current.srcObject = stream }, [stream])
  // Lectura continua: rellena el campo al detectar un QR; la entrada solo se consume al pulsar «Validar ingreso».
  useEffect(() => {
    if (!stream || !detectorSupported) return
    const Detector = (window as unknown as { BarcodeDetector: BarcodeDetectorConstructor }).BarcodeDetector
    const detector = new Detector({ formats: ['qr_code'] })
    let last = ''
    const timer = window.setInterval(async () => {
      if (!videoRef.current || videoRef.current.readyState < 2) return
      try {
        const found = await detector.detect(videoRef.current)
        const value = found[0]?.rawValue
        if (value && value !== last) { last = value; setToken(value); setResult(null); navigator.vibrate?.(60); document.getElementById('op-validate')?.focus() }
      } catch { /* fotograma no disponible */ }
    }, 450)
    return () => window.clearInterval(timer)
  }, [stream, detectorSupported])
  useEffect(() => { if (result) resultRef.current?.scrollIntoView?.({ block: 'nearest', behavior: 'smooth' }) }, [result])

  async function startCamera() {
    setCameraError(null)
    try { setStream(await navigator.mediaDevices.getUserMedia({ video: { facingMode: 'environment' } })) }
    catch { setCameraError('No se pudo abrir la cámara. Escribe o pega el código en el campo manual.') }
  }
  function stopCamera() { stream?.getTracks().forEach((track) => track.stop()); setStream(null) }

  async function validate(event: FormEvent) {
    event.preventDefault()
    if (busy) return
    setBusy(true); setResult(null)
    try {
      const response = await api('/api/operator/validate', { method: 'POST', body: JSON.stringify({ event_id: eventId, qr_token: token.trim() }) })
      const body = await response.json().catch(() => null) as unknown
      if (response.status === 401) { onExpired(); return }
      setResult(classify(response.status, body))
      setToken('')
      fieldRef.current?.focus()
      navigator.vibrate?.(response.ok ? 80 : [120, 60, 120])
    } catch {
      setResult({ tone: 'error', title: 'Sin conexión', detail: 'No pudimos conectar con el servicio de validación. Revisa tu conexión e inténtalo de nuevo.' })
    } finally { setBusy(false) }
  }

  return <section className="workspace operator">
    <header className="op-head"><h1 className="page-title">Control de acceso</h1><p className="muted">Valida las entradas de los eventos asignados a tu cuenta.</p></header>
    {!loaded && <div className="status" role="status"><span className="spinner" />Cargando tus eventos…</div>}
    {loaded && events.length === 0 && <div className="empty-state"><span className="empty-icon"><Icon name="qr" size={26} /></span><h2>No tienes eventos asignados</h2><p>Cuando un organizador te asigne un evento, aparecerá aquí para validar entradas.</p></div>}
    {loaded && events.length > 0 && <>
      <div className="op-event">
        {events.length > 1
          ? <label>Evento<select value={eventId} onChange={(event) => { setEventId(Number(event.target.value)); setResult(null) }}>{events.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
          : <div><span className="op-label">Evento</span><strong>{current?.name}</strong><select className="sr-only" aria-label="Evento asignado" value={eventId} onChange={() => undefined}>{events.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></div>}
        {current && <p className="op-event-meta"><span><Icon name="calendar" size={16} />{formatDate(current.date)} · {formatTime(current.time)}</span><span><Icon name="location" size={16} />{current.venue}, {current.city}</span></p>}
      </div>
      <div ref={resultRef} aria-live="assertive" role="status">{result && <div className={`op-result ${result.tone}`}>
        <span className="op-result-icon"><Icon name={result.tone === 'ok' ? 'check' : 'close'} size={30} /></span>
        <div><strong>{result.title}</strong><p>{result.detail}</p>{result.note && <small>{result.note}</small>}{current && result.tone === 'ok' && <small>{current.name}</small>}</div>
      </div>}</div>
      <div className="op-grid">
        <div className="op-camera">
          <h2>Escanear código QR</h2>
          {stream ? <><video ref={videoRef} autoPlay playsInline muted aria-label="Vista de la cámara" />{!detectorSupported && <p className="op-hint">Este navegador no lee QR directamente. Escribe o pega el código en el campo manual.</p>}<button type="button" className="button secondary" onClick={stopCamera}>Cerrar cámara</button></>
            : <><p className="op-hint">Apunta la cámara al QR de la entrada. Lo leeremos y tú confirmas el ingreso.</p><button type="button" className="button secondary" onClick={() => void startCamera()}>Permitir cámara</button></>}
          {cameraError && <p className="form-error" role="alert">{cameraError}</p>}
        </div>
        <form className="op-form" onSubmit={(event) => void validate(event)}>
          <label>Código QR o código manual<textarea ref={fieldRef} value={token} onChange={(event) => setToken(event.target.value)} minLength={20} required rows={3} placeholder="Pega aquí el código de la entrada" /></label>
          <button id="op-validate" className="button primary" disabled={busy} aria-busy={busy}>{busy && <span className="spinner" />}{busy ? 'Validando…' : 'Validar ingreso'}</button>
          <small>La entrada se consume únicamente al confirmar «Validar ingreso».</small>
        </form>
      </div>
    </>}
  </section>
}
