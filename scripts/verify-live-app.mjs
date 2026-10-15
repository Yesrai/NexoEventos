#!/usr/bin/env node
// Conduce Chrome (headless, WebGL por software) por la interfaz real. Lo lanza scripts/e2e-organizer.sh.
// No imprime contraseñas ni el contenido de los QR.
import { spawn } from 'node:child_process'
import { mkdir, writeFile } from 'node:fs/promises'
import { resolve } from 'node:path'

const chrome = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
const base = process.env.E2E_BASE
const apiBase = process.env.E2E_API
const output = resolve(process.argv[2])
const stamp = new Date().toISOString().slice(0, 10)
await mkdir(output, { recursive: true })

const _unused = {
  organizer: { email: 'e2e-organizador@example.com', password: process.env.E2E_ORGANIZER_PASSWORD },
  operator: { email: 'e2e-operador@example.com', password: process.env.E2E_OPERATOR_PASSWORD },
  client: { email: 'e2e-cliente@example.com', password: process.env.E2E_CLIENT_PASSWORD, name: 'Cliente E2E' },
}
const _evt = `Función E2E ${Date.now().toString(36)}`
const plusDays = (days) => new Date(Date.now() + days * 86400000).toISOString().slice(0, 10)

const port = 9600 + Math.floor(Math.random() * 300)
const browser = spawn(chrome, ['--headless=new', `--remote-debugging-port=${port}`, '--window-size=1440,1000', '--use-angle=swiftshader', '--enable-webgl', '--ignore-gpu-blocklist', '--disable-gpu-sandbox', '--disable-extensions', `--user-data-dir=/tmp/nexoeventos-e2e-${Date.now()}`, 'about:blank'], { stdio: 'ignore' })
const pause = (ms) => new Promise((done) => setTimeout(done, ms))
let page
for (let attempt = 0; attempt < 100 && !page; attempt += 1) {
  try { page = (await fetch(`http://127.0.0.1:${port}/json`).then((response) => response.json())).find((item) => item.type === 'page') } catch { /* Chrome inicia */ }
  if (!page) await pause(200)
}
const socket = new WebSocket(page.webSocketDebuggerUrl)
await new Promise((done, fail) => { socket.addEventListener('open', done, { once: true }); socket.addEventListener('error', fail, { once: true }) })
let sequence = 0
const pending = new Map()
const pageErrors = []
socket.addEventListener('message', (event) => {
  const message = JSON.parse(event.data)
  if (message.method === 'Runtime.exceptionThrown') pageErrors.push(message.params.exceptionDetails.exception?.description ?? message.params.exceptionDetails.text)
  const waiting = message.id && pending.get(message.id)
  if (!waiting) return
  pending.delete(message.id)
  if (message.error) waiting.reject(new Error(message.error.message)); else waiting.resolve(message.result)
})
const send = (method, params = {}) => new Promise((done, fail) => { const id = ++sequence; pending.set(id, { resolve: done, reject: fail }); socket.send(JSON.stringify({ id, method, params })) })
const evaluate = async (expression) => {
  const result = await send('Runtime.evaluate', { expression, awaitPromise: true, returnByValue: true })
  if (result.exceptionDetails) throw new Error(result.exceptionDetails.exception?.description ?? result.exceptionDetails.text)
  return result.result.value
}
await send('Page.enable'); await send('Runtime.enable')
await send('Emulation.setDeviceMetricsOverride', { width: 1440, height: 1000, deviceScaleFactor: 1, mobile: false })

const results = []
const check = (name, passed, detail = '') => { results.push({ name, passed: Boolean(passed), detail }); console.log(`${passed ? 'OK  ' : 'FALLÓ'} ${name}${detail ? ` — ${detail}` : ''}`); if (!passed) throw new Error(`Falló: ${name}`) }

const waitFor = async (expression, label, timeout = 15000) => {
  const started = Date.now()
  while (Date.now() - started < timeout) { try { const value = await evaluate(expression); if (value) return value } catch { /* la página puede estar recargando */ } await pause(150) }
  throw new Error(`Tiempo agotado esperando: ${label}`)
}
const J = JSON.stringify
const textButton = (text, selector = 'button') => `[...document.querySelectorAll(${J(selector)})].find((node) => node.textContent.trim() === ${J(text)} || node.getAttribute('aria-label') === ${J(text)})`
const clickText = async (text, selector = 'button') => { await waitFor(`!!(${textButton(text, selector)})`, `botón «${text}»`); await evaluate(`${textButton(text, selector)}.click()`); await pause(150) }
const controlByLabel = (label) => `(() => { const node = [...document.querySelectorAll('label')].find((item) => item.textContent.trim().startsWith(${J(label)})); return node && (node.control || node.querySelector('input,select,textarea')) })()`
const setField = async (label, value) => {
  await waitFor(`!!${controlByLabel(label)}`, `campo «${label}»`)
  await evaluate(`(() => { const control = ${controlByLabel(label)}; const proto = control instanceof HTMLSelectElement ? HTMLSelectElement.prototype : control instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype; Object.getOwnPropertyDescriptor(proto, 'value').set.call(control, ${J(value)}); control.dispatchEvent(new Event(control instanceof HTMLSelectElement ? 'change' : 'input', { bubbles: true })) })()`)
  await pause(80)
}
const setFieldById = async (id, value) => { await evaluate(`(() => { const control = document.getElementById(${J(id)}); Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(control, ${J(value)}); control.dispatchEvent(new Event('input', { bubbles: true })) })()`); await pause(60) }
const optionValue = (label, text) => evaluate(`${controlByLabel(label)}.options ? [...${controlByLabel(label)}.options].find((option) => option.textContent.includes(${J(text)}))?.value ?? null : null`)
const shot = async (name, selector = null) => {
  const rect = selector ? await evaluate(`(() => { const node = document.querySelector(${J(selector)}); if (!node) return null; node.scrollIntoView({ block: 'start' }); const r = node.getBoundingClientRect(); return { x: r.x + scrollX, y: r.y + scrollY, width: r.width, height: r.height } })()`) : null
  await pause(400)
  const params = { format: 'png', fromSurface: true, captureBeyondViewport: true, ...(rect ? { clip: { ...rect, scale: 1 } } : {}) }
  await writeFile(resolve(output, `${name}-${stamp}.png`), Buffer.from((await send('Page.captureScreenshot', params)).data, 'base64'))
  console.log(`captura ${name}`)
}
const go = async () => { await send('Page.navigate', { url: base }); await pause(1500) }
const loginAs = async ({ email, password }) => {
  await go()
  await clickText('Ingresar', 'button.nav-link, header button, nav button')
  await waitFor(`!!document.getElementById('auth-email')`, 'formulario de acceso')
  await setFieldById('auth-email', email); await setFieldById('auth-password', password)
  await clickText('Iniciar sesión')
  await waitFor(`!!document.querySelector('[aria-label^="Abrir menú de"]')`, 'sesión iniciada')
}
const logout = async () => {
  await evaluate(`document.querySelector('[aria-label^="Abrir menú de"]').click()`)
  await pause(200)
  await clickText('Cerrar sesión', '[role="menuitem"]')
  await waitFor(`!document.querySelector('[aria-label^="Abrir menú de"]')`, 'sesión cerrada')
}
const apiJson = (path) => evaluate(`fetch(${J(apiBase + path)}, { credentials: 'include' }).then((response) => response.json())`)


const accounts = { client: { email: `verificacion-${Date.now().toString(36)}@example.com`, password: `Prueba-${Math.random().toString(36).slice(2)}-Zz9!`, name: 'Cuenta de verificación' } }
try {
  await go()
  await waitFor(`document.querySelectorAll('.event-card, article').length > 3`, 'catálogo visible')
  check('El catálogo de eventos carga sin iniciar sesión', true)
  await clickText('Ingresar', 'button.nav-link, header button, nav button')
  await clickText('Registrarme', '[role="tab"]')
  await setFieldById('display-name', accounts.client.name); await setFieldById('auth-email', accounts.client.email); await setFieldById('auth-password', accounts.client.password)
  await clickText('Crear cuenta de cliente')
  await waitFor(`/Tu cuenta está lista/.test(document.body.innerText)`, 'registro correcto')
  check('Registro de una cuenta nueva desde el formulario', true)
  await go()
  await logout()
  check('Cierre de sesión', true)
  await clickText('Ingresar', 'button.nav-link, header button, nav button')
  await clickText('Registrarme', '[role="tab"]')
  await setFieldById('display-name', accounts.client.name); await setFieldById('auth-email', accounts.client.email); await setFieldById('auth-password', accounts.client.password)
  await clickText('Crear cuenta de cliente')
  await waitFor(`/Si ya te registraste antes, inicia sesión/.test(document.body.innerText)`, 'mensaje de correo duplicado')
  check('Un correo ya registrado muestra un mensaje claro', true)
  await clickText('Ya tengo cuenta: iniciar sesión con este correo')
  await setFieldById('auth-password', 'contraseña-incorrecta-1')
  await clickText('Iniciar sesión')
  await waitFor(`/Correo o contraseña incorrectos/.test(document.body.innerText)`, 'mensaje de contraseña incorrecta')
  check('Una contraseña incorrecta muestra un mensaje claro', true)
  await setFieldById('auth-password', accounts.client.password)
  await clickText('Iniciar sesión')
  await waitFor(`!!document.querySelector('[aria-label^="Abrir menú de"]')`, 'sesión iniciada')
  check('Inicio de sesión con la cuenta creada', true)
  const venues = [['Voces en el Auditorio', 'Sala 3D'], ['Noche del Parque', 'Recinto 3D'], ['Miradas Contemporáneas', 'Recorrido 3D'], ['Clásico Metropolitano', 'Vista 3D']]
  for (const [name, toggle] of venues) {
    await go()
    await setFieldById('main-search', name)
    await clickText(`Ver ${name}`)
    await waitFor(`!!document.querySelector('.venue-3d-canvas, .stadium-3d-canvas')`, `3D de ${name}`, 20000)
    await pause(1500)
    const alive = await evaluate(`(() => { const c = document.querySelector('.venue-3d-canvas, .stadium-3d-canvas'); const r = c.getBoundingClientRect(); return r.width > 300 && r.height > 300 })()`)
    check(`Recinto 3D de «${name}» se abre en la aplicación`, alive)
  }
  console.log(pageErrors.length ? `Excepciones de página: ${pageErrors.length} ${pageErrors[0]}` : 'Sin excepciones de página')
} catch (error) {
  console.error('Verificación fallida:', error.message)
  process.exitCode = 1
} finally {
  socket.close()
  browser.kill('SIGTERM')
}
