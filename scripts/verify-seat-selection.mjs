#!/usr/bin/env node
// Verifica en Chrome real (escritorio y móvil) que los eventos con asientos numerados abren en el recinto 3D,
// que se selecciona con clic sobre las butacas y que Plano/Lista son alternativas (nunca simultáneas ni una lista enorme).
// Uso: node scripts/verify-seat-selection.mjs <carpeta>
import { spawn } from 'node:child_process'
import { mkdir, writeFile } from 'node:fs/promises'
import { resolve } from 'node:path'

const output = resolve(process.argv[2] ?? 'docs/evidencias/ui/seleccion-asientos')
await mkdir(output, { recursive: true })
const events = [
  { slug: 'auditorio', name: 'Voces en el Auditorio' },
  { slug: 'estadio', name: 'Clásico Metropolitano' },
  { slug: 'heredado-escena', name: 'Movimiento en Escena' },
  { slug: 'heredado-pulso', name: 'Pulso Eléctrico' },
]
const viewports = [{ name: 'escritorio', width: 1440, height: 900, mobile: false, scale: 1 }, { name: 'movil', width: 390, height: 844, mobile: true, scale: 2 }]
const port = 9800 + Math.floor(Math.random() * 90)
const chrome = spawn('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', ['--headless=new', `--remote-debugging-port=${port}`, '--use-angle=swiftshader', '--enable-webgl', '--ignore-gpu-blocklist', '--disable-gpu-sandbox', `--user-data-dir=/tmp/nexo-seat-${Date.now()}`, 'about:blank'], { stdio: 'ignore' })
const pause = (ms) => new Promise((done) => setTimeout(done, ms))
let page
for (let i = 0; i < 100 && !page; i += 1) { try { page = (await fetch(`http://127.0.0.1:${port}/json`).then((r) => r.json())).find((t) => t.type === 'page') } catch {} if (!page) await pause(200) }
const socket = new WebSocket(page.webSocketDebuggerUrl)
await new Promise((done) => socket.addEventListener('open', done, { once: true }))
let seq = 0; const waiting = new Map()
socket.addEventListener('message', (e) => { const m = JSON.parse(e.data); const w = m.id && waiting.get(m.id); if (w) { waiting.delete(m.id); m.error ? w.reject(new Error(m.error.message)) : w.resolve(m.result) } })
const send = (method, params = {}) => new Promise((resolveCall, reject) => { const id = ++seq; waiting.set(id, { resolve: resolveCall, reject }); socket.send(JSON.stringify({ id, method, params })) })
const evaluate = async (expression) => (await send('Runtime.evaluate', { expression, awaitPromise: true, returnByValue: true })).result.value
await send('Page.enable'); await send('Runtime.enable')
const errors = []
socket.addEventListener('message', (e) => { const m = JSON.parse(e.data); if (m.method === 'Runtime.exceptionThrown') errors.push(m.params.exceptionDetails.text) })
const snapshot = () => evaluate(`(() => ({
  canvas: document.querySelectorAll('.venue-3d-canvas,.stadium-3d-canvas').length,
  checkboxes: document.querySelectorAll('.ep-stage input[type="checkbox"]').length,
  seatButtons: document.querySelectorAll('.ep-stage .ep-seat').length,
  listVisible: !!document.querySelector('.ep-seat-list-view'),
  planVisible: !!document.querySelector('.ep-seat-grid,.ep-stadium-plan'),
  pressed: [...document.querySelectorAll('.ep-segmented button[aria-pressed="true"]')].map((b) => b.textContent.trim()),
  modes: [...document.querySelectorAll('.ep-segmented button')].map((b) => b.textContent.trim()),
  panelSeats: [...document.querySelectorAll('.ep-seat-list li span')].map((s) => s.textContent),
  overflowX: document.documentElement.scrollWidth > innerWidth + 1,
}))()`)
const shot = async (name) => writeFile(resolve(output, name), Buffer.from((await send('Page.captureScreenshot', { format: 'png' })).data, 'base64'))
async function clickCanvas(points) {
  const rect = await evaluate(`(() => { const r = document.querySelector('.venue-3d-canvas,.stadium-3d-canvas').getBoundingClientRect(); return { x: r.x, y: r.y, width: r.width, height: r.height } })()`)
  for (const [fx, fy] of points) {
    const x = rect.x + rect.width * fx, y = rect.y + rect.height * fy
    await send('Input.dispatchMouseEvent', { type: 'mouseMoved', x, y })
    await send('Input.dispatchMouseEvent', { type: 'mousePressed', x, y, button: 'left', clickCount: 1 })
    await send('Input.dispatchMouseEvent', { type: 'mouseReleased', x, y, button: 'left', clickCount: 1 })
    await pause(200)
    if (await evaluate(`document.querySelectorAll('.ep-seat-list li').length >= 1`)) return [fx, fy]
  }
  return null
}
const fine = (x0, x1, y0, y1, step) => { const p = []; for (let y = y0; y <= y1; y += step) for (let x = x0; x <= x1; x += step) p.push([+x.toFixed(3), +y.toFixed(3)]); return p }
const results = []
for (const ev of events) for (const vp of viewports) {
  await send('Emulation.setDeviceMetricsOverride', { width: vp.width, height: vp.height, deviceScaleFactor: vp.scale, mobile: vp.mobile })
  await send('Page.navigate', { url: 'http://127.0.0.1:5173/' }); await pause(1800)
  await evaluate(`(() => { const i = document.querySelector('#main-search'); Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(i, ${JSON.stringify(ev.name)}); i.dispatchEvent(new Event('input', { bubbles: true })) })()`)
  await pause(400)
  for (let a = 0; a < 10 && !(await evaluate(`!!document.querySelector('.ep-stage')`)); a += 1) { await evaluate(`[...document.querySelectorAll('button')].find((b) => b.getAttribute('aria-label') === ${JSON.stringify(`Ver ${ev.name}`)})?.click()`); await pause(700) }
  for (let a = 0; a < 40 && !(await evaluate(`!!document.querySelector('.venue-3d-canvas,.stadium-3d-canvas')`)); a += 1) await pause(300)
  await pause(2500)
  await evaluate(`document.querySelector('.ep-stage').scrollIntoView({ block: 'start' })`); await pause(600)
  const initial = await snapshot()
  await shot(`${ev.slug}-${vp.name}-1-3d-inicial.png`)
  const hit = await clickCanvas(ev.slug === 'estadio' ? [...fine(.3, .7, .35, .6, .05), ...fine(.3, .7, .3, .8, .025)] : fine(.2, .8, .45, .9, .04))
  await pause(500)
  const afterClick = await snapshot()
  await shot(`${ev.slug}-${vp.name}-2-3d-seleccion.png`)
  const label = async (text) => { await evaluate(`[...document.querySelectorAll('.ep-segmented button')].find((b) => b.textContent.trim() === ${JSON.stringify(text)})?.click()`); await pause(900) }
  await label('Lista'); const list = await snapshot(); await shot(`${ev.slug}-${vp.name}-3-lista.png`)
  await label('Plano'); const plan = await snapshot(); await shot(`${ev.slug}-${vp.name}-4-plano.png`)
  results.push({ evento: ev.name, pantalla: vp.name, inicial: initial, seleccionPorClicEn3D: Boolean(hit), tras_clic: afterClick.panelSeats, lista: list, plano: plan })
  console.log(ev.slug, vp.name, 'inicial=', JSON.stringify(initial.pressed), 'canvas=', initial.canvas, 'checkboxes=', initial.checkboxes, 'clic3D=', Boolean(hit), 'panel=', afterClick.panelSeats.length, 'lista(checkboxes)=', list.checkboxes, 'overflow=', initial.overflowX)
}
await writeFile(resolve(output, 'resultados.json'), JSON.stringify({ nota: 'Chrome headless con WebGL por software (SwiftShader)', results, errors }, null, 2))
if (errors.length) console.error('Excepciones:', errors)
socket.close(); chrome.kill('SIGTERM')
