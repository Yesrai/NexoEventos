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

const accounts = {
  organizer: { email: 'e2e-organizador@example.com', password: process.env.E2E_ORGANIZER_PASSWORD },
  operator: { email: 'e2e-operador@example.com', password: process.env.E2E_OPERATOR_PASSWORD },
  client: { email: 'e2e-cliente@example.com', password: process.env.E2E_CLIENT_PASSWORD, name: 'Cliente E2E' },
}
const eventName = `Función E2E ${Date.now().toString(36)}`
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

try {
  // 1) Organizador: crear evento, elegir recinto y plano, configurar entradas.
  await loginAs(accounts.organizer)
  await clickText('Mis eventos')
  await clickText('Nuevo evento')
  await setField('Nombre', eventName)
  await setField('Fecha', plusDays(21))
  await setField('Hora', '20:00')
  await setField('Descripción', 'Función ficticia creada de punta a punta desde el panel del organizador.')
  await setField('Recinto', await optionValue('Recinto', 'Auditorio Nexo'))
  await waitFor(`${controlByLabel('Plano del recinto')}.value !== ''`, 'plano seleccionado')
  check('El plano del recinto se rellena según el recinto elegido', await evaluate(`/Sala frontal/.test(${controlByLabel('Plano del recinto')}.selectedOptions[0].textContent)`))
  await setField('Nombre de sección', 'Platea')
  await shot('01-nuevo-evento-escritorio', '.organizer-detail')
  await clickText('Crear borrador')
  await waitFor(`!!document.querySelector('.organizer-head .organizer-badge.draft')`, 'borrador creado')
  check('Se crea como borrador', true)
  check('El borrador no es público', (await evaluate(`fetch(${J(apiBase + '/api/events')}).then((response) => response.json())`)).every((item) => item.name !== eventName))

  // 2) Vista previa 2D y 3D con el inventario real configurado.
  await clickText('Vista previa')
  await waitFor(`!!document.querySelector('.ep-preview-banner')`, 'vista previa')
  await clickText('Plano')
  await waitFor(`!!document.querySelector('.ep-seat')`, 'plano 2D')
  const seatCount = await evaluate(`document.querySelectorAll('.ep-seat').length`)
  check('La vista previa 2D muestra todos los asientos configurados', seatCount === 96, `${seatCount} asientos`)
  await shot('02-vista-previa-2d', '.organizer-detail')
  await clickText('Mapa 3D')
  await waitFor(`!!document.querySelector('.venue-3d-canvas')`, 'vista previa 3D')
  await pause(2500)
  await shot('03-vista-previa-3d', '.ep')

  // 3) Operador y publicación.
  await clickText('Operadores')
  await setField('Correo del operador', accounts.operator.email)
  await clickText('Asignar operador')
  await waitFor(`/Operador asignado/.test(document.body.innerText)`, 'operador asignado')
  check('El organizador asigna un operador por correo', true)
  await clickText('Resumen')
  await clickText('Publicar evento')
  await waitFor(`/Evento publicado/.test(document.body.innerText)`, 'publicación')
  check('El evento publicado aparece en el catálogo público', (await evaluate(`fetch(${J(apiBase + '/api/events')}).then((response) => response.json())`)).some((item) => item.name === eventName))
  await shot('04-publicado-resumen', '.organizer-detail')
  await logout()

  // 4) Cliente: registrarse, elegir asiento en el plano y reservar.
  await go()
  await clickText('Ingresar', 'button.nav-link, header button, nav button')
  await clickText('Registrarme', '[role="tab"]')
  await setFieldById('display-name', accounts.client.name); await setFieldById('auth-email', accounts.client.email); await setFieldById('auth-password', accounts.client.password)
  await clickText('Crear cuenta de cliente')
  await waitFor(`/Ir a Mis entradas|Continuar con mi reserva/.test(document.body.innerText)`, 'cuenta creada')
  await go()
  await setFieldById('main-search', eventName)
  await clickText(`Ver ${eventName}`)
  await waitFor(`!!document.querySelector('.venue-3d-canvas')`, 'recinto 3D del cliente'); await pause(2000)
  await shot('04b-cliente-compra-3d-escritorio', '.ep')
  await clickText('Plano')
  await waitFor(`!!document.querySelector('.ep-seat[aria-label*="asiento 1, disponible"]')`, 'plano del cliente')
  await evaluate(`document.querySelector('.ep-seat[aria-label*="asiento 1, disponible"]').click()`)
  await shot('04c-cliente-seleccion-panel', '.ep-layout')
  await clickText('Confirmar compra')
  await waitFor(`/Compra confirmada/.test(document.body.innerText) && !!document.querySelector('.confirm')`, 'pantalla de confirmación')
  check('El cliente reserva un asiento numerado', true)
  check('La confirmación resume el pedido (evento, asiento, total, número de reserva y aviso de pago simulado)', await evaluate(`(() => { const t = document.querySelector('.confirm').innerText; return t.includes(${J(eventName)}) && /Fila A · Asiento 1/.test(t) && /Total/.test(t) && /Número de reserva/.test(t) && /Pago simulado/.test(t) })()`))
  await shot('04d-confirmacion-compra')
  const tickets = await apiJson('/api/me/tickets')
  check('Se emite una entrada con asiento', tickets.length === 1 && tickets[0].seat === 1 && tickets[0].zone === 'Platea', `${tickets[0]?.zone} ${tickets[0]?.row}-${tickets[0]?.seat}`)
  const token = (await apiJson(`/api/me/tickets/${tickets[0].id}`)).qr_token
  await clickText('Seguir explorando eventos')
  await setFieldById('main-search', eventName)
  await clickText(`Ver ${eventName}`)
  await waitFor(`!!document.querySelector('.venue-3d-canvas')`, '3D del cliente'); await pause(2500)
  await shot('05-cliente-3d-asiento-ocupado', '.ep-stage')
  await logout()

  // 5) Operador: validar ingreso, luego rechazar la reutilización.
  await loginAs(accounts.operator)
  await clickText('Control de acceso')
  await waitFor(`[...document.querySelectorAll('select option')].some((option) => option.textContent === ${J(eventName)})`, 'evento asignado al operador')
  const operatorSelect = `[...document.querySelectorAll('select')].find((node) => [...node.options].some((option) => option.textContent === ${J(eventName)}))`
  await evaluate(`(() => { const select = ${operatorSelect}; const option = [...select.options].find((item) => item.textContent === ${J(eventName)}); Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value').set.call(select, option.value); select.dispatchEvent(new Event('change', { bubbles: true })) })()`)
  await setField('Código QR', token)
  await clickText('Validar ingreso')
  await waitFor(`/Ingreso aceptado/.test(document.body.innerText)`, 'ingreso aceptado')
  check('El operador valida el QR y registra el ingreso', true)
  await shot('06-operador-ingreso-aceptado', '.operator-grid')
  await clickText('Validar ingreso')
  await waitFor(`/Entrada ya utilizada/.test(document.body.innerText)`, 'reutilización rechazada')
  check('Una segunda validación del mismo QR se rechaza', true)
  await logout()

  // 6) Organizador: estadísticas y bloqueos tras la venta.
  await loginAs(accounts.organizer)
  await clickText('Mis eventos')
  await clickText(`${eventName}`, 'button.organizer-item strong')
  await waitFor(`!!document.querySelector('.organizer-kpis')`, 'estadísticas')
  const kpis = await evaluate(`Object.fromEntries([...document.querySelectorAll('.organizer-kpis > div')].map((node) => [node.querySelector('dt').textContent, node.querySelector('dd').textContent]))`)
  check('Las estadísticas reflejan venta e ingreso', kpis['Entradas vendidas'] === '1 de 96' && kpis['Ya ingresaron'] === '1' && kpis['Ingresos simulados'] === 'S/ 35.00', JSON.stringify(kpis))
  await shot('07-estadisticas-tras-venta', '.organizer-detail')
  await clickText('Recinto y entradas')
  check('El recinto y el inventario quedan bloqueados tras la venta', await evaluate(`document.querySelector('.organizer-fieldset').disabled === true && !document.body.innerText.includes('Guardar recinto e inventario')`))
  await shot('08-inventario-bloqueado', '.organizer-detail')
  await clickText('Datos')
  check('La fecha queda bloqueada tras la venta', await evaluate(`${controlByLabel('Fecha')}.disabled === true`))
  await clickText('Resumen')
  check('No se puede despublicar con ventas', await evaluate(`${textButton('Despublicar')}.disabled === true`))
  await clickText('Nueva función')
  await setField('Fecha', plusDays(35))
  await clickText('Crear función')
  await waitFor(`/Nueva función creada como borrador/.test(document.body.innerText)`, 'aviso de nueva función')
  await waitFor(`!!document.querySelector('.organizer-head .organizer-badge.draft')`, 'función en borrador')
  await clickText('Vista previa')
  await waitFor(`!!document.querySelector('.ep-preview-banner')`, 'vista previa de la función')
  await clickText('Plano')
  await waitFor(`document.querySelectorAll('.ep-seat:not(:disabled)').length === 96`, 'inventario independiente de la nueva función')
  check('Una nueva función copia el plano con inventario independiente (96 disponibles)', true)

  // 7) Fila virtual: el servidor decide quién compra y en qué orden.
  await clickText(eventName, 'button.organizer-item strong')
  await waitFor(`!!document.querySelector('.organizer-kpis')`, 'evento original')
  await clickText('Ventas y fila')
  await evaluate(`${controlByLabel('Activar fila virtual')}.click()`)
  await setField('Personas comprando a la vez', '1')
  await clickText('Guardar ventas y fila')
  await waitFor(`/Ventas y fila virtual guardadas/.test(document.body.innerText)`, 'fila activada')
  check('El organizador activa la fila virtual (1 persona a la vez)', true)
  await logout()
  const openEvent = async () => { await go(); await setFieldById('main-search', eventName); await clickText(`Ver ${eventName}`); await waitFor(`!!document.querySelector('.ep')`, 'página del evento'); await pause(800) }
  const eventId = (await evaluate(`fetch(${J(apiBase + '/api/events')}).then((r) => r.json())`)).find((item) => item.name === eventName).id
  await loginAs(accounts.client)
  await openEvent()
  await waitFor(`!!${textButton('Entrar a la fila')}`, 'botón de la fila')
  check('Con fila activa la compra queda bloqueada hasta tener turno', await evaluate(`${textButton('Compra no disponible todavía')}.disabled === true`))
  const free = (await apiJson(`/api/events/${eventId}`)).seats.find((seat) => seat.available)
  const attempt = await evaluate(`fetch(${J(apiBase + '/api/events/' + eventId + '/reservations')}, { method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json', 'Idempotency-Key': 'e2e-skip-the-line-0001', 'X-CSRF-Token': document.cookie.split('; ').find((c) => c.startsWith('nexoeventos_csrf=')).split('=')[1] }, body: JSON.stringify({ quantity: 1, zone_id: null, seat_ids: [${free.id}] }) }).then(async (r) => ({ status: r.status, body: await r.json() }))`)
  check('El servidor rechaza comprar sin turno aunque se salte la interfaz', attempt.status === 403 && attempt.body.detail.code === 'queue_required', `${attempt.status} ${attempt.body.detail.code}`)
  await clickText('Entrar a la fila')
  await waitFor(`/Es tu turno/.test(document.body.innerText)`, 'turno asignado')
  check('La primera persona recibe turno de compra', true)
  await shot('11-fila-turno-activo', '.ep')
  await logout()
  const second = { email: 'e2e-cliente-b@example.com', password: `${accounts.client.password}-b`, name: 'Cliente B' }
  await go()
  await clickText('Ingresar', 'button.nav-link, header button, nav button')
  await clickText('Registrarme', '[role="tab"]')
  await setFieldById('display-name', second.name); await setFieldById('auth-email', second.email); await setFieldById('auth-password', second.password)
  await clickText('Crear cuenta de cliente')
  await waitFor(`/Tu cuenta está lista/.test(document.body.innerText)`, 'segundo cliente registrado')
  await openEvent()
  await clickText('Entrar a la fila')
  await waitFor(`/Eres la siguiente persona/.test(document.body.innerText)`, 'segundo cliente en espera')
  check('La segunda persona queda en espera con su posición real', await evaluate(`/1 en espera/.test(document.body.innerText)`))
  await shot('12-fila-sala-de-espera', '.ep')
  await openEvent()
  await waitFor(`/Eres la siguiente persona/.test(document.body.innerText)`, 'posición tras recargar')
  check('Recargar la página no hace saltar la fila', await evaluate(`${textButton('Compra no disponible todavía')}.disabled === true`))
  await logout()
  await loginAs(accounts.client)
  await openEvent()
  await clickText('Renunciar a mi turno')
  await waitFor(`!!${textButton('Entrar a la fila')}`, 'turno liberado')
  await logout()
  await loginAs(second)
  await openEvent()
  await waitFor(`/Es tu turno/.test(document.body.innerText)`, 'admisión del siguiente', 20000)
  check('Al salir la primera persona, la siguiente es admitida por el servidor', true)
  await send('Emulation.setDeviceMetricsOverride', { width: 390, height: 844, deviceScaleFactor: 2, mobile: true })
  await openEvent()
  await waitFor(`!!document.querySelector('.ep-bar')`, 'barra móvil')
  check('En móvil la página no desborda y hay barra de compra inferior', (await evaluate(`document.documentElement.scrollWidth - document.documentElement.clientWidth`)) <= 1)
  await shot('13-compra-movil-turno')
  await clickText('Ver compra')
  await pause(500)
  await shot('14-compra-movil-panel-abierto')
  await send('Emulation.setDeviceMetricsOverride', { width: 1440, height: 1000, deviceScaleFactor: 1, mobile: false })
  await logout()
  await loginAs(accounts.organizer)
  await clickText('Mis eventos')

  // 8) Móvil del organizador.
  await send('Emulation.setDeviceMetricsOverride', { width: 390, height: 844, deviceScaleFactor: 2, mobile: true })
  await go()
  await clickText('Mis eventos', 'button')
  await waitFor(`!!document.querySelector('.organizer-tabs')`, 'panel móvil')
  const overflow = await evaluate(`document.documentElement.scrollWidth - document.documentElement.clientWidth`)
  check('El panel del organizador no desborda horizontalmente en móvil', overflow <= 1, `${overflow}px`)
  await shot('09-organizador-movil')
  await clickText('Recinto y entradas')
  await shot('10-inventario-movil', '.organizer-detail')
  await writeFile(resolve(output, `resultado-e2e-${stamp}.json`), JSON.stringify({ fecha: stamp, flujo: 'crear → recinto/plano → función → publicar → reservar → QR → validar', verificaciones: results, excepcionesDePagina: pageErrors }, null, 2))
  console.log(pageErrors.length ? `Excepciones de página: ${pageErrors.length}` : 'Sin excepciones de página')
} catch (error) {
  console.error('E2E fallido:', error.message)
  await shot('error-final').catch(() => undefined)
  await writeFile(resolve(output, `resultado-e2e-${stamp}.json`), JSON.stringify({ fecha: stamp, verificaciones: results, error: error.message, excepcionesDePagina: pageErrors }, null, 2)).catch(() => undefined)
  process.exitCode = 1
} finally {
  socket.close()
  browser.kill('SIGTERM')
}
