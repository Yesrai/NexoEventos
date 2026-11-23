# -*- coding: utf-8 -*-
"""Anexos de evidencias: capturas auténticas, criterios de cada expediente, salidas de prueba."""
import os, sys, json, glob, re, subprocess
sys.path.insert(0, os.path.dirname(__file__))
from docbuild import Doc
from docx.shared import Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from PIL import Image

S = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = "~/Workspace/NexoEventos"
OUTD = "~/Workspace/NexoEventos-informe-final/docs/entrega-final"
D = Doc(f"{S}/build/inventario.json"); d = D.d; INV = D.inv
by = {i["ruta"]: i for i in INV}

p = d.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER; r = p.add_run("NexoEventos"); r.font.size = Pt(26); r.bold = True; r.font.color.rgb = RGBColor(0x0D, 0x3B, 0x66)
p = d.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER; r = p.add_run("Anexos de evidencias del informe académico final"); r.font.size = Pt(15); r.bold = True
p = d.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER; r = p.add_run("Yesenia Ramirez Medina · Cloud Computing · UPeU · corte 23-nov-2026 (UTC)"); r.font.size = Pt(11)
D.pj("Este documento acompaña a `NexoEventos_Informe_Final_Completo_Con_Evidencias`. Reproduce, sin alterar su contenido, las **capturas auténticas de consola** (copias redactadas que ya estaban en el repositorio), los **criterios y valores medidos** de cada expediente real (leídos de `resultado.json`), los **criterios previos** de las etapas no ejecutadas y las **salidas de prueba**. Cada elemento lleva su ID del inventario maestro, su ruta y su SHA-256. No se generó ninguna imagen que imite una consola cloud: los únicos gráficos están en el informe y se rotulan como derivados de datos.")
D.header_footer("NexoEventos · Anexos de evidencias · corte 23-nov-2026 (UTC)")
D.page_break(); D.toc("Índice de anexos", 'TOC \\o "1-2" \\h \\z \\u')
D.toc("Índice de figuras de los anexos", 'TOC \\h \\z \\c "Figura"')

# ---------------------------------------------------------------- Anexo A: resumen del inventario
D.h("Anexo A. Resumen del inventario maestro", 1)
from collections import Counter
c_et = Counter(i["etapa"] for i in INV); c_res = Counter(i["resultado"].split(" ")[0] for i in INV); c_tipo = Counter(i["tipo"] for i in INV)
D.pj(f"El inventario maestro contiene **{len(INV)} evidencias**. La etapa T0 agrupa la evidencia histórica previa a la batería T1–T8 (Entregables 1–3, capturas de consola e IaC). El detalle completo (ruta exacta, fecha UTC y su fuente, tipo, naturaleza directa/indirecta, lugar, resultado, SHA-256 completo y limitación) está en `INVENTARIO-MAESTRO-EVIDENCIAS.xlsx` y `.md`.")
D.table(["Etapa", "Evidencias"], [[k, str(v)] for k, v in sorted(c_et.items())], widths=[3, 3], caption="Evidencias por etapa")
D.table(["Tipo", "Evidencias"], [[k, str(v)] for k, v in c_tipo.most_common()], widths=[10, 3], caption="Evidencias por tipo")
D.table(["Resultado (primer término)", "Evidencias"], [[k, str(v)] for k, v in c_res.most_common()], widths=[6, 3], caption="Evidencias por resultado",
        source="Fuente: inventario maestro. «N/A» = configuración, código, histórico o procedimiento (no es una medición con veredicto).")

# ---------------------------------------------------------------- Anexo B: capturas
D.h("Anexo B. Capturas auténticas de consola (copias redactadas)", 1)
D.pj("Las capturas son copias redactadas de originales que la autora conserva fuera del repositorio: cuenta, usuario, correo, ID de suscripción, namespace/OCID, ARN, IDs y direcciones aparecen tapados con rectángulos negros. Son **históricas** (octubre–noviembre de 2026) y no describen el estado actual de las nubes. Las horas de RDS están en UTC−05:00; las de CloudWatch, en UTC.")
caps = [i for i in INV if i["tipo"].startswith("Captura")]
groups = [("B.1 AWS", "capturas/aws/"), ("B.2 Azure", "capturas/azure/"), ("B.3 OCI", "capturas/oci/"), ("B.4 GitHub Actions (CI)", "capturas/github/"), ("B.5 Recortes de correo, Grafana y sitio público", "")]
done = set()
for title, key in groups:
    D.h(title, 2)
    for i in caps:
        if i["id"] in done: continue
        if key and key not in i["ruta"]: continue
        done.add(i["id"])
        path = os.path.join(REPO, i["ruta"])
        w, h = Image.open(path).size
        width = 15.5 if w / h > 1.25 else 11.5
        D.figure(path, i['descripcion'].replace('Captura de consola: ', '').replace('**', '').replace('`', '')[:170],
                 f"ID {i['id']} · ruta `{i['ruta']}` · fecha (git) {i['fecha_utc']} · SHA-256 {i['sha256'][:16]}… · Limitación: {i['limitacion']}", width)

# ---------------------------------------------------------------- Anexo C: expedientes
D.h("Anexo C. Criterios y valores de cada expediente real", 1)
D.pj("Para cada expediente se transcriben los criterios tal como figuran en `resultado.json` (identificador, regla, valor medido y resultado), junto con la verificación del manifiesto realizada para este informe. Los valores largos se recortan con «…»; el archivo íntegro está en la ruta indicada.")
for dpath in sorted(glob.glob(f"{REPO}/work/evidencias/T*")):
    name = os.path.basename(dpath)
    r = json.load(open(f"{dpath}/resultado.json"))
    chk = subprocess.run(["shasum", "-a", "256", "-c", "MANIFIESTO.sha256"], cwd=dpath, capture_output=True, text=True).stdout
    ok = chk.count(": OK"); bad = len([l for l in chk.splitlines() if l and not l.endswith(": OK")])
    rid = by[f"work/evidencias/{name}/resultado.json"]["id"]
    D.h(f"C · {name} — {r['veredicto']}", 2)
    D.p(f"**Título:** {r.get('titulo', '')}  ·  **Inicio:** {r['inicio_utc']}  ·  **Fin:** {r['fin_utc']}  ·  **ID:** {rid}  ·  **SHA-256 de resultado.json:** `{by[f'work/evidencias/{name}/resultado.json']['sha256'][:24]}…`  ·  **Manifiesto:** {ok} archivos OK, {bad} discrepancias.", size=9)
    rows = []
    for c in r["criterios"]:
        v = c.get("valor"); vs = json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else str(v)
        vs = re.sub(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", lambda m: m.group(0) if m.group(0) in ("1.1.1.1", "8.8.8.8", "9.9.9.9") else "[IP oculta]", vs)
        if len(vs) > 150: vs = vs[:150] + "…"
        rows.append([c["id"], c.get("regla", ""), vs, c["resultado"]])
    D.table(["Criterio", "Regla", "Valor medido", "Resultado"], rows, widths=[4.2, 2, 6.8, 2], size=7.5, color_col=3,
            source=f"Fuente: `work/evidencias/{name}/resultado.json` ({rid}).")
    if r.get("nota"): D.p("**Nota del expediente:** " + str(r["nota"])[:900], size=9)

# ---------------------------------------------------------------- Anexo D: criterios de etapas no ejecutadas
D.h("Anexo D. Criterios previos de T6, T7 y T8 (no cumplidos en nube)", 1)
for et in ("T6", "T7", "T8"):
    js = json.load(open(f"{REPO}/ops_center/criterios/{et}.json"))
    rid = by[f"ops_center/criterios/{et}.json"]["id"]
    D.h(f"{et} — {js['title']}", 2)
    D.table(["Criterio", "Tipo", "Umbral", "Descripción", "Estado"],
            [[c["id"], c["kind"], str(c.get("threshold", "—")), c["desc"], "NOT_TESTED" if et != "T6" else "BLOCKED / NOT_TESTED"] for c in js["criteria"]],
            widths=[3.5, 1.2, 1.3, 7.5, 2.5], size=7.5, color_col=4, source=f"Fuente: `ops_center/criterios/{et}.json` ({rid}).")

# ---------------------------------------------------------------- Anexo E: salidas de prueba
D.h("Anexo E. Salidas de prueba", 1)
for rel, title in [("docs/evidencias/T6-local/regresion-final.txt", "Regresión del 23-nov 04:19Z (registro de la sesión T6)"),
                   ("docs/evidencias/T6-local/g5-exhaustivo-len5.txt", "Exploración exhaustiva G5 (T6, LOCAL)"),
                   ("docs/entrega-final/control-calidad/pytest-regresion.txt", "Re-ejecución para este informe: backend/tests y scripts/multicloud"),
                   ("docs/entrega-final/control-calidad/pytest-nexoops.txt", "Re-ejecución para este informe: suite NexoOps (rama codex/t7-t8)")]:
    i = by[rel]; path = os.path.join(REPO if rel.startswith("docs/evidencias") else OUTD.replace("/docs/entrega-final", ""), rel)
    D.h(title, 2)
    D.p(f"ID {i['id']} · `{rel}` · SHA-256 `{i['sha256'][:24]}…`", size=9)
    txt = open(path).read().replace("~", "~")
    lines = [l for l in txt.splitlines() if "DeprecationWarning" not in l and "from websockets" not in l][-40:]
    q = d.add_paragraph(); r = q.add_run("\n".join(lines)); r.font.name = "Courier New"; r.font.size = Pt(8)

D.h("Anexo F. Evidencia indirecta: despliegue A1 en curso", 1)
a1 = next(i for i in INV if i["descripcion"].startswith("Despliegue A1"))
D.table(["Campo", "Valor"], [[k, str(a1[k])] for k in ("id", "etapa", "descripcion", "ruta", "fecha_utc", "fuente_fecha", "naturaleza", "resultado", "limitacion")],
        widths=[3, 12], caption="Registro de la evidencia indirecta del despliegue A1", source="Fuente: nota de estado de la sesión que ejecutaba A1 (23-nov-2026 04:44Z); sin expediente ni capturas.")
D.save(f"{S}/build/anexos_raw.docx")
print("anexos ok")
