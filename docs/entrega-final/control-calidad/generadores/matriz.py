# -*- coding: utf-8 -*-
"""Matriz rúbrica → evidencias (XLSX + JSON para el informe). La rúbrica se lee literalmente del xlsx oficial."""
import json, os, openpyxl
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
from openpyxl.utils import get_column_letter

S = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = "~/Workspace/NexoEventos-informe-final/docs/entrega-final"
RUB = "~/Downloads/rúbrica proyecto_qod3szrctm.xlsx"
inv = json.load(open(f"{S}/build/inventario.json"))
by = {i["ruta"]: i for i in inv}
A1 = next(i["id"] for i in inv if i["descripcion"].startswith("Despliegue A1"))
NXO = next(i["id"] for i in inv if i["ruta"].endswith("pytest-nexoops.txt"))
REG = next((i["id"] for i in inv if i["ruta"].endswith("pytest-regresion.txt")), None)
def e(r): return by[r]["id"]
def x(n, f="resultado.json"): return by[f"work/evidencias/{n}/{f}"]["id"]
T1P, T2P, T3P, T4P, T5F, T5P = "T1-20261122T070851Z-9aa1", "T2-20261122T142443Z-9eec", "T3-20261122T172554Z-f812", "T4-20261122T193829Z-8374", "T5-20261123T005244Z-9eed", "T5-20261123T023342Z-0532"

ws = openpyxl.load_workbook(RUB)["Rúbrica"]
R = [dict(criterio=r[0], exc=r[1], bueno=r[3], proc=r[5], defi=r[7], peso=float(r[9])) for r in ws.iter_rows(min_row=2, values_only=True) if r[0] and r[0][0].isdigit()]
assert len(R) == 14

M = [
 dict(ev=[e("docs/evidencias/EV11/resultado-2026-10-09.md"), x(T3P), x(T5P), e("ops_center/criterios/T5.json"), e("docs/evidencias/EV10/README.md")],
      nivel="Excelente", just="Problema, actores, RF y RNF definidos con meta, estado medido y evidencia (cap. II, Tablas 4–6); restricciones de Academy/OCI/Azure explícitas; trazabilidad requisito → componente → prueba.",
      brechas="Cifras de negocio (aforo, usuarios) son supuestos del caso; RTO/RPO de failover son objetivos no medidos.", accion="Ninguna imprescindible."),
 dict(ev=[e("docs/entrega-final/diagramas/01-arquitectura-multicloud.png"), e("docs/entrega-final/diagramas/04-flujo-t6-previsto.png"), e("docs/evidencias/medicion-v2-20261022/resultado.md"), x(T5P), x(T3P)],
      nivel="Bueno – Excelente", just="Arquitectura modular con roles separados por nube, decisiones justificadas con alternativas (Tabla 8), dos modos de operación medidos, escalable (ASG) y alineada al negocio (aperturas de venta).",
      brechas="El componente de failover (compuerta, sello, standby) es DISEÑO en nube; región única en AWS.", accion="Exponer la Figura 1 indicando qué está probado."),
 dict(ev=[e("infra/aws/network.tf"), e("infra/aws-v2/network.tf"), e("infra/oci/modules/network/main.tf"), e("docs/evidencias/capturas/aws/05-web-sg-entrada.png"), e("docs/evidencias/multicloud/aws/20261028-auditoria-solo-lectura/red-y-cloudtrail.json"), e("docs/evidencias/multicloud/azure/20261028-vm/nsg-reglas.txt"), x(T3P)],
      nivel="Bueno (alto)", just="CIDR por nube (10.20/10.30/10.40), subredes públicas y privadas, rutas sin salida para datos, IGW/Service Gateway, SG→SG, NSG /32; en T3 solo 443 alcanzable.",
      brechas="Sin red privada entre nubes (solo HTTPS 443); EC2 de V2 en subred pública con IPv4 y sin NAT (decisión de costo, riesgo declarado).", accion="Defender la decisión de costo."),
 dict(ev=[e("docs/evidencias/capturas/aws/A3-RDS-MultiAZ-Cifrado.png"), e("docs/evidencias/capturas/aws/01-rds-config.png"), e("docs/evidencias/EV06/README.md"), x(T3P), e("docs/evidencias/capturas/oci/OCI-01-Bucket-Seguridad.png"), x(T5P)],
      nivel="Excelente", just="EC2/ASG, RDS Multi-AZ cifrada con verify-full, S3 y Object Storage seleccionados por función e integrados: la app opera sobre RDS y sobre PostgreSQL restaurado en OCI (T3 23/23).",
      brechas="La forma Micro de OCI requirió tres intentos (dnf, OOM, kdump); protección contra borrado de RDS desactivada.", accion="Ninguna."),
 dict(ev=[e("docs/evidencias/multicloud/aws/20261028-auditoria-solo-lectura/resultado.md"), e("docs/evidencias/multicloud/oci/20261023-iam-carga/resultado.md"), e("docs/evidencias/multicloud/azure/20261028-vm/identidad-administrada.txt"), e("backend/app/failover/tlsctx.py"), x(T1P), x(T4P), e("docs/evidencias/capturas/aws/A9-CloudTrail-Sin-Trails.png"), e("docs/evidencias/capturas/aws/A13-IAM-LabRole-Politicas.png")],
      nivel="Bueno (alto)", just="Mínimo privilegio en OCI, Azure y PostgreSQL; SG/NSG restrictivos; cifrado en reposo y tránsito; respaldo CMS con clave independiente; pruebas negativas reales (PAR 401, panel 401/403, DNS rechazado).",
      brechas="LabRole de Academy amplio e inmodificable; sin trail de CloudTrail; sin MFA en la app; NexoOps (OTP) solo LOCAL.", accion="Regenerar el token de DuckDNS y revocar temporales (T8)."),
 dict(ev=[x(T5F), e("docs/evidencias/T5-20261123-intento2-abortado.md"), x(T5P), e("docs/evidencias/escalado-v2-20261022/resultado.md"), e("docs/evidencias/multicloud/aws/20261023-rds-multiaz/failover/resultado.md"), e("docs/evidencias/capturas/aws/06-asg-escalabilidad.png")],
      nivel="Excelente (con límites)", just="ALB + ASG en 2 zonas + RDS Multi-AZ implementados y probados: detección 9,6 s, recuperación 125 s, 99,49 %; escalado 2→3→2; failover RDS ≈ 14 s.",
      brechas="PASS de una sola ejecución; parada controlada, no caída abrupta; tráfico de solo lectura; con 2 instancias FAIL 95,21 %.", accion="No repetir sin presupuesto."),
 dict(ev=[x(T4P), x(T5P, "capturas/azure.json"), e("docs/evidencias/capturas/azure/B3-Azure-Alerta-CPU-Activacion.png"), e("docs/evidencias/20261105-azure-ventana2/grafana-azure-vm-historico-20261104.png"), e("docs/evidencias/20261104-fase-d-notificacion-v2/correos-alarm-ok.png"), e("docs/evidencias/multicloud/aws/20261028-cloudwatch/resultado.md")],
      nivel="Excelente", just="Métricas (CloudWatch, Azure Monitor, Zabbix), dashboard (Grafana), logs (CloudWatch Logs, Log Analytics) y alarmas con notificación demostradas (T4 alerta Fired + correo; T5 sonda de 5 s capturó el incidente).",
      brechas="Cabecera del correo no verificada; NexoOps no desplegado (A1 incompleto).", accion="Completar A1 con capturas fechadas."),
 dict(ev=[e("infra/aws-v2/alb.tf"), e("infra/oci/modules/recovery/main.tf"), e("infra/azure/main.tf"), e("backend/tests/test_v2_plan_review.py"), x(T3P), e("docs/evidencias/EV09/README.md")],
      nivel="Bueno – Excelente", just="5 módulos raíz Terraform organizados por nube y por módulo; planes revisados por escenario; T3 apply 11 / destroy 11 con inventario idéntico; CI con validación.",
      brechas="Estado de aws-v2 desfasado por la eliminación del ALB por API (documentado); RDS fuera del estado de aws-v2; software de VM por scripts.", accion="Ninguna."),
 dict(ev=[x(T3P), e("docs/evidencias/EV07/resultado-restauracion-2026-10-10.md"), e("docs/evidencias/multicloud/oci/20261023-recuperacion-aplicacion/resultado.md"), e("docs/evidencias/20261122-copia-externa-respaldo/resultado.md"), e("docs/evidencias/T6-20261123-estado-local.md"), e("ops_center/criterios/T6.json")],
      nivel="Bueno (Excelente en la recuperación)", just="Estrategia documentada (Tabla 20) y recuperación probada con éxito: PITR (RPO 3 min 32 s), reconstrucción en OCI (649 s, 23/23) y copias externas verificadas.",
      brechas="RTO/RPO del failover NO medidos (T6 BLOCKED); respaldo lógico no programado; con el respaldo actual el RPO del failover fallaría.", accion="Respaldo fresco y T6 con autorización."),
 dict(ev=[x(T1P), x(T2P), x(T3P), x(T4P), e("docs/evidencias/T6-BLOQUEOS-OBLIGATORIOS.md"), e("docs/evidencias/T6-local/g5-exhaustivo-len5.txt")],
      nivel="Bueno", just="Integración real, segura y demostrable por piezas: lease/CAS en OCI (T1), DNS (T2), reconstrucción en OCI desde respaldo de AWS (T3), observación de AWS desde Azure (T4/T5).",
      brechas="El failover AWS→OCI (T6) no se ejecutó: barreras D1–D8 y B-T6-1 abiertas en nube; sin red privada entre nubes.", accion="Ejecutar T6 solo con autorización y barreras cerradas."),
 dict(ev=[x(T5P, "capturas/costos.json"), x(T5F, "capturas/costos.json"), e("docs/evidencias/T4-20261122-resultado.md"), e("docs/entrega-final/06-COSTOS.md")],
      nivel="Bueno – Excelente", just="Costos por ventana, dimensionamiento (2 vs 6 instancias), análisis (×2 costo para pasar de 95 % a 99 %) y propuestas concretas (escalado programado, Spot, Graviton).",
      brechas="Todo es ESTIMADO: sin Cost Explorer ni Cost Management observados.", accion="Capturas de saldo de Academy y Cost Management."),
 dict(ev=[x(T1P), x(T2P), x(T3P), x(T4P), x(T5P)] + ([REG] if REG else []) + [NXO, e("docs/evidencias/T6-local/regresion-final.txt")],
      nivel="Excelente", just="Pruebas funcionales (T3 23/23), conectividad (T2, T3 puertos), seguridad (negativas T1/T2/T4), HA (T5), monitoreo (T4) y recuperación (T3) con criterios previos, expedientes y FAIL conservados; regresión local 343 + 704 + 68.",
      brechas="T6 (failover) sin ejecución; T7 sin despliegue en nube.", accion="Ninguna."),
 dict(ev=[e("docs/entrega-final/02-INFORME-TECNICO-FINAL.md"), e("docs/entrega-final/diagramas/02-red-por-proveedor.png")],
      nivel="Excelente (sujeto a la revisión de calidad)", just=f"Informe completo con índices automáticos, diagramas legibles, {len(inv)} evidencias inventariadas con ruta, fecha UTC, tipo, resultado y SHA-256; anexos y ZIP verificados.",
      brechas="Los expedientes completos de work/evidencias no están versionados (custodia externa con manifiesto); código de estudiante ausente en la portada.", accion="Revisión final de la autora."),
 dict(ev=[e("docs/entrega-final/08-INDICE-EVIDENCIAS.md")],
      nivel="No evaluable en el documento", just="Depende de la exposición; existen guion (09-GUION-EXPOSICION.md), demo local (10-DEMO.md) y presentación de 22 diapositivas.",
      brechas="Ensayo no evidenciado.", accion="Ensayar 15 min y la demo local."),
]
assert len(M) == 14
out = []
for i, (r, m) in enumerate(zip(R, M)):
    out.append(dict(n=i + 1, criterio=r["criterio"], exc=r["exc"], bueno=r["bueno"], proc=r["proc"], defi=r["defi"], peso=r["peso"],
                    evid=m["ev"], evid_cortas=", ".join(m["ev"]), nivel=m["nivel"], just=m["just"], brechas=m["brechas"], accion=m["accion"],
                    todas=", ".join(sorted({it["id"] for it in inv if str(i + 1) in [c.strip() for c in it["criterios"].split(",")]}))))
json.dump(out, open(f"{S}/build/matriz.json", "w"), ensure_ascii=False, indent=1)

wb = openpyxl.Workbook()
thin = Side(style="thin", color="BBBBBB"); B = Border(left=thin, right=thin, top=thin, bottom=thin)
H = PatternFill("solid", fgColor="0D3B66"); HF = Font(bold=True, color="FFFFFF")
ws = wb.active; ws.title = "Matriz"
ws.append(["NexoEventos — Matriz rúbrica → evidencias (corte 23-nov-2026 UTC). Rúbrica: «rúbrica proyecto_qod3szrctm.xlsx», hoja «Rúbrica» (transcripción literal). «Nivel defendible» = lectura de la evidencia; NO es una nota y no se suma un total."])
ws.merge_cells("A1:M1"); ws["A1"].font = Font(bold=True); ws["A1"].alignment = Alignment(wrap_text=True); ws.row_dimensions[1].height = 32
hdr = ["#", "Criterio (literal)", "Puntaje máx.", "Excelente (literal)", "Bueno (literal)", "En proceso (literal)", "Deficiente (literal)",
       "Evidencia principal (IDs)", "Nivel defendible", "Justificación", "Brechas declaradas", "Acción pendiente", "Todas las evidencias vinculadas (IDs del inventario)"]
ws.append(hdr)
for c in ws[2]: c.fill = H; c.font = HF; c.alignment = Alignment(wrap_text=True, vertical="center"); c.border = B
for o in out:
    ws.append([o["n"], o["criterio"], o["peso"], o["exc"], o["bueno"], o["proc"], o["defi"], o["evid_cortas"], o["nivel"], o["just"], o["brechas"], o["accion"], o["todas"]])
ws.append(["", "Suma de puntajes de la rúbrica (la hoja oficial declara TOTAL 20; la suma real es 18,5: inconsistencia de la fuente)", "=SUM(C3:C16)", "", "", "", "", "", "", "", "", "", ""])
widths = [4, 26, 8, 30, 22, 22, 22, 30, 16, 45, 40, 26, 60]
for j, w in enumerate(widths): ws.column_dimensions[get_column_letter(j + 1)].width = w
fills = {"Excelente": "D7EED9", "Bueno": "E3ECF7", "No evaluable": "EEEEEE"}
for row in ws.iter_rows(min_row=3, max_row=17):
    for c in row:
        c.alignment = Alignment(wrap_text=True, vertical="top"); c.border = B
    lv = row[8].value or ""
    for k, v in fills.items():
        if lv.startswith(k): row[8].fill = PatternFill("solid", fgColor=v)
ws["B17"].font = Font(bold=True); ws["C17"].font = Font(bold=True)
ws.freeze_panes = "C3"
ws2 = wb.create_sheet("Rúbrica oficial (literal)")
src = openpyxl.load_workbook(RUB)["Rúbrica"]
for r in src.iter_rows(values_only=True): ws2.append(list(r))
for j, w in enumerate([34, 30, 2, 26, 2, 24, 2, 26, 2, 10]): ws2.column_dimensions[get_column_letter(j + 1)].width = w
for row in ws2.iter_rows():
    for c in row: c.alignment = Alignment(wrap_text=True, vertical="top")
for c in ws2[1]: c.font = Font(bold=True)
ws3 = wb.create_sheet("Leyenda")
for r in [["Campo", "Significado"], ["Nivel defendible", "Nivel de la rúbrica que la evidencia permite sostener; NO es una nota."],
          ["Evidencia principal", "IDs EV-Tn-NNN del INVENTARIO-MAESTRO-EVIDENCIAS.xlsx (ruta, fecha UTC, SHA-256)."],
          ["Todas las evidencias vinculadas", "Todas las entradas del inventario cuyo campo «criterios» incluye el número del criterio."],
          ["Fuente de la rúbrica", "~/Downloads/rúbrica proyecto_qod3szrctm.xlsx (y copias (1) y (2), idénticas: SHA-256 945dec8dfeae387b35a49cae0cba6cde4c81be24f741db8989e52daac78d7bae)."]]:
    ws3.append(r)
ws3.column_dimensions["A"].width = 30; ws3.column_dimensions["B"].width = 110
wb.save(f"{OUT}/MATRIZ-RUBRICA-EVIDENCIAS.xlsx")
print("matriz ok", sum(o["peso"] for o in out))
