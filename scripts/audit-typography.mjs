#!/usr/bin/env node
// Audita en Chrome real la tipografía renderizada (familia, pesos, tamaños mínimos, mayúsculas) de las pantallas públicas.
// Uso: node scripts/audit-typography.mjs <carpeta>   (requiere frontend en http://127.0.0.1:5173)
import { spawn } from 'node:child_process'
import { mkdir, writeFile } from 'node:fs/promises'
import { resolve } from 'node:path'

const output = resolve(process.argv[2] ?? 'docs/evidencias/ui/tipografia')
await mkdir(output, { recursive: true })
const base = process.env.E2E_BASE ?? 'http://127.0.0.1:5173'
const port = 9700 + Math.floor(Math.random() * 90)
const chrome = spawn('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', ['--headless=new', `--remote-debugging-port=${port}`, '--use-angle=swiftshader', '--enable-webgl', '--ignore-gpu-blocklist', '--disable-gpu-sandbox', `--user-data-dir=/tmp/nexo-typo-${Date.now()}`, 'about:blank'], { stdio: 'ignore' })
const pause = (ms) => new Promise((done) => setTimeout(done, ms))
let page
for (let i = 0; i < 100 && !page; i += 1) { try { page = (await fetch(`http://127.0.0.1:${port}/json`).then((r) => r.json())).find((t) => t.type === 'page') } catch {} if (!page) await pause(200) }
const socket = new WebSocket(page.webSocketDebuggerUrl)
await new Promise((done) => socket.addEventListener('open', done, { once: true }))
let seq = 0; const waiting = new Map()
socket.addEventListener('message', (e) => { const m = JSON.parse(e.data); const w = m.id && waiting.get(m.id); if (w) { waiting.delete(m.id); m.error ? w.reject(new Error(m.error.message)) : w.resolve(m.result) } })
const send = (method, params = {}) => new Promise((res, rej) => { const id = ++seq; waiting.set(id, { resolve: res, reject: rej }); socket.send(JSON.stringify({ id, method, params })) })
const evaluate = async (expression) => (await send('Runtime.evaluate', { expression, awaitPromise: true, returnByValue: true })).result.value
await send('Page.enable'); await send('Runtime.enable')
const audit = `(() => {
  const families = {}, weights = {}, small = [], upper = [], sizes = {}
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT)
  while (walker.nextNode()) {
    const node = walker.currentNode; const text = node.textContent.trim(); if (!text) continue
    const el = node.parentElement; if (!el || el.closest('canvas, svg, script, style')) continue
    const s = getComputedStyle(el); if (s.display === 'none' || s.visibility === 'hidden' || el.closest('.sr-only')) continue
    const rect = el.getBoundingClientRect(); if (!rect.width || !rect.height) continue
    const fam = s.fontFamily.split(',')[0].replace(/"/g, ''); families[fam] = (families[fam] || 0) + 1
    weights[s.fontWeight] = (weights[s.fontWeight] || 0) + 1
    const px = Math.round(parseFloat(s.fontSize) * 10) / 10; sizes[px] = (sizes[px] || 0) + 1
    if (px < 14) small.push(text.slice(0, 30) + ' (' + px + 'px)')
    if (s.textTransform === 'uppercase') upper.push(text.slice(0, 30))
  }
  const h1 = document.querySelector('h1:not(.sr-only), .nx-hero-title, .ep-hero h1'); const h1s = h1 && getComputedStyle(h1)
  return { families, weights, sizes, small: small.slice(0, 8), upper: upper.slice(0, 8), h1: h1s ? { px: parseFloat(h1s.fontSize), weight: h1s.fontWeight, lh: h1s.lineHeight } : null, overflowX: document.documentElement.scrollWidth > innerWidth + 1 }
})()`
const screens = [
  { slug: 'inicio', event: null }, { slug: 'detalle-concierto', event: 'Noche del Parque' }, { slug: 'detalle-auditorio', event: 'Voces en el Auditorio' },
  { slug: 'ingresar', auth: 'login' }, { slug: 'registro', auth: 'register' },
]
const viewports = [{ name: 'escritorio', width: 1440, height: 900, mobile: false, scale: 1 }, { name: 'movil', width: 390, height: 844, mobile: true, scale: 2 }]
const results = []
for (const screen of screens) for (const vp of viewports) {
  await send('Emulation.setDeviceMetricsOverride', { width: vp.width, height: vp.height, deviceScaleFactor: vp.scale, mobile: vp.mobile })
  await send('Page.navigate', { url: base }); await pause(1800)
  if (screen.event) {
    await evaluate(`(() => { const i = document.querySelector('#main-search'); Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(i, ${JSON.stringify(screen.event)}); i.dispatchEvent(new Event('input', { bubbles: true })) })()`); await pause(400)
    for (let a = 0; a < 10 && !(await evaluate(`!!document.querySelector('.ep-stage')`)); a += 1) { await evaluate(`[...document.querySelectorAll('button')].find((b) => b.getAttribute('aria-label') === ${JSON.stringify(`Ver ${screen.event}`)})?.click()`); await pause(700) }
    await pause(3500)
  }
  if (screen.auth) {
    await evaluate(`(document.querySelector('button[aria-label="Ingresar"]') || [...document.querySelectorAll('.nx-tabbar button')].pop())?.click()`); await pause(900)
    if (screen.auth === 'register') { await evaluate(`[...document.querySelectorAll('button')].find((b) => /crear cuenta|regístrate|registrarme/i.test(b.textContent))?.click()`); await pause(700) }
  }
  await evaluate('window.scrollTo(0, 0)'); await pause(500)
  const data = await evaluate(audit)
  const shot = await send('Page.captureScreenshot', { format: 'png' })
  await writeFile(resolve(output, `${screen.slug}-${vp.name}.png`), Buffer.from(shot.data, 'base64'))
  results.push({ pantalla: screen.slug, vista: vp.name, ...data })
  console.log(screen.slug, vp.name, 'fuentes=', JSON.stringify(data.families), 'pesos=', JSON.stringify(data.weights), 'h1=', JSON.stringify(data.h1), 'menores14=', data.small.length, 'mayusculas=', data.upper.length, 'overflowX=', data.overflowX)
}
await writeFile(resolve(output, 'auditoria.json'), JSON.stringify({ nota: 'Estilos calculados por Chrome sobre texto visible (excluye canvas 3D y SVG).', results }, null, 2))
socket.close(); chrome.kill('SIGTERM')
