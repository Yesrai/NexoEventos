# -*- coding: utf-8 -*-
"""Copia los entregables, arma el ZIP sin secretos y ejecuta el control de calidad automático."""
import os, re, json, shutil, zipfile, hashlib, subprocess, datetime as dt, glob
import fitz, docx, openpyxl

S = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = "~/Workspace/NexoEventos"
WT = "~/Workspace/NexoEventos-informe-final"
CODEX = "~/Workspace/NexoEventos-codex-t7-t8"
OUT = f"{WT}/docs/entrega-final"
B = f"{S}/build"
NAMES = {"informe_docx": "NexoEventos_Informe_Final_Completo_Con_Evidencias.docx", "informe_pdf": "NexoEventos_Informe_Final_Completo_Con_Evidencias.pdf",
         "anexos_pdf": "NexoEventos_Anexos_Evidencias.pdf", "zip": "NexoEventos_Entrega_Final.zip"}
shutil.copy(f"{B}/informe.docx", f"{OUT}/{NAMES['informe_docx']}")
shutil.copy(f"{B}/informe.pdf", f"{OUT}/{NAMES['informe_pdf']}")
shutil.copy(f"{B}/anexos.pdf", f"{OUT}/{NAMES['anexos_pdf']}")
inv = json.load(open(f"{B}/inventario.json")); absmap = json.load(open(f"{B}/inventario_abs.json"))

def sha(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()

# ------------------------------------------------------------------ ZIP staging
ST = f"{B}/zipstage"; shutil.rmtree(ST, ignore_errors=True); os.makedirs(ST)
root = f"{ST}/NexoEventos_Entrega_Final"
redactadas = []
def put(src, rel):
    dst = os.path.join(root, rel); os.makedirs(os.path.dirname(dst), exist_ok=True); shutil.copy(src, dst)
for k in ("informe_docx", "informe_pdf", "anexos_pdf"): put(f"{OUT}/{NAMES[k]}", NAMES[k])
for f in ("INVENTARIO-MAESTRO-EVIDENCIAS.xlsx", "INVENTARIO-MAESTRO-EVIDENCIAS.md", "MATRIZ-RUBRICA-EVIDENCIAS.xlsx"): put(f"{OUT}/{f}", f)
for f in glob.glob(f"{OUT}/graficos-informe/*.png"): put(f, "graficos-informe/" + os.path.basename(f))
for f in glob.glob(f"{REPO}/docs/entrega-final/diagramas/*"): put(f, "diagramas/" + os.path.basename(f))
for f in glob.glob(f"{OUT}/control-calidad/*.txt") + glob.glob(f"{OUT}/control-calidad/*.md"):
    txt = open(f).read().replace("~", "~"); dst = f"{root}/control-calidad/{os.path.basename(f)}"; os.makedirs(os.path.dirname(dst), exist_ok=True); open(dst, "w").write(txt)
put("~/Downloads/rúbrica proyecto_qod3szrctm.xlsx", "fuentes/rubrica-oficial_qod3szrctm.xlsx")
n_ev = 0
for i in inv:
    if i["en_zip"] != "sí" or i["id"] not in absmap or not absmap[i["id"]]: continue
    src = absmap[i["id"]]
    if src.startswith(OUT): continue  # ya incluidos arriba
    rel = "evidencias/" + i["ruta"].replace("../NexoEventos-codex-t7-t8/", "rama-codex-t7-t8/")
    if src.endswith((".json", ".md", ".txt", ".jsonl", ".py", ".sh", ".tf", ".conf", ".service", ".timer", ".sha256")):
        txt = open(src, errors="surrogateescape").read()
        new = re.sub(r"https://(\d{1,3}\.){3}\d{1,3}", "https://[IP-oculta]", txt)
        new = re.sub(r"/subscriptions/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", "/subscriptions/[ID-suscripcion-oculto]", new)
        new = re.sub(r"\b100\.(6[4-9]|[7-9]\d|1[01]\d|12[0-7])\.\d{1,3}\.\d{1,3}\b", "[IP-tailnet-oculta]", new)
        new = new.replace("~", "~").replace("/private/tmp/claude-501", "[tmp]")
        if new != txt:
            dst = os.path.join(root, rel); os.makedirs(os.path.dirname(dst), exist_ok=True); open(dst, "w", errors="surrogateescape").write(new); redactadas.append(rel); n_ev += 1; continue
    put(src, rel); n_ev += 1

readme = f"""# NexoEventos — Entrega final (paquete)

Generado: {dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%MZ')} desde la rama `informe-final-completo` (base `cierre-t6-t8` @ 5e1fed1).

| Ruta | Contenido |
|---|---|
| `{NAMES['informe_docx']}` / `.pdf` | Informe académico final (capítulos I–XV, índices automáticos) |
| `{NAMES['anexos_pdf']}` | Anexos: capturas auténticas redactadas, criterios de cada expediente, salidas de prueba |
| `INVENTARIO-MAESTRO-EVIDENCIAS.xlsx` / `.md` | {len(inv)} evidencias con ID, ruta, fecha UTC, tipo, resultado, SHA-256 y limitación |
| `MATRIZ-RUBRICA-EVIDENCIAS.xlsx` | 14 criterios de la rúbrica (literal) contrastados con la evidencia |
| `evidencias/` | {n_ev} archivos de evidencia con la misma ruta relativa que en el inventario |
| `graficos-informe/`, `diagramas/` | gráficos derivados de datos reales y diagramas de elaboración propia |
| `control-calidad/` | salidas de pytest re-ejecutadas y registro del control de calidad |
| `fuentes/rubrica-oficial_qod3szrctm.xlsx` | copia de la rúbrica oficial |

**Excluido a propósito:** estados de Terraform (`*.tfstate`, `.terraform/`), `*.tfvars` reales, planes binarios, bases de datos y volcados, respaldos cifrados, claves, tokens, `.env` y configuraciones privadas; archivos de despliegue de NexoOps **sin commit** (A1 en curso).

**Copias redactadas** (difieren del original y por eso su línea del `MANIFIESTO.sha256` no coincide): {', '.join('`' + r + '`' for r in redactadas)} — se ocultaron IP públicas efímeras de VM de OCI ya destruidas, IP de la red privada Tailscale, el ID de suscripción de Azure y la ruta del directorio personal del equipo (sustituida por `~`). El SHA-256 del original figura en el inventario.

Para verificar un expediente: `cd evidencias/work/evidencias/<expediente> && shasum -a 256 -c MANIFIESTO.sha256`.
"""
open(f"{root}/LEEME.md", "w").write(readme)

# ------------------------------------------------------------------ búsqueda de secretos en el staging
PAT = {"IPv4 no pública-de-resolvedor": r"\b(?:\d{1,3}\.){3}\d{1,3}\b", "OCID": r"ocid1\.[a-z]+\.", "URL de PAR": r"objectstorage\.[\w.-]+oraclecloud\.com/p/",
       "clave AWS": r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b", "clave privada": r"-----BEGIN [A-Z ]*PRIVATE KEY-----", "token tipo UUID": r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b",
       "correo": r"[\w.+-]+@(?:gmail|hotmail|outlook|upeu)\.[\w.]+", "Bearer": r"Bearer\s+[A-Za-z0-9._-]{20,}", "contraseña asignada": r"(?i)password\s*[=:]\s*['\"][^'\"]{6,}"}
OKIP = {"1.1.1.1", "8.8.8.8", "9.9.9.9", "0.0.0.0", "127.0.0.1", "168.63.129.16"}
hallazgos = []
for dp, _, fs in os.walk(root):
    for f in fs:
        p = os.path.join(dp, f)
        if f.endswith((".png", ".jpg", ".pdf", ".docx", ".xlsx", ".zip")): continue
        txt = open(p, errors="ignore").read()
        for k, rx in PAT.items():
            for m in re.finditer(rx, txt):
                v = m.group(0)
                if k.startswith("IPv4"):
                    parts = v.split(".")
                    if v in OKIP or any(int(x) > 255 for x in parts) or v.startswith(("10.", "0.")) or re.match(r"\d+\.\d+\.\d+\.\d+", v) and len(parts[0]) == 1 and parts[0] in "0123456789" and txt[m.start()-1:m.start()] in "vV": continue
                    ctx = txt[max(0, m.start() - 25):m.end() + 5]
                    if re.search(r"(version|v\d|==|>=|\d\.\d+\.\d+\.\d+-)", ctx): continue
                hallazgos.append((os.path.relpath(p, root), k, v[:60]))
# texto de los PDF y DOCX
for f in (NAMES["informe_pdf"], NAMES["anexos_pdf"]):
    txt = "".join(pg.get_text() for pg in fitz.open(f"{root}/{f}"))
    for k, rx in PAT.items():
        for m in re.finditer(rx, txt):
            v = m.group(0)
            if k.startswith("IPv4") and (v in OKIP or v.startswith("10.") or re.search(r"\d+\.\d+\.\d+\.\d+$", v) and int(v.split(".")[0]) > 255): continue
            hallazgos.append((f, k, v[:60]))
json.dump(hallazgos, open(f"{B}/hallazgos_secretos.json", "w"), ensure_ascii=False, indent=1)

# ------------------------------------------------------------------ ZIP
zp = f"{OUT}/{NAMES['zip']}"
if os.path.exists(zp): os.remove(zp)
with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED) as z:
    for dp, _, fs in os.walk(root):
        for f in sorted(fs):
            p = os.path.join(dp, f); z.write(p, os.path.relpath(p, ST))
with zipfile.ZipFile(zp) as z:
    bad = z.testzip(); names = z.namelist()
forbidden = [n for n in names if re.search(r"(\.tfstate|/\.terraform/|\.tfvars$|\.dump$|\.sql\.gz$|\.cms$|\.pem$|\.key$|\.env$|id_rsa|nexoops\.env)", n)]
print("zip", len(names), "archivos", os.path.getsize(zp), "bytes; testzip:", bad, "; prohibidos:", forbidden, "; hallazgos:", len(hallazgos))
json.dump({"zip_files": len(names), "zip_bytes": os.path.getsize(zp), "testzip": bad, "forbidden": forbidden, "redactadas": redactadas, "n_ev": n_ev,
           "zip_sha256": sha(zp)}, open(f"{B}/zipinfo.json", "w"), indent=1)

open(f"{zp}.sha256", "w").write(f"{sha(zp)}  {NAMES['zip']}\n")
