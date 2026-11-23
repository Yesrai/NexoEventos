# -*- coding: utf-8 -*-
"""Control de calidad de los entregables: páginas, índices, referencias, criterios, apertura de archivos."""
import os, re, json, zipfile, fitz, docx, openpyxl
S = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = "~/Workspace/NexoEventos-informe-final/docs/entrega-final"
R = {}
for key, f in [("informe", "NexoEventos_Informe_Final_Completo_Con_Evidencias.pdf"), ("anexos", "NexoEventos_Anexos_Evidencias.pdf")]:
    d = fitz.open(f"{OUT}/{f}")
    pages = []
    for i, p in enumerate(d):
        t = p.get_text(); pages.append(dict(n=i + 1, chars=len(t.strip()), imgs=len(p.get_images())))
    txt = "".join(p.get_text() for p in d)
    caps = {}
    for m in re.finditer(r"\n(Tabla|Figura|Evidencia) (\d+)\. ", txt): caps.setdefault(m.group(1), set()).add(int(m.group(2)))
    cont = {k: (sorted(v) == list(range(1, max(v) + 1))) for k, v in caps.items()}
    refs = set((m.group(1), int(m.group(2))) for m in re.finditer(r"\b(Tabla|Figura)s? (\d+)\b", txt))
    broken = sorted(f"{a} {b}" for a, b in refs if b not in caps.get(a, set()))
    sust = None
    if key == "informe":
        st = next(pg["n"] for pg, p in zip(pages, d) if "Resumen ejecutivo\n" in p.get_text() and pg["n"] > 6)
        en = next(pg["n"] for pg, p in zip(pages, d) if "Referencias y glosario\n" in p.get_text() and pg["n"] > 6) - 1
        sust = (st, en, en - st + 1)
    R[key] = dict(archivo=f, paginas=d.page_count, sustantivas=sust, casi_vacias=[p["n"] for p in pages if p["chars"] < 250],
                  max_por_tipo={k: max(v) for k, v in caps.items()}, numeracion_continua=cont,
                  referencias_rotas=broken, marcadores_sin_actualizar=len(re.findall(r"\(índice: se actualiza|Error! Reference|¡Error!", txt)),
                  metadatos=d.metadata.get("title", ""))
# 14 criterios presentes en el informe y en la matriz
import openpyxl as ox
rub = [r[0] for r in ox.load_workbook("~/Downloads/rúbrica proyecto_qod3szrctm.xlsx")["Rúbrica"].iter_rows(min_row=2, values_only=True) if r[0] and r[0][0].isdigit()]
txt = re.sub(r"\s+", " ", "".join(p.get_text() for p in fitz.open(f"{OUT}/NexoEventos_Informe_Final_Completo_Con_Evidencias.pdf")))
nos = txt.replace(" ", "")
R["criterios_en_informe"] = {c: (c.split(". ", 1)[1].replace(" ", "") in nos) for c in rub}
mx = ox.load_workbook(f"{OUT}/MATRIZ-RUBRICA-EVIDENCIAS.xlsx")["Matriz"]
R["criterios_en_matriz"] = sum(1 for r in mx.iter_rows(min_row=3, max_row=16, values_only=True) if r[0] and r[8] and r[7])
# apertura de archivos
op = {}
for f in sorted(os.listdir(OUT)):
    p = f"{OUT}/{f}"
    if os.path.isdir(p): continue
    try:
        if f.endswith(".docx"): dd = docx.Document(p); op[f] = f"OK docx: {len(dd.paragraphs)} párrafos, {len(dd.tables)} tablas, {len(dd.inline_shapes)} imágenes"
        elif f.endswith(".pdf"): op[f] = f"OK pdf: {fitz.open(p).page_count} páginas"
        elif f.endswith(".xlsx"): wb = ox.load_workbook(p); op[f] = "OK xlsx: " + ", ".join(f"{ws.title} ({ws.max_row} filas)" for ws in wb)
        elif f.endswith(".zip"):
            with zipfile.ZipFile(p) as z: op[f] = f"OK zip: {len(z.namelist())} archivos, testzip={z.testzip()}"
        elif f.endswith(".md"): op[f] = f"OK md: {sum(1 for _ in open(p))} líneas"
    except Exception as e: op[f] = "ERROR " + repr(e)
R["apertura"] = op
json.dump(R, open(f"{S}/build/qc.json", "w"), ensure_ascii=False, indent=1, default=list)
print(json.dumps(R, ensure_ascii=False, indent=1, default=list))
