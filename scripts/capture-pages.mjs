#!/usr/bin/env node
// Capturas de página completa (no recortadas) de la experiencia de compra, escritorio y móvil, sobre los servidores locales.
// Uso: node scripts/capture-pages.mjs <carpeta> [prefijo] [filtro]
import { spawn } from 'node:child_process'
import { mkdir, writeFile } from 'node:fs/promises'
import { resolve } from 'node:path'

const output = resolve(process.argv[2] ?? 'docs/evidencias/ui/compra')
const prefix = process.argv[3] ?? ''
const filter = process.argv[4] ?? ''
const base = process.env.E2E_BASE ?? 'http://127.0.0.1:5173'
await mkdir(output, { recursive: true })
const pages = [
  { slug: 'inicio', event: null },
  { slug: 'concierto', event: 'Noche del Parque' },
  { slug: 'estadio', event: 'Clásico Metropolitano' },
  { slug: 'auditorio', event: 'Voces en el Auditorio' },
  { slug: 'museo', event: 'Rutas del Arte' },
  { slug: 'feria', event: 'Feria de Sabores Locales' },
].filter((item) => item.slug.includes(filter))
const viewports = [{ name: 'escritorio', width: 1440, height: 900, mobile: false, scale: 1 }, { name: 'movil', width: 390, height: 844, mobile: true, scale: 2 }]
const port = 9900 + Math.floor(Math.random() * 90)
const chrome = spawn('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', ['--headless=new', `--remote-debugging-port=${port}`, '--use-angle=swiftshader', '--enable-webgl', '--ignore-gpu-blocklist', '--disable-gpu-sandbox', `--user-data-dir=/tmp/nexo-pages-${Date.now()}`, 'about:blank'], { stdio: 'ignore' })
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
for (const item of pages) for (const viewport of viewports) {
  await send('Emulation.setDeviceMetricsOverride', { width: viewport.width, height: viewport.height, deviceScaleFactor: viewport.scale, mobile: viewport.mobile })
  await send('Page.navigate', { url: base }); await pause(1800)
  if (item.event) await evaluate(`(() => { const input = document.querySelector('#main-search'); Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(input, ${JSON.stringify(item.event)}); input.dispatchEvent(new Event('input', { bubbles: true })) })()`)
  await pause(300)
  if (item.event) for (let attempt = 0; attempt < 12 && !(await evaluate(`!!document.querySelector('.ep')`)); attempt += 1) {
    await evaluate(`[...document.querySelectorAll('button')].find((b) => b.getAttribute('aria-label') === ${JSON.stringify(`Ver ${item.event}`)})?.click()`)
    await pause(700)
  }
  await pause(3500)
  await evaluate(`(async () => { for (let y = 0; y < document.documentElement.scrollHeight; y += 500) { window.scrollTo(0, y); await new Promise((r) => setTimeout(r, 90)) } window.scrollTo(0, 0) })()`)
  await pause(1200)
  const height = await evaluate('Math.ceil(document.documentElement.scrollHeight)')
  const shot = await send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: true, clip: { x: 0, y: 0, width: viewport.width, height: Math.min(height, item.event ? 6000 : 3400), scale: 1 } })
  for (const [label, top] of [['pantalla', 0], ['pantalla-2', item.event ? 700 : 1300]]) {
    await evaluate(`window.scrollTo(0, ${top})`)
    await pause(900)
    const view = await send('Page.captureScreenshot', { format: 'png' })
    await writeFile(resolve(output, `${prefix}${item.slug}-${viewport.name}-${label}.png`), Buffer.from(view.data, 'base64'))
  }
  const name = `${prefix}${item.slug}-${viewport.name}.png`
  await writeFile(resolve(output, name), Buffer.from(shot.data, 'base64')); console.log(name, height)
}
socket.close(); chrome.kill('SIGTERM')
