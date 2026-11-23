#!/usr/bin/env python3
"""Auditoría ESTÁTICA (no ejecuta nada de nube) de un script de comprobación de solo lectura.
Comprueba: (1) toda llamada a `oci` usa una acción de consulta (list/get); (2) ninguna palabra de modificación en el código; (3) ningún instalador ni escritura de archivos;
(4) ningún `oci setup`/`session`/`raw-request`; (5) el filtro de salida oculta los datos sensibles (prueba local con textos de ejemplo, sin red).
Uso: python3 scripts/multicloud/auditar-solo-lectura.py scripts/multicloud/viabilidad-readonly-oci.sh"""
import re, subprocess, sys
from pathlib import Path

path = Path(sys.argv[1])
text = path.read_text()
code = [l for l in text.splitlines() if l.strip() and not l.lstrip().startswith("#")]
fails = []

print(f"Archivo: {path}  ·  {len(code)} líneas de código")
print("\n[1] Llamadas a la CLI de OCI (servicio recurso acción):")
calls = []
for l in code:
    m = re.search(r'(?:^|[\s=($])(?:run|rawall|raw)\s+([a-z-]+)\s+([a-z-]+)\s+([a-z-]+)', l)
    if m and not l.lstrip().startswith(("run()", "raw()", "rawall()", "run ()", "raw ()")):
        calls.append(m.groups())
for s, r, a in calls:
    ok = a in ("list", "get")
    print(f"   {'OK ' if ok else 'MAL'} oci {s} {r} {a}")
    if not ok:
        fails.append(f"acción no consultiva: {s} {r} {a}")
direct = [l.strip() for l in code if re.search(r'(^|[;&|(]|\s)oci\s', l) and not re.search(r'(run|raw|rawall)\(\)', l) and not l.strip().startswith(("command -v", "stop()", "echo"))]
print("   (llamadas directas a `oci` fuera de run/raw:", len(direct), ")")
for d in direct:
    print("     ", d[:110]); fails.append("llamada directa a oci: " + d[:60])

print("\n[2] Palabras de modificación en el código (no comentarios):")
forbidden = r'\b(create|update|delete|launch|start|stop|terminate|reboot|reset|attach|detach|move|change|import|export|put|post|patch|setup|session|generate|rotate|upload|download|copy|restore|rename|bulk|remove|add|activate|cancel|capacity-report|raw-request)\b'
hits = []
for l in code:
    if l.strip().startswith(("echo", "stop()")):
        l = re.sub(r'"[^"]*"', '""', l)      # los textos de los mensajes no son comandos
    for m in re.finditer(forbidden, l):
        hits.append((m.group(1), l.strip()[:90]))
print("   ", "ninguna" if not hits else hits)
fails += [f"palabra prohibida {w}" for w, _ in hits]

print("\n[3] Instaladores, escritura de archivos y otras herramientas:")
bad_tools = r'\b(pip3?|brew|apt|yum|dnf|curl|wget|sudo|rm|mv|cp|tee|eval|chmod|chown|ssh|scp|git|terraform|aws|az|docker)\b'
bt = [(m.group(1), l.strip()[:80]) for l in code for m in re.finditer(bad_tools, l)]
print("   herramientas no permitidas:", "ninguna" if not bt else bt)
fails += [f"herramienta {t}" for t, _ in bt]
def sin_textos(l):
    return re.sub(r"'[^']*'|\"[^\"]*\"", "''", l)
redirs = [l.strip()[:80] for l in code if re.search(r'(?<![0-9&])>(?![&])', sin_textos(l)) and '/dev/null' not in l]
print("   redirecciones de salida a archivos:", "ninguna" if not redirs else redirs)
fails += ["redirección a archivo: " + r for r in redirs]
used = sorted(set(re.findall(r'\b(awk|sed|printf|command|oci|read|echo|exit|env|tail|grep|tr)\b', "\n".join(code))))
print("   programas usados:", ", ".join(used))

print("\n[4] Lectura de la configuración local:")
cfg_refs = [l.strip()[:110] for l in code if "CFG" in l]
for c in cfg_refs: print("    ", c)
print("   (solo se LEE: `-r` y `awk`; ninguna escritura)")

print("\n[5] Prueba local del filtro de salida (sin red) con datos sensibles de ejemplo:")
fn = re.search(r'mask\(\) \{\n(.*?)\n\}', text, re.S).group(1)
samples = [
    "tenancy=ocid1.tenancy.oc1..aaaaaaaabbbbbbbbccccccccddddddddeeeeeeeeffffffff",
    "fingerprint=aa:bb:cc:dd:ee:ff:00:11:22:33:44:55:66:77:88:99",
    "key_file=/Users/alguien/.oci/oci_api_key.pem",
    "-----BEGIN RSA PRIVATE KEY-----",
    "Authorization: Bearer eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.abcdefghijklmnopqrstuvwxyz0123456789",
    "pass_phrase=MiClaveSecreta123",
    "IP pública 129.151.20.33 y correo persona@example.com",
    "cadena larga: QWxhZGRpbjpvcGVuIHNlc2FtZVF3ZXJ0eXVpb3Bhc2RmZ2hqa2xaeGN2Ym5tMTIzNDU2Nzg5MA==",
    "Warning: To increase security of your API key located at /Users/alguien/.oci/mi_clave_api.",
]
script = "set -u\nmask() {\n" + fn + "\n}\nmask\n"
out = subprocess.run(["bash", "-c", script], input="\n".join(samples), capture_output=True, text=True).stdout
leaks = []
for s in samples:
    o = subprocess.run(["bash", "-c", script], input=s + "\n", capture_output=True, text=True).stdout.strip()
    print(f"   {s[:58]:<58} -> {o[:60] or '(línea eliminada)'}")
for secret in ("aaaaaaaabbbbbbbb", "aa:bb:cc", "oci_api_key.pem", "eyJhbGci", "MiClaveSecreta", "129.151.20.33", "persona@example.com", "QWxhZGRpbjpvcGVu", "/Users/alguien"):
    if secret in out:
        leaks.append(secret)
print("   líneas con 'PRIVATE KEY' eliminadas:", "PRIVATE KEY" not in out)
if leaks:
    fails.append("el filtro deja pasar: " + ", ".join(leaks))
if "PRIVATE KEY" in out:
    fails.append("el filtro deja pasar bloques de claves privadas")

print("\nRESULTADO:", "APTO: solo consultas, sin instalación ni escritura, salida filtrada" if not fails else "NO APTO: " + "; ".join(fails))
sys.exit(0 if not fails else 1)
