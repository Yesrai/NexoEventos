(function () {
  'use strict'
  let token = ''
  const $ = (id) => document.getElementById(id)
  const el = (tag, text, cls) => { const e = document.createElement(tag); if (text !== undefined) e.textContent = text; if (cls) e.className = cls; return e }
  const cls = (s) => ({ OK: 'ok', ADVERTENCIA: 'warn', ERROR: 'err' }[s] || 'unk')
  async function api(path, opts) {
    const r = await fetch(path, Object.assign({ headers: { Authorization: 'Bearer ' + token, 'Content-Type': 'application/json' } }, opts || {}))
    const body = await r.json().catch(() => ({}))
    if (!r.ok) throw new Error(body.detail || ('Error ' + r.status))
    return body
  }
  function fill(node, children) { node.replaceChildren(...children) }
  function card(title, state, detail) { const c = el('div', undefined, 'card'); c.append(el('strong', title + ' · '), el('span', state || 'No verificado', cls(state)), el('div', detail || '', 'note')); return c }
  async function refresh() {
    try {
      const o = await api('api/ops/overview')
      fill($('clouds'), Object.entries(o.nubes.nubes).map(([n, v]) => card(n.toUpperCase(), v.estado, v.detalle + ' (' + v.origen + ')')))
      fill($('sections'), [card('Respaldo', o.respaldo.estado, o.respaldo.detalle), card('Failover', o.failover.estado, o.failover.detalle)])
      $('gate').textContent = o.barreras_failover.ok ? 'Todas las barreras pasan (la ejecución sigue sin estar cableada).' : 'Ejecución BLOQUEADA: ' + o.barreras_failover.barriers.filter((b) => !b.ok).length + ' barreras sin cumplir.'
      fill($('barriers'), o.barreras_failover.barriers.map((b) => { const li = el('li', (b.ok ? 'PASA ' : 'BLOQUEA ') + b.id + ' — ' + b.detalle, b.ok ? 'ok' : 'err'); return li }))
      const l = await api('api/ops/recovery-requests')
      fill($('tipo'), Object.entries(l.tipos).map(([k, v]) => { const op = el('option', v); op.value = k; return op }))
      fill($('reqs'), l.solicitudes.map((r) => {
        const c = card(r.id + ' · ' + r.tipo, r.state, r.reason + ' — solicitada por ' + r.requested_by)
        if (r.state === 'VALIDADA') for (const [act, label] of [['approve', 'Aprobar'], ['deny', 'Denegar']]) { const b = el('button', label); b.onclick = async () => { try { await api('api/ops/recovery-requests/' + r.id + '/' + act, { method: 'POST', body: JSON.stringify({ comment: '' }) }); refresh() } catch (e) { $('msg').textContent = e.message } }; c.append(b) }
        if (['SOLICITADA', 'VALIDADA', 'APROBADA'].includes(r.state)) { const b = el('button', 'Cancelar'); b.onclick = async () => { try { await api('api/ops/recovery-requests/' + r.id + '/cancel', { method: 'POST' }); refresh() } catch (e) { $('msg').textContent = e.message } }; c.append(b) }
        return c
      }))
      const a = await api('api/ops/audit')
      $('chain').textContent = 'Cadena de auditoría: ' + (a.verificacion.ok ? 'íntegra (' + a.verificacion.entradas + ' entradas)' : 'ROTA — ' + a.verificacion.error)
      fill($('audit'), a.entradas.slice(-15).reverse().map((e) => el('li', e.at + ' · ' + e.actor + ' · ' + e.event + ' ' + (e.data.id || ''))))
      $('msg').textContent = ''
    } catch (e) { $('msg').textContent = e.message }
  }
  $('enter').onclick = () => { token = $('token').value; $('token').value = ''; $('app').hidden = false; refresh() }
  $('send').onclick = async () => { try { await api('api/ops/recovery-requests', { method: 'POST', body: JSON.stringify({ tipo: $('tipo').value, reason: $('reason').value }) }); $('reason').value = ''; refresh() } catch (e) { $('msg').textContent = e.message } }
  setInterval(() => { if (token) refresh() }, 30000)
})()
