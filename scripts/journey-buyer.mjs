#!/usr/bin/env node
// Recorrido del comprador en Chrome real (escritorio y móvil) sobre una base aislada: lo lanza scripts/journey-buyer.sh
// catálogo → detalle → asiento en el 3D → «Inicia sesión» → vuelve con la selección → confirmación → Mis entradas → QR.
import { spawn } from 'node:child_process'
import { mkdir, writeFile } from 'node:fs/promises'
import { resolve } from 'node:path'

const base = process.env.E2E_BASE
const output = resolve(process.argv[2])
await mkdir(output, { recursive: true })
const J = JSON.stringify
const port = 9400 + Math.floor(Math.random() * 300)
const browser = spawn('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', ['--headless=new', `--remote-debugging-port=${port}`, '--use-angle=swiftshader', '--enable-webgl', '--ignore-gpu-blocklist', '--disable-gpu-sandbox', `--user-data-dir=/tmp/nexo-journey-${Date.now()}`, 'about:blank'], { stdio: 'ignore' })
const pause = (ms) => new Promise((done) => setTimeout(done, ms))
let page
for (let i = 0; i < 100 && !page; i += 1) { try { page = (await fetch(`http://127.0.0.1:${port}/json`).then((r) => r.json())).find((t) => t.type === 'page') } catch {} if (!page) await pause(200) }
const socket = new WebSocket(page.webSocketDebuggerUrl)
await new Promise((done) => socket.addEventListener('open', done, { once: true }))
let seq = 0; const waiting = new Map(); const pageErrors = []
socket.addEventListener('message', (e) => { const m = JSON.parse(e.data); if (m.method === 'Runtime.exceptionThrown') pageErrors.push(m.params.exceptionDetails.text); const w = m.id && waiting.get(m.id); if (w) { waiting.delete(m.id); m.error ? w.reject(new Error(m.error.message)) : w.resolve(m.result) } })
const send = (method, params = {}) => new Promise((res, rej) => { const id = ++seq; waiting.set(id, { resolve: res, reject: rej }); socket.send(JSON.stringify({ id, method, params })) })
const evaluate = async (expression) => (await send('Runtime.evaluate', { expression, awaitPromise: true, returnByValue: true })).result.value
await send('Page.enable'); await send('Runtime.enable')
const results = []
const check = (name, ok, detail = '') => { results.push({ name, ok: Boolean(ok), detail }); console.log(`${ok ? 'OK   ' : 'FALLÓ'} ${name}${detail ? ` — ${detail}` : ''}`) }
const waitFor = async (expr, label, timeout = 20000) => { const t = Date.now(); while (Date.now() - t < timeout) { try { if (await evaluate(expr)) return true } catch {} await pause(150) } console.log('TIMEOUT', label); return false }
const setValue = (selector, value) => evaluate(`(() => { const c = document.querySelector(${J(selector)}); if (!c) return false; Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(c, ${J(value)}); c.dispatchEvent(new Event('input', { bubbles: true })); return true })()`)
const clickText = (text, selector = 'button') => evaluate(`(() => { const n = [...document.querySelectorAll(${J(selector)})].find((b) => b.textContent.trim() === ${J(text)} || b.getAttribute('aria-label') === ${J(text)}); n?.click(); return !!n })()`)
const shot = async (name) => { await pause(400); await writeFile(resolve(output, `${name}.png`), Buffer.from((await send('Page.captureScreenshot', { format: 'png' })).data, 'base64')); console.log('captura', name) }
async function clickCanvas() {
  const rect = await evaluate(`(() => { const r = document.querySelector('.venue-3d-canvas').getBoundingClientRect(); return { x: r.x, y: r.y, width: r.width, height: r.height } })()`)
  for (let fy = .45; fy <= .9; fy += .04) for (let fx = .2; fx <= .8; fx += .04) {
    const x = rect.x + rect.width * fx, y = rect.y + rect.height * fy
    await send('Input.dispatchMouseEvent', { type: 'mouseMoved', x, y }); await send('Input.dispatchMouseEvent', { type: 'mousePressed', x, y, button: 'left', clickCount: 1 }); await send('Input.dispatchMouseEvent', { type: 'mouseReleased', x, y, button: 'left', clickCount: 1 })
    await pause(120)
    if (await evaluate(`document.querySelectorAll('.ep-seat-list li').length >= 1`)) return true
  }
  return false
}
const client = { name: 'Comprador Recorrido', email: 'recorrido-comprador@example.com', password: process.env.E2E_CLIENT_PASSWORD }
const viewports = [{ name: 'escritorio', width: 1440, height: 900, mobile: false, scale: 1 }, { name: 'movil', width: 390, height: 844, mobile: true, scale: 2 }]
for (const vp of viewports) {
  await send('Network.enable'); await send('Network.clearBrowserCookies')
  await send('Emulation.setDeviceMetricsOverride', { width: vp.width, height: vp.height, deviceScaleFactor: vp.scale, mobile: vp.mobile })
  const tag = vp.name
  // 1 catálogo → detalle
  await send('Page.navigate', { url: base }); await waitFor(`document.querySelectorAll('.card').length > 3`, 'catálogo'); await pause(800)
  await setValue('#main-search', 'Voces en el Auditorio'); await pause(500)
  await clickText('Ver Voces en el Auditorio'); await waitFor(`!!document.querySelector('.venue-3d-canvas')`, 'recinto 3D'); await pause(2500)
  check(`[${tag}] El detalle abre con el recinto 3D como vista principal`, await evaluate(`document.querySelector('.ep-segmented button[aria-pressed="true"]')?.textContent.trim() === 'Mapa 3D' && !document.querySelector('.ep-seat-list-view')`))
  // «Atrás» del navegador sube un nivel (no sale del sitio) y se puede volver a abrir el evento
  await evaluate('history.back()')
  check(`[${tag}] El botón Atrás del navegador vuelve al catálogo`, await waitFor(`!document.querySelector('.ep') && document.querySelectorAll('.card').length > 0`, 'atrás'))
  await clickText('Ver Voces en el Auditorio'); await waitFor(`!!document.querySelector('.venue-3d-canvas')`, 'recinto 3D (de nuevo)'); await pause(2500)
  await evaluate(`document.querySelector('.ep-stage').scrollIntoView({ block: 'start' })`); await pause(500)
  // 2 asiento en el 3D
  check(`[${tag}] Un clic sobre una butaca del 3D la selecciona y aparece en el panel`, await clickCanvas())
  if (vp.mobile) { await evaluate(`document.querySelector('.ep-bar .ep-button')?.click()`); await pause(500) }
  const panel = await evaluate(`(() => { const p = document.querySelector('.ep-panel'); return { text: p.innerText, rows: p.querySelectorAll('.ep-seat-list li').length } })()`)
  check(`[${tag}] El panel muestra asiento, cantidad, precio unitario y total`, panel.rows === 1 && /1 × S\/ \d+\.\d{2}/.test(panel.text) && /Total · 1 entrada/.test(panel.text), panel.text.replace(/\s+/g, ' ').slice(0, 140))
  await shot(`j1-${tag}-seleccion-3d`)
  // 3 inicio de sesión (registro) y regreso con la selección
  await clickText('Inicia sesión para comprar'); await waitFor(`!!document.getElementById('auth-email')`, 'formulario de acceso')
  await clickText('Registrarme'); await pause(300)
  await setValue('#display-name', client.name); await setValue('#auth-email', `${tag}-${client.email}`); await setValue('#auth-password', client.password)
  await clickText('Crear cuenta de cliente'); await pause(500)
  // 4 vuelve al evento con la selección intacta (sin pasos extra)
  await waitFor(`!!document.querySelector('.ep-panel')`, 'regreso al evento'); await pause(1500)
  if (vp.mobile) { await evaluate(`document.querySelector('.ep-bar .ep-button')?.click()`); await pause(500) }
  check(`[${tag}] Tras registrarse vuelve al evento con el asiento todavía seleccionado`, await evaluate(`document.querySelectorAll('.ep-seat-list li').length === 1`))
  await shot(`j2-${tag}-regreso-con-seleccion`)
  // 5 confirmación
  await clickText('Confirmar compra'); await waitFor(`!!document.querySelector('.confirm')`, 'confirmación')
  const confirm = await evaluate(`document.querySelector('.confirm')?.innerText ?? ''`)
  check(`[${tag}] La confirmación resume evento, asiento, total y aviso de pago simulado`, /Voces en el Auditorio/.test(confirm) && /Fila . · Asiento \d+/.test(confirm) && /Total/.test(confirm) && /Pago simulado/.test(confirm))
  await shot(`j3-${tag}-confirmacion`)
  // 6 Mis entradas y QR
  await clickText('Ver mis entradas'); await waitFor(`!!document.querySelector('.wallet-ticket')`, 'Mis entradas'); await pause(1200)
  check(`[${tag}] Mis entradas muestra la entrada con su QR visible en la tarjeta`, await evaluate(`!!document.querySelector('.wallet-ticket .wt-qrimg') && /Ver entrada QR/.test(document.querySelector('.wallet-ticket').innerText)`))
  await shot(`j4-${tag}-mis-entradas`)
  await evaluate(`document.querySelector('.wallet-ticket').click()`); await waitFor(`!!document.querySelector('.qr-image')`, 'QR grande')
  check(`[${tag}] El QR se abre a tamaño completo`, await evaluate(`document.querySelector('.qr-image')?.naturalWidth > 100`))
  await shot(`j5-${tag}-qr`)
}
await writeFile(resolve(output, 'resultado.json'), JSON.stringify({ results, pageErrors }, null, 2))
console.log(pageErrors.length ? `Excepciones: ${pageErrors.length}` : 'Sin excepciones de página')
socket.close(); browser.kill('SIGTERM')
