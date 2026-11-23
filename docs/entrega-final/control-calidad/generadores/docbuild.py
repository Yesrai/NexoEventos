# -*- coding: utf-8 -*-
"""Utilidades de python-docx: estilos, campos (TOC/SEQ/PAGE), tablas, figuras y recuadros de evidencia."""
import re, json, os
import docx
from docx.shared import Pt, Cm, RGBColor, Emu
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.section import WD_ORIENT
from docx.oxml.ns import qn
from docx.oxml import OxmlElement

FONT = "Arial"
AZUL = RGBColor(0x0D, 0x3B, 0x66)

def _field(par, instr, placeholder=""):
    def run_el(tag, **attrs):
        r = OxmlElement("w:r"); e = OxmlElement(tag)
        for k, v in attrs.items(): e.set(qn(k), v)
        r.append(e); par._p.append(r); return e
    run_el("w:fldChar", **{"w:fldCharType": "begin"})
    r = OxmlElement("w:r"); t = OxmlElement("w:instrText"); t.set(qn("xml:space"), "preserve"); t.text = " " + instr + " "; r.append(t); par._p.append(r)
    run_el("w:fldChar", **{"w:fldCharType": "separate"})
    rr = par.add_run(placeholder)
    run_el("w:fldChar", **{"w:fldCharType": "end"})
    return rr

def shade(cell, hexcolor):
    tcPr = cell._tc.get_or_add_tcPr(); s = OxmlElement("w:shd")
    s.set(qn("w:val"), "clear"); s.set(qn("w:color"), "auto"); s.set(qn("w:fill"), hexcolor); tcPr.append(s)

def cell_margins(table, top=40, bottom=40, left=70, right=70):
    tblPr = table._tbl.tblPr; m = OxmlElement("w:tblCellMar")
    for k, v in (("top", top), ("left", left), ("bottom", bottom), ("right", right)):
        e = OxmlElement(f"w:{k}"); e.set(qn("w:w"), str(v)); e.set(qn("w:type"), "dxa"); m.append(e)
    tblPr.append(m)

def repeat_header(row):
    trPr = row._tr.get_or_add_trPr(); e = OxmlElement("w:tblHeader"); e.set(qn("w:val"), "true"); trPr.append(e)

def no_split(row):
    trPr = row._tr.get_or_add_trPr(); e = OxmlElement("w:cantSplit"); e.set(qn("w:val"), "true"); trPr.append(e)

class Doc:
    def __init__(self, inv_json, root_abs_map=None):
        self.d = docx.Document()
        self.inv = json.load(open(inv_json))
        self.by_path = {}
        for i in self.inv: self.by_path.setdefault(i["ruta"], i["id"])
        self._styles()
        sec = self.d.sections[0]
        sec.page_height, sec.page_width = Cm(29.7), Cm(21.0)
        sec.left_margin = sec.right_margin = Cm(2.3); sec.top_margin = Cm(2.2); sec.bottom_margin = Cm(2.0)
        self.width = sec.page_width - sec.left_margin - sec.right_margin
        self.used = []   # evidencias citadas

    def _styles(self):
        st = self.d.styles
        n = st["Normal"]; n.font.name = FONT; n.font.size = Pt(11)
        n.element.rPr.rFonts.set(qn("w:eastAsia"), FONT)
        n.paragraph_format.space_after = Pt(5); n.paragraph_format.line_spacing = 1.12
        for lvl, size, col in ((1, 16, AZUL), (2, 13, AZUL), (3, 11.5, RGBColor(0x22, 0x22, 0x22))):
            h = st[f"Heading {lvl}"]; h.font.name = FONT; h.font.size = Pt(size); h.font.bold = True; h.font.color.rgb = col
            h.element.rPr.rFonts.set(qn("w:eastAsia"), FONT); h.element.rPr.rFonts.set(qn("w:ascii"), FONT); h.element.rPr.rFonts.set(qn("w:hAnsi"), FONT)
            h.paragraph_format.space_before = Pt(14 if lvl == 1 else 10); h.paragraph_format.space_after = Pt(6); h.paragraph_format.keep_with_next = True
        c = st["Caption"]; c.font.name = FONT; c.font.size = Pt(9); c.font.bold = True; c.font.italic = False; c.font.color.rgb = RGBColor(0x33, 0x33, 0x33)
        c.paragraph_format.space_after = Pt(2)
        if "Fuente" not in [s.name for s in st]:
            f = st.add_style("Fuente", 1); f.base_style = n; f.font.size = Pt(8); f.font.italic = True; f.font.color.rgb = RGBColor(0x55, 0x55, 0x55)
            f.paragraph_format.space_after = Pt(8)
        for name in ("List Bullet", "List Number"):
            s = st[name]; s.font.name = FONT; s.font.size = Pt(11); s.paragraph_format.space_after = Pt(3)

    # ------------------------------------------------------------ texto con **negrita** y `código`
    def _rich(self, p, text, size=None, color=None):
        for part in re.split(r"(\*\*[^*]+\*\*|`[^`]+`)", text):
            if not part: continue
            if part.startswith("**"): r = p.add_run(part[2:-2]); r.bold = True
            elif part.startswith("`"): r = p.add_run(part[1:-1]); r.font.name = "Courier New"; r.font.size = Pt((size or 10.5) - 1)
            else: r = p.add_run(part)
            if size and not part.startswith("`"): r.font.size = Pt(size)
            if color: r.font.color.rgb = color
        return p

    def ev(self, ruta):
        i = self.by_path.get(ruta)
        if not i: raise KeyError("ruta sin ID de evidencia: " + ruta)
        self.used.append(i); return i

    def evs(self, *rutas): return ", ".join(self.ev(r) for r in rutas)

    def h(self, text, lvl=1):
        hp = self.d.add_heading(text, lvl)
        if lvl == 1: hp.paragraph_format.page_break_before = True
        return hp

    def p(self, text, align=None, size=None, italic=False, style=None):
        p = self.d.add_paragraph(style=style); self._rich(p, text, size)
        if align == "j": p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
        elif align == "c": p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        if italic:
            for r in p.runs: r.italic = True
        return p

    def pj(self, text): return self.p(text, align="j")

    def bullets(self, items, numbered=False):
        for it in items:
            p = self.d.add_paragraph(style="List Number" if numbered else "List Bullet"); self._rich(p, it)

    def page_break(self):
        if len(self.d.paragraphs) > 0:
            self.d.add_paragraph().add_run().add_break(WD_BREAK.PAGE)

    def caption(self, kind, text):
        p = self.d.add_paragraph(style="Caption")
        p.add_run(kind + " "); _field(p, f"SEQ {kind} \\* ARABIC", "#"); p.add_run(". " + text)
        p.paragraph_format.keep_with_next = True
        return p

    def table(self, header, rows, widths=None, caption=None, source=None, size=9, first_bold=False, color_col=None):
        if caption: self.caption("Tabla", caption)
        t = self.d.add_table(rows=1, cols=len(header)); t.style = "Table Grid"; t.alignment = WD_TABLE_ALIGNMENT.CENTER
        cell_margins(t)
        for j, htxt in enumerate(header):
            c = t.rows[0].cells[j]; c.text = ""; pp = c.paragraphs[0]; r = pp.add_run(htxt); r.bold = True; r.font.size = Pt(size); r.font.color.rgb = RGBColor(255, 255, 255)
            shade(c, "0D3B66")
        repeat_header(t.rows[0])
        for row in rows:
            cells = t.add_row().cells
            for j, v in enumerate(row):
                c = cells[j]; c.text = ""; pp = c.paragraphs[0]; pp.paragraph_format.space_after = Pt(0)
                self._rich(pp, str(v), size)
                if first_bold and j == 0:
                    for r in pp.runs: r.bold = True
                if color_col is not None and j == color_col:
                    s = str(v).upper()
                    col = None
                    if s.startswith("PASS") or s.startswith("CUMPLE") or s.startswith("EXCELENTE"): col = "D7EED9"
                    elif s.startswith("FAIL") or s.startswith("NO CUMPLE") or s.startswith("NO_CUMPLE") or s.startswith("DEFICIENTE"): col = "F8D7D7"
                    elif s.startswith("BLOCKED") or s.startswith("NOT_TESTED") or s.startswith("EN PROCESO") or s.startswith("SIN_MEDIR") or s.startswith("ABORT"): col = "FCE8C8"
                    elif s.startswith("BUENO") or s.startswith("LOCAL") or s.startswith("PARCIAL"): col = "E3ECF7"
                    if col: shade(c, col)
        for r_ in t.rows: no_split(r_)
        if not widths: widths = [1] * len(header)
        self._widths(t, widths)
        if source: self.d.add_paragraph(source, style="Fuente")
        else: self.d.add_paragraph().paragraph_format.space_after = Pt(2)
        return t

    def _widths(self, t, widths):
        tot = sum(widths); t.autofit = False
        tw = [int(self.width * w / tot) for w in widths]
        tblPr = t._tbl.tblPr
        lay = OxmlElement("w:tblLayout"); lay.set(qn("w:type"), "fixed"); tblPr.append(lay)
        tblW = tblPr.find(qn("w:tblW"))
        if tblW is None: tblW = OxmlElement("w:tblW"); tblPr.append(tblW)
        tblW.set(qn("w:w"), str(int(sum(tw) / 635))); tblW.set(qn("w:type"), "dxa")
        grid = t._tbl.tblGrid
        for k, gc in enumerate(grid.findall(qn("w:gridCol"))):
            gc.set(qn("w:w"), str(int(tw[k] / 635)))
        for r_ in t.rows:
            for j, w in enumerate(tw): r_.cells[j].width = Emu(w)

    def figure(self, path, caption, source, width_cm=16.0):
        p = self.d.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER; p.paragraph_format.keep_with_next = True
        p.add_run().add_picture(path, width=Cm(width_cm))
        self.caption("Figura", caption)
        self.d.add_paragraph(source, style="Fuente")

    def evbox(self, ev_ids, title, body, kind="Evidencia"):
        """Recuadro de evidencia numerado (alimenta el índice de evidencias)."""
        t = self.d.add_table(rows=1, cols=1); t.style = "Table Grid"; t.alignment = WD_TABLE_ALIGNMENT.CENTER; cell_margins(t, 60, 60, 110, 110)
        self._widths(t, [1]); c = t.rows[0].cells[0]; shade(c, "EEF3F8"); no_split(t.rows[0])
        p = c.paragraphs[0]; p.style = self.d.styles["Caption"]
        p.add_run(kind + " "); _field(p, f"SEQ {kind} \\* ARABIC", "#"); p.add_run(f". {title} [{ev_ids}]")
        q = c.add_paragraph(); self._rich(q, body, 9); q.paragraph_format.space_after = Pt(0)
        self.d.add_paragraph().paragraph_format.space_after = Pt(2)

    def toc(self, title, instr):
        p = self.d.add_paragraph(); r = p.add_run(title); r.bold = True; r.font.size = Pt(14); r.font.color.rgb = AZUL
        _field(self.d.add_paragraph(), instr, "(índice: se actualiza al abrir o al exportar)")

    def header_footer(self, text):
        sec = self.d.sections[0]
        hp = sec.header.paragraphs[0]; hp.text = ""; r = hp.add_run(text); r.font.size = Pt(8); r.font.color.rgb = RGBColor(0x66, 0x66, 0x66)
        fp = sec.footer.paragraphs[0]; fp.alignment = WD_ALIGN_PARAGRAPH.CENTER
        r = fp.add_run("Página "); r.font.size = Pt(8); _field(fp, "PAGE", "1"); r = fp.add_run(" de "); r.font.size = Pt(8); _field(fp, "NUMPAGES", "1")
        sec.different_first_page_header_footer = True

    def save(self, path): self.d.save(path)
