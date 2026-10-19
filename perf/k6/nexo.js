// Escenarios k6 de NexoEventos (solo entorno local aislado; datos ficticios).
// Uso: lo lanzan perf/run_local.py y perf/run_cloud.py. Variables: BASE_URL, SCENARIO, PROFILE (smoke|progressive|step), RUN_ID, ORIGIN, STEP_VUS, STEP_SECONDS.
// Escenarios: catalog | detail | availability | reserve | same_seat
import http from 'k6/http'
import { check, sleep } from 'k6'
import { Counter } from 'k6/metrics'
import exec from 'k6/execution'

const BASE = __ENV.BASE_URL
const SCENARIO = __ENV.SCENARIO
const PROFILE = __ENV.PROFILE || 'smoke'
const RUN = __ENV.RUN_ID || String(Date.now())
const ORIGIN = __ENV.ORIGIN || 'http://localhost:5173' // origen permitido por el backend (local o dominio del despliegue)
const FIX = { general: 90001, zones: 90002, seats: 90003, dispute: 90004 } // creados por perf/fixture.py
const SEAT_EVENTS = [1028, 1029, 1030] // asientos numerados del catálogo demo
const MAX_VUS = 50 // límite duro de esta fase
const JSON_HEADERS = { 'Content-Type': 'application/json', Origin: ORIGIN }

const reservasOk = new Counter('reservas_ok')
const reservasRepetidas = new Counter('reservas_repetidas_idempotentes')
const conflictosEsperados = new Counter('conflictos_esperados')
const erroresInesperados = new Counter('errores_inesperados')
const intentosMismoAsiento = new Counter('intentos_mismo_asiento')

const smoke = PROFILE === 'smoke'
const step = PROFILE === 'step' // un peldaño de la escalera de nube: STEP_VUS usuarios (≤ MAX_VUS), STEP_SECONDS de meseta
const STEP_VUS = Math.min(Number(__ENV.STEP_VUS || 10), MAX_VUS)
const STEP_SECONDS = Math.min(Number(__ENV.STEP_SECONDS || 120), 300)
const stages = (peak) => step
  ? [{ duration: '30s', target: peak }, { duration: `${STEP_SECONDS}s`, target: peak }, { duration: '5s', target: 0 }]
  : smoke
  ? [{ duration: '5s', target: 2 }, { duration: '10s', target: 2 }, { duration: '2s', target: 0 }]
  : [{ duration: '20s', target: Math.round(peak / 5) }, { duration: '30s', target: Math.round(peak / 2) }, { duration: '30s', target: peak }, { duration: '40s', target: peak }, { duration: '5s', target: 0 }]
const PEAK = step ? { catalog: STEP_VUS, detail: STEP_VUS, availability: STEP_VUS, reserve: STEP_VUS } : { catalog: 50, detail: 50, availability: 50, reserve: 40 }
const DISPUTE_SEATS = smoke ? 3 : 20
const DISPUTE_VUS = smoke ? 5 : step ? Math.max(5, STEP_VUS) : MAX_VUS

function scenarioConfig() {
  if (SCENARIO === 'same_seat') return { executor: 'per-vu-iterations', vus: DISPUTE_VUS, iterations: DISPUTE_SEATS, maxDuration: '3m', exec: 'same_seat' }
  if (!(SCENARIO in PEAK)) throw new Error(`SCENARIO desconocido: ${SCENARIO}`)
  return { executor: 'ramping-vus', startVUs: 0, stages: stages(PEAK[SCENARIO]), gracefulRampDown: '5s', exec: SCENARIO }
}

// En la nube la prueba se corta sola si el servicio se degrada (parada automática del peldaño).
const abortThresholds = step ? {
  http_req_failed: [{ threshold: 'rate<0.01', abortOnFail: true, delayAbortEval: '30s' }],
  ...(SCENARIO === 'same_seat' ? {} : { 'http_req_duration{op:reserve}': [{ threshold: 'p(95)<2000', abortOnFail: true, delayAbortEval: '45s' }] }),
  'http_req_duration{name:GET /api/events}': [{ threshold: 'p(95)<2000', abortOnFail: true, delayAbortEval: '45s' }],
} : {}

export const options = {
  scenarios: { [SCENARIO]: scenarioConfig() },
  noCookiesReset: true, // la sesión de cada usuario virtual persiste entre iteraciones
  summaryTrendStats: ['avg', 'med', 'p(90)', 'p(95)', 'p(99)', 'max'],
  thresholds: {
    http_req_duration: ['p(95)<2000'], // objetivo del proyecto (E01)
    ...(step ? {} : { http_req_failed: ['rate<0.01'] }),
    ...abortThresholds,
    errores_inesperados: ['count==0'],
    ...(step ? {} : { 'http_req_duration{op:reserve}': ['p(95)<2000'] }), // solo la reserva, sin el inicio de sesión (que usa Argon2)
    'http_req_duration{op:login}': ['p(95)<3600000'], // sin límite real: solo hace que k6 informe la latencia del inicio de sesión
  },
}

const expected = http.expectedStatuses({ min: 200, max: 299 }, 409)
const rand = (n) => Math.floor(Math.random() * n)
const pick = (list) => list[rand(list.length)]
const secret = () => Array.from({ length: 24 }, () => 'abcdefghijkmnpqrstuvwxyz23456789'[rand(32)]).join('') // contraseña efímera de prueba

function jsonOf(response) { try { return response.json() } catch (e) { return null } }

export function setup() {
  const catalog = http.get(`${BASE}/api/events`)
  const ids = (jsonOf(catalog) || []).map((item) => item.id).filter((id) => id < 90000)
  const data = { ids, users: [], seatIds: {}, startAt: 0 }
  if (SCENARIO === 'reserve' || SCENARIO === 'same_seat') {
    const total = SCENARIO === 'same_seat' ? DISPUTE_VUS : PEAK.reserve
    for (let i = 0; i < total; i += 1) {
      const user = { email: `k6-${RUN}-${i}@example.com`, password: secret(), display_name: `Usuario K6 ${i}` }
      const response = http.post(`${BASE}/api/auth/register`, JSON.stringify(user), { headers: JSON_HEADERS })
      if (response.status !== 201) throw new Error(`No se pudo registrar el usuario ficticio ${i}: ${response.status}`)
      data.users.push(user)
    }
    for (const [name, id] of [['seats', FIX.seats], ['dispute', FIX.dispute]]) {
      const detail = jsonOf(http.get(`${BASE}/api/events/${id}`))
      if (!detail || !detail.seats) throw new Error(`Falta el fixture ${id}: ejecuta perf/fixture.py`)
      data.seatIds[name] = detail.seats.map((seat) => seat.id)
    }
    data.startAt = Date.now() + 10000
  }
  return data
}

let sessionReady = false
function login(data) {
  if (sessionReady) return true
  const user = data.users[(exec.vu.idInTest - 1) % data.users.length]
  const response = http.post(`${BASE}/api/auth/login`, JSON.stringify({ email: user.email, password: user.password }), { headers: JSON_HEADERS, tags: { name: 'POST /api/auth/login', op: 'login' } })
  if (response.status !== 200) { if (__ENV.DEBUG) console.log(`login ${response.status} ${String(response.body).slice(0, 160)}`); erroresInesperados.add(1); return false }
  sessionReady = true
  return true
}

function postReservation(eventId, body, key) {
  const csrf = http.cookieJar().cookiesForURL(BASE)['nexoeventos_csrf']
  const headers = { ...JSON_HEADERS, 'Idempotency-Key': key, 'X-CSRF-Token': csrf ? csrf[0] : '' }
  const response = http.post(`${BASE}/api/events/${eventId}/reservations`, JSON.stringify(body), { headers, responseCallback: expected, tags: { name: 'POST /api/events/{id}/reservations', op: 'reserve' } })
  if (response.status === 201) reservasOk.add(1)
  else if (response.status === 200) { /* repetición idempotente: la cuenta quien la envía */ }
  else if (response.status === 409 && /ya no están disponibles|No hay cupos/.test(response.body)) conflictosEsperados.add(1)
  else { if (__ENV.DEBUG) console.log(`inesperado ${response.status} ${String(response.body).slice(0, 160)}`); erroresInesperados.add(1) } // 5xx, 4xx inesperado o 409 por otro motivo (p. ej. clave de idempotencia)
  return response
}

export function catalog() {
  const response = http.get(`${BASE}/api/events`, { tags: { name: 'GET /api/events' } })
  check(response, { 'catálogo 200 con eventos': (r) => r.status === 200 && jsonOf(r).length > 0 })
  sleep(0.3 + Math.random() * 0.7)
}

export function detail(data) {
  const response = http.get(`${BASE}/api/events/${pick(data.ids)}`, { tags: { name: 'GET /api/events/{id}' } })
  check(response, { 'detalle 200': (r) => r.status === 200 && jsonOf(r).id > 0 })
  sleep(0.3 + Math.random() * 0.7)
}

export function availability() {
  const id = pick(SEAT_EVENTS)
  const response = http.get(`${BASE}/api/events/${id}`, { tags: { name: 'GET /api/events/{id} (asientos y zonas)' } })
  const body = jsonOf(response)
  check(response, {
    'inventario de asientos y zonas': (r) => r.status === 200 && body && body.seats.length > 0 && body.zones.length > 0,
    'disponibilidad coherente': () => body && body.seats.every((s) => typeof s.available === 'boolean') && body.zones.every((z) => z.available_capacity >= 0 && z.available_capacity <= z.capacity),
  })
  const sales = http.get(`${BASE}/api/events/${id}/sales`, { tags: { name: 'GET /api/events/{id}/sales' } })
  check(sales, { 'estado de ventas 200': (r) => r.status === 200 })
  sleep(0.3 + Math.random() * 0.7)
}

export function reserve(data) {
  if (!login(data)) { sleep(1); return }
  http.get(`${BASE}/api/events`, { tags: { name: 'GET /api/events' } })
  const roll = Math.random()
  const key = `k6-${RUN}-${exec.vu.idInTest}-${exec.scenario.iterationInTest}`
  if (roll < 0.5) {
    const zones = jsonOf(http.get(`${BASE}/api/events/${FIX.zones}`, { tags: { name: 'GET /api/events/{id}' } })).zones
    const body = { quantity: 1 + rand(2), zone_id: pick(zones).id, seat_ids: [] }
    const response = postReservation(FIX.zones, body, key)
    if (response.status === 201 && Math.random() < 0.15) { // repetición idempotente: no debe duplicar la reserva
      const again = postReservation(FIX.zones, body, key)
      const same = again.status === 200 && jsonOf(again).replayed === true && jsonOf(again).reservation_id === jsonOf(response).reservation_id
      check(again, { 'repetición idempotente devuelve la misma reserva': () => same })
      if (same) reservasRepetidas.add(1); else erroresInesperados.add(1)
    }
  } else if (roll < 0.8) {
    postReservation(FIX.general, { quantity: 1 + rand(3), zone_id: null, seat_ids: [] }, key)
  } else {
    const seats = data.seatIds.seats
    const index = (exec.scenario.iterationInTest * MAX_VUS + exec.vu.idInTest) % seats.length // asientos distintos por iteración
    postReservation(FIX.seats, { quantity: 1, zone_id: null, seat_ids: [seats[index]] }, key)
  }
  if (Math.random() < 0.1) {
    const mine = http.get(`${BASE}/api/me/tickets`, { tags: { name: 'GET /api/me/tickets' } })
    check(mine, { 'mis entradas 200': (r) => r.status === 200 })
  }
  sleep(0.3 + Math.random() * 0.7)
}

// Todos los usuarios intentan el MISMO asiento casi a la vez; cada «oleada» es un asiento distinto.
export function same_seat(data) {
  const wave = exec.vu.iterationInScenario
  if (!login(data)) return
  const seatId = data.seatIds.dispute[wave]
  const wait = data.startAt + wave * 600 - Date.now()
  if (wait > 0) sleep(wait / 1000)
  intentosMismoAsiento.add(1)
  postReservation(FIX.dispute, { quantity: 1, zone_id: null, seat_ids: [seatId] }, `k6-${RUN}-${exec.vu.idInTest}-${wave}`)
}

export function handleSummary(data) {
  const pick = (name, keys) => { const m = data.metrics[name]; return m ? Object.fromEntries(keys.filter((k) => k in m.values).map((k) => [k, m.values[k]])) : null }
  const thresholds = {}
  for (const [name, metric] of Object.entries(data.metrics)) for (const [rule, result] of Object.entries(metric.thresholds || {})) thresholds[`${name}: ${rule}`] = result.ok
  const compact = {
    duration_ms: data.state.testRunDurationMs,
    requests: pick('http_reqs', ['count', 'rate']),
    latency_ms: pick('http_req_duration', ['avg', 'med', 'p(90)', 'p(95)', 'p(99)', 'max']),
    latency_by_op: { reserve: pick('http_req_duration{op:reserve}', ['med', 'p(95)', 'p(99)', 'max']), login: pick('http_req_duration{op:login}', ['med', 'p(95)', 'p(99)', 'max']) },
    failed_rate: pick('http_req_failed', ['rate']),
    vus_max: pick('vus_max', ['max']),
    iterations: pick('iterations', ['count']),
    checks: pick('checks', ['passes', 'fails']),
    counters: Object.fromEntries(['reservas_ok', 'reservas_repetidas_idempotentes', 'conflictos_esperados', 'errores_inesperados', 'intentos_mismo_asiento'].map((n) => [n, data.metrics[n] ? data.metrics[n].values.count : 0])),
    thresholds,
  }
  return { stdout: `K6SUMMARY ${JSON.stringify(compact)}\n` }
}
