#!/usr/bin/env node
// Auditoría visual: recorre las pantallas públicas y de cliente en Chrome real (escritorio y móvil). Lo lanza scripts/audit-visual.sh
import { spawn } from 'node:child_process'
import { mkdir, writeFile } from 'node:fs/promises'
import { resolve } from 'node:path'

const base = process.env.E2E_BASE
const output = resolve(process.argv[2])
await mkdir(output, { recursive: true })
const client = { name: 'Cliente Auditoría', email: 'auditoria-cliente@example.com', password: process.env.E2E_CLIENT_PASSWORD }
const port = 9500 + Math.floor(Math.random() * 300)
const browser = spawn('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', ['--headless=new', `--remote-debugging-port=${port}`, '--use-angle=swiftshader', '--enable-webgl', '--ignore-gpu-blocklist', '--disable-gpu-sandbox', `--user-data-dir=/tmp/nexo-audit-${Date.now()}`, 'about:blank'], { stdio: 'ignore' })
const pause = (ms) => new Promise((done) => setTimeout(done, ms))
let page
for (let i = 0; i < 100 && !page; i += 1) { try { page = (await fetch(`http://127.0.0.1:${port}/json`).then((r) => r.json())).find((t) => t.type === 'page') } catch {} if (!page) await pause(200) }
const socket = new WebSocket(page.webSocketDebuggerUrl)
await new Promise((done) => socket.addEventListener('open', done, { once: true }))
let seq = 0; const waiting = new Map(); const pageErrors = []
socket.addEventListener('message', (e) => { const m = JSON.parse(e.data); if (m.method === 'Runtime.exceptionThrown') pageErrors.push(m.params.exceptionDetails.text); const w = m.id && waiting.get(m.id); if (w) { waiting.delete(m.id); m.error ? w.reject(new Error(m.error.message)) : w.resolve(m.result) } })
const send = (method, params = {}) => new Promise((res, rej) => { const id = ++seq; waiting.set(id, { resolve: res, reject: rej }); socket.send(JSON.stringify({ id, method, params })) })
const evaluate = async (expression) => (await send('Runtime.evaluate', { expression, awaitPromise: true, returnByValue: true })).result.value
await send('Page.enable'); await send('Runtime.enable'); await send('Network.enable')
const J = JSON.stringify
const waitFor = async (expr, label, timeout = 15000) => { const t = Date.now(); while (Date.now() - t < timeout) { try { if (await evaluate(expr)) return true } catch {} await pause(150) } console.log('TIMEOUT', label); return false }
const setValue = (selector, value) => evaluate(`(() => { const c = document.querySelector(${J(selector)}); if (!c) return false; Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(c, ${J(value)}); c.dispatchEvent(new Event('input', { bubbles: true })); return true })()`)
const clickText = (text, selector = 'button') => evaluate(`(() => { const n = [...document.querySelectorAll(${J(selector)})].find((b) => b.textContent.trim() === ${J(text)} || b.getAttribute('aria-label') === ${J(text)}); n?.click(); return !!n })()`)
let vp
const shots = []
async function shot(name, full = true) {
  if (full) { await evaluate(`(async () => { for (let y = 0; y < document.documentElement.scrollHeight; y += 450) { window.scrollTo(0, y); await new Promise((r) => setTimeout(r, 80)) } window.scrollTo(0, 0) })()`); await pause(900) }
  await pause(500)
  const height = full ? Math.min(await evaluate('Math.ceil(document.documentElement.scrollHeight)'), 5200) : null
  const params = { format: 'png', ...(full ? { captureBeyondViewport: true, clip: { x: 0, y: 0, width: vp.width, height, scale: 1 } } : {}) }
  await writeFile(resolve(output, `${name}-${vp.name}.png`), Buffer.from((await send('Page.captureScreenshot', params)).data, 'base64')); shots.push(`${name}-${vp.name}`); console.log('captura', `${name}-${vp.name}`)
}
const home = async () => { await send('Page.navigate', { url: base }); await waitFor(`document.querySelectorAll('.card').length > 3`, 'catálogo'); await pause(900) }
const openEvent = async (name) => {
  await home()
  await setValue('#main-search', name); await pause(500)
  await clickText(`Ver ${name}`)
  await waitFor(`!!document.querySelector('.ep')`, `evento ${name}`); await pause(3200)
}
const viewports = [{ name: 'escritorio', width: 1440, height: 900, mobile: false, scale: 1 }, { name: 'movil', width: 390, height: 844, mobile: true, scale: 2 }]
for (vp of viewports) {
  await send('Emulation.setDeviceMetricsOverride', { width: vp.width, height: vp.height, deviceScaleFactor: vp.scale, mobile: vp.mobile })
  // 1 Inicio y catálogo
  await home(); await shot('01-inicio')
  // 2 Carga (esqueletos): red lenta
  if (!vp.mobile) {
    await send('Network.emulateNetworkConditions', { offline: false, latency: 2500, downloadThroughput: -1, uploadThroughput: -1 })
    await send('Page.navigate', { url: base }); await pause(1400); await shot('02-carga', false)
    await send('Network.emulateNetworkConditions', { offline: false, latency: 0, downloadThroughput: -1, uploadThroughput: -1 })
  }
  // 3 Sin resultados
  await home(); await setValue('#main-search', 'zzzxq'); await pause(700)
  await evaluate(`document.getElementById('catalogo')?.scrollIntoView()`); await shot('03-sin-resultados', false)
  // 4 Filtro de ciudad / más filtros abierto
  await home(); await evaluate(`document.querySelector('.more-filters')?.click()`); await pause(500)
  await evaluate(`document.getElementById('catalogo')?.scrollIntoView()`); await shot('04-mas-filtros', false)
  // 5 Eventos (distintas modalidades)
  for (const [slug, name] of [['05-concierto-zonas', 'Noche del Parque'], ['06-teatro-asientos', 'Voces en el Auditorio'], ['07-estadio-asientos', 'Clásico Metropolitano'], ['08-museo-general', 'Miradas Contemporáneas'], ['09-gratuito-general', 'Feria de Sabores Locales']]) {
    await openEvent(name); await shot(slug)
  }
  // 6 Estado deshabilitado del panel (concierto sin zona) y compra que exige sesión
  await openEvent('Noche del Parque')
  await evaluate(`document.querySelector('.ep-panel')?.scrollIntoView({ block: 'start' })`); await pause(300)
  if (vp.mobile) { await evaluate(`document.querySelector('.ep-bar .ep-button')?.click()`); await pause(500) }
  await shot('10-panel-deshabilitado', false)
  // 7 Acceso con error y registro con errores de validación
  await home(); await clickText('Ingresar'); await waitFor(`!!document.getElementById('auth-email')`, 'login')
  await setValue('#auth-email', 'nadie@example.com'); await setValue('#auth-password', 'contraseña-incorrecta-123'); await clickText('Iniciar sesión'); await pause(1200)
  await shot('11-ingreso-error', false)
  await clickText('Registrarme'); await pause(400); await clickText('Crear cuenta de cliente'); await pause(600); await shot('12-registro-validacion', false)
}
// Sesión de cliente (solo una vez, ambas pantallas)
for (vp of viewports) {
  await send('Emulation.setDeviceMetricsOverride', { width: vp.width, height: vp.height, deviceScaleFactor: vp.scale, mobile: vp.mobile })
  if (vp.mobile) { await home(); await send('Network.clearBrowserCookies') }
  await home(); await clickText('Ingresar'); await waitFor(`!!document.getElementById('auth-email')`, 'login')
  if (!vp.mobile) {
    await clickText('Registrarme'); await pause(300)
    await setValue('#display-name', client.name); await setValue('#auth-email', client.email); await setValue('#auth-password', client.password)
    await shot('13-registro-completo', false)
    await clickText('Crear cuenta de cliente'); await waitFor(`!!document.querySelector('.auth-success')`, 'registro'); await pause(600); await shot('14-registro-exitoso', false)
  } else {
    await setValue('#auth-email', client.email); await setValue('#auth-password', client.password); await clickText('Iniciar sesión')
  }
  await waitFor(`!!document.querySelector('[aria-label^="Abrir menú de"]')`, 'sesión')
  await home(); await evaluate(`(document.querySelector('button[aria-label="Mis entradas"]') || [...document.querySelectorAll('.nx-tabbar button')][2])?.click()`); await pause(1200); await shot('15-mis-entradas-vacio', false)
  await openEvent('Feria de Sabores Locales')
  await evaluate(`document.querySelector('.ep-panel')?.scrollIntoView({ block: 'start' })`)
  if (vp.mobile) { await evaluate(`document.querySelector('.ep-bar .ep-button')?.click()`); await pause(500) }
  await shot('16-compra-lista', false)
  await evaluate(`[...document.querySelectorAll('.ep-panel button')].find((b) => /Confirmar compra/.test(b.textContent))?.click()`)
  await waitFor(`!!document.querySelector('.confirm')`, 'compra confirmada'); await pause(900); await shot('17-compra-confirmada', false)
  await evaluate(`[...document.querySelectorAll('.confirm button')].find((b) => /Ver mis entradas/.test(b.textContent))?.click()`); await pause(2200)
  await shot('18-mis-entradas-con-qr')
  await evaluate(`document.querySelector('[aria-label^="Abrir menú de"]')?.click()`); await pause(300); await clickText('Cerrar sesión', '[role="menuitem"]'); await pause(800)
}
await writeFile(resolve(output, 'excepciones.json'), JSON.stringify({ excepciones: pageErrors, capturas: shots }, null, 2))
console.log(pageErrors.length ? `Excepciones de página: ${pageErrors.length}` : 'Sin excepciones de página')
socket.close(); browser.kill('SIGTERM')
