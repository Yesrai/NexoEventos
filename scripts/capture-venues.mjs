#!/usr/bin/env node
// Captura real (Chrome headless + WebGL por software) de cada recinto 3D y de sus vistas de cámara.
// Requiere backend y frontend locales en marcha. Uso: node scripts/capture-venues.mjs [filtro] [carpeta]
import { spawn } from 'node:child_process'
import { mkdir, writeFile } from 'node:fs/promises'
import { resolve } from 'node:path'

const chrome = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
const filter = process.argv[2] ?? ''
const output = resolve(process.argv[3] ?? 'docs/evidencias/ui/recintos-3d')
const stamp = new Date().toISOString().slice(0, 10)
await mkdir(output, { recursive: true })

const venues = [
  { slug: 'auditorio', event: 'Voces en el Auditorio', toggle: 'Sala 3D', views: ['Desde la sala', 'Platea', 'Vista general'] },
  { slug: 'concierto', event: 'Noche del Parque', toggle: 'Recinto 3D', views: ['Desde la entrada', 'Zonas', 'Frente al escenario', 'Lateral'] },
  { slug: 'museo', event: 'Miradas Contemporáneas', toggle: 'Recorrido 3D', views: ['Vista general', 'Ingreso', 'Sala 1', 'Sala 2', 'Sala 3'] },
  { slug: 'estadio', event: 'Clásico Metropolitano', toggle: 'Vista 3D', views: [] },
].filter((venue) => venue.slug.includes(filter))
const viewports = [
  { name: 'escritorio', width: 1440, height: 1000, mobile: false, scale: 1 },
  { name: 'movil', width: 390, height: 844, mobile: true, scale: 2 },
]

const port = 9335 + Math.floor(Math.random() * 200)
const browser = spawn(chrome, [
  '--headless=new', `--remote-debugging-port=${port}`, '--window-size=1440,1000',
  '--use-angle=swiftshader', '--enable-webgl', '--ignore-gpu-blocklist', '--disable-gpu-sandbox', '--disable-extensions',
  `--user-data-dir=/tmp/nexoeventos-capture-${Date.now()}`, 'http://127.0.0.1:5173/',
], { stdio: 'ignore' })
const pause = (milliseconds) => new Promise((done) => setTimeout(done, milliseconds))
let page
for (let attempt = 0; attempt < 100 && !page; attempt += 1) {
  try { page = (await fetch(`http://127.0.0.1:${port}/json`).then((response) => response.json())).find((candidate) => candidate.type === 'page') } catch { /* Chrome inicia */ }
  if (!page) await pause(200)
}
if (!page) throw new Error('Chrome headless no abrió una página controlable.')
const socket = new WebSocket(page.webSocketDebuggerUrl)
await new Promise((done, fail) => { socket.addEventListener('open', done, { once: true }); socket.addEventListener('error', fail, { once: true }) })
let sequence = 0
const pending = new Map()
socket.addEventListener('message', (event) => {
  const message = JSON.parse(event.data)
  const waiting = message.id && pending.get(message.id)
  if (!waiting) return
  pending.delete(message.id)
  if (message.error) waiting.reject(new Error(message.error.message)); else waiting.resolve(message.result)
})
const send = (method, params = {}) => new Promise((resolveCall, reject) => { const id = ++sequence; pending.set(id, { resolve: resolveCall, reject }); socket.send(JSON.stringify({ id, method, params })) })
const evaluate = async (expression) => {
  const result = await send('Runtime.evaluate', { expression, awaitPromise: true, returnByValue: true })
  if (result.exceptionDetails) throw new Error(result.exceptionDetails.exception?.description ?? result.exceptionDetails.text)
  return result.result.value
}
await send('Page.enable'); await send('Runtime.enable')
const consoleErrors = []
socket.addEventListener('message', (event) => {
  const message = JSON.parse(event.data)
  if (message.method === 'Runtime.exceptionThrown') consoleErrors.push(message.params.exceptionDetails.text)
})

async function open(venue, viewport) {
  await send('Emulation.setDeviceMetricsOverride', { width: viewport.width, height: viewport.height, deviceScaleFactor: viewport.scale, mobile: viewport.mobile })
  await pause(300)
  await send('Page.navigate', { url: 'http://127.0.0.1:5173/' })
  await pause(1800)
  await evaluate(`(() => { const input = document.querySelector('#main-search'); const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set; setter.call(input, ${JSON.stringify(venue.event)}); input.dispatchEvent(new Event('input', { bubbles: true })) })()`)
  await pause(300)
  await evaluate(`[...document.querySelectorAll('button')].find((button) => button.getAttribute('aria-label') === ${JSON.stringify(`Ver ${venue.event}`)})?.click()`)
  await pause(800)
  await evaluate(`[...document.querySelectorAll('button')].find((button) => button.textContent.trim() === ${JSON.stringify(venue.toggle)})?.click()`)
  await pause(2200)
  await evaluate(`document.querySelector('.venue-3d-stage,.stadium-3d-stage')?.scrollIntoView({ block: 'center' })`)
  await pause(500)
}

async function shot(name) {
  const rect = await evaluate(`(() => { const r = document.querySelector('.venue-3d-stage,.stadium-3d-stage').getBoundingClientRect(); return { x: r.x + scrollX, y: r.y + scrollY, width: r.width, height: r.height } })()`)
  const result = await send('Page.captureScreenshot', { format: 'png', fromSurface: true, captureBeyondViewport: true, clip: { ...rect, scale: 1 } })
  await writeFile(resolve(output, name), Buffer.from(result.data, 'base64'))
  console.log(name)
}

for (const venue of venues) for (const viewport of viewports) {
  await open(venue, viewport)
  await shot(`${venue.slug}-${viewport.name}-${stamp}.png`)
  for (const [index, label] of venue.views.entries()) {
    if (index === 0) continue
    await evaluate(`[...document.querySelectorAll('.venue-3d-views button')].find((button) => button.textContent.trim() === ${JSON.stringify(label)})?.click()`)
    await pause(1200)
    await shot(`${venue.slug}-${viewport.name}-${label.toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '').replace(/[^a-z0-9]+/g, '-')}-${stamp}.png`)
  }
}
if (consoleErrors.length) console.error('Excepciones de página:', consoleErrors)
socket.close()
browser.kill('SIGTERM')
