# -*- coding: utf-8 -*-
"""Inventario maestro de evidencias de NexoEventos (solo lectura de las fuentes).
Recorre las evidencias originales, calcula SHA-256, fecha UTC y clasifica cada archivo.
Salida: JSON (para el informe), XLSX y MD en el worktree de la rama informe-final-completo."""
import os, re, json, glob, hashlib, subprocess, datetime as dt, sys
from collections import OrderedDict

REPO = "~/Workspace/NexoEventos"            # fuente (rama cierre-t6-t8 + work/ no versionado)
CODEX = "~/Workspace/NexoEventos-codex-t7-t8"  # solo lectura
OUT = "~/Workspace/NexoEventos-informe-final/docs/entrega-final"
S = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""): h.update(b)
    return h.hexdigest()

_gitcache = {}
def git_date(root, rel):
    key = (root, rel)
    if key in _gitcache: return _gitcache[key]
    r = subprocess.run(["git", "-C", root, "log", "-1", "--format=%cI", "--", rel], capture_output=True, text=True).stdout.strip()
    v = None
    if r:
        v = dt.datetime.fromisoformat(r).astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
    _gitcache[key] = v
    return v

def tracked(root, rel):
    return subprocess.run(["git", "-C", root, "ls-files", "--error-unmatch", rel], capture_output=True).returncode == 0

def mtime(p):
    return dt.datetime.fromtimestamp(os.path.getmtime(p), dt.timezone.utc).strftime("%Y-%m-%dT%H:%MZ")

items = []
counters = {}
def add(etapa, crit, desc, root, rel, tipo, nat, lugar, res, lim, fecha=None, fuente_fecha=None, zip_ok=True, ruta_show=None):
    p = os.path.join(root, rel)
    if not os.path.isfile(p):
        print("FALTA", p, file=sys.stderr); return
    n = counters.get(etapa, 0) + 1; counters[etapa] = n
    if fecha is None:
        if tracked(root, rel):
            fecha = git_date(root, rel); fuente_fecha = "último commit (git)"
        else:
            fecha = mtime(p); fuente_fecha = "fecha de modificación del archivo (no versionado)"
    if ruta_show is None:
        ruta_show = rel if root == REPO else "../NexoEventos-codex-t7-t8/" + rel
    items.append(OrderedDict(
        id=f"EV-{etapa}-{n:03d}", etapa=etapa, criterios=crit, descripcion=desc, ruta=ruta_show,
        fecha_utc=fecha, fuente_fecha=fuente_fecha, tipo=tipo, naturaleza=nat, lugar=lugar,
        resultado=res, sha256=sha(p), bytes=os.path.getsize(p), limitacion=lim, en_zip="sí" if zip_ok else "no",
        _abs=p))

# ---------------------------------------------------------------- criterios por etapa
CRIT = {"T1": "10, 5, 12", "T2": "10, 5, 12", "T3": "9, 4, 3, 8, 10, 12", "T4": "7, 5, 10, 12",
        "T5": "6, 7, 8, 11, 12", "T6": "9, 10, 12", "T7": "7, 5, 12", "T8": "13, 14, 11"}

# ---------------------------------------------------------------- 1. Expedientes reales (work/evidencias)
EXP = OrderedDict()
for d in sorted(glob.glob(f"{REPO}/work/evidencias/T*")):
    name = os.path.basename(d)
    etapa = name[:2]
    r = json.load(open(f"{d}/resultado.json")); m = json.load(open(f"{d}/meta.json"))
    ver = r["veredicto"]
    cnt = {}
    for c in r["criterios"]: cnt[c["resultado"]] = cnt.get(c["resultado"], 0) + 1
    tot = len(r["criterios"]); cum = cnt.get("CUMPLE", 0)
    EXP[name] = dict(etapa=etapa, veredicto=ver, inicio=r["inicio_utc"], fin=r["fin_utc"], total=tot, cumple=cum, cnt=cnt,
                     titulo=m.get("title") or r.get("titulo"))
    f_ini = m.get("started_utc", r["inicio_utc"])[:16] + "Z"
    nota = {"T3-20261122T154757Z-ccfe": "Expediente duplicado del intento 1: el recolector contó como RTO el tiempo de una recuperación abortada (error corregido en …c535, que es el válido)."}.get(name, "")
    base_lim = "Expediente no versionado en git (work/ está en .gitignore); integridad por MANIFIESTO.sha256 (verificado: 0 discrepancias)."
    for f in sorted(glob.glob(f"{d}/**/*", recursive=True)):
        if not os.path.isfile(f): continue
        rel = os.path.relpath(f, REPO); bn = os.path.relpath(f, d)
        if bn == "resultado.json": desc = f"Veredicto y {tot} criterios medidos ({cum} CUMPLE; {', '.join(f'{v} {k}' for k, v in cnt.items() if k != 'CUMPLE') or 'ningún otro estado'}) — {EXP[name]['titulo']}"
        elif bn == "resultado.md": desc = "Resumen legible del veredicto del expediente"
        elif bn == "meta.json": desc = "Metadatos: criterios escritos ANTES de la ejecución, valores y hashes"
        elif bn == "events.jsonl": desc = "Bitácora de eventos con marcas UTC (milisegundos)"
        elif bn == "MANIFIESTO.sha256": desc = "Manifiesto SHA-256 de todos los archivos del expediente"
        else: desc = f"Captura de datos del expediente: {bn}"
        lim = base_lim + (" " + nota if nota else "")
        if "smoke.json" in bn: lim += " Contiene la IP pública efímera de una VM ya destruida: en el ZIP va una copia con la IP oculta."
        add(etapa, CRIT[etapa], desc, REPO, rel, "Expediente real (datos crudos)", "directa", "REAL",
            ver, lim, fecha=f_ini, fuente_fecha="inicio del expediente (meta.json)")

# ---------------------------------------------------------------- 2. Informes de resultados y tarjetas (docs/evidencias)
DOCS_T = [
 ("T1", "docs/evidencias/T1-20261122-resultado.md", "Informe T1: 1.ª ejecución FAIL (NameError) → corrección → 2.ª ejecución PASS 12/12", "PASS (final); conserva FAIL"),
 ("T2", "docs/evidencias/T2-TARJETA-AUTORIZACION.md", "Tarjeta de autorización de T2 (alcance, riesgos, reversión)", "N/A"),
 ("T2", "docs/evidencias/T2-20261122-resultado.md", "Informe T2: 1.ª ejecución FAIL (almacén de CA ausente) → corrección TLS → PASS 13/13", "PASS (final); conserva FAIL"),
 ("T3", "docs/evidencias/T3-TARJETA-AUTORIZACION.md", "Tarjeta de autorización de T3 rev. 2", "N/A"),
 ("T3", "docs/evidencias/T3-20261122-intento1-resultado.md", "T3 intento 1: FAIL/abortado (dnf sin límites satura la VM E2.1.Micro)", "FAIL"),
 ("T3", "docs/evidencias/T3-20261122-intento2-resultado.md", "T3 intento 2: FAIL 18/19 (OOM de dnf-makecache)", "FAIL"),
 ("T3", "docs/evidencias/T3-INTENTO3-AUTORIZACION.md", "Autorización del intento 3 de T3", "N/A"),
 ("T3", "docs/evidencias/T3-20261122-intento3-resultado.md", "T3 intento 3: PASS 19/19 (reconstrucción en OCI, fase A 649 s, fase B 23/23)", "PASS"),
 ("T4", "docs/evidencias/T4-TARJETA-AUTORIZACION.md", "Tarjeta de autorización de T4", "N/A"),
 ("T4", "docs/evidencias/T4-20261122-resultado.md", "Informe T4: centro de operaciones en Azure PASS 18/18", "PASS"),
 ("T5", "docs/evidencias/T5-TARJETA-AUTORIZACION.md", "Tarjeta de autorización de T5", "N/A"),
 ("T5", "docs/evidencias/T5-20261123-intento1-resultado.md", "T5 intento 1 (2 EC2): FAIL 8/9, disponibilidad 95,21 %", "FAIL"),
 ("T5", "docs/evidencias/T5-ANALISIS-Y-PROPUESTA-2-INTENTO.md", "Análisis causal del FAIL de T5 y propuesta del 2.º intento", "N/A"),
 ("T5", "docs/evidencias/T5-TARJETA-2-INTENTO.md", "Tarjeta del 2.º intento de T5 (variante C)", "N/A"),
 ("T5", "docs/evidencias/T5-20261123-intento2-abortado.md", "T5 intento 2: ABORTADO sin medición (SCP de Academy deniega UpdateAutoScalingGroup)", "BLOCKED"),
 ("T5", "docs/evidencias/T5-20261123-resultado.md", "T5 intento 3 (6 EC2): PASS 9/9, 99,49 %, detección 9,6 s, recuperación 125 s", "PASS"),
 ("T6", "docs/evidencias/T6-BLOQUEOS-OBLIGATORIOS.md", "Bloqueos obligatorios de T6 (B-T6-1, D1–D8)", "BLOCKED"),
 ("T6", "docs/evidencias/T6-PREPARACION-SOLO-LECTURA.md", "Preparación de solo lectura de T6 y regla de parada", "BLOCKED"),
 ("T6", "docs/evidencias/T6-20261123-estado-local.md", "Estado T6 al 23-nov: barreras locales PASS; failover real no ejecutado", "BLOCKED"),
 ("T6", "docs/evidencias/T6-local/g5-exhaustivo-len5.txt", "Salida de la exploración exhaustiva G5 (59 049 secuencias, control negativo)", "PASS (local)"),
 ("T6", "docs/evidencias/T6-local/regresion-final.txt", "Regresión: scripts/multicloud 704 + 66 subtests; backend/tests 343 (exit 0)", "PASS (local)"),
 ("T7", "docs/evidencias/AUTORIZACIONES-T6-T7.md", "Tarjetas A1 (despliegue NexoOps en Azure), A2 (anclaje OCI), A3 (T6 completo)", "BLOCKED"),
 ("T8", "docs/evidencias/REGISTRO-CIERRE-T6-T8.md", "Registro único de cierre T6–T8", "N/A"),
 ("T8", "docs/evidencias/MATRIZ-CIERRE-CLOUD.md", "Matriz de cierre cloud", "N/A"),
 ("T8", "docs/evidencias/PLAN-PRUEBAS-OBLIGATORIAS-CLOUD.md", "Plan de pruebas obligatorias T1–T8", "N/A"),
 ("T8", "docs/evidencias/VENTANA-UNICA-AWS.md", "Procedimiento de ventana única en AWS", "N/A"),
 ("T8", "docs/evidencias/PROCEDIMIENTOS-T2-T4.md", "Procedimientos T2–T4", "N/A"),
 ("T8", "docs/evidencias/PRIMERA-OPERACION-CLOUD.md", "Primera operación cloud (procedimiento)", "N/A"),
]
for et, rel, desc, res in DOCS_T:
    lugar = "LOCAL" if "T6-local" in rel else ("DISEÑO" if res in ("N/A",) else "REAL")
    if et == "T6" and "T6-local" not in rel: lugar = "LOCAL / DISEÑO"
    if et == "T7": lugar = "DISEÑO"
    nat = "directa (salida de prueba)" if rel.endswith(".txt") else ("resumen respaldado por expediente" if "resultado" in rel or "abortado" in rel else "documento de procedimiento")
    lim = {"T6": "No existe ejecución en nube: RTO/RPO de failover NO medidos.",
           "T7": "Ninguna autorización estaba concedida al redactarse; A1 se inició después (ver EV-T7 de despliegue en curso)."}.get(et, "Resumen redactado a partir del expediente; la fuente primaria es work/evidencias/.")
    if res == "N/A": lim = "Documento de planificación/autorización: no es una medición."
    crit = CRIT[et]
    add(et, crit, desc, REPO, rel, "Informe de resultado" if "resultado" in rel else ("Salida de prueba" if rel.endswith(".txt") else "Procedimiento / autorización"), nat, lugar, res, lim)

# Criterios escritos antes (ops_center/criterios)
for t in range(1, 9):
    et = f"T{t}"; rel = f"ops_center/criterios/{et}.json"
    js = json.load(open(f"{REPO}/{rel}"))
    add(et, "12, " + CRIT[et], f"Criterios de aceptación de {et} escritos antes de ejecutar ({len(js['criteria'])} criterios): {js['title'][:90]}", REPO, rel,
        "Criterio previo (JSON)", "directa (definición)", "DISEÑO", {"T6": "NOT_TESTED", "T7": "NOT_TESTED", "T8": "NOT_TESTED"}.get(et, "N/A"),
        {"T6": "Los 12 criterios siguen NOT_TESTED/BLOCKED.", "T7": "Define «flujo operativo desde Azure»; no coincide con el alcance local de NexoOps; 0 criterios cumplidos en nube.",
         "T8": "Los 5 criterios técnicos de cierre (limpieza verificada) siguen NOT_TESTED."}.get(et, "Definición; el resultado está en el expediente."))

# ---------------------------------------------------------------- 3. Fallos y correcciones (código y pruebas de regresión)
FIX = [
 ("T1", "scripts/multicloud/hybrid/oci_par_probe.py", "Probe de PAR/lease en OCI (corregido: faltaba import lease_race → NameError)"),
 ("T1", "scripts/multicloud/tests/test_probe_race_path.py", "Prueba de regresión que reproduce el NameError de T1 y verifica nombres globales"),
 ("T2", "backend/app/failover/tlsctx.py", "Corrección T2: contexto TLS verificado con respaldo a certifi (falla cerrado)"),
 ("T2", "scripts/multicloud/tests/test_tls_context.py", "Pruebas del contexto TLS (autofirmado rechazado, SSL_CERT_FILE)"),
 ("T2", "scripts/multicloud/tests/test_witness_thread_safety.py", "Regresión de la carrera entre hilos del testigo (23/35 fallos antes, 35/35 después)"),
 ("T2", "scripts/multicloud/dns_switch.py", "Conmutador DNS con lista blanca, frase, intervalo mínimo y reversión"),
 ("T3", "scripts/multicloud/oci-drill/safe-dnf.sh", "Corrección T3-1: dnf con repos mínimos, cgroup de memoria y límite de tiempo"),
 ("T3", "scripts/multicloud/oci-drill/ensure-swap.sh", "Corrección T3-1: swap total ≥ 2 GB"),
 ("T3", "scripts/multicloud/oci-drill/quiesce-vm.sh", "Corrección T3-2/3: neutraliza dnf-makecache, ksplice y kdump antes de instalar"),
 ("T3", "ops_center/tests/test_vm_helpers.py", "Pruebas de los ayudantes de la VM (swap, repos, sin dnf directo)"),
 ("T3", "scripts/ops/ejecutar_t3.py", "Orquestador de T3 con guarda de destrucción y known_hosts de la ejecución"),
 ("T5", "backend/tests/test_v2_plan_review.py", "Revisor de planes de Terraform por escenario (rechaza destrucciones no previstas)"),
 ("T5", "scripts/v2-ops/rds-window.sh", "Ventana de RDS con watchdog (evita que quede encendida)"),
 ("T6", "backend/app/failover/anchor.py", "B-T6-1: anclaje anti-rollback del historial del testigo"),
 ("T6", "scripts/multicloud/tests/test_witness_anchor.py", "19 casos del anclaje anti-rollback"),
 ("T6", "scripts/multicloud/tests/test_g5_single_writer_exhaustive.py", "Exploración exhaustiva G5: nunca dos escritores"),
 ("T6", "scripts/multicloud/failover/real_providers.py", "G1: proveedores reales cableados (sin ejecutar contra API reales)"),
 ("T6", "scripts/multicloud/failover/adapters_probes.py", "G9: sondas TLS con certificado fijado"),
]
for et, rel, desc in FIX:
    res = "PASS (local)" if "test" in rel else "N/A"
    lim = "Corrección local verificada con pruebas; validada en nube solo a través de la ejecución posterior del T correspondiente." if et != "T6" else "Solo validado en local; T6 no ejecutado en nube."
    add(et, CRIT[et], desc, REPO, rel, "Código / prueba de regresión", "directa (código)", "LOCAL", res, lim)

# ---------------------------------------------------------------- 4. T7 NexoOps (worktree codex, solo lectura)
for rel in ["docs/codex/ARQUITECTURA-T7.md", "docs/codex/INFORME-TECNICO-T7-T8.md", "docs/codex/MATRIZ-CUMPLIMIENTO.md", "docs/codex/RESULTADOS-Y-COSTOS.md",
            "docs/codex/T7-T8-REGISTRO.md", "docs/codex/DECISIONES-T7-T8.md", "docs/codex/INDICE-EVIDENCIAS.md"]:
    add("T7" if "T7" in rel or "ARQ" in rel else "T8", "7, 13", f"Documento T7/T8 de la rama codex/t7-t8: {os.path.basename(rel)}", CODEX, rel, "Documento técnico", "resumen", "LOCAL / DISEÑO", "N/A",
        "Documento de la rama codex/t7-t8 (sin merge). La cifra «≈ USD 0,50» de RESULTADOS-Y-COSTOS solo suma T4 y el PASS de T5." if "COSTOS" in rel else "Documento de la rama codex/t7-t8 (sin merge).")
for rel in sorted(glob.glob(f"{CODEX}/nexoops/tests/test_*.py")):
    r = os.path.relpath(rel, CODEX)
    add("T7", "7, 5, 12", f"Prueba automatizada de NexoOps: {os.path.basename(r)}", CODEX, r, "Prueba automatizada", "directa (código)", "LOCAL", "PASS (local)",
        "Parte de la suite NexoOps (68 passed el 23-nov 04:49Z en 310279c). Local: no prueba el despliegue en Azure.")
for rel in ["nexoops/auth.py", "nexoops/security.py", "nexoops/actions.py", "nexoops/app.py", "deploy/nexoops/nexoops.service", "deploy/nexoops/nginx-nexoops.conf",
            "deploy/nexoops/instalar-en-vm.sh", "deploy/nexoops/configurar-secretos.sh", "deploy/nexoops/nexoops-feed.sh", "deploy/nexoops/nexoops-feed.service", "deploy/nexoops/nexoops-feed.timer"]:
    unc = subprocess.run(["git", "-C", CODEX, "status", "--porcelain", "--", rel], capture_output=True, text=True).stdout.strip()
    lim = "Código versionado en codex/t7-t8 (sin merge)."
    if unc: lim = "SIN COMMIT en codex/t7-t8 (cambio del despliegue A1 en curso: puerto distinto del 8760 del testigo y espejo de solo lectura nexoops-feed). Se cita tal cual; no se modificó."
    add("T7", "7, 5, 8", f"NexoOps: {rel}", CODEX, rel, "Código / despliegue", "directa (código)", "LOCAL / DISEÑO", "N/A", lim, zip_ok=not unc)

# ---------------------------------------------------------------- 5. Histórico previo a T1 (T0): resultados, capturas, EV01–EV11, IaC
idx = open(f"{REPO}/docs/evidencias/capturas/INDICE.md").read()
capdesc = {m.group(1): m.group(2).strip() for m in re.finditer(r"^\| (?:\.\./)?([\w/.-]+\.png) \| ([^|]+)\|", idx, re.M)}
CAPCRIT = {"aws/01": "4, 5", "aws/02": "4, 5", "aws/04": "3, 5", "aws/05": "3, 5", "aws/06": "6, 7", "aws/07": "6, 7", "aws/08": "6, 7", "aws/09": "6, 7",
           "aws/10": "9, 4", "aws/11": "6, 9", "aws/A1": "5", "aws/A2": "4, 5", "aws/A3": "4, 6", "aws/A4": "9", "aws/A5": "9", "aws/A8": "5, 7", "aws/A9": "5",
           "aws/A13": "5", "aws/A14": "5", "aws/A15": "11", "aws/A16": "4, 11", "azure/B": "7", "oci/": "5, 9, 10", "github/": "5, 12"}
for f in sorted(glob.glob(f"{REPO}/docs/evidencias/capturas/*/*.png")):
    rel = os.path.relpath(f, REPO); k = rel.split("capturas/")[1]
    crit = next((v for kk, v in CAPCRIT.items() if k.startswith(kk)), "13")
    desc = capdesc.get(k, "Captura auténtica de consola (copia redactada): " + os.path.basename(k).replace(".png", "").replace("-", " "))
    add("T0", crit, "Captura de consola: " + desc, REPO, rel, "Captura auténtica de consola (copia redactada)", "directa", "REAL", "N/A (configuración observada)",
        "Copia con cuenta, usuario, ARN, IDs y direcciones ocultos (originales fuera del repositorio). Histórica (oct–nov): no refleja el estado de hoy.")
for rel in ["docs/evidencias/20261104-fase-d-notificacion-v2/correos-alarm-ok.png", "docs/evidencias/20261105-azure-ventana2/correos-azure-monitor.png",
            "docs/evidencias/20261105-azure-ventana2/grafana-azure-vm-historico-20261104.png", "docs/evidencias/20261104-p2-cpu-real/correos-alarm-ok.png",
            "docs/evidencias/EV05/public-home-2026-10-03.png", "docs/evidencias/EV10/EV10-sitio-actualizado-2026-10-07-desktop.png"]:
    k = rel.replace("docs/evidencias/", "")
    add("T0", "7" if "correo" in rel or "grafana" in rel else "4, 12", capdesc.get(k, "Captura: " + os.path.basename(rel)), REPO, rel,
        "Captura (recorte de correo / sitio)", "directa", "REAL", "N/A (observación)", "Recorte: solo asunto/hora o vista pública; no muestra cabeceras completas.")
for f in sorted(glob.glob(f"{REPO}/docs/evidencias/EV*/README.md")):
    rel = os.path.relpath(f, REPO); first = open(f).readline().strip("# \n")
    ev = rel.split("/")[2]
    crit = {"EV01": "12", "EV02": "3", "EV03": "3", "EV04": "3, 5", "EV05": "4", "EV06": "4", "EV07": "9", "EV08": "7", "EV09": "8", "EV10": "12, 5", "EV11": "6, 12"}[ev]
    add("T0", crit, f"Entregable 1 — {first}", REPO, rel, "Ficha de evidencia (E1)", "resumen (lectura API / suite)", "REAL", "N/A (histórico)",
        "Ficha resumida del Entregable 1 (oct-2026); varias capturas de consola quedaron pendientes según la propia ficha.")
crit_hist = [("multicloud/oci", "9, 10, 4"), ("multicloud/azure", "7, 5"), ("multicloud/aws/20261023-rds-multiaz", "6, 9, 4"), ("multicloud/aws/20261028-auditoria", "5, 3"),
             ("multicloud/aws/20261028-cloudwatch", "7, 6"), ("multicloud/aws", "9, 4"), ("multicloud/automatizacion", "8, 5"), ("escalado", "6"), ("tolerancia", "6"),
             ("medicion", "6, 12"), ("validacion", "12, 4"), ("azure", "7"), ("ci-github", "5, 12"), ("tls-rds", "5"), ("fase", "8, 7"), ("p1-", "7"), ("p2-", "7"),
             ("b2-autohealing", "6"), ("d2-failover", "6, 9"), ("c04", "9"), ("copia-externa", "9"), ("rds", "4"), ("terraform", "8, 5"), ("apagado", "11"), ("despliegue", "8, 6"), ("recuperacion", "9")]
for f in sorted(glob.glob(f"{REPO}/docs/evidencias/**/resultado*.md", recursive=True)):
    rel = os.path.relpath(f, REPO)
    if re.match(r"docs/evidencias/T\d", rel): continue
    sub = rel.replace("docs/evidencias/", "")
    crit = next((v for k, v in crit_hist if k in sub), "12")
    title = next((l.strip("# \n") for l in open(f) if l.startswith("#")), os.path.basename(f))
    folder = os.path.dirname(f); raw = [x for x in os.listdir(folder) if not x.endswith(".md")]
    nat = "directa (con datos crudos en la carpeta)" if raw else "indirecta (solo resumen)"
    add("T0", crit, f"Histórico: {title[:150]}", REPO, rel, "Informe de resultado histórico", nat, "REAL" if "local" not in sub else "LOCAL",
        "N/A (histórico; ver documento)", "Previo a la batería T1–T8 (oct–nov 2026); su veredicto y límites están en el propio documento." + ("" if raw else " Solo hay resumen: evidencia indirecta."))
for f in ["docs/evidencias/multicloud/aws/20261028-cloudwatch/series-originales.json", "docs/evidencias/multicloud/aws/20261023-rds-multiaz/rds-eventos.txt",
          "docs/evidencias/multicloud/aws/20261028-auditoria-solo-lectura/detalle-seguridad.json", "docs/evidencias/multicloud/aws/20261028-auditoria-solo-lectura/red-y-cloudtrail.json",
          "docs/evidencias/multicloud/azure/20261028-vm/nsg-reglas.txt", "docs/evidencias/multicloud/azure/20261028-vm/identidad-administrada.txt",
          "docs/evidencias/multicloud/azure/20261028-vm/acceso-https-y-puertos.txt"]:
    if os.path.isfile(f"{REPO}/{f}"):
        add("T0", "5, 3, 7", "Datos crudos: " + f.split("/")[-2] + "/" + os.path.basename(f), REPO, f, "Datos crudos (lectura API)", "directa", "REAL", "N/A (configuración observada)",
            "Lectura de solo lectura histórica (oct-2026); no refleja el estado actual.")
# IaC
for f in sorted(glob.glob(f"{REPO}/infra/**/*.tf", recursive=True)):
    rel = os.path.relpath(f, REPO); mod = rel.split("/")[1]
    if rel.endswith("tfstate") or "tfvars" in rel and not rel.endswith(".example"): continue
    n = sum(1 for _ in open(f)); res_n = len(re.findall(r'^resource\s+"', open(f).read(), re.M))
    crit = "8, 3" if "network" in rel else "8"
    add("T0", crit, f"Terraform {mod}: {os.path.basename(rel)} ({n} líneas, {res_n} bloques resource)", REPO, rel, "Configuración IaC (Terraform)", "directa (código)", "DISEÑO→REAL",
        "N/A (código)", "Código fuente; la aplicación real se acredita en los expedientes (p. ej. T3 apply 11/destroy 11, T5 plan revisado). Sin tfstate ni tfvars reales en el inventario.")

# ---------------------------------------------------------------- 6. T8: paquete documental previo y diagramas
for f in sorted(glob.glob(f"{REPO}/docs/entrega-final/*.md")) + sorted(glob.glob(f"{REPO}/docs/entrega-final/diagramas/*.png")) + sorted(glob.glob(f"{REPO}/docs/entrega-final/graficos/*.png")):
    rel = os.path.relpath(f, REPO)
    tipo = "Diagrama (elaboración propia)" if "diagramas" in rel else ("Gráfico derivado de datos de expedientes" if "graficos" in rel else "Documento del paquete T8 previo")
    add("T8", "13, 2" if "diagramas" in rel else "13", f"Paquete T8 (commit 5e1fed1): {os.path.basename(rel)}", REPO, rel, tipo, "elaboración propia" if "diagramas" in rel else "resumen", "DISEÑO" if "diagramas" in rel else "—", "N/A",
        "Elaboración propia a partir de los expedientes; no es una captura de consola." if ("diagramas" in rel or "graficos" in rel) else "Síntesis previa; este informe vuelve a las fuentes originales.")

for f in sorted(glob.glob(f"{OUT}/graficos-informe/*.png")):
    rel = os.path.relpath(f, OUT)
    add("T8", "13, 12", f"Gráfico del informe generado a partir de datos reales de expedientes: {os.path.basename(f)}", OUT, rel, "Gráfico derivado de datos de expedientes", "derivada (de datos directos)", "REAL (datos) / elaboración propia (gráfico)", "N/A",
        "Gráfico generado con matplotlib a partir de los JSON de work/evidencias; no es una captura de consola. El pie de cada gráfico indica el archivo de origen.", ruta_show="docs/entrega-final/" + rel)
# Fresh test runs (scratch → copiados a control-calidad)
for fn, desc, res in [("pytest-nexoops.txt", "Re-ejecución de la suite NexoOps en codex/t7-t8 (310279c): 68 passed", "PASS (local)"),
                      ("pytest-regresion.txt", "Re-ejecución de backend/tests y scripts/multicloud en cierre-t6-t8 (5e1fed1)", "ver archivo")]:
    p = os.path.join(OUT, "control-calidad", fn)
    if os.path.isfile(p):
        txt = open(p).read()
        if fn == "pytest-regresion.txt":
            nums = re.findall(r"(\d+) passed", txt)
            res = "PASS (local)" if "failed" not in txt and len(nums) >= 2 else ("FAIL (local)" if "failed" in txt else "NOT_TESTED")
            desc += " — " + "; ".join(l.strip() for l in txt.splitlines() if "passed" in l or "failed" in l)
        add("T8" if fn != "pytest-nexoops.txt" else "T7", "12", desc, OUT, os.path.join("control-calidad", fn), "Salida de prueba (re-ejecución para este informe)", "directa", "LOCAL", res,
            "Ejecutada el 23-nov-2026 con -p no:cacheprovider; no toca nubes.", ruta_show="docs/entrega-final/control-calidad/" + fn)

# Entrada explícita: despliegue A1 incompleto (no hay expediente)
n = counters.get("T7", 0) + 1; counters["T7"] = n
items.append(OrderedDict(id=f"EV-T7-{n:03d}", etapa="T7", criterios="7, 13", descripcion="Despliegue A1 de NexoOps en la VM de Azure vm-nexoeventos-obs: EN CURSO / INCOMPLETO al cierre del informe (VM encendida desde 04:28:57Z; servicio NexoOps no arrancado; configuración de secretos en curso). Hallazgos: conflicto de puerto 8760 con el testigo (falso positivo de /nexoops/healthz) y falta de permiso de lectura sobre /var/lib/ops-center (espejo nexoops-feed añadido). Cambios sin commit.",
    ruta="../NexoEventos-codex-t7-t8/deploy/nexoops/ (cambios sin commit) y commit 99719d6", fecha_utc="2026-11-23T04:44Z", fuente_fecha="nota de la sesión de origen",
    tipo="Estado operativo informado (sin expediente)", naturaleza="indirecta (sin expediente ni capturas)", lugar="REAL (parcial)", resultado="NOT_TESTED (despliegue incompleto)",
    sha256="—", bytes=0, limitacion="No existe expediente ni captura fechada del despliegue; NO se presenta T7 como desplegado en Azure. La VM debe quedar desasignada al terminar A1 (no verificado aquí).", en_zip="no", _abs=None))

json.dump([{k: v for k, v in i.items() if k != "_abs"} for i in items], open(f"{S}/build/inventario.json", "w"), ensure_ascii=False, indent=1)
json.dump(EXP, open(f"{S}/build/expedientes.json", "w"), ensure_ascii=False, indent=1)
json.dump({i["id"]: i["_abs"] for i in items}, open(f"{S}/build/inventario_abs.json", "w"), ensure_ascii=False)
print(len(items), counters)

# ---------------------------------------------------------------- exportación XLSX y MD
import openpyxl
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.table import Table, TableStyleInfo
cols = [("id", "ID", 13), ("etapa", "Etapa", 7), ("criterios", "Criterio(s) de rúbrica", 12), ("descripcion", "Descripción", 60), ("ruta", "Ruta exacta", 62),
        ("fecha_utc", "Fecha UTC", 18), ("fuente_fecha", "Fuente de la fecha", 26), ("tipo", "Tipo", 30), ("naturaleza", "Directa / indirecta", 24), ("lugar", "Lugar", 16),
        ("resultado", "Resultado", 22), ("sha256", "SHA-256", 66), ("bytes", "Bytes", 10), ("limitacion", "Limitación", 70), ("en_zip", "En el ZIP", 9)]
wb = openpyxl.Workbook(); ws = wb.active; ws.title = "Inventario"
ws.append([c[1] for c in cols])
for i in items: ws.append([i[c[0]] for c in cols])
for j, c in enumerate(cols): ws.column_dimensions[get_column_letter(j + 1)].width = c[2]
for c in ws[1]: c.font = Font(bold=True, color="FFFFFF"); c.fill = PatternFill("solid", fgColor="0D3B66"); c.alignment = Alignment(wrap_text=True, vertical="center")
fill = {"PASS": "D7EED9", "FAIL": "F8D7D7", "BLOCKED": "FCE8C8", "NOT_TESTED": "FCE8C8"}
for row in ws.iter_rows(min_row=2):
    for c in row: c.alignment = Alignment(wrap_text=True, vertical="top")
    k = str(row[10].value).split(" ")[0]
    if k in fill: row[10].fill = PatternFill("solid", fgColor=fill[k])
tab = Table(displayName="Inventario", ref=f"A1:{get_column_letter(len(cols))}{len(items) + 1}"); tab.tableStyleInfo = TableStyleInfo(name="TableStyleLight9", showRowStripes=True)
ws.add_table(tab); ws.freeze_panes = "B2"
ws2 = wb.create_sheet("Resumen")
from collections import Counter
ws2.append(["Inventario maestro de evidencias — NexoEventos (corte 23-nov-2026 UTC)"]); ws2["A1"].font = Font(bold=True, size=13)
ws2.append([f"Total de evidencias: {len(items)}"]); ws2.append([])
ws2.append(["Etapa", "Evidencias", "Fórmula de control"])
for k in sorted(counters): ws2.append([k, counters[k], f'=COUNTIF(Inventario!B:B,"{k}")'])
ws2.append([]); ws2.append(["Resultado", "Evidencias"])
for k, v in Counter(i["resultado"] for i in items).most_common(): ws2.append([k, v])
ws2.append([]); ws2.append(["Expediente", "Veredicto", "Criterios CUMPLE / total", "Inicio UTC"])
for k, v in EXP.items(): ws2.append([k, v["veredicto"], f"{v['cumple']}/{v['total']}", v["inicio"]])
ws2.column_dimensions["A"].width = 34; ws2.column_dimensions["B"].width = 16; ws2.column_dimensions["C"].width = 26; ws2.column_dimensions["D"].width = 26
ws3 = wb.create_sheet("Leyenda")
for r in [["Campo", "Significado"],
          ["ID", "EV-Tn-NNN. T0 = evidencia histórica previa a la batería T1–T8 (Entregables 1–3, capturas, IaC)."],
          ["Ruta exacta", "Relativa a la raíz del repositorio (rama cierre-t6-t8). «../NexoEventos-codex-t7-t8/…» = worktree de la rama codex/t7-t8. «work/…» = no versionado (.gitignore)."],
          ["Fecha UTC", "Según «Fuente de la fecha»: inicio del expediente (meta.json), último commit git o fecha de modificación para archivos no versionados."],
          ["Resultado", "PASS / FAIL / BLOCKED / NOT_TESTED. «N/A (…)» = configuración, código, procedimiento o documento histórico sin veredicto propio. «(local)» = solo en el equipo."],
          ["Directa / indirecta", "Directa: datos crudos, captura o código. Indirecta: solo un resumen o un estado informado sin expediente."],
          ["Lugar", "REAL (nube), LOCAL, DISEÑO, ESTIMADO."],
          ["En el ZIP", "sí = el archivo (o una copia redactada, si se indica en la limitación) va en NexoEventos_Entrega_Final.zip."]]:
    ws3.append(r)
ws3.column_dimensions["A"].width = 22; ws3.column_dimensions["B"].width = 140
wb.save(f"{OUT}/INVENTARIO-MAESTRO-EVIDENCIAS.xlsx")
md = ["# Inventario maestro de evidencias — NexoEventos", "",
      f"Corte: 23-nov-2026 (UTC). Total: **{len(items)}** evidencias. Generado desde las fuentes originales (solo lectura); la versión con filtros está en `INVENTARIO-MAESTRO-EVIDENCIAS.xlsx`.", "",
      "Resultados: PASS / FAIL / BLOCKED / NOT_TESTED; «N/A» = configuración, código, procedimiento o histórico sin veredicto propio. T0 = evidencia previa a T1–T8.", "",
      "| Etapa | Evidencias |", "|---|---:|"] + [f"| {k} | {counters[k]} |" for k in sorted(counters)] + ["",
      "| ID | Etapa | Criterio(s) | Descripción | Ruta | Fecha UTC | Tipo | Naturaleza | Resultado | SHA-256 | Limitación |", "|---|---|---|---|---|---|---|---|---|---|---|"]
esc = lambda s: str(s).replace("|", "\\|").replace("\n", " ")
for i in items:
    md.append("| " + " | ".join(esc(x) for x in [i["id"], i["etapa"], i["criterios"], i["descripcion"], f"`{i['ruta']}`", i["fecha_utc"], i["tipo"], i["naturaleza"], i["resultado"], f"`{i['sha256']}`", i["limitacion"]]) + " |")
open(f"{OUT}/INVENTARIO-MAESTRO-EVIDENCIAS.md", "w").write("\n".join(md) + "\n")
print("xlsx/md ok")
