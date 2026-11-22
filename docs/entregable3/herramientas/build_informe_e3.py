#!/usr/bin/env python3
"""Genera el Word (.docx) del informe consolidado del Entregable 3 a partir de 15-informe-consolidado-entregable3.md.
Sin dependencias externas (solo la biblioteca estándar y Pillow para leer el tamaño de los PNG). No toca el Markdown original.
Uso: python3 build_informe_e3.py <salida.docx> [paginas.json]   (paginas.json = {"titulo del encabezado": nº de página} para el índice estático)"""
import json, re, sys, zipfile
from pathlib import Path
from xml.sax.saxutils import escape

try:
    from PIL import Image
except Exception:
    Image = None

HERE = Path(__file__).resolve().parent
E3 = HERE.parent
ROOT = E3.parent.parent
MD = E3 / "15-informe-consolidado-entregable3.md"
import argparse
_ap = argparse.ArgumentParser(description="Genera el Word del informe E3.")
_ap.add_argument("salida"); _ap.add_argument("paginas", nargs="?", help="JSON {encabezado: página} para el índice estático")
_ap.add_argument("--entrega", action="store_true", help="versión de ENTREGA: sin Anexo C, sin marcas de borrador ni notas internas; exige --portada completa")
_ap.add_argument("--portada", help="JSON con los datos académicos (ver portada-plantilla.json)")
ARGS = _ap.parse_args()
OUT = Path(ARGS.salida)
PAGES = json.loads(Path(ARGS.paginas).read_text()) if ARGS.paginas else {}
PORTADA = json.loads(Path(ARGS.portada).read_text()) if ARGS.portada else {}
ENTREGA = ARGS.entrega
CAMPOS = ["institucion", "curso", "autores", "docente", "fecha_entrega", "fecha_documento"]
if ENTREGA:
    faltan = [k for k in CAMPOS if not str(PORTADA.get(k, "")).strip() or "[" in str(PORTADA.get(k, ""))]
    if faltan:
        sys.exit("VERSIÓN DE ENTREGA RECHAZADA: faltan o están sin completar los datos de portada: " + ", ".join(faltan))
TEXT_W = 9638          # ancho útil (A4, márgenes de 2 cm) en twips
FONT, MONO = "Arial", "Courier New"
NAVY, GREY, LIGHT = "1F3864", "595959", "D9E2F3"

media, rels = [], []   # imágenes y relaciones


def esc(t):
    return escape(t)


def run(text, bold=False, italic=False, mono=False, color=None, size=None, hl=None):
    rpr = ""
    if mono:
        rpr += f'<w:rFonts w:ascii="{MONO}" w:hAnsi="{MONO}" w:cs="{MONO}"/>'
    if bold:
        rpr += "<w:b/>"
    if italic:
        rpr += "<w:i/>"
    if color:
        rpr += f'<w:color w:val="{color}"/>'
    if size:
        rpr += f'<w:sz w:val="{size}"/><w:szCs w:val="{size}"/>'
    if hl:
        rpr += f'<w:highlight w:val="{hl}"/>'
    return f'<w:r><w:rPr>{rpr}</w:rPr><w:t xml:space="preserve">{esc(text)}</w:t></w:r>'


TOKEN = re.compile(r"(\*\*.+?\*\*|`[^`]+`|\[[^\]]+\]\([^)]+\))")


def inline(text, size=None, base_bold=False, color=None):
    out = []
    for part in TOKEN.split(text):
        if not part:
            continue
        if part.startswith("**") and part.endswith("**"):
            out.append(run(part[2:-2], bold=True, size=size, color=color))
        elif part.startswith("`") and part.endswith("`"):
            out.append(run(part[1:-1], mono=True, size=(size - 1 if size else 18), color=color))
        elif re.fullmatch(r"\[[^\]]+\]\([^)]+\)", part):
            m = re.match(r"\[([^\]]+)\]\(([^)]+)\)", part)
            out.append(run(m.group(1), bold=base_bold, size=size, color=color))
        else:
            out.append(run(part, bold=base_bold, size=size, color=color))
    return "".join(out)


def para(content, style=None, align=None, keep=False, spacing=None, shade=None, border=None, ind=None):
    ppr = ""
    if style:
        ppr += f'<w:pStyle w:val="{style}"/>'
    if keep:
        ppr += "<w:keepNext/>"
    if border:
        ppr += f'<w:pBdr><w:left w:val="single" w:sz="24" w:space="8" w:color="{border}"/></w:pBdr>'
    if shade:
        ppr += f'<w:shd w:val="clear" w:color="auto" w:fill="{shade}"/>'
    if spacing:
        ppr += f'<w:spacing {spacing}/>'
    if ind:
        ppr += f'<w:ind {ind}/>'
    if align:
        ppr += f'<w:jc w:val="{align}"/>'
    return f"<w:p><w:pPr>{ppr}</w:pPr>{content}</w:p>"


def page_break():
    return '<w:p><w:r><w:br w:type="page"/></w:r></w:p>'


def cell(text, w, header=False, size=17, shade=None, bold=False):
    fill = LIGHT if header else shade
    tcpr = f'<w:tcW w:w="{w}" w:type="dxa"/>'
    if fill:
        tcpr += f'<w:shd w:val="clear" w:color="auto" w:fill="{fill}"/>'
    p = para(inline(text, size=size, base_bold=header or bold), style="TableText", keep=header)
    return f"<w:tc><w:tcPr>{tcpr}</w:tcPr>{p}</w:tc>"


def table(rows, widths=None, size=17):
    n = len(rows[0])
    if widths is None:
        score = [max(min(len(re.sub(r"[*`]", "", r[i])), 60), 6) ** 0.8 for r in rows for i in range(n)]
        col = [max(score[i::n]) for i in range(n)]
        tot = sum(col)
        widths = [max(int(TEXT_W * c / tot), 520) for c in col]
        widths[-1] += TEXT_W - sum(widths)
    grid = "".join(f'<w:gridCol w:w="{w}"/>' for w in widths)
    b = '<w:{0} w:val="single" w:sz="4" w:space="0" w:color="BFBFBF"/>'
    borders = "".join(b.format(x) for x in ("top", "left", "bottom", "right", "insideH", "insideV"))
    out = [f'<w:tbl><w:tblPr><w:tblW w:w="{TEXT_W}" w:type="dxa"/><w:tblBorders>{borders}</w:tblBorders><w:tblLayout w:type="fixed"/>'
           f'<w:tblCellMar><w:top w:w="40" w:type="dxa"/><w:left w:w="70" w:type="dxa"/><w:bottom w:w="40" w:type="dxa"/><w:right w:w="70" w:type="dxa"/></w:tblCellMar></w:tblPr><w:tblGrid>{grid}</w:tblGrid>']
    for ri, r in enumerate(rows):
        trpr = "<w:trPr><w:cantSplit/>" + ("<w:tblHeader/>" if ri == 0 else "") + "</w:trPr>"
        cells = "".join(cell(r[i], widths[i], header=(ri == 0), size=size, shade=("F7F7F7" if ri % 2 == 0 and ri else None)) for i in range(n))
        out.append(f"<w:tr>{trpr}{cells}</w:tr>")
    out.append("</w:tbl>")
    return "".join(out) + para("", spacing='w:after="60"')


def image(path, width_in=6.55, alt=""):
    p = Path(path)
    w, h = Image.open(p).size if Image else (1920, 1120)
    cx = int(width_in * 914400)
    cy = int(cx * h / w)
    idx = len(media) + 1
    rid = f"rIdImg{idx}"
    media.append((rid, p, f"image{idx}.png"))
    drawing = (f'<w:drawing><wp:inline distT="0" distB="0" distL="0" distR="0"><wp:extent cx="{cx}" cy="{cy}"/><wp:docPr id="{idx}" name="Diagrama {idx}" descr="{esc(alt)}"/>'
               f'<a:graphic xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">'
               f'<pic:pic xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture"><pic:nvPicPr><pic:cNvPr id="{idx}" name="image{idx}.png"/><pic:cNvPicPr/></pic:nvPicPr>'
               f'<pic:blipFill><a:blip r:embed="{rid}"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill>'
               f'<pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="{cx}" cy="{cy}"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr></pic:pic></a:graphicData></a:graphic></wp:inline></w:drawing>')
    return para(f"<w:r>{drawing}</w:r>", align="center", keep=True, spacing='w:before="60" w:after="40"')


def split_row(line):
    return [c.strip() for c in line.strip().strip("|").split("|")]


# ------------------------------------------------------------------ contenido
def parse_md(text):
    """Devuelve bloques: ('h1', texto) ('p', texto) ('quote', [líneas]) ('table', filas) ('bullets', [líneas]) ('img', alt, ruta)."""
    lines = text.splitlines()
    blocks, i = [], 0
    while i < len(lines):
        ln = lines[i]
        if not ln.strip():
            i += 1
        elif ln.startswith("# "):
            blocks.append(("title", ln[2:].strip())); i += 1
        elif ln.startswith("## "):
            blocks.append(("h1", ln[3:].strip())); i += 1
        elif ln.startswith("### "):
            blocks.append(("h2", ln[4:].strip())); i += 1
        elif ln.startswith(">"):
            q = []
            while i < len(lines) and lines[i].startswith(">"):
                q.append(lines[i].lstrip("> ").rstrip()); i += 1
            blocks.append(("quote", q))
        elif ln.startswith("|"):
            rows = []
            while i < len(lines) and lines[i].startswith("|"):
                if not re.match(r"^\|[\s:|-]+\|$", lines[i]):
                    rows.append(split_row(lines[i]))
                i += 1
            blocks.append(("table", rows))
        elif re.match(r"^- ", ln):
            b = []
            while i < len(lines) and lines[i].startswith("- "):
                b.append(lines[i][2:].strip()); i += 1
            blocks.append(("bullets", b))
        elif ln.startswith("!["):
            m = re.match(r"!\[([^\]]*)\]\(([^)]+)\)", ln)
            blocks.append(("img", m.group(1), m.group(2))); i += 1
        else:
            buf = [ln.strip()]; i += 1
            while i < len(lines) and lines[i].strip() and not re.match(r"^(#|>|\||- |!\[)", lines[i]):
                buf.append(lines[i].strip()); i += 1
            blocks.append(("p", " ".join(buf)))
    return blocks


ANEXO_A = [
    ["Tema", "Evidencia (ruta desde la raíz del repositorio)", "Entorno"],
    ["Ventana AWS del respaldo (11-nov)", "docs/entregable3/evidencias/aws-ventana-respaldo-rds-20261111.txt; respaldo-rds-20261111.json; linea-base-restauracion-rds-20261111.json", "AWS"],
    ["Subida a OCI y verificación", "docs/entregable3/evidencias/oci-subida-respaldo-rds-20261111.txt", "OCI"],
    ["Restauración aislada del respaldo del 11-nov", "docs/entregable3/evidencias/restauracion-aislada-local-rds-20261111.txt", "Docker local"],
    ["Pruebas del script y del flujo", "docs/entregable3/evidencias/prueba-local-db-backup-cms-20261111.txt (9/9); prueba-local-pipeline-restauracion-20261111.txt (16/16)", "Local/Docker"],
    ["Instantánea manual y parada de RDS", "docs/entregable3/evidencias/rds-instantanea-manual-20261111.txt; rds-parada-20261111.txt", "AWS"],
    ["ALB eliminado (plan guardado y apply)", "docs/entregable3/evidencias/terraform-plan-destroy-alb-target-20261111.txt; terraform-apply-destroy-alb-target-20261111.txt", "AWS"],
    ["Copia cifrada de evidencias", "docs/entregable3/evidencias/copia-cifrada-evidencias-20261111T171139Z.txt", "Local"],
    ["Consultas de solo lectura", "docs/entregable3/evidencias/aws-consulta-solo-lectura-estado-20261110.txt; aws-planificacion-solo-lectura-20261110.txt; oci-consulta-solo-lectura-v4-20261110.txt; auditoria-estatica-viabilidad-*.txt", "AWS/OCI"],
    ["Laboratorio de replicación y fencing", "docs/entregable3/evidencias/repl-20261110-* (A+E 8/8, B 13/13, C, D, F 33/33, F4R 5/5; corridas fallidas incluidas)", "Docker local"],
    ["Prueba real de V2 (6-nov)", "docs/evidencias/20261106-prueba-real-v2/", "AWS"],
    ["Escalado, mediciones y tolerancia a fallos de V2", "docs/evidencias/escalado-v2-20261022/; medicion-v2-20261022/; tolerancia-fallos-v2-20261022/", "AWS"],
    ["Failover de RDS Multi-AZ", "docs/evidencias/multicloud/aws/20261023-rds-multiaz/", "AWS"],
    ["Recuperación de la aplicación en OCI (23-oct)", "docs/evidencias/multicloud/oci/20261023-recuperacion-aplicacion/; 20261023-simulacro-restauracion/; 20261023-transferencia-0008/; 20261023-cierre-recuperacion-aplicacion/", "OCI"],
    ["Observabilidad en Azure", "docs/evidencias/multicloud/azure/20261028-vm/; docs/evidencias/20261109-azure-tailscale/", "Azure"],
    ["Componentes locales de failover (lease, compuerta, DNS, orquestador)", "docs/entregable3/evidencias/prueba-local-lease-compuerta-y-defectos-20261111.txt (54); prueba-local-b12-dns-switch-20261111.txt (14); prueba-local-b13-orquestador-20261111.txt (19); prueba-local-b10-autoprueba-lease-20261111.txt (10); simulacion-lease-margen-20261111.txt", "Local / simulado"],
    ["Verificador de recursos residuales", "docs/entregable3/evidencias/prueba-local-b17-verify-clean-20261111.txt (27); verify-clean-live-solo-lectura-20261111.txt (OCI: 0 recursos; AWS no verificable)", "Local + OCI (solo lectura)"],
    ["Backlog técnico y procedimientos cloud preparados (no ejecutados)", "docs/entregable3/19-backlog-tecnico-y-auditoria-fase1.md; docs/entregable3/20-procedimientos-cloud-pendientes.md", "Documentación"],
    ["Integridad de las evidencias", "docs/entregable3/evidencias/MANIFIESTO-SHA256-20261110.txt (SHA-256 de cada archivo)", "Local"],
]

ANEXO_C = [
    "**Vocabulario entre documentos.** La matriz `14-matriz-cumplimiento-y-plan-minimo.md` usa Cumplido / Parcial / Pendiente; este informe usa los niveles de la rúbrica (Excelente / Bueno / En proceso). Equivalencias: Cumplido ≈ Excelente (criterios 1, 4, 8); «Cumplido con límites» ≈ Excelente defendible (criterio 9); Parcial ≈ Bueno (criterios 2, 3, 5, 6, 7, 10, 11, 12, 13); Pendiente ≈ En proceso (criterio 14: el guion ya existe, falta el ensayo).",
    "**Pesos.** Los pesos de los 14 criterios proceden de la columna «Puntaje» de la rúbrica original y suman 20,0; coinciden en los tres documentos.",
    "**Cifras que coinciden entre el informe 15, la matriz 14 y el guion 16:** restauración local 8–9 s; recuperación completa en OCI 32 min 42 s (23-oct); conmutación de BD 3–4,4 s solo en Docker; 328 reservas perdidas en modo asíncrono con retraso inducido frente a 0 en modo protegido; reinicio automático de RDS ≈ 18-nov 16:52 UTC; expiración de Academy ≈ 26-nov.",
    "**Datos que requieren revisión humana antes de entregar:** (1) portada: autores, docente, institución y fecha de entrega; (2) saldo real de crédito de Academy (hoy solo consta el consumo declarado de 21,70 de 50 USD hacia el 10-nov); (3) confirmar que las cifras heredadas de E2 (37/37, 15/15, 8 min 6 s, ≈ 14 s, 17 min 54 s) siguen vigentes con sus capturas; (4) valorar si se aceptan «respaldo + recuperación + despliegue temporal en OCI» como integración real para el criterio 10; (5) el índice es estático: actualizar números de página si se edita el texto.",
    "**Estado del failover (11-nov, cierre de etapa):** los componentes B-10…B-13 y B-17 están implementados y probados **solo en local/simulado**; el failover AWS–OCI **no está validado en la nube**. La compuerta de escritura está desactivada por defecto y no se desplegó en ninguna instancia. Una consulta real de solo lectura a OCI mostró 0 recursos; AWS no pudo verificarse (laboratorio no activo). La afirmación sobre `verify-full` se corrigió (V2, 4-nov).",
    "**Elementos internos que conviene retirar de la versión final:** este Anexo C.",
]

PRIORIDADES = [
    ["Prioridad", "Acción", "Criterios (peso)", "Costo"],
    ["1", "Cerrar datos de portada y confirmar las correcciones de redacción pendientes; generar la versión de entrega (modo `--entrega`)", "13, 14, 2, 3 (0,5 + 0,5 + 2,0 + 2,0)", "0"],
    ["2", "Ensayo de la defensa con la demo local (restauración en Docker de ≈ 9 s)", "14 (0,5)", "0"],
    ["3", "Captura del saldo de Academy y del estado del Free Trial de OCI; tabla de costos con consumo real", "11 (0,5)", "0"],
    ["4", "Autoprueba REAL del almacén del lease en OCI (procedimiento A; requiere autorización)", "6, 10, 5, 12 (1,5 + 1,5 + 2,5 + 1,0)", "0 USD"],
    ["5", "Una sola ventana de AWS: verificar recursos, capturas y, si procede, cambio de DNS de prueba (procedimiento B)", "5, 7, 11, 6 (2,5 + 1,0 + 0,5 + 1,5)", "≈ 0,05–0,2 USD"],
    ["6", "Opcional O1: restaurar el respaldo del 11-nov en una VM temporal de OCI (requiere autorización)", "9, 10 (3,0 en total)", "0 (Always Free) o ≈ 0,05–0,10 USD"],
    ["7", "Opcional C: simulacro real de failover AWS→OCI (solo tras A, B, O1 y los adaptadores reales; requiere autorización)", "6, 10, 9, 12, 7 (6,0 en total)", "≈ 0,25–0,5 USD"],
]


def build_body():
    blocks = parse_md(MD.read_text())
    body, heads = [], []
    first_quotes = []
    state = {"after_title": True}
    for b in blocks:
        kind = b[0]
        if kind == "title":
            continue                       # va en la portada
        if kind == "quote" and state["after_title"]:
            first_quotes.append(b[1]); continue
        if kind == "h1":
            state["after_title"] = False
            heads.append(b[1])
            body.append(para(inline(b[1]), style="Heading1"))
            if b[1].startswith("14."):
                continue
        elif kind == "h2":
            body.append(para(inline(b[1]), style="Heading2"))
        elif kind == "p":
            if b[1].startswith("Ver la lista priorizada"):
                body.append(para(inline("Prioridad por peso de la rúbrica frente a costo (todo lo imprescindible es gratuito; lo opcional requiere tu autorización aparte):"), style="BodyText"))
                body.append(table(PRIORIDADES, widths=[1000, 5238, 2000, 1400]))
                body.append(para(inline("Sin O1 ni el simulacro C el criterio 10 queda en «Bueno»; solo sube a «Excelente» si se acepta respaldo, recuperación y despliegue temporal como integración real. El simulacro C (conmutación real AWS→OCI) solo tendría sentido después de las acciones 1 a 5 (incluida la autoprueba real del lease), de O1 y de los adaptadores reales, y exige autorización explícita; **el failover AWS–OCI no está validado en la nube**."), style="BodyText"))
            elif re.match(r"^1\. .*\s2\. ", b[1]):
                for item in re.split(r"(?<=[.)])\s+(?=\d+\. )", b[1]):
                    body.append(para(inline(re.sub(r"^\d+\.\s+", "", item)), style="ListBullet"))
            else:
                body.append(para(inline(b[1]), style="BodyText"))
        elif kind == "quote":
            for q in b[1]:
                body.append(para(inline(q, size=19), style="Callout"))
        elif kind == "table":
            wide = len(b[1][0]) >= 7
            body.append(table(b[1], widths=([400, 1500, 560, 2300, 1300, 2500, 1078] if wide else None), size=(15 if wide else 17)))
        elif kind == "bullets":
            for t in b[1]:
                body.append(para(inline(t), style="ListBullet"))
        elif kind == "img":
            path = (E3 / b[2]).with_suffix(".png")
            assert path.exists(), path
            body.append(image(path, alt=b[1]))
            body.append(para(inline({"Capas": "Figura 1. Capas de la integración: qué está probado y dónde.", "Flujo": "Figura 2. Flujo del respaldo cifrado AWS → OCI y restauración aislada.",
                                    "Redes": "Figura 3. Redes por proveedor y ausencia de canal privado entre nubes."}[b[1]], size=17, color=GREY), style="Caption"))
    # anexos
    heads_ann = ["Anexo A. Índice de evidencias", "Anexo B. Referencias cruzadas"] + ([] if ENTREGA else ["Anexo C. Coherencia y puntos de revisión humana (retirar antes de entregar)"])
    body.append(page_break())
    body.append(para(inline(heads_ann[0]), style="Heading1"))
    for r in ANEXO_A[1:]:
        assert True
    # comprueba que las rutas existen (coherencia: no citar evidencias inexistentes)
    missing = []
    for r in ANEXO_A[1:]:
        for frag in re.split(r";\s*", r[1]):
            frag = frag.strip().split(" (")[0]
            if frag.startswith("docs/"):
                base = frag
            elif frag.startswith(("aws-", "oci-", "rds-", "terraform-", "copia-", "prueba-", "restauracion-", "respaldo-", "linea-", "auditoria-", "repl-", "MANIFIESTO", "20261023", "escalado", "medicion", "tolerancia")):
                base = None
            else:
                base = None
            if base and "*" not in base and not (ROOT / base).exists():
                missing.append(base)
    assert not missing, missing
    body.append(para(inline("Rutas relativas a la raíz del repositorio. «Entorno» indica dónde se obtuvo la evidencia; **Docker local** y **Local** no son pruebas entre nubes."), style="BodyText"))
    body.append(table(ANEXO_A, widths=[2300, 6038, 1300], size=16))
    body.append(para(inline(heads_ann[1]), style="Heading1"))
    body.append(table([["Documento", "Contenido"],
                       ["`15-informe-consolidado-entregable3.md`", "Fuente de este Word y del PDF (se conserva sin cambios)."],
                       ["`14-matriz-cumplimiento-y-plan-minimo.md`", "Matriz de cumplimiento, plan mínimo, inventario Git y secretos para recuperar."],
                       ["`16-guion-defensa-entregable3.md`", "Guion de sustentación, demo local y preguntas probables."],
                       ["`13-respaldo-rds-a-oci-cierre.md`", "Cierre del respaldo AWS–OCI y limitaciones."],
                       ["`04`–`07`", "Laboratorio Docker de replicación y viabilidad AWS–OCI (diseño y simulación)."],
                       ["`19-backlog-tecnico-y-auditoria-fase1.md`", "Backlog técnico, resultados de B-17 y B-10…B-13 y estado final de la etapa."],
                       ["`20-procedimientos-cloud-pendientes.md`", "Procedimientos cloud preparados y NO ejecutados (autoprueba del lease, DNS, simulacro)."],
                       ["`diagramas/`", "SVG editables y PNG de 1920 px de las tres figuras."]], widths=[3800, 5838], size=17))
    if not ENTREGA:
        body.append(para(inline(heads_ann[2]), style="Heading1"))
        for t in ANEXO_C:
            body.append(para(inline(t), style="ListBullet"))
    return body, heads, heads_ann, first_quotes


def cover(first_quotes):
    c = []
    c.append(para("", spacing='w:before="1200"'))
    pv = lambda k, ph: PORTADA.get(k) or ph
    if ENTREGA or PORTADA.get("institucion"):
        c.append(para(run(pv("institucion", ""), color="595959", size=22), align="center"))
    else:
        c.append(para(run("UNIVERSIDAD / FACULTAD — completar", color="7F7F7F", size=20, hl="yellow"), align="center"))
    c.append(para(run("Curso: " + pv("curso", "Cloud Computing"), color="7F7F7F", size=22), align="center", spacing='w:after="1000"'))
    c.append(para(run("NexoEventos", bold=True, size=64, color=NAVY), align="center", spacing='w:after="120"'))
    c.append(para(run("Entregable 3", bold=True, size=40, color=NAVY), align="center", spacing='w:after="60"'))
    c.append(para(run("Informe técnico consolidado", size=32, color=NAVY), align="center", spacing='w:after="200"'))
    c.append(para(run("Integración AWS Academy – OCI: respaldo, recuperación y límites de la solución multicloud", size=24, color=GREY), align="center", spacing='w:after="700"'))
    if ENTREGA:
        rows = [["Autor(es)", PORTADA["autores"]], ["Docente", PORTADA["docente"]], ["Fecha de entrega", PORTADA["fecha_entrega"]]]
    else:
        rows = [["Autor(es)", pv("autores", "[completar]")], ["Docente", pv("docente", "[completar]")], ["Fecha de este borrador", pv("fecha_documento", "11 de noviembre de 2026")],
                ["Fecha de entrega", pv("fecha_entrega", "[sin confirmar]")], ["Estado del documento", "Borrador para revisión humana (no es la nota)"]]
    c.append(table(rows, widths=[3200, 6438], size=19))
    for qs in first_quotes[:1]:
        for q in qs:
            if ENTREGA and "borrador" in q.lower():
                continue
            c.append(para(inline(q, size=19), style="Callout"))
    if not ENTREGA:
        c.append(para(inline("Fuente: `15-informe-consolidado-entregable3.md`. Rúbrica: «rúbrica proyecto_qod3szrctm (1).xlsx» (14 criterios, 20 puntos).", size=17, color=GREY), align="center", spacing='w:before="240"'))
    return c


def toc(heads_all):
    t = [para(run("Índice", bold=True, size=32, color=NAVY), style="TOCTitle")]
    for h in heads_all:
        n = PAGES.get(h, 0)
        t.append(f'<w:p><w:pPr><w:pStyle w:val="TOC1"/></w:pPr>{inline(h, size=20)}<w:r><w:tab/></w:r>{run(str(n) if n else "–", size=20)}</w:p>')
    t.append(para(inline("Figuras: 1 (capas), 2 (flujo del respaldo), 3 (redes)." + ("" if ENTREGA else " Índice estático: actualizar los números si se edita el texto."), size=17, color=GREY), spacing='w:before="200"'))
    return t


def styles_xml():
    def pstyle(sid, name, based="Normal", nxt=None, rpr="", ppr="", extra=""):
        return (f'<w:style w:type="paragraph" w:styleId="{sid}"><w:name w:val="{name}"/><w:basedOn w:val="{based}"/>' + (f'<w:next w:val="{nxt}"/>' if nxt else "") +
                f'<w:qFormat/>{extra}<w:pPr>{ppr}</w:pPr><w:rPr>{rpr}</w:rPr></w:style>')
    f = f'<w:rFonts w:ascii="{FONT}" w:hAnsi="{FONT}" w:cs="{FONT}" w:eastAsia="{FONT}"/>'
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            f'<w:docDefaults><w:rPrDefault><w:rPr>{f}<w:sz w:val="20"/><w:szCs w:val="20"/><w:lang w:val="es-PE" w:eastAsia="es-PE"/></w:rPr></w:rPrDefault><w:pPrDefault><w:pPr><w:spacing w:after="100" w:line="264" w:lineRule="auto"/></w:pPr></w:pPrDefault></w:docDefaults>'
            '<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/><w:qFormat/></w:style>'
            + pstyle("BodyText", "Body Text", ppr='<w:jc w:val="both"/>')
            + pstyle("Heading1", "heading 1", nxt="BodyText", rpr=f'<w:b/><w:color w:val="{NAVY}"/><w:sz w:val="30"/><w:szCs w:val="30"/>',
                     ppr=f'<w:keepNext/><w:keepLines/><w:pBdr><w:bottom w:val="single" w:sz="8" w:space="2" w:color="{NAVY}"/></w:pBdr><w:spacing w:before="360" w:after="140"/><w:outlineLvl w:val="0"/>')
            + pstyle("Heading2", "heading 2", nxt="BodyText", rpr=f'<w:b/><w:color w:val="{NAVY}"/><w:sz w:val="24"/><w:szCs w:val="24"/>', ppr='<w:keepNext/><w:spacing w:before="240" w:after="100"/><w:outlineLvl w:val="1"/>')
            + pstyle("TableText", "Table Text", rpr='<w:sz w:val="17"/><w:szCs w:val="17"/>', ppr='<w:spacing w:after="0" w:line="240" w:lineRule="auto"/>')
            + pstyle("Callout", "Callout", ppr=f'<w:pBdr><w:left w:val="single" w:sz="24" w:space="8" w:color="C00000"/></w:pBdr><w:shd w:val="clear" w:color="auto" w:fill="FDECEA"/><w:spacing w:before="60" w:after="60"/><w:ind w:left="200" w:right="100"/>')
            + pstyle("Caption", "caption", ppr='<w:spacing w:before="0" w:after="200"/><w:jc w:val="center"/>', rpr='<w:i/>')
            + pstyle("ListBullet", "List Bullet", ppr='<w:numPr><w:ilvl w:val="0"/><w:numId w:val="1"/></w:numPr><w:spacing w:after="60"/><w:jc w:val="both"/>')
            + pstyle("TOCTitle", "TOC Title", ppr='<w:spacing w:before="0" w:after="240"/>')
            + pstyle("TOC1", "toc 1", ppr=f'<w:tabs><w:tab w:val="right" w:leader="dot" w:pos="{TEXT_W}"/></w:tabs><w:spacing w:before="60" w:after="60"/>')
            + pstyle("Header", "header", ppr=f'<w:tabs><w:tab w:val="right" w:pos="{TEXT_W}"/></w:tabs><w:spacing w:after="0"/>', rpr='<w:sz w:val="16"/><w:color w:val="595959"/>')
            + pstyle("Footer", "footer", ppr=f'<w:tabs><w:tab w:val="right" w:pos="{TEXT_W}"/></w:tabs><w:spacing w:after="0"/>', rpr='<w:sz w:val="15"/><w:color w:val="595959"/>')
            + '</w:styles>')


NS = ('xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
      'xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"')


def fld(instr):
    return (f'<w:r><w:fldChar w:fldCharType="begin"/></w:r><w:r><w:instrText xml:space="preserve"> {instr} </w:instrText></w:r><w:r><w:fldChar w:fldCharType="separate"/></w:r>'
            f'<w:r><w:t>1</w:t></w:r><w:r><w:fldChar w:fldCharType="end"/></w:r>')


def main():
    body, heads, heads_ann, first_quotes = build_body()
    all_heads = heads + heads_ann
    doc = cover(first_quotes) + [page_break()] + toc(all_heads) + [page_break()] + body
    sect = ('<w:sectPr><w:headerReference w:type="default" r:id="rIdH1"/><w:headerReference w:type="first" r:id="rIdH2"/><w:footerReference w:type="default" r:id="rIdF1"/><w:footerReference w:type="first" r:id="rIdF2"/>'
            '<w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="1418" w:right="1134" w:bottom="1304" w:left="1134" w:header="567" w:footer="454" w:gutter="0"/><w:titlePg/></w:sectPr>')
    document = f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document {NS}><w:body>{"".join(doc)}{sect}</w:body></w:document>'
    header = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:hdr {NS}><w:p><w:pPr><w:pStyle w:val="Header"/><w:pBdr><w:bottom w:val="single" w:sz="4" w:space="3" w:color="BFBFBF"/></w:pBdr></w:pPr>'
              f'{run("NexoEventos · Entregable 3 — Informe técnico consolidado", size=16, color=GREY)}<w:r><w:tab/></w:r>{run((PORTADA.get("fecha_entrega", "") if ENTREGA else "Borrador para revisión · 11-nov-2026"), size=16, color=GREY)}</w:p></w:hdr>')
    footer = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:ftr {NS}><w:p><w:pPr><w:pStyle w:val="Footer"/><w:pBdr><w:top w:val="single" w:sz="4" w:space="3" w:color="BFBFBF"/></w:pBdr></w:pPr>'
              f'{run("Fechas clave: reinicio automático de RDS ≈ 18-nov-2026 16:52 UTC · AWS Academy expira ≈ 26-nov-2026", size=15, color="C00000", bold=True)}<w:r><w:tab/></w:r>'
              f'{run("Página ", size=15, color=GREY)}{fld("PAGE")}{run(" de ", size=15, color=GREY)}{fld("NUMPAGES")}</w:p></w:ftr>')
    empty_h = f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:hdr {NS}><w:p><w:pPr><w:pStyle w:val="Header"/></w:pPr></w:p></w:hdr>'
    empty_f = f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:ftr {NS}><w:p><w:pPr><w:pStyle w:val="Footer"/></w:pPr>{run("Fechas clave: reinicio automático de RDS ≈ 18-nov-2026 16:52 UTC · AWS Academy expira ≈ 26-nov-2026", size=15, color="C00000", bold=True)}</w:p></w:ftr>'
    numbering = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:numbering xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:abstractNum w:abstractNumId="0"><w:multiLevelType w:val="hybridMultilevel"/>'
                 '<w:lvl w:ilvl="0"><w:start w:val="1"/><w:numFmt w:val="bullet"/><w:lvlText w:val="•"/><w:lvlJc w:val="left"/><w:pPr><w:ind w:left="500" w:hanging="260"/></w:pPr><w:rPr><w:rFonts w:ascii="Arial" w:hAnsi="Arial"/></w:rPr></w:lvl></w:abstractNum>'
                 '<w:num w:numId="1"><w:abstractNumId w:val="0"/></w:num></w:numbering>')
    settings = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:settings xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:defaultTabStop w:val="720"/><w:compat><w:compatSetting w:name="compatibilityMode" w:uri="http://schemas.microsoft.com/office/word" w:val="15"/></w:compat></w:settings>'
    ctypes = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
              '<Default Extension="xml" ContentType="application/xml"/><Default Extension="png" ContentType="image/png"/>'
              '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
              '<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>'
              '<Override PartName="/word/numbering.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.numbering+xml"/>'
              '<Override PartName="/word/settings.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.settings+xml"/>'
              '<Override PartName="/word/header1.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.header+xml"/><Override PartName="/word/header2.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.header+xml"/>'
              '<Override PartName="/word/footer1.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.footer+xml"/><Override PartName="/word/footer2.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.footer+xml"/>'
              '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/><Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/></Types>')
    rootrels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
                '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>'
                '<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/></Relationships>')
    R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    drels = [f'<Relationship Id="rIdS" Type="{R}/styles" Target="styles.xml"/>', f'<Relationship Id="rIdN" Type="{R}/numbering" Target="numbering.xml"/>', f'<Relationship Id="rIdSet" Type="{R}/settings" Target="settings.xml"/>',
             f'<Relationship Id="rIdH1" Type="{R}/header" Target="header1.xml"/>', f'<Relationship Id="rIdH2" Type="{R}/header" Target="header2.xml"/>',
             f'<Relationship Id="rIdF1" Type="{R}/footer" Target="footer1.xml"/>', f'<Relationship Id="rIdF2" Type="{R}/footer" Target="footer2.xml"/>']
    drels += [f'<Relationship Id="{rid}" Type="{R}/image" Target="media/{name}"/>' for rid, _, name in media]
    docrels = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' + "".join(drels) + "</Relationships>"
    core = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/" '
            'xmlns:dcterms="http://purl.org/dc/terms/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"><dc:title>NexoEventos — Entregable 3: informe técnico consolidado (borrador)</dc:title><dc:creator>Equipo NexoEventos</dc:creator>'
            '<dcterms:created xsi:type="dcterms:W3CDTF">2026-11-11T12:00:00Z</dcterms:created></cp:coreProperties>')
    app = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties"><Application>Microsoft Office Word</Application></Properties>'
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", ctypes)
        z.writestr("_rels/.rels", rootrels)
        z.writestr("word/document.xml", document)
        z.writestr("word/_rels/document.xml.rels", docrels)
        z.writestr("word/styles.xml", styles_xml())
        z.writestr("word/numbering.xml", numbering)
        z.writestr("word/settings.xml", settings)
        z.writestr("word/header1.xml", header); z.writestr("word/header2.xml", empty_h)
        z.writestr("word/footer1.xml", footer); z.writestr("word/footer2.xml", empty_f)
        z.writestr("docProps/core.xml", core); z.writestr("docProps/app.xml", app)
        for _, p, name in media:
            z.write(p, f"word/media/{name}")
    Path(str(OUT) + ".heads.json").write_text(json.dumps(all_heads, ensure_ascii=False))
    print(f"OK {OUT} ({OUT.stat().st_size} bytes; {len(media)} imágenes; {len(all_heads)} encabezados)")


if __name__ == "__main__":
    main()
