#!/usr/bin/env node
import { spawn } from 'node:child_process'
import { mkdir, writeFile } from 'node:fs/promises'
import { resolve } from 'node:path'

const chrome = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
const port = 9334
const output = resolve('docs/evidencias/ui/recintos-3d')
await mkdir(output, { recursive: true })
const process = spawn(chrome, [
  '--headless=new', `--remote-debugging-port=${port}`, '--window-size=1440,1000',
  '--use-angle=swiftshader', '--enable-webgl', '--disable-gpu-sandbox', '--disable-extensions',
  `--user-data-dir=/tmp/nexoeventos-capture-${Date.now()}`, 'http://127.0.0.1:5173/',
], { stdio: 'ignore' })

const pause = (milliseconds) => new Promise((resolvePause) => setTimeout(resolvePause, milliseconds))
let page
for (let attempt = 0; attempt < 100; attempt += 1) {
  try {
    const pages = await fetch(`http://127.0.0.1:${port}/json`).then((response) => response.json())
    page = pages.find((candidate) => candidate.type === 'page')
    if (page) break
  } catch { /* Chrome todavía inicia. */ }
  await pause(200)
}
if (!page) throw new Error('Chrome headless no abrió una página controlable.')

const socket = new WebSocket(page.webSocketDebuggerUrl)
await new Promise((resolveOpen, reject) => { socket.addEventListener('open', resolveOpen, { once: true }); socket.addEventListener('error', reject, { once: true }) })
let sequence = 0
const pending = new Map()
socket.addEventListener('message', (event) => {
  const message = JSON.parse(event.data)
  if (!message.id || !pending.has(message.id)) return
  const { resolve: resolveMessage, reject } = pending.get(message.id)
  pending.delete(message.id)
  if (message.error) reject(new Error(message.error.message)); else resolveMessage(message.result)
})
const send = (method, params = {}) => new Promise((resolveMessage, reject) => {
  const id = ++sequence
  pending.set(id, { resolve: resolveMessage, reject })
  socket.send(JSON.stringify({ id, method, params }))
})
await send('Page.enable')
await send('Runtime.enable')
await send('Emulation.setDeviceMetricsOverride', { width: 1440, height: 1000, deviceScaleFactor: 1, mobile: false })

async function evaluate(expression) {
  const result = await send('Runtime.evaluate', { expression, awaitPromise: true, returnByValue: true })
  if (result.exceptionDetails) throw new Error(result.exceptionDetails.text)
  return result.result.value
}

async function openVenue(name, viewLabel) {
  await send('Page.reload', { ignoreCache: true })
  await pause(700)
  await evaluate(`(() => {
    const input = document.querySelector('#main-search');
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
    setter.call(input, ${JSON.stringify(name)});
    input.dispatchEvent(new Event('input', { bubbles: true }));
  })()`)
  await pause(250)
  await evaluate(`[...document.querySelectorAll('button')].find((button) => button.getAttribute('aria-label') === ${JSON.stringify(`Ver ${name}`)})?.click()`)
  await pause(650)
  await evaluate(`[...document.querySelectorAll('button')].find((button) => button.textContent.trim() === ${JSON.stringify(viewLabel)})?.click()`)
  await pause(1300)
  await evaluate(`document.querySelector('.stadium-3d-stage,.venue-3d-stage')?.scrollIntoView({block:'center'})`)
  await pause(350)
}

async function screenshot(filename) {
  const result = await send('Page.captureScreenshot', { format: 'png', fromSurface: true })
  await writeFile(resolve(output, filename), Buffer.from(result.data, 'base64'))
}

const venues = [
  ['Clásico Metropolitano', 'Vista 3D', 'estadio-desktop-2026-10-14.png'],
  ['Voces en el Auditorio', 'Sala 3D', 'auditorio-desktop-2026-10-14.png'],
  ['Noche del Parque', 'Recinto 3D', 'concierto-desktop-2026-10-14.png'],
  ['Miradas Contemporáneas', 'Recorrido 3D', 'museo-desktop-2026-10-14.png'],
]
for (const [name, label, filename] of venues) {
  await openVenue(name, label)
  await screenshot(filename)
}

await openVenue('Clásico Metropolitano', 'Vista 3D')
const bounds = await evaluate(`(() => { const r = document.querySelector('.stadium-3d-canvas').getBoundingClientRect(); return {x:r.x,y:r.y,width:r.width,height:r.height} })()`)
const startX = bounds.x + bounds.width * .64
const startY = bounds.y + bounds.height * .48
await send('Input.dispatchMouseEvent', { type: 'mousePressed', x: startX, y: startY, button: 'left', clickCount: 1 })
for (let frame = 0; frame < 24; frame += 1) {
  await send('Input.dispatchMouseEvent', { type: 'mouseMoved', x: startX - frame * 9, y: startY + Math.sin(frame / 4) * 18, button: 'left', buttons: 1 })
  await pause(45)
  await screenshot(`tour-frame-${String(frame).padStart(2, '0')}.png`)
}
await send('Input.dispatchMouseEvent', { type: 'mouseReleased', x: startX - 210, y: startY, button: 'left', clickCount: 1 })

socket.close()
process.kill('SIGTERM')
console.log(output)
