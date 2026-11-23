"use strict";
// NexoOps — SPA sin dependencias. Todo el texto de la API entra por textContent (nunca innerHTML) ⇒ sin XSS.
const $ = (s, r = document) => r.querySelector(s);
let CSRF = "", USER = null;
function h(tag, attrs, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (k === "class") e.className = v; else if (k === "style") e.style.cssText = v; else if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
    else if (v === true) e.setAttribute(k, ""); else if (v !== false && v != null) e.setAttribute(k, v);
  }
  for (const c of kids.flat()) if (c != null && c !== false) e.append(c.nodeType ? c : document.createTextNode(String(c)));
  return e;
}
const BASE = (document.querySelector('meta[name="nexoops-base"]') || {}).content || "";
const ic = (n, cls = "") => h("i", { class: "ic " + cls, style: `--i:url(${BASE}/static/icons/${n}.svg)` });
async function api(path, opt = {}) {
  const r = await fetch(BASE + path, { method: opt.method || "GET", headers: { "Content-Type": "application/json", ...(opt.method && opt.method !== "GET" ? { "X-CSRF-Token": CSRF } : {}) }, body: opt.body ? JSON.stringify(opt.body) : undefined, credentials: "same-origin" });
  let j = null; try { j = await r.json(); } catch (_) {}
  if (r.status === 401 && !path.startsWith("/api/auth/")) { USER = null; route(); throw new Error("sesión expirada"); }
  if (!r.ok) { const e = new Error((j && j.detail) || r.statusText); e.status = r.status; throw e; }
  return j;
}
function toast(msg, err) { const t = h("div", { class: "toast" + (err ? " err" : "") }, msg); document.body.append(t); setTimeout(() => t.remove(), 4500); }
const chipFor = (s) => { const m = { OK: "", ADVERTENCIA: "warn", ERROR: "err" }; return h("span", { class: "chip " + (s in m ? m[s] : "mute") }, s === "OK" ? "Operativo" : s === "ADVERTENCIA" ? "En espera / advertencia" : s === "ERROR" ? "Con fallo" : "No verificado"); };
function src(m) {
  if (!m) return null;
  return h("div", { class: "src" }, h("span", { class: "dot " + (m.fresh ? "fresh" : m.observed_at ? "stale" : "") }), `${m.source} · ${m.observed_at || "sin dato"} · ${m.fresh ? "actualizado" : m.observed_at ? "desactualizado" : "no verificado"}`);
}
const val = (m) => h("b", {}, m.value ?? "No verificado");
const metric = (label, m) => h("div", {}, h("span", { class: "label" }, label), val(m), src(m));
function card(cls, icon, title, right, ...body) {
  return h("section", { class: "card " + cls }, h("div", { class: "chead" }, h("div", { class: "ctitle" }, h("span", { class: "cicon" }, ic(icon)), title), right || null), ...body);
}
const st = (e) => e && e.status !== "ok" ? h("div", { class: "note warn" }, `${e.source}: ${e.status === "not_configured" ? "no configurado" : "no disponible"} — ${e.detail}`) : null;

// ---------------- autenticación ----------------
function loginView() {
  const root = $("#root"); root.replaceChildren();
  const err = h("div", { class: "err-t" });
  const email = h("input", { type: "email", autocomplete: "username", required: true }), pw = h("input", { type: "password", autocomplete: "current-password", required: true });
  const box = h("div", { class: "authcard" });
  const step1 = () => {
    let pending = false;
    const submitButton = h("button", { class: "btn", style: "width:100%;justify-content:center", type: "submit" }, ic("lock"), "Continuar");
    box.replaceChildren(h("div", { class: "logo" }, ic("cloud")), h("h1", {}, "NexoOps"), h("div", { class: "label" }, "Centro de Operaciones · acceso de TI"),
      h("form", { style: "margin-top:26px", onsubmit: async (ev) => {
        ev.preventDefault(); err.textContent = "";
        if (pending) return;
        pending = true; submitButton.disabled = true;
        try { await api("/api/auth/login", { method: "POST", body: { email: email.value, password: pw.value } }); pw.value = ""; step2(); }
        catch (e) { err.textContent = e.message; pending = false; submitButton.disabled = false; }
      } }, h("div", { class: "field" }, h("label", { class: "label" }, "Correo electrónico"), email), h("div", { class: "field" }, h("label", { class: "label" }, "Contraseña"), pw), err,
      submitButton));
  };
  const step2 = () => {
    let pending = false;
    const boxes = [...Array(6)].map((_, i) => h("input", { inputmode: "numeric", autocomplete: i ? "off" : "one-time-code" }));
    const read = () => boxes.map((b) => b.value).join("");
    const verifyButton = h("button", { class: "btn" }, "Verificar");
    const submit = async () => {
      if (pending) return;
      pending = true; verifyButton.disabled = true; err.textContent = "";
      try { const r = await api("/api/auth/verify", { method: "POST", body: { code: read() } }); CSRF = r.csrf; USER = r.user; route(); }
      catch (e) { err.textContent = e.message; boxes.forEach((b) => (b.value = "")); boxes[0].focus(); pending = false; verifyButton.disabled = false; }
    };
    verifyButton.addEventListener("click", submit);
    boxes.forEach((b, i) => { b.addEventListener("input", () => { const d = b.value.replace(/\D/g, ""); b.value = d.slice(0, 1); [...d.slice(1)].forEach((c, k) => { if (boxes[i + 1 + k]) boxes[i + 1 + k].value = c; }); const nx = Math.min(5, i + Math.max(1, d.length)); if (d && nx !== i) boxes[nx].focus(); if (read().length === 6) submit(); }); b.addEventListener("keydown", (e) => { if (e.key === "Backspace" && !b.value && i) boxes[i - 1].focus(); });
      b.addEventListener("paste", (e) => { const d = (e.clipboardData.getData("text") || "").replace(/\D/g, "").slice(0, 6); if (d) { e.preventDefault(); [...d].forEach((c, k) => (boxes[k].value = c)); if (d.length === 6) submit(); } }); });
    box.replaceChildren(h("div", { class: "logo" }, ic("mail")), h("h1", {}, "Verifica tu identidad"), h("div", { class: "label" }, "Enviamos un código de 6 dígitos a tu correo. Caduca en 5 minutos."), h("div", { class: "otp" }, boxes), err,
      h("div", { style: "display:flex;gap:10px;justify-content:space-between;margin-top:8px" }, h("button", { class: "btn ghost", onclick: async () => { try { await api("/api/auth/resend", { method: "POST" }); toast("Código reenviado"); } catch (e) { err.textContent = e.message; } } }, "Reenviar código"),
        verifyButton));
    boxes[0].focus();
  };
  step1(); root.append(h("div", { class: "auth" }, box));
  api("/api/auth/challenge").then(() => step2()).catch(() => {});
}

// ---------------- estructura ----------------
const NAV = [["overview", "Overview"], ["infra", "Infraestructura"], ["monitoreo", "Monitoreo"], ["incidentes", "Incidentes"], ["recuperacion", "Recuperación"], ["auditoria", "Auditoría"], ["config", "Configuración"]];
const VIEWS = {};
async function route() {
  if (!USER) { try { const s = await api("/api/auth/session"); USER = s.user; CSRF = s.csrf; } catch (_) { return loginView(); } }
  const key = (location.hash.slice(2) || "overview"); const view = VIEWS[key] || VIEWS.overview;
  const root = $("#root"); root.replaceChildren();
  const content = h("main", {}, h("div", { class: "empty" }, "Cargando…"));
  root.append(h("div", { class: "shell" }, h("header", {},
    h("div", { class: "brand" }, h("span", { class: "logo" }, ic("cloud")), h("div", {}, "NexoOps — Centro de Operaciones", h("small", {}, `${USER.role} · ${USER.email}`))),
    h("nav", {}, NAV.map(([k, l]) => h("a", { class: k === key ? "on" : "", onclick: () => (location.hash = "#/" + k) }, l))),
    h("div", { class: "tools" }, h("button", { class: "pill ai", onclick: () => (location.hash = "#/asistente") }, ic("sparkles"), "NexoOps AI"), h("button", { class: "pill", title: "Actualizar", onclick: route }, ic("refresh-cw")),
      h("button", { class: "pill", title: "Cerrar sesión", onclick: async () => { try { await api("/api/auth/logout", { method: "POST" }); } catch (_) {} USER = null; route(); } }, ic("log-out")))), content));
  try { content.replaceChildren(await view()); } catch (e) { content.replaceChildren(h("div", { class: "note err" }, e.message)); }
}
addEventListener("hashchange", route);

// ---------------- vistas ----------------
VIEWS.overview = async () => {
  const [o, r] = await Promise.all([api("/api/overview"), api("/api/recovery")]);
  const s = o.service, c = o.clouds;
  const worst = ["ERROR", "ADVERTENCIA", "No verificado", "OK"].find((x) => Object.values(c).some((y) => y.estado === x)) || "No verificado";
  const main = card("s7", "heart-pulse", "Estado general de NexoEventos", chipFor(s.estado.value),
    h("div", { class: "label" }, "Servicio · nube primaria"), h("div", { class: "big" }, s.estado.value === "OK" ? "Operativo" : s.estado.value === "ERROR" ? "Con fallo" : s.estado.value === "ADVERTENCIA" ? "Degradado" : "No verificado"), src(s.estado),
    h("div", { class: "kv" }, metric("Nube primaria", s.nube_primaria), metric("Disponibilidad", s.disponibilidad), metric("Salud de API", s.api), metric("Base de datos", s.base_datos), metric("Última comprobación", s.ultima_comprobacion),
      h("div", {}, h("span", { class: "label" }, "Recolector"), h("b", {}, o.collector.status === "ok" ? "Activo" : "Sin datos"), h("div", { class: "src" }, o.collector.detail || ""))));
  const cloudRow = (n, label) => h("div", { class: "cloud" }, h("div", {}, h("b", {}, label), h("div", { class: "label" }, c[n].detalle), c[n].observed_at ? h("div", { class: "src" }, `${c[n].origen} · ${c[n].observed_at}`) : null), chipFor(c[n].estado));
  const green = card("green s5", "cloud", "Cloud Health", h("span", { class: "chip dark" }, worst === "OK" ? "Todo operativo" : worst === "No verificado" ? "Sin verificar" : "Atención"),
    h("div", { class: "label" }, "Alertas Zabbix activas"), h("div", { class: "mid" }, o.zabbix.activos ?? "—", h("span", { class: "label", style: "font-size:13px;margin-left:10px" }, o.zabbix.status === "ok" ? `${o.zabbix.altos} altas` : "Zabbix " + (o.zabbix.status === "not_configured" ? "sin configurar" : "no disponible"))),
    h("div", { class: "clouds" }, cloudRow("aws", "AWS" + (c.aws.alarmas != null ? ` · ${c.aws.alarmas} alarmas` : "")), cloudRow("oci", "OCI"), cloudRow("azure", "Azure")));
  const ser = o.latency.series.filter((x) => x.ms != null);
  const spark = ser.length > 1 ? (() => { const mx = Math.max(...ser.map((x) => x.ms)), W = 300, H = 80; const pts = ser.map((x, i) => `${(i / (ser.length - 1)) * W},${H - (x.ms / mx) * (H - 8) - 4}`).join(" "); const ns = "http://www.w3.org/2000/svg"; const svg = document.createElementNS(ns, "svg"); svg.setAttribute("viewBox", `0 0 ${W} ${H}`); svg.setAttribute("class", "spark"); svg.setAttribute("preserveAspectRatio", "none"); const p = document.createElementNS(ns, "polyline"); p.setAttribute("points", pts); p.setAttribute("fill", "none"); p.setAttribute("stroke", "#7cc83a"); p.setAttribute("stroke-width", "3"); p.setAttribute("stroke-linecap", "round"); svg.append(p); return svg; })() : h("div", { class: "empty" }, "Sin muestras de latencia del recolector.");
  const lat = card("s4", "activity", "Disponibilidad y latencia", null, h("div", { class: "mid" }, s.disponibilidad.value ?? "No verificado"), spark, h("div", { class: "src" }, `${o.latency.source} · ${o.latency.observed_at || "sin dato"}`));
  const rec = card("s4", "life-buoy", "Recuperación y continuidad", h("span", { class: "chip err" }, h("i", { class: "ic", style: `--i:url(${BASE}/static/icons/lock.svg);width:12px;height:12px` }), "Failover bloqueado"),
    h("div", { class: "rows" }, [["Fencing", (r.fencing || {}).veredicto || "UNKNOWN"], ["Epoch autorizado", String(r.epoch_autorizado)], ["Última copia", r.ultima_copia_validada.estado], ["RTO observado", typeof r.rto_observado_s === "number" ? r.rto_observado_s + " s" : r.rto_observado_s],
      ["Barreras cumplidas", `${r.barreras.barriers.filter((b) => b.ok).length}/${r.barreras.barriers.length}`]].map(([a, b]) => h("div", { class: "row" }, a, h("b", {}, b)))), h("div", { class: "src" }, r.source));
  const au = await api("/api/audit");
  const inc = card("s4", "scroll-text", "Incidentes y auditoría reciente", h("span", { class: "chip " + (au.verificacion.ok ? "" : "err") }, au.verificacion.ok ? "Cadena íntegra" : "Cadena rota"),
    h("div", { class: "rows" }, au.entradas.slice(0, 5).map((e) => h("div", { class: "row" }, h("div", {}, e.event, h("small", {}, `${e.actor} · ${e.at}`)), h("span", { class: "mono" }, `#${e.seq}`)))), au.entradas.length ? null : h("div", { class: "empty" }, "Sin entradas."));
  return h("div", {}, h("div", { class: "grid" }, main, green, lat, rec, inc));
};

VIEWS.infra = async () => {
  const [a, oa] = await Promise.all([api("/api/infra/aws"), api("/api/infra/oci-azure")]);
  const t = (head, rows) => rows.length ? h("table", {}, h("tr", {}, head.map((x) => h("th", {}, x))), rows.map((r) => h("tr", {}, r.map((x) => h("td", {}, x))))) : h("div", { class: "empty" }, "Sin elementos.");
  const d = a.data || {};
  const aws = card("s12", "server", "AWS — solo lectura", a.observed_at ? h("span", { class: "src" }, `${a.source} · ${a.observed_at}`) : null, st(a),
    a.status === "ok" ? h("div", { class: "grid" }, h("div", { class: "s6" }, h("h4", { class: "label" }, "EC2"), t(["Instancia", "Estado", "Tipo"], d.ec2.map((x) => [x.id, x.state, x.type]))),
      h("div", { class: "s6" }, h("h4", { class: "label" }, "Auto Scaling Groups"), t(["ASG", "Deseado", "En servicio"], d.asg.map((x) => [x.name, x.desired, x.in_service]))),
      h("div", { class: "s6" }, h("h4", { class: "label" }, "ALB"), t(["Nombre", "Estado"], d.alb.map((x) => [x.name, x.state]))), h("div", { class: "s6" }, h("h4", { class: "label" }, "RDS"), t(["Id", "Estado", "Multi-AZ"], d.rds.map((x) => [x.id, x.status, x.multi_az ? "sí" : "no"]))),
      h("div", { class: "s12" }, h("h4", { class: "label" }, "Alarmas en ALARM"), t(["Alarma", "Motivo"], d.alarms_in_alarm.map((x) => [x.name, x.reason])))) : null);
  const cl = (oa.snapshot.data || {}).clouds || {};
  const oci = card("s6", "hard-drive", "OCI — recuperación", chipFor((cl.oci || {}).estado), h("p", { class: "label" }, (cl.oci || {}).detalle || oa.snapshot.detail), src({ source: oa.snapshot.source, observed_at: oa.snapshot.observed_at, fresh: oa.snapshot.status === "ok" }),
    h("div", { class: "note warn", style: "margin-top:14px" }, "Consulta directa con el SDK de OCI: pendiente. El estado proviene de las sondas del recolector."));
  const az = card("s6", "box", "Azure — operación", chipFor((cl.azure || {}).estado), h("p", { class: "label" }, (cl.azure || {}).detalle || oa.snapshot.detail), src({ source: oa.snapshot.source, observed_at: oa.snapshot.observed_at, fresh: oa.snapshot.status === "ok" }));
  return h("div", {}, h("div", { class: "title" }, "Infraestructura"), h("div", { class: "grid" }, aws, oci, az));
};

let GSEL = { uid: null, range: "1h" };
VIEWS.monitoreo = async () => {
  const [gd, z] = await Promise.all([api("/api/monitoring/grafana"), api("/api/monitoring/zabbix")]);
  const body = h("div", { class: "panelgrid" });
  const ds = (gd.data || {}).dashboards || [];
  const sel = h("select", { class: "sel", onchange: () => { GSEL.uid = sel.value; load(); } }, ds.map((d) => h("option", { value: d.uid }, `${d.folder} / ${d.title}`)));
  if (GSEL.uid) sel.value = GSEL.uid;
  const seg = h("div", { class: "seg" }, ["15m", "1h", "6h", "24h", "7d"].map((k) => h("button", { class: GSEL.range === k ? "on" : "", onclick: () => { GSEL.range = k; load(); } }, k)));
  async function load() {
    seg.querySelectorAll("button").forEach((b) => b.classList.toggle("on", b.textContent === GSEL.range));
    const uid = sel.value || (ds[0] && ds[0].uid); if (!uid) return; GSEL.uid = uid; body.replaceChildren(h("div", { class: "empty" }, "Cargando paneles…"));
    const p = await api(`/api/monitoring/grafana/${encodeURIComponent(uid)}?range=${GSEL.range}`);
    const panelView = (x) => {
      const metrics = h("div", { class: "label" }, "Métricas no consultadas todavía.");
      const query = h("button", { class: "btn ghost", onclick: async () => {
        query.disabled = true; metrics.replaceChildren("Consultando la API de Grafana…");
        try {
          const m = await api(`/api/monitoring/grafana/${encodeURIComponent(uid)}/panels/${x.id}/metrics?range=${GSEL.range}`);
          const fields = (m.data?.series || []).flatMap((s) => s.fields || []).filter((f) => f.type === "number" || f.type === "boolean");
          metrics.replaceChildren(fields.length ? h("div", { class: "rows" }, fields.map((f) => h("div", { class: "row" }, f.name || "valor", h("b", {}, String(f.values.filter((v) => v != null).at(-1) ?? "sin dato"))))) : h("div", { class: "empty" }, "El panel no devolvió series numéricas."),
            h("div", { class: "src" }, `${m.source} · ${m.observed_at || "sin hora"}`));
        } catch (e) { metrics.replaceChildren(h("div", { class: "note err" }, e.message)); }
        finally { query.disabled = false; }
      } }, "Consultar métricas");
      return h("div", { class: "panel" }, h("div", { class: "row" }, x.title || "(sin título)", h("span", {}, query, " · ", h("a", { href: x.open_url, target: "_blank", rel: "noopener" }, "Abrir"), " · ", h("a", { href: x.edit_url, target: "_blank", rel: "noopener" }, "Editar"))),
        metrics, x.embed_url ? h("iframe", { src: x.embed_url, loading: "lazy", sandbox: "allow-scripts allow-same-origin" }) : h("div", { class: "label" }, "Incrustación desactivada (NEXOOPS_GRAFANA_EMBED). Usa «Abrir» para ver el panel autenticado en Grafana."));
    };
    body.replaceChildren(...(p.status !== "ok" ? [st(p)] : p.data.panels.map(panelView)));
  }
  const graf = card("s12", "chart-line", "Grafana", h("div", { style: "display:flex;gap:10px" }, ds.length ? [sel, seg] : []), st(gd), body, gd.observed_at ? h("div", { class: "src" }, `${gd.source} · ${gd.observed_at}`) : null);
  if (ds.length) setTimeout(load, 0);
  const probs = (z.problems.data || {}).problems || [], hosts = (z.hosts.data || {}).hosts || [];
  const zc = card("s7", "siren", "Zabbix — problemas activos", z.problems.observed_at ? h("span", { class: "src" }, `${z.problems.source} · ${z.problems.observed_at}`) : null, st(z.problems),
    probs.length ? h("table", {}, h("tr", {}, ["Severidad", "Problema", "Host", "Desde"].map((x) => h("th", {}, x))), probs.map((p) => h("tr", {}, h("td", {}, h("span", { class: "chip " + (p.severity_n >= 4 ? "err" : "warn") }, p.severity)), h("td", {}, p.name), h("td", {}, (p.hosts || []).map((x) => x.name).join(", ") || "—"), h("td", { class: "mono" }, p.since)))) : (z.problems.status === "ok" ? h("div", { class: "empty" }, "Sin problemas activos.") : null));
  const zh = card("s5", "server", "Zabbix — hosts", null, st(z.hosts), hosts.length ? h("div", { class: "rows" }, hosts.map((x) => h("div", { class: "row" }, h("div", {}, x.name, h("small", {}, x.monitored ? "monitorizado" : "sin monitorizar")), h("span", { class: "chip " + (x.available === "disponible" ? "" : x.available === "no disponible" ? "err" : "mute") }, x.available)))) : null);
  return h("div", {}, h("div", { class: "title" }, "Monitoreo"), h("div", { class: "grid" }, graf, zc, zh));
};

VIEWS.incidentes = async () => {
  const i = await api("/api/incidents");
  const ev = (i.zabbix.data || {}).events || [];
  const hist = card("s7", "siren", "Historial de incidentes (Zabbix)", null, st(i.zabbix), ev.length ? h("table", {}, h("tr", {}, ["Hora UTC", "Severidad", "Incidente", "Estado"].map((x) => h("th", {}, x))), ev.map((e) => h("tr", {}, h("td", { class: "mono" }, e.at), h("td", {}, e.severity), h("td", {}, e.name), h("td", {}, h("span", { class: "chip " + (e.recovered ? "" : "err") }, e.recovered ? "Recuperado" : "Abierto"))))) : (i.zabbix.status === "ok" ? h("div", { class: "empty" }, "Sin incidentes.") : null));
  const svc = h("select", { class: "sel" }, ["nexoeventos-api", "grafana-server", "zabbix-server", "ops-center"].map((s) => h("option", {}, s)));
  const reason = h("textarea", { placeholder: "Justificación (10–300 caracteres)" }), conf = h("input", { type: "checkbox" });
  const form = card("s5", "play-circle".replace("play-circle", "lock-keyhole"), "Solicitar reinicio controlado", null, h("div", { class: "note warn" }, "Solo registra una solicitud. No se ejecuta nada: queda bloqueada hasta contar con una aprobación independiente (hay un único usuario TI)."),
    h("div", { class: "field", style: "margin-top:14px" }, svc, reason, h("label", { class: "label" }, conf, " Confirmo que entiendo que esto solo crea una solicitud")),
    h("button", { class: "btn", onclick: async () => { try { const r = await api("/api/actions", { method: "POST", body: { name: "service.restart.request", confirm: conf.checked, params: { service: svc.value, reason: reason.value } } }); toast(`Solicitud ${r.result.id} registrada (bloqueada)`); route(); } catch (e) { toast(e.message, true); } } }, "Registrar solicitud"));
  const reqs = card("s12", "scroll-text", "Solicitudes de intervención", null, i.solicitudes_intervencion.length ? h("table", {}, h("tr", {}, ["Id", "Servicio", "Creada", "Estado"].map((x) => h("th", {}, x))), i.solicitudes_intervencion.map((r) => h("tr", {}, h("td", { class: "mono" }, r.id), h("td", {}, r.service), h("td", { class: "mono" }, r.created_at), h("td", {}, h("span", { class: "chip warn" }, r.state))))) : h("div", { class: "empty" }, "Sin solicitudes."));
  return h("div", {}, h("div", { class: "title" }, "Incidentes"), h("div", { class: "grid" }, hist, form, reqs));
};

VIEWS.recuperacion = async () => {
  const r = await api("/api/recovery");
  const kv = (a, b, d) => h("div", { class: "row" }, h("div", {}, a, d ? h("small", {}, d) : null), h("b", {}, b));
  const main = card("s7", "life-buoy", "Recuperación AWS → OCI", h("span", { class: "lock" }, ic("lock"), "Failover y failback reales: BLOQUEADOS"),
    h("div", { class: "note err" }, r.nota), h("div", { class: "rows" }, kv("Estado de AWS", r.aws.estado, r.aws.detalle), kv("Estado de OCI", r.oci.estado, r.oci.detalle), kv("Fuente de verdad", r.fuente_de_verdad.valor, r.fuente_de_verdad.detalle), kv("Lease", r.lease.estado, r.lease.detalle),
      kv("Fencing", (r.fencing || {}).veredicto || "UNKNOWN"), kv("Epoch autorizado", String(r.epoch_autorizado)), kv("Última copia validada", r.ultima_copia_validada.estado, r.ultima_copia_validada.detalle), kv("RTO observado", typeof r.rto_observado_s === "number" ? r.rto_observado_s + " s" : r.rto_observado_s), kv("RPO observado", r.rpo_observado.valor, r.rpo_observado.detalle)), h("div", { class: "src" }, r.source + " · " + r.generated_at));
  const bar = card("s5", "shield-check", "Barreras de seguridad", h("span", { class: "chip " + (r.barreras.ok ? "" : "err") }, r.barreras.ok ? "Todas OK" : "Incumplidas"), h("div", { class: "rows" }, r.barreras.barriers.map((b) => h("div", { class: "row" }, h("div", {}, b.id, h("small", {}, b.detalle)), h("span", { class: "chip " + (b.ok ? "" : "err") }, b.ok ? "OK" : "NO")))));
  const pend = card("s6", "clock", "Operaciones pendientes", null, r.operaciones_pendientes.length ? h("div", { class: "rows" }, r.operaciones_pendientes.map((p) => kv(p.tipo, p.estado, `${p.id} · ${p.solicitada_por} · ${p.creada}`))) : h("div", { class: "empty" }, "Ninguna."));
  const ap = card("s6", "scroll-text", "Historial de aprobaciones", null, r.historial_aprobaciones.length ? h("div", { class: "rows" }, r.historial_aprobaciones.map((p) => kv(p.tipo, p.decision.approved ? "Aprobada" : "Denegada", `${p.decision.by} · ${p.decision.at}`))) : h("div", { class: "empty" }, "Sin decisiones registradas."));
  return h("div", {}, h("div", { class: "title" }, "Recuperación"), h("div", { class: "grid" }, main, bar, pend, ap));
};

VIEWS.auditoria = async () => {
  const a = await api("/api/audit");
  return h("div", {}, h("div", { class: "title" }, "Auditoría"), h("div", { class: "grid" }, card("s12", "scroll-text", "Registro de operaciones (cadena de hashes)", h("span", { class: "chip " + (a.verificacion.ok ? "" : "err") }, a.verificacion.ok ? `Íntegra · ${a.verificacion.entradas} entradas` : a.verificacion.error),
    h("table", {}, h("tr", {}, ["#", "UTC", "Usuario", "Evento", "Detalle"].map((x) => h("th", {}, x))), a.entradas.map((e) => h("tr", {}, h("td", { class: "mono" }, e.seq), h("td", { class: "mono" }, e.at), h("td", {}, e.actor), h("td", {}, e.event), h("td", { class: "mono" }, JSON.stringify(e.data))))))));
};

VIEWS.config = async () => {
  const [c, a] = await Promise.all([api("/api/config"), api("/api/actions")]);
  const yes = (v) => h("span", { class: "chip " + (v && v !== "pendiente" ? "" : "mute") }, v === true ? "Configurado" : v === false ? "Sin configurar" : String(v));
  return h("div", {}, h("div", { class: "title" }, "Configuración"), h("div", { class: "grid" },
    card("s5", "settings", "Integraciones", null, h("div", { class: "rows" }, Object.entries(c.integraciones).map(([k, v]) => h("div", { class: "row" }, k, yes(v)))), h("div", { class: "note", style: "margin-top:14px" }, c.politica)),
    card("s7", "lock-keyhole", "Acciones permitidas", null, h("div", { class: "rows" }, a.acciones.map((x) => h("div", { class: "row" }, h("div", {}, x.label, h("small", { class: "mono" }, x.name)), h("span", { class: "chip " + (x.risk === "bloqueada" ? "err" : x.risk === "solicitud" ? "warn" : "") }, x.risk)))),
      h("div", { style: "display:flex;gap:10px;margin-top:14px;flex-wrap:wrap" }, a.acciones.filter((x) => x.risk === "lectura").map((x) => h("button", { class: "btn ghost", onclick: async () => { try { const r = await api("/api/actions", { method: "POST", body: { name: x.name, params: {} } }); toast(`${x.name}: ${r.result.status || "ok"} · ${r.execution_id}`); } catch (e) { toast(e.message, true); } } }, x.name))))));
};

VIEWS.asistente = async () => {
  const out = h("div", { class: "chat" }), q = h("input", { placeholder: "Pregunta sobre incidentes, recuperación o latencia…", style: "flex:1;height:48px;border-radius:999px;border:1px solid var(--line);padding:0 20px;font:inherit" });
  const sec = (cls, t, items) => items.length ? h("div", { class: "sec " + cls }, h("h4", {}, t), h("ul", {}, items)) : null;
  const ask = async () => {
    out.replaceChildren(h("div", { class: "empty" }, "Analizando datos autorizados…"));
    try {
      const r = await api("/api/assistant", { method: "POST", body: { question: q.value } });
      out.replaceChildren(h("div", { class: "note" }, `Motor: ${r.engine}. IA generativa: ${r.llm.estado}. ${r.llm.detalle}`),
        sec("f", "Hechos observados", r.hechos.map((x) => h("li", {}, x.text, h("div", { class: "src" }, `${x.source} · ${x.observed_at || "sin hora"}`)))),
        sec("h", "Hipótesis (no confirmadas)", r.hipotesis.map((x) => h("li", {}, x.text, h("div", { class: "src" }, "confianza " + x.confidence)))),
        sec("r", "Recomendaciones", r.recomendaciones.map((x) => h("li", {}, x.text, x.action ? h("div", { class: "src" }, "acción permitida: " + x.action) : null))),
        r.borrador_solicitud ? h("div", { class: "sec" }, h("h4", {}, "Borrador de solicitud de intervención"), h("div", {}, `${r.borrador_solicitud.action} · ${r.borrador_solicitud.params.service}`), h("div", { class: "src" }, r.borrador_solicitud.nota)) : null);
    } catch (e) { out.replaceChildren(h("div", { class: "note err" }, e.message)); }
  };
  q.addEventListener("keydown", (e) => e.key === "Enter" && ask());
  return h("div", {}, h("div", { class: "title" }, "NexoOps AI — Asistente de operaciones"), card("s12", "sparkles", "Diagnóstico", null, h("div", { style: "display:flex;gap:10px;margin-bottom:18px" }, q, h("button", { class: "btn", onclick: ask }, "Analizar")), out));
};

route();
