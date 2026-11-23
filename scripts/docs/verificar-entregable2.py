#!/usr/bin/env python3
"""Verificador local (sin red, sin nube, sin costo) de la documentación del Entregable 2.
1) El informe tiene exactamente las secciones 01–20 en orden. 2) Todos los enlaces relativos (archivos y anclas) de docs/entregable2 existen y los SVG son XML válido.
3) Ninguna IP pública, correo, UUID, ID de cuenta de 12 dígitos ni material de claves en docs/entregable2 ni en las evidencias de Azure de la ventana. 4) Cifras clave del informe
aparecen en el archivo de evidencia que las respalda. Sale con código 1 si algo falla. Uso: python3 scripts/docs/verificar-entregable2.py"""
import pathlib, re, sys, xml.dom.minidom

ROOT = pathlib.Path(__file__).resolve().parents[2]; D = ROOT / "docs/entregable2"
fails, notes = [], []
def ok(msg): print("OK    ", msg)
def ko(msg): print("FALLA ", msg); fails.append(msg)

def slug(h):
    h = h.strip().lower(); h = re.sub(r"[^\w\s-]", "", h, flags=re.U); return re.sub(r"\s", "-", h)
def anchors(p):
    return {slug(m.group(1)) for m in re.finditer(r"^#{1,6}\s+(.+?)\s*$", p.read_text(), re.M)}

# 1) secciones
inf = (D / "informe-entregable2.md").read_text()
secs = re.findall(r"^## (\d\d) · ", inf, re.M)
(ok if secs == [f"{i:02d}" for i in range(1, 21)] else ko)(f"informe: secciones 01–20 en orden ({len(secs)} encontradas)")

# 2) enlaces
bad = 0; total = 0
for md in sorted(D.glob("*.md")):
    for m in re.finditer(r"!?\[[^\]]*\]\(([^)\s]+)\)", md.read_text()):
        url = m.group(1)
        if re.match(r"^(https?:|mailto:)", url): continue
        total += 1; path, _, frag = url.partition("#")
        target = (md.parent / path).resolve() if path else md
        if not target.exists(): ko(f"{md.name}: enlace roto → {url}"); bad += 1; continue
        if frag and target.suffix == ".md" and frag not in anchors(target): ko(f"{md.name}: ancla inexistente → {url}"); bad += 1
if not bad: ok(f"{total} enlaces relativos y anclas resuelven")
for svg in sorted((D / "diagramas").glob("*.svg")):
    try: xml.dom.minidom.parse(str(svg)); ok(f"SVG válido: {svg.name}")
    except Exception as e: ko(f"SVG inválido {svg.name}: {e}")

# 3) datos sensibles
files = list(D.rglob("*.md")) + list(D.rglob("*.svg")) + list((ROOT / "docs/evidencias/multicloud/azure/20261028-vm").glob("*"))
priv = re.compile(r"^(10\.|127\.|0\.|169\.254\.|172\.(1[6-9]|2\d|3[01])\.|192\.168\.|168\.63\.129\.16)")
pats = {"correo": re.compile(r"[\w.+-]+@[\w-]+\.[a-z]{2,}"), "UUID": re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b"),
        "ID de cuenta (12 dígitos)": re.compile(r"(?<![\d.])\d{12}(?![\d.])"), "clave privada": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY|AKIA[0-9A-Z]{16}|SHA256:[A-Za-z0-9+/]{43}")}
leaks = []
for f in files:
    if f.is_dir() or f.suffix in (".log",): continue
    t = f.read_text(errors="ignore")
    for ip in re.findall(r"(?<![\d.])(\d{1,3}(?:\.\d{1,3}){3})(?![\d.]|/\d)", t):
        if not priv.match(ip) and all(0 <= int(o) <= 255 for o in ip.split(".")) and not re.fullmatch(r"\d+\.\d+\.\d+\.\d+", ip) is None and ip.count(".") == 3:
            # versiones tipo 0.24.04.1 no son IP: se exige que el primer octeto sea ≥ 1 y que no aparezca tras «ubuntu»
            if int(ip.split(".")[0]) >= 1 and not re.search(r"ubuntu" + re.escape(ip), t) and "x.x" not in ip: leaks.append((f.name, "IPv4 pública", ip))
    for name, rx in pats.items():
        for m in rx.findall(t): leaks.append((f.name, name, str(m)[:30]))
(ok if not leaks else ko)(f"datos sensibles en {len(files)} archivos revisados" + ("" if not leaks else f": {leaks[:5]}"))
# nota: la huella ED25519 PÚBLICA del servidor SSH no es secreta, pero la regla SHA256: se aplica a todo el directorio por prudencia

# 4) cifras ↔ evidencias
EV = ROOT / "docs/evidencias"
checks = [("EV11/resultado-2026-10-09.md", "421.2", "E01 p95"), ("EV11/resultado-2026-10-09.md", "2 520", "E01 solicitudes"),
          ("medicion-v2-20261022/resultado.md", "288 → 190", "p95 V1→V2 a 50 usuarios"), ("medicion-v2-20261022/resultado.md", "35 366", "solicitudes V2 sin 5xx"),
          ("escalado-v2-20261022/resultado.md", "8 min 6 s", "alarma de escalado"), ("tolerancia-fallos-v2-20261022/resultado.md", "20,0 s", "detección ALB"),
          ("tolerancia-fallos-v2-20261022/resultado.md", "15,8 s", "recuperación"), ("multicloud/aws/20261023-rds-multiaz/failover/resultado.md", "≈ 14 s", "failover PostgreSQL"),
          ("EV07/resultado-restauracion-2026-10-10.md", "21 min 4 s", "R01 datos"), ("EV07/resultado-restauracion-2026-10-10.md", "3 min 32 s", "R01 RPO"),
          ("multicloud/oci/20261023-recuperacion-aplicacion/resultado.md", "32 min 42 s", "T_funcional OCI"), ("multicloud/oci/20261023-recuperacion-aplicacion/resultado.md", "14/14", "pruebas OCI"),
          ("multicloud/azure/20261028-vm/resultado.md", "17 min 54 s", "detección alerta Azure"), ("multicloud/azure/20261028-vm/carga-historica.txt", "1202", "puntos históricos")]
for rel, needle, what in checks:
    p = EV / rel
    if not p.exists(): ko(f"cifra «{what}»: falta {rel}"); continue
    if needle in p.read_text(): ok(f"cifra «{what}» ({needle}) está en {rel}")
    else: ko(f"cifra «{what}» ({needle}) NO está en {rel}")
for needle in ["421,2", "288 → 190", "17 min 54 s", "32 min 42 s", "21 min 4 s", "35 366", "8 min 6 s"]:
    (ok if needle in inf else ko)(f"el informe cita «{needle}»")

pend = len(re.findall(r"\[PENDIENTE", inf)); nov = len(re.findall(r"\[NO (VERIFICADO|IMPLEMENTADO|MEDIDO)", inf))
print(f"\nMarcadores honestos en el informe: {pend} [PENDIENTE…], {nov} [NO VERIFICADO/IMPLEMENTADO/MEDIDO]")
print("\nRESULTADO:", "TODO CORRECTO" if not fails else f"{len(fails)} FALLA(S)"); sys.exit(1 if fails else 0)
