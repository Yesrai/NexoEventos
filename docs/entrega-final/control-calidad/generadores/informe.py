# -*- coding: utf-8 -*-
"""Informe académico final completo de NexoEventos (DOCX). Fuentes: evidencias originales del repositorio."""
import os, sys, json, openpyxl
sys.path.insert(0, os.path.dirname(__file__))
from docbuild import Doc, _field
from docx.shared import Pt, Cm, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH

S = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = "~/Workspace/NexoEventos"
OUTD = "~/Workspace/NexoEventos-informe-final/docs/entrega-final"
RUB = "~/Downloads/rúbrica proyecto_qod3szrctm.xlsx"
G = OUTD + "/graficos-informe/"
DG = REPO + "/docs/entrega-final/diagramas/"
CAP = REPO + "/docs/evidencias/capturas/"

D = Doc(f"{S}/build/inventario.json")
E = D.ev
INV = D.inv
A1 = next(i["id"] for i in INV if i["descripcion"].startswith("Despliegue A1"))
REG = next((i for i in INV if i["ruta"].endswith("control-calidad/pytest-regresion.txt")), None)
NXO = next(i["id"] for i in INV if i["ruta"].endswith("control-calidad/pytest-nexoops.txt"))

def X(name, f="resultado.json"):
    return E(f"work/evidencias/{name}/{f}")
T1F, T1P = "T1-20261122T070354Z-f59a", "T1-20261122T070851Z-9aa1"
T2F, T2P = "T2-20261122T141351Z-84bb", "T2-20261122T142443Z-9eec"
T3D, T3A, T3B, T3P = "T3-20261122T154757Z-ccfe", "T3-20261122T154813Z-c535", "T3-20261122T163943Z-589d", "T3-20261122T172554Z-f812"
T4P = "T4-20261122T193829Z-8374"
T5F, T5P = "T5-20261123T005244Z-9eed", "T5-20261123T023342Z-0532"

rub = openpyxl.load_workbook(RUB)["Rúbrica"]
RUBRICA = []
for r in rub.iter_rows(min_row=2, values_only=True):
    if r[0] and r[0][0].isdigit():
        RUBRICA.append(dict(criterio=r[0], exc=r[1], bueno=r[3], proc=r[5], defi=r[7], peso=float(r[9])))
assert len(RUBRICA) == 14
SUMA = sum(x["peso"] for x in RUBRICA)  # 18,5 aunque la hoja declara TOTAL 20

# =====================================================================================
# PORTADA
d = D.d
for txt, sz, b in [("UNIVERSIDAD PERUANA UNIÓN", 16, True), ("Facultad de Ingeniería y Arquitectura", 12, False), ("Escuela Profesional de Ingeniería de Sistemas", 12, False)]:
    p = d.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER; r = p.add_run(txt); r.font.size = Pt(sz); r.bold = b
d.add_paragraph(); d.add_paragraph()
p = d.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER; r = p.add_run("NexoEventos"); r.font.size = Pt(30); r.bold = True; r.font.color.rgb = RGBColor(0x0D, 0x3B, 0x66)
p = d.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER; r = p.add_run("Informe académico final con evidencias"); r.font.size = Pt(16); r.bold = True
p = d.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER
r = p.add_run("Plataforma de reservas de eventos con entradas QR sobre una arquitectura multicloud:\nAWS (producción) · OCI (recuperación y lease) · Azure (observabilidad)"); r.font.size = Pt(11.5)
d.add_paragraph(); d.add_paragraph()
D.table(["Campo", "Dato"], [
    ["Curso", "Cloud Computing — Proyecto integrador"],
    ["Integrante", "Yesenia Ramirez Medina (proyecto individual)"],
    ["Código de estudiante", "[completar: no consta en el repositorio]"],
    ["Docente", "Fernando Asín"],
    ["Fecha de corte de la evidencia", "23 de noviembre de 2026, 04:50 UTC"],
    ["Rama y commit de origen", "`cierre-t6-t8` @ `5e1fed1`; T7 en `codex/t7-t8` @ `310279c` (sin merge); informe en la rama `informe-final-completo`"],
    ["Rúbrica aplicada", "«rúbrica proyecto_qod3szrctm.xlsx», hoja «Rúbrica»: 14 criterios; la hoja declara TOTAL 20, pero sus puntajes suman 18,5 (ver cap. XIV)"],
    ["Estado del documento", "Versión final para revisión de la autora; no contiene autoasignación de nota"],
], widths=[4, 11], size=9.5, first_bold=True)
p = d.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER
r = p.add_run("Lima, Perú — noviembre de 2026"); r.font.size = Pt(11)
p = d.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER
r = p.add_run("Fuente de los datos de portada: portada del Entregable 2 (outputs/entregable2-final/…CORREGIDO_v2.docx) y registro git del repositorio."); r.font.size = Pt(7.5); r.italic = True
D.header_footer("NexoEventos · Informe académico final con evidencias · corte 23-nov-2026 (UTC)")

# HOJA DE CONTROL
D.page_break()
p = d.add_paragraph(); r = p.add_run("Convenciones y control del documento"); r.bold = True; r.font.size = Pt(14); r.font.color.rgb = RGBColor(0x0D, 0x3B, 0x66)
D.pj(f"Este informe se construyó **directamente desde las evidencias originales** del repositorio (expedientes con manifiesto SHA-256, resultados, capturas redactadas, criterios escritos antes de ejecutar, código de infraestructura y salidas de prueba), no desde resúmenes previos. Cada afirmación técnica relevante cita uno o más **identificadores de evidencia** con el formato `EV-Tn-NNN`, definidos en `INVENTARIO-MAESTRO-EVIDENCIAS.xlsx` ({len(INV)} entradas con ruta exacta, fecha UTC, tipo, resultado, SHA-256 y limitación).")
D.table(["Rótulo", "Significado"], [
    ["**REAL**", "Ejecutado en la nube real (AWS, OCI, Azure o DuckDNS) con expediente o captura de consola."],
    ["**LOCAL**", "Probado en el equipo de desarrollo, sin nube (pytest, Docker, servidores locales)."],
    ["**DISEÑO**", "Documentado o codificado, pero no ejecutado en la nube."],
    ["**ESTIMADO**", "Cálculo con tarifas públicas o supuestos; no es una medición ni una factura."],
    ["**PASS / FAIL**", "Veredicto del recolector frente a criterios escritos antes de ejecutar."],
    ["**BLOCKED**", "No se pudo ejecutar por una barrera técnica o de autorización declarada."],
    ["**NOT_TESTED**", "No ejecutado; no se infiere ningún resultado."],
    ["**Directa / indirecta**", "Directa: datos crudos, captura o código. Indirecta: solo existe un resumen o un estado informado sin expediente."],
], widths=[3, 12], caption="Convenciones de rotulado de evidencias y estados", source="Fuente: elaboración propia; reglas de `docs/entrega-final/README.md` y `docs/evidencias/REGISTRO-CIERRE-T6-T8.md`.")
D.pj("**Advertencias que rigen todo el documento.** (1) T6 —el failover real AWS→OCI— **no se ejecutó**: no existen RTO ni RPO de failover medidos y no se suman tiempos de piezas para simularlos. (2) T7 (portal NexoOps) está **probado en local**; su despliegue en la VM de Azure (autorización A1) estaba **en curso e incompleto** al cierre de este informe. (3) El 99,49 % de T5 proviene de **una sola ejecución**. (4) Todos los costos son **estimaciones**. (5) No se reproducen secretos, tokens, URL de PAR, IP privadas, OCID ni identificadores de cuenta.")

# ÍNDICES
D.page_break(); D.toc("Índice de contenido", 'TOC \\o "1-2" \\h \\z \\u')
D.page_break(); D.toc("Índice de tablas", 'TOC \\h \\z \\c "Tabla"')
D.toc("Índice de figuras", 'TOC \\h \\z \\c "Figura"')
D.page_break(); D.toc("Índice de evidencias citadas en recuadros", 'TOC \\h \\z \\c "Evidencia"')

# RESUMEN EJECUTIVO
D.h("Resumen ejecutivo", 1)
D.pj("NexoEventos es una plataforma de reservas de eventos con entradas QR (React + FastAPI + PostgreSQL). Partió de una arquitectura V1 en AWS con una sola instancia y una base Single-AZ, y evolucionó hacia una arquitectura multicloud con **roles separados**: AWS sirve la aplicación (ALB + Auto Scaling + RDS PostgreSQL Multi-AZ), OCI conserva los respaldos cifrados, aloja el *lease* de escritor único y reconstruye la aplicación, y Azure observa desde fuera de AWS (Zabbix, Grafana, Azure Monitor, recolector de sondas, testigo y centro de operaciones).")
D.pj("Entre el 22 y el 23 de noviembre de 2026 se ejecutó en nube real una batería obligatoria (T1–T5), con criterios escritos **antes** de cada ejecución y expedientes con manifiesto SHA-256. Se conservaron todos los intentos fallidos con su causa raíz y su corrección. La Tabla 2 resume el estado final, verificado contra los `resultado.json` originales.")
EXP = json.load(open(f"{S}/build/expedientes.json"))
D.table(["Etapa", "Objetivo", "Resultado final", "Historial conservado", "Evidencia"], [
    ["T1", "Lease y CAS atómico por PAR en OCI Object Storage", "PASS 12/12 [REAL]", "1 FAIL (NameError en el probe)", f"{X(T1F)}, {X(T1P)}"],
    ["T2", "Cambio y reversión de DNS de pruebas (DuckDNS)", "PASS 13/13 [REAL]", "1 FAIL (almacén de CA ausente)", f"{X(T2F)}, {X(T2P)}"],
    ["T3", "Reconstrucción de PostgreSQL y de la aplicación en OCI", "PASS 19/19 [REAL]", "2 FAIL (dnf sin límites; OOM de dnf-makecache)", f"{X(T3A)}, {X(T3B)}, {X(T3P)}"],
    ["T4", "Centro de operaciones y alertas en Azure", "PASS 18/18 [REAL]", "incidentes resueltos dentro de la ventana", X(T4P)],
    ["T5", "Alta disponibilidad AWS (caída de 1 EC2)", "PASS 9/9 [REAL] con 6 EC2", "1 FAIL (95,21 % con 2 EC2) y 1 aborto por SCP", f"{X(T5F)}, {X(T5P)}"],
    ["T6", "Failover real AWS→OCI", "BLOCKED", "barreras D1–D8 y B-T6-1 abiertas en nube; PASS solo local", E("docs/evidencias/T6-20261123-estado-local.md")],
    ["T7", "Portal NexoOps", "PASS local; despliegue Azure NO completado", "A1 en curso: conflicto de puerto 8760 y permisos detectados", f"{NXO}, {A1}"],
    ["T8", "Cierre y entrega académica", "Documentación (este paquete); limpieza cloud NOT_TESTED", "—", E("ops_center/criterios/T8.json")],
], widths=[1.1, 4.5, 3.2, 4.2, 3.2], caption="Estado final de la batería T1–T8", source="Fuente: `work/evidencias/T*/resultado.json` (veredictos), `docs/evidencias/T6-20261123-estado-local.md`, nota de estado de A1 (23-nov 04:44Z).", color_col=2)
D.pj("**Cifras clave verificadas en los datos crudos.** T5 (intento 3): 396 sondeos `/healthz` con 2 fallos → **99,49 %**; sobre todo el tráfico 816/824 → **99,03 %**; detección **9,6 s**; capacidad completa (6 destinos sanos) a **125,0 s**; costo de la ventana ≈ **USD 0,29** estimado. T3: reconstrucción en OCI en **649 s** con 136 reservas y 136 entradas íntegras. T1: 20/20 rondas CAS y 20/20 rondas de adquisición del lease con p95 de PUT 0,414 s. T2: propagación DNS de 62,1 s y 62,0 s. Costo estimado total de las ventanas T1–T5, incluidos los intentos fallidos: **≈ USD 0,95** (no es factura).")
D.pj("**Lo que no se afirma.** No hubo failover AWS→OCI; el RTO y el RPO del failover **no se midieron**; NexoOps **no** quedó desplegado en Azure; el PASS de T5 no es un SLA; la caída abrupta de una instancia y el tráfico de escritura durante la sustitución no se probaron. Frente a la rúbrica, el informe sostiene un nivel **Excelente o Bueno** en los criterios 1–13 según la evidencia, con las brechas declaradas en el capítulo XIV; **no se atribuye 20/20**.")

# =====================================================================================
D.h("I. Introducción", 1)
D.h("1.1 Contexto", 2)
D.pj("El caso de estudio sitúa la aplicación de una empresa de venta de entradas y su base PostgreSQL en un único servidor de la sede de Lima. Un incidente en esa ubicación interrumpe reservas y validaciones de acceso; los picos de apertura de venta compiten por CPU, memoria y conexiones; los cambios manuales no son reproducibles y las copias guardadas en el mismo lugar no protegen frente a la pérdida del sitio. El proyecto NexoEventos responde a ese problema llevando la solución a nube pública con infraestructura como código, segmentación de red, mínimo privilegio, respaldos cifrados fuera del proveedor principal y una evolución verificable hacia alta disponibilidad, recuperación entre nubes y observabilidad externa.")
D.h("1.2 Objetivos", 2)
D.bullets([
    "**General:** diseñar, implementar y validar con evidencias una arquitectura cloud segura, disponible y recuperable para NexoEventos, usando AWS, OCI y Azure con funciones complementarias.",
    "Eliminar los puntos únicos de falla de la V1 (instancia única y base Single-AZ) y medir la tolerancia a fallos.",
    "Proteger los datos con cifrado en reposo y en tránsito, respaldos cifrados con clave independiente y copia fuera de AWS.",
    "Demostrar la reconstrucción completa de la aplicación en otra nube (OCI) a partir del respaldo.",
    "Observar AWS desde fuera de AWS (Azure) con métricas, paneles, registros y alertas que lleguen a una persona.",
    "Ejecutar una batería de pruebas con criterios previos, conservando los fallos y sus correcciones.",
    "Documentar costos, límites y pendientes sin presentar diseño o estimación como resultado.",
])
D.h("1.3 Alcance y método de evidencia", 2)
D.pj("El alcance abarca la aplicación, su infraestructura en tres nubes y la batería de pruebas T1–T8. El método se apoya en cuatro reglas: (1) **criterio antes que ejecución**: cada prueba tiene un archivo `ops_center/criterios/Tn.json` con umbrales escritos antes de ejecutarla; (2) **expediente inmutable**: cada ejecución genera `meta.json`, `events.jsonl`, `resultado.json`, `resultado.md`, capturas de datos y un `MANIFIESTO.sha256`; (3) **un FAIL no se reescribe**: se conserva, se analiza la causa raíz, se corrige con una prueba de regresión y se vuelve a ejecutar solo con una nueva autorización; (4) **autorización explícita por ventana** con costo máximo, reversión y limpieza verificada.")
D.evbox(f"{X(T5P, 'MANIFIESTO.sha256')}, {X(T3P, 'MANIFIESTO.sha256')}", "Integridad de los expedientes",
        "Los 11 expedientes de `work/evidencias/` se verificaron para este informe con `shasum -a 256 -c MANIFIESTO.sha256`: **0 discrepancias** en los 11. Los expedientes no están versionados en git (la carpeta `work/` está en `.gitignore`); su integridad se acredita por el manifiesto y por el SHA-256 de cada archivo registrado en el inventario maestro.")
D.h("1.4 Fuentes y estructura del informe", 2)
D.table(["Fuente", "Contenido", "Uso en el informe"], [
    ["`work/evidencias/T*-*/` (11 expedientes)", "Datos crudos de T1–T5, incluidos 6 expedientes FAIL", "Cifras, veredictos y gráficos"],
    ["`docs/evidencias/T*-resultado.md`, tarjetas y autorizaciones", "Informes por intento, causas raíz, correcciones", "Narrativa de pruebas"],
    ["`docs/evidencias/capturas/` (41 PNG) y recortes", "Capturas auténticas de consola, redactadas", "Figuras de configuración"],
    ["`docs/evidencias/EV01–EV11`, `multicloud/`, carpetas fechadas", "Evidencia histórica oct–nov 2026", "Antecedentes V1/V2"],
    ["`ops_center/criterios/T1–T8.json`", "Criterios previos", "Trazabilidad de umbrales"],
    ["`infra/aws`, `aws-v2`, `aws-recovery`, `oci`, `azure`", "Terraform", "Capítulos de redes, IaC y nubes"],
    ["`../NexoEventos-codex-t7-t8` (rama `codex/t7-t8`)", "NexoOps (T7) y documentos T7/T8", "Capítulo X (solo lectura)"],
    ["`docs/entrega-final/` (commit 5e1fed1)", "Paquete T8 previo y diagramas", "Diagramas de elaboración propia"],
], widths=[5, 5, 4], caption="Fuentes primarias utilizadas", source="Fuente: inventario maestro de evidencias (este paquete).")
D.pj("El documento sigue el orden solicitado: requisitos (II), arquitectura (III), cada nube (IV–VI), seguridad (VII), alta disponibilidad (VIII), respaldo y recuperación (IX), monitoreo y NexoOps (X), IaC (XI), pruebas T1–T8 (XII), costos (XIII), matriz de rúbrica (XIV) y conclusiones (XV). El documento `NexoEventos_Anexos_Evidencias.pdf` reproduce las capturas, los resúmenes de expediente y los criterios completos.")

# =====================================================================================
D.h("II. Análisis del problema y requisitos", 1)
D.h("2.1 Problema y actores", 2)
D.pj("El problema central es la **continuidad** de un servicio transaccional con picos de demanda: un único servidor concentra cómputo y datos (punto único de falla), no escala ante aperturas masivas y no tiene una copia fuera del sitio. La integridad es crítica: una sobreventa o una entrada duplicada es un fallo de negocio, no solo técnico. Los actores son el **cliente** (compra y presenta su QR), el **organizador** (publica eventos y aforos) y el **operador** (valida entradas en puerta en los eventos que tiene asignados). En el plano operativo intervienen la **propietaria/operadora cloud** y, en T7, el rol `SUPER_ADMIN_TI` del portal NexoOps.")
D.h("2.2 Requisitos funcionales", 2)
D.table(["ID", "Requisito funcional", "Evidencia de cumplimiento"], [
    ["RF-01", "Catálogo público de eventos con detalle, recintos y planos (estadio, auditorio, museo, concierto)", f"{E('docs/evidencias/EV05/public-home-2026-10-03.png')}, {E('docs/evidencias/EV10/EV10-sitio-actualizado-2026-10-07-desktop.png')}"],
    ["RF-02", "Registro e inicio de sesión de clientes con cookie de sesión segura", f"{E('docs/evidencias/EV10/README.md')}; T3 fase B (login con cookie Secure+HttpOnly) {X(T3P)}"],
    ["RF-03", "Reserva con control de aforo por zona/asiento e idempotencia", f"T3 fase B: reserva 201, repetición idempotente, 409 sin cupo, 422 inválida {X(T3P)}"],
    ["RF-04", "Emisión de entradas con QR cifrado y consulta «mis reservas»", f"T3 fase B: «mis reservas» + QR {X(T3P)}; {E('docs/evidencias/EV10/README.md')}"],
    ["RF-05", "Validación en puerta por operador asignado; segundo uso rechazado", f"{E('docs/evidencias/EV10/README.md')}; T3: QR nuevo aceptado → 409 al repetir {X(T3P)}"],
    ["RF-06", "Roles cliente / organizador / operador con segregación", f"{E('docs/evidencias/EV10/README.md')} (registro público limitado a cliente)"],
], widths=[1.3, 7.2, 6.5], caption="Requisitos funcionales y su evidencia", source="Fuente: `docs/entregable2/informe-entregable2.md` §02 y §07; evidencias citadas.")
D.h("2.3 Requisitos no funcionales", 2)
D.table(["ID", "Requisito no funcional", "Meta", "Estado medido", "Evidencia"], [
    ["RNF-01", "Integridad: sin sobreventa ni reserva duplicada", "0 sobreventas", "PASS: 132 reservas = 132 claves de idempotencia = 132 entradas (carga E01); 4 reservas concurrentes en OCI, cupos 178→173", f"{E('docs/evidencias/EV11/resultado-2026-10-09.md')}, {X(T3P)}"],
    ["RNF-02", "Disponibilidad ante caída de una instancia web", "≥ 99 % durante el experimento", "PASS con 6 EC2 (99,49 %); FAIL con 2 EC2 (95,21 %)", f"{X(T5P)}, {X(T5F)}"],
    ["RNF-03", "Detección y sustitución automática de instancias", "detección ≤ 30 s; sustitución ≤ 300 s", "9,6 s y 125,0 s (6 EC2); 24,9 s y 159,8 s (2 EC2)", f"{X(T5P)}"],
    ["RNF-04", "Rendimiento a escala de laboratorio", "p95 < 2 s; errores < 1 %", "p95 421,2 ms, 0 % errores inesperados (20 VU × 300 s)", E("docs/evidencias/EV11/resultado-2026-10-09.md")],
    ["RNF-05", "Confidencialidad: cifrado en reposo y tránsito", "100 % de almacenes cifrados; TLS", "RDS/EBS/S3 cifrados; CMS AES-256; TLS 1.3/1.2; `verify-full` a RDS", f"{E('docs/evidencias/multicloud/aws/20261028-auditoria-solo-lectura/resultado.md')}, {E('docs/evidencias/20261104-fase-c-d-v2/resultado.md')}"],
    ["RNF-06", "Recuperación fuera de AWS", "reconstrucción completa en otra nube", "PASS T3: 649 s, 136/136, humo 11/11 y 23/23", X(T3P)],
    ["RNF-07", "RTO del failover AWS→OCI", "≤ 3600 s (criterio T6)", "NOT_TESTED (T6 BLOCKED)", E("ops_center/criterios/T6.json")],
    ["RNF-08", "RPO del failover", "≤ 5400 s (criterio T6)", "NOT_TESTED (T6 BLOCKED)", E("ops_center/criterios/T6.json")],
    ["RNF-09", "Observabilidad externa con alerta a una persona", "alerta y correo reales", "PASS T4 (alerta Fired 19:03:19Z y correo)", X(T4P)],
    ["RNF-10", "Costo acotado al crédito educativo", "≤ USD 1,5 por ventana", "≈ USD 0,95 en total T1–T5 (ESTIMADO)", f"{E('work/evidencias/T5-20261123T023342Z-0532/capturas/costos.json')}"],
    ["RNF-11", "Reproducibilidad", "infraestructura en Terraform", "5 módulos raíz; T3 apply/destroy 11/11 con inventario idéntico", X(T3P)],
], widths=[1.3, 3.8, 2.6, 4.6, 3.2], caption="Requisitos no funcionales, metas y estado medido", source="Fuente: criterios `ops_center/criterios/*.json` y expedientes citados.", color_col=3)
D.h("2.4 Restricciones y supuestos", 2)
D.bullets([
    "**AWS Academy Learner Lab:** credenciales temporales (sesiones de ≈ 4 h), rol `LabRole` impuesto y no modificable, sin usuarios IAM propios, sin Cost Explorer y con una política de control de servicio (SCP) que deniega ciertos parámetros (demostrado en T5: un ASG de máximo 7 se deniega; máximo 6 se permite).",
    "**OCI Always Free** y **Azure for Students**: formas pequeñas (E2.1.Micro con 945 MB de RAM) y presupuesto limitado; la VM de Azure solo se enciende en ventanas.",
    "**Crédito:** techo de USD 1,5 por ventana de prueba y operación por ventanas cortas con limpieza verificada.",
    "**Supuestos del caso** (aforo, número de usuarios, volumen) **no son mediciones**; los escalones de 100 a 5 000 usuarios del Entregable 2 son proyección lineal.",
    "**Sin red privada entre nubes:** la integración es por HTTPS 443 (Object Storage, PAR, sondas); no hay VPN ni peering.",
])
D.h("2.5 Trazabilidad requisito → componente → prueba", 2)
D.table(["Requisito", "Componente cloud", "Prueba", "Criterio de rúbrica"], [
    ["RNF-02/03", "ALB + ASG en 2 zonas (AWS)", "T5", "6"], ["RNF-05", "KMS/SSE, CMS, TLS, SG/NSG", "T1, T2, T4 (negativas)", "5"],
    ["RNF-06", "Object Storage + VM temporal (OCI)", "T3", "9, 10"], ["RNF-07/08", "lease + DNS + standby (diseño)", "T6 (BLOCKED)", "9, 10"],
    ["RNF-09", "Zabbix, Grafana, Azure Monitor (Azure)", "T4, T5", "7"], ["RNF-11", "Terraform por nube", "T3, T5 (planes revisados)", "8"],
    ["RF-01…06", "FastAPI + PostgreSQL", "EV10, EV11, T3 fase B", "4, 12"], ["RNF-10", "Ventanas y watchdog", "T4, T5 (costo)", "11"],
], widths=[3, 5.5, 3.5, 3], caption="Matriz de trazabilidad resumida", source="Fuente: elaboración propia a partir de las Tablas 4 y 5.")
D.pj("**Lectura de la trazabilidad.** Todos los requisitos funcionales tienen al menos una prueba real que los ejercita (validación pública de octubre y la fase B de T3 en OCI). Entre los no funcionales, dos quedan sin medición por depender de T6: el RTO y el RPO del failover (RNF-07 y RNF-08). Esa ausencia se arrastra a los criterios 9 y 10 de la rúbrica y se declara en cada capítulo donde aparece; ningún otro tiempo medido se usa como sustituto.")

# =====================================================================================
D.h("III. Arquitectura multicloud", 1)
D.h("3.1 Visión general y roles de cada nube", 2)
D.pj("La arquitectura final asigna a cada proveedor una función distinta para evitar duplicar herramientas y para que la falla de un proveedor no arrastre a los demás: **AWS (us-east-1) produce**, **OCI (sa-saopaulo-1) conserva y recupera**, y **Azure (centralus) observa**. La Figura 1 rotula cada componente según su grado de demostración (REAL, LOCAL, DISEÑO, PARCIAL).")
D.figure(DG + "01-arquitectura-multicloud.png", "Arquitectura multicloud final de NexoEventos con rótulos REAL/LOCAL/DISEÑO",
         f"Fuente: elaboración propia (diagrama, no captura de consola), `docs/entrega-final/diagramas/01-arquitectura-multicloud.svg`, 23-nov-2026; ID {E('docs/entrega-final/diagramas/01-arquitectura-multicloud.png')}. Explicación: las flechas verdes son integraciones probadas en nube (T1–T5); las rojas discontinuas son el failover T6, no ejecutado.", 16.2)
D.h("3.2 Evolución V1 → V2 → multicloud", 2)
D.table(["Aspecto", "V1 (E1, oct-2026)", "V2 + multicloud (final)", "Mejora y evidencia"], [
    ["Cómputo", "1 EC2 `t3.small`", "ASG 2–6 EC2 `t3.small` en 2 zonas tras ALB", f"CPU por instancia a 50 usuarios 39,4 % → ≈ 20 %; {E('docs/evidencias/medicion-v2-20261022/resultado.md')}"],
    ["Base de datos", "RDS Single-AZ", "RDS PostgreSQL Multi-AZ cifrada, `verify-full`", f"failover forzado ≈ 14 s con huella idéntica; {E('docs/evidencias/multicloud/aws/20261023-rds-multiaz/failover/resultado.md')}"],
    ["Entrada", "TLS en la EC2 (Let's Encrypt)", "ALB HTTPS TLS 1.3/1.2, 80→301", f"{E('docs/evidencias/20261104-fase-b1-acm/resultado.md')}"],
    ["Escalado", "fijo", "seguimiento de CPU 40 %; modo HA de 6", f"2→3→2 con alarma a 8 min 6 s; {E('docs/evidencias/escalado-v2-20261022/resultado.md')}"],
    ["Respaldo", "backups RDS + dump en S3", "+ CMS AES-256 con clave independiente, copia en OCI y copias externas verificadas", f"{E('docs/evidencias/multicloud/oci/20261023-transferencia-0008/resultado.md')}, {E('docs/evidencias/20261122-copia-externa-respaldo/resultado.md')}"],
    ["Recuperación", "no probada", "PITR en AWS y reconstrucción en OCI", f"R01 21 min 4 s / RPO 3 min 32 s {E('docs/evidencias/EV07/resultado-restauracion-2026-10-10.md')}; T3 649 s {X(T3P)}"],
    ["Observabilidad", "CloudWatch (misma nube)", "+ Zabbix/Grafana/Azure Monitor externos", f"T4 PASS 18/18 {X(T4P)}"],
], widths=[2.2, 3.3, 4.7, 5.3], caption="Evolución de la arquitectura y evidencia de cada mejora", source="Fuente: `docs/entregable2/informe-entregable2.md` §05 y evidencias citadas.")
D.h("3.3 Decisiones de arquitectura y su justificación", 2)
D.table(["Decisión", "Alternativa descartada", "Justificación"], [
    ["ALB + ASG de EC2", "EKS / contenedores gestionados", "EKS cuesta ≈ USD 0,10/h por clúster antes de nodos y añade permisos que Academy restringe; una aplicación única no lo justifica."],
    ["EC2 en subredes públicas con SG cerrado al ALB", "subredes privadas + NAT Gateway", "El NAT tiene costo fijo alto; el riesgo (IPv4 pública por instancia) se declara y se mitiga con SG que solo acepta 80 desde el SG del ALB."],
    ["Recuperación entre nubes por respaldo cifrado", "replicación síncrona AWS↔OCI", "Cada COMMIT esperaría el viaje a São Paulo y el vallado de Docker no es transferible a RDS; se prefirió respaldo + reconstrucción + conmutación controlada."],
    ["Lease de escritor único en OCI por PAR con CAS (If-Match)", "base de consenso externa", "Object Storage ofrece escritura condicional atómica (demostrada en T1) sin servidor adicional; la autoridad se protege con firma Ed25519 y época."],
    ["Observabilidad en Azure", "solo CloudWatch", "Si AWS cae, el observador debe seguir vivo; Azure aporta independencia de proveedor."],
    ["Dos modos de operación en AWS", "un solo dimensionamiento", "Económico (mín 2) para el día a día y alta disponibilidad (mín 6) para aperturas de venta: T5 mostró que solo el segundo alcanza 99 %."],
    ["Testigo con historial encadenado y anclaje", "testigo con archivo local", "T4 mostró que un prefijo restaurado no se detecta localmente; se diseñó y probó en local el anclaje anti-rollback (B-T6-1)."],
], widths=[4, 3.8, 7.7], caption="Decisiones de arquitectura", source="Fuente: `docs/entregable2/informe-entregable2.md` §06, `docs/entregable3/15-informe-consolidado-entregable3.md` §4, expedientes T4 y T5.")
D.h("3.4 Flujo previsto de failover (no ejecutado)", 2)
D.pj("El failover diseñado sigue la secuencia: detección por quórum de sondas → congelación de escrituras en AWS por la compuerta en modo `enforce` → respaldo final y verificación → adquisición del lease en OCI con nueva época → habilitación del standby → cambio de DNS → verificación por efecto (0 respuestas 201 desde AWS). La Figura 2 lo muestra; **ninguno de sus pasos encadenados se ejecutó en nube**. Las piezas que sí tienen evidencia real por separado son el lease (T1), el DNS (T2) y la reconstrucción (T3).")
D.figure(DG + "04-flujo-t6-previsto.png", "Flujo previsto de T6 (failover AWS→OCI) — DISEÑO, no ejecutado",
         f"Fuente: elaboración propia, `docs/entrega-final/diagramas/04-flujo-t6-previsto.svg`; ID {E('docs/entrega-final/diagramas/04-flujo-t6-previsto.png')}. Explicación: cada paso indica qué pieza tiene evidencia real independiente; el conjunto está BLOCKED.", 15.5)

# =====================================================================================
D.h("IV. Amazon Web Services (producción)", 1)
D.h("4.1 Red (VPC 10.20.0.0/16)", 2)
D.table(["Subred", "Tipo", "CIDR", "Zona", "Recursos", "Ruta por defecto"], [
    ["pública-a", "pública", "10.20.1.0/24", "us-east-1a", "EC2 V1; ALB y EC2 de V2", "0.0.0.0/0 → IGW"],
    ["pública-b", "pública", "10.20.2.0/24", "us-east-1b", "ALB y EC2 de V2", "0.0.0.0/0 → IGW"],
    ["datos-a", "privada", "10.20.21.0/24", "zona ≠ datos-b", "RDS (grupo de subredes)", "sin ruta a Internet"],
    ["datos-b", "privada", "10.20.22.0/24", "zona ≠ datos-a", "RDS (grupo de subredes)", "sin ruta a Internet"],
], widths=[2, 1.6, 2.4, 2.2, 4, 3], caption="Subredes de la VPC de AWS", source=f"Fuente: `infra/aws/network.tf` ({E('infra/aws/network.tf')}), `infra/aws-v2/network.tf` ({E('infra/aws-v2/network.tf')}); verificación por API: {E('docs/evidencias/EV03/README.md')}, {E('docs/evidencias/multicloud/aws/20261028-auditoria-solo-lectura/red-y-cloudtrail.json')}.")
D.table(["Grupo / regla", "Dir.", "Puerto", "Origen / destino", "Propósito"], [
    ["SG ALB (V2)", "entrada", "443", "0.0.0.0/0", "HTTPS público"], ["SG ALB (V2)", "entrada", "80", "0.0.0.0/0", "solo redirección 301"],
    ["SG web (V2)", "entrada", "80", "SG del ALB", "tráfico del balanceador"], ["SG web (V1)", "entrada", "80/443", "0.0.0.0/0", "sitio público; **sin SSH**"],
    ["SG web", "salida", "443", "0.0.0.0/0", "servicios AWS y paquetes"], ["SG web", "salida", "53 TCP/UDP", "CIDR de la VPC", "DNS"],
    ["SG web", "salida", "5432", "SG de la base", "PostgreSQL"], ["SG base", "entrada", "5432", "SG web", "solo la aplicación"],
], widths=[3, 1.6, 2, 3.4, 5], caption="Reglas de grupos de seguridad en AWS", source=f"Fuente: `infra/aws*/network.tf`; verificación por API 28-oct ({E('docs/evidencias/multicloud/aws/20261028-auditoria-solo-lectura/resultado.md')}) y capturas {E('docs/evidencias/capturas/aws/05-web-sg-entrada.png')}, {E('docs/evidencias/capturas/aws/04-web-sg-salida.png')}.")
D.figure(CAP + "aws/05-web-sg-entrada.png", "Consola EC2: reglas de entrada del SG web de V1 (80 y 443; sin puerto 22)",
         f"Fuente: captura auténtica de consola AWS, copia redactada (cuenta, ARN e IDs ocultos), oct-2026; ID {E('docs/evidencias/capturas/aws/05-web-sg-entrada.png')}. Explicación: confirma la superficie mínima de entrada de V1; la administración se hace por Session Manager, no por SSH. Histórica: no refleja el estado actual.", 14)
D.h("4.2 Cómputo: EC2, ALB y Auto Scaling", 2)
D.pj("La capa web usa EC2 `t3.small` con Amazon Linux 2023, Nginx y FastAPI (limitado a `127.0.0.1:8000`), IMDSv2 obligatorio y EBS cifrado. En V2 un **Application Load Balancer** con TLS 1.3/1.2 reparte el tráfico entre instancias de un **Auto Scaling Group** en dos zonas, con *health check* de tipo ELB. El ALB se elimina por API al cerrar cada ventana para ahorrar costo, por lo que el estado de Terraform queda desfasado de forma conocida y documentada (el siguiente plan lo recrea y es revisado antes de aplicarse).")
D.table(["Parámetro", "Modo económico", "Modo alta disponibilidad"], [
    ["Instancias del ASG", "mín 2 / deseada 2 / máx 3 (valores por defecto)", "mín 6 / deseada 6 / máx 6 (`academy-v2-t5c.tfvars`)"],
    ["Health check del ALB", "10 s / 5 s, umbrales 2/2", "5 s / 3 s, umbrales 2/2"],
    ["Algoritmo", "`least_outstanding_requests`", "`weighted_random` + mitigación de anomalías"],
    ["Pool de conexiones a la BD", "5 + 5 por instancia", "3 + 2 por instancia (6×5 = 30 ≤ límite de la `db.t3.micro`)"],
    ["Costo aproximado [ESTIMADO]", "≈ 0,13 USD/h", "≈ 0,26 USD/h (peor caso)"],
    ["Resultado T5", "FAIL 95,21 %", "PASS 99,49 % (1 ejecución)"],
], widths=[3.5, 5.5, 6], caption="Modos operativos de la V2 en AWS", source=f"Fuente: `docs/evidencias/T5-20261123-resultado.md` §«Modos operativos» ({E('docs/evidencias/T5-20261123-resultado.md')}); `infra/aws-v2/alb.tf` ({E('infra/aws-v2/alb.tf')}), `infra/aws-v2/compute.tf` ({E('infra/aws-v2/compute.tf')}).")
D.h("4.3 Base de datos y almacenamiento", 2)
D.pj("La base es **RDS PostgreSQL 18.3 Multi-AZ** `db.t3.micro`, 20 GiB gp2, cifrada con KMS, no pública, con copias automáticas de 7 días, `rds.force_ssl = 1` y conexión de la aplicación con `sslmode=verify-full` y CA fijada (TLS 1.3; con otra CA la conexión se rechaza). La credencial maestra está en Secrets Manager. PostgreSQL usa tres roles: `nexoeventos_owner` (sin login), `nexoeventos_migrator` y `nexoeventos_app` (sin `DELETE` sobre `users`). S3 guarda respaldos con bloqueo público total, versionado y SSE-S3.")
D.figure(CAP + "aws/A3-RDS-MultiAZ-Cifrado.png", "Consola RDS: instancia Multi-AZ con almacenamiento cifrado",
         f"Fuente: captura auténtica de consola AWS (copia redactada), 29-oct-2026; ID {E('docs/evidencias/capturas/aws/A3-RDS-MultiAZ-Cifrado.png')}. Explicación: acredita Multi-AZ y cifrado en reposo de la base de producción.", 14)
D.evbox(f"{E('docs/evidencias/multicloud/aws/20261028-auditoria-solo-lectura/resultado.md')}, {E('docs/evidencias/multicloud/aws/20261028-auditoria-solo-lectura/detalle-seguridad.json')}", "Auditoría de solo lectura de AWS (28-oct-2026)",
        "Verificado por API: RDS `StorageEncrypted=true`, no pública, Multi-AZ, copias 7 días, TLS obligatorio; EBS cifrado; IMDSv2 `required`; S3 con bloqueo público, SSE AES256 y versionado; SG web sin SSH; subredes de datos sin ruta a Internet. **Ausente (comprobado):** trail de CloudTrail, protección contra borrado de la RDS, política de bucket que exija TLS y margen de autoescalado de almacenamiento (máximo = 20 GiB asignados).")
D.h("4.4 Observabilidad nativa en AWS", 2)
D.pj("CloudWatch conserva los logs de API y Nginx (7 días), cinco alarmas de V1 con notificación SNS (probadas con estado forzado y con CPU real, correos recibidos) y las alarmas y el panel de V2, que se recrean con el ALB. Las series originales del 22-oct (40 series, resolución 60 s) confirman el escalado 0→2→3→2→0 y los dos únicos minutos con 5xx (25 y 40) que coinciden con las pruebas de tolerancia a fallos.")
D.figure(CAP + "aws/06-asg-escalabilidad.png", "CloudWatch: GroupInServiceInstances del ASG de V2 el 22-oct-2026 (0→2→3→2→0)",
         f"Fuente: captura auténtica de consola CloudWatch (Media, 1 min, 14:00–18:00 UTC), copia redactada; ID {E('docs/evidencias/capturas/aws/06-asg-escalabilidad.png')}; serie original {E('docs/evidencias/multicloud/aws/20261028-cloudwatch/series-originales.json')}. Explicación: el paso a 3 instancias lo provocó una carga de CPU controlada; no se asocia a un número de usuarios.", 14.5)
D.h("4.5 Estado final de AWS (último verificado)", 2)
D.pj(f"Tras T5 (02:33Z del 23-nov): ASG 0/0 con máximo 6, 0 EC2, sin ALB, RDS `stopped`, EC2 de V1 `stopped`; grupo de destino y plantilla de lanzamiento con la configuración de alta disponibilidad aplicada y coherente con el estado de Terraform ({X(T5P, 'capturas/limpieza.json')}). La RDS detenida se reinicia sola a los 7 días: es un riesgo de costo que debe vigilarse en el cierre (T8, NOT_TESTED).")

# =====================================================================================
D.h("V. Oracle Cloud Infrastructure (recuperación y lease)", 1)
D.h("5.1 Red e identidad", 2)
D.table(["Recurso", "Configuración", "Módulo Terraform", "Último estado verificado"], [
    ["VCN", "10.30.0.0/16", "`network`", "existe"], ["Subred privada", "10.30.1.0/24, sin IP pública, Service Gateway", "`network`", "existe"],
    ["NSG + lista de seguridad + 2 tablas de rutas", "solo lo necesario", "`network`", "existen"],
    ["Subred pública + IGW + entrada 443", "10.30.2.0/24, solo durante T3", "`public_entry`", "destruidas tras T3 (0 IGW)"],
    ["VM de recuperación + Bastion", "E2.1.Micro, OL 9.8; acceso por reenvío de puerto", "`recovery`", "destruidas tras T3 (0 instancias)"],
    ["Grupo y usuario de carga", "solo crear/leer/inspeccionar objetos de un bucket", "`iam`", "existen"],
    ["Política del lease", "PAR de alcance mínimo por prefijo", "`lease`", "0 PAR activos tras T1"],
], widths=[4, 5, 2.5, 4], caption="Inventario de OCI (sa-saopaulo-1)", source=f"Fuente: `infra/oci/modules/*` ({E('infra/oci/modules/network/main.tf')}, {E('infra/oci/modules/iam/main.tf')}); estado final de T3 ({X(T3P)}) y T1 ({X(T1P)}).")
D.h("5.2 Almacenamiento de respaldos", 2)
D.pj("El bucket `nexoeventos-recovery` es privado (`NoPublicAccess`), versionado y cifrado con clave de Oracle. Contiene los respaldos CMS AES-256 con su SHA-256. El usuario de carga no puede borrar ni sobrescribir objetos: una prueba negativa del 11-nov rechazó reintentar la subida del mismo objeto. Antes y después de T1 y T3 el inventario fue idéntico: **21 objetos / 471 979 B y 0 PAR**.")
D.figure(CAP + "oci/OCI-01-Bucket-Seguridad.png", "Consola OCI: bucket de respaldos privado",
         f"Fuente: captura auténtica de consola OCI (copia redactada: namespace/OCID ocultos), 29-oct-2026; ID {E('docs/evidencias/capturas/oci/OCI-01-Bucket-Seguridad.png')}. Explicación: acredita visibilidad privada y cifrado del bucket de recuperación.", 14)
D.figure(CAP + "oci/OCI-06-Politica-Reglas.png", "Consola OCI: reglas de la política de la identidad de carga (mínimo privilegio)",
         f"Fuente: captura auténtica de consola OCI (copia redactada), 29-oct-2026; ID {E('docs/evidencias/capturas/oci/OCI-06-Politica-Reglas.png')}. Limitación: la vista trunca la lista de permisos; la verificación completa está en {E('docs/evidencias/multicloud/oci/20261023-iam-carga/resultado.md')}.", 14)
D.h("5.3 Lease de escritor único (T1)", 2)
D.pj(f"El lease es un objeto en un prefijo dedicado al que se accede con PAR temporales. La adquisición usa `If-None-Match: *` (crear si no existe) y `If-Match: <ETag>` (CAS); el contenido está firmado con Ed25519 y lleva una **época** monótona. T1 demostró en OCI real la atomicidad bajo concurrencia y la exclusividad de la adquisición con el cliente real (detalle en §12.1). Un hallazgo medido que se documenta: el PAR permite escribir sin condición (`sobrescribe_el_lease = true`), por lo que la protección del lease recae en la firma y la época, no en el PAR ({X(T1P, 'capturas/probe-salida.json')}).")
D.h("5.4 Reconstrucción en OCI (T3)", 2)
D.pj(f"La VM temporal se crea con `terraform apply` (11 recursos), descarga el respaldo, verifica SHA-256, instala PostgreSQL 18 con límites (`safe-dnf.sh`), restaura, carga las claves de aplicación, levanta Nginx con certificado fijado y ejecuta pruebas de humo de solo lectura (fase A) y funcionales sobre una copia desechable (fase B). Luego se destruye con una guarda que exige 0 altas / 0 cambios / 11 destrucciones. El detalle de los tres intentos está en §9.4 y §12.3.")

# =====================================================================================
D.h("VI. Microsoft Azure (observabilidad)", 1)
D.h("6.1 Red, cómputo e identidad", 2)
D.table(["Recurso", "Configuración", "Evidencia"], [
    ["Grupo de recursos, VNet 10.40.0.0/16, subred 10.40.1.0/24", "`infra/azure/modules/network`", E("infra/azure/modules/network/main.tf")],
    ["NSG", "22 y 443 solo desde la IP /32 de la operadora; resto denegado; NSG de entrada idéntico antes/después de T4 (`9bdc6910…`)", f"{E('docs/evidencias/multicloud/azure/20261028-vm/nsg-reglas.txt')}, {X(T4P)}"],
    ["VM `vm-nexoeventos-obs` D2s_v4, Ubuntu 24.04, Trusted Launch", "encendida solo en ventanas; apagado automático 17:38 UTC", f"{E('infra/azure/modules/vm/main.tf')}, {E('docs/evidencias/capturas/azure/B1-Azure-VM-Desasignada.png')}"],
    ["Identidad administrada", "*Monitoring Reader* solo sobre el grupo de recursos; una escritura devuelve 403", E("docs/evidencias/multicloud/azure/20261028-vm/identidad-administrada.txt")],
    ["Log Analytics, diagnósticos, grupo de acciones, alerta métrica, web test, presupuesto", "`infra/azure/modules/monitor`, `budget`", E("infra/azure/modules/monitor/main.tf")],
], widths=[5, 6.5, 3.5], caption="Componentes de Azure (centralus)", source="Fuente: `infra/azure` y evidencias citadas.")
D.h("6.2 Pila de observación", 2)
D.pj("En la VM corren **Zabbix** (sondas HTTP a `/healthz` y `/api/events`, días restantes del certificado, CPU/memoria/disco), **Grafana** (paneles de Azure Monitor y Zabbix) y **Nginx** con HTTPS; además el **recolector de sondas** (servicio con temporizador), el **testigo** (historial encadenado por hash con firma) y el **centro de operaciones** (panel de solo lectura con roles y auditoría, sin endpoints de ejecución: `REAL_EXECUTION_WIRED=False`). La métrica personalizada de la sonda se publica con la identidad administrada y alimenta la alerta `alerta-nexo-sonda`.")
D.figure(REPO + "/docs/evidencias/20261105-azure-ventana2/grafana-azure-vm-historico-20261104.png", "Grafana «Azure — VM de monitoreo»: CPU de Azure Monitor y del agente Zabbix (rango histórico 4-nov)",
         f"Fuente: captura de Grafana en la VM de Azure (recorte sin barra del navegador), 5-nov-2026; ID {E('docs/evidencias/20261105-azure-ventana2/grafana-azure-vm-historico-20261104.png')}. Explicación: dos fuentes independientes muestran el mismo pico de CPU; son datos históricos recuperados, no en vivo.", 15)
D.figure(CAP + "azure/B3-Azure-Alerta-CPU-Activacion.png", "Azure Monitor: activación real de la alerta de CPU",
         f"Fuente: captura auténtica del portal de Azure (copia redactada), 29-oct-2026; ID {E('docs/evidencias/capturas/azure/B3-Azure-Alerta-CPU-Activacion.png')}. Explicación: la regla se disparó con una carga real; el envío al grupo de acciones consta en {E('docs/evidencias/capturas/azure/B9-Azure-Historial-Alerta-Grupo-Acciones-Desencadenado.png')}.", 14)
D.h("6.3 Estado final de Azure y despliegue A1", 2)
D.pj(f"Tras T4 y T5 la VM quedó **desasignada** con el apagado automático restaurado exactamente, los tokens en claro destruidos y la regla de correo de prueba retirada ({X(T4P)}, {X(T5P)}). El **23-nov a las 04:28:57Z** la VM se volvió a encender para la autorización **A1** (despliegue de NexoOps). Al cierre de este informe (04:44Z según la nota de estado; sin expediente) el servicio de NexoOps **no estaba arrancado** y la usuaria estaba configurando secretos. Por eso este informe **no** presenta T7 como desplegado y **no** puede verificar que la VM haya vuelto a desasignarse ({A1}).")

# =====================================================================================
D.h("VII. Seguridad cloud", 1)
D.h("7.1 Identidad y mínimo privilegio", 2)
D.table(["Nube / capa", "Identidad", "Privilegios", "Evidencia", "Límite"], [
    ["AWS", "`LabRole` / `LabInstanceProfile` (Academy)", "7 políticas; recurso `*` pero sin `Action:*` en las legibles", f"{E('docs/evidencias/capturas/aws/A13-IAM-LabRole-Politicas.png')}, {E('docs/evidencias/capturas/aws/A14-IAM-Acceso-Denegado.png')}", "Más amplio de lo necesario y **no modificable**; `VocLabPolicy1–3` ilegibles"],
    ["OCI", "usuario `nexoeventos-backup-uploader` (solo clave API)", "crear/leer/inspeccionar objetos de 1 bucket; sin borrar ni sobrescribir", E("docs/evidencias/multicloud/oci/20261023-iam-carga/resultado.md"), "—"],
    ["OCI (lease)", "PAR temporales por prefijo", "lectura/escritura de 1 objeto; caducan; revocados tras T1 (401)", X(T1P), "El PAR no impone la condición: protege la firma"],
    ["Azure", "identidad administrada de la VM", "*Monitoring Reader* sobre el grupo; escritura → 403", E("docs/evidencias/multicloud/azure/20261028-vm/identidad-administrada.txt"), "—"],
    ["PostgreSQL", "owner / migrator / app", "`REVOKE ALL FROM PUBLIC`; app sin `DELETE` en `users`", E("docs/evidencias/EV06/README.md"), "—"],
    ["Aplicación", "client / organizer / operator", "propiedad y asignación por evento; CSRF", E("docs/evidencias/EV10/README.md"), "**Sin MFA**"],
    ["Centro de operaciones (T4)", "viewer / requester / aprobador", "401 anónimo, 403 sin rol, aprobador distinto, failover rechazado, sin endpoints de ejecución", X(T4P), "—"],
    ["NexoOps (T7)", "`SUPER_ADMIN_TI` con OTP por correo + Argon2id", "acciones seguras sin ejecución remota", f"{E('../NexoEventos-codex-t7-t8/nexoops/tests/test_actions_security.py')}, {E('../NexoEventos-codex-t7-t8/nexoops/tests/test_auth.py')}", "**LOCAL**; no desplegado"],
], widths=[2.2, 3.4, 4, 3, 3], caption="IAM y mínimo privilegio por nube y capa", source="Fuente: evidencias citadas; `docs/entregable2/informe-entregable2.md` §09.", size=8)
D.figure(CAP + "aws/A9-CloudTrail-Sin-Trails.png", "Consola CloudTrail: no existe ningún trail configurado (riesgo residual comprobado)",
         f"Fuente: captura auténtica de consola AWS (copia redactada), 29-oct-2026; ID {E('docs/evidencias/capturas/aws/A9-CloudTrail-Sin-Trails.png')}. Explicación: solo existe el historial de eventos de 90 días ({E('docs/evidencias/capturas/aws/A8-CloudTrail-Historial-Eventos.png')}); no hay registro duradero de la API. Se declara como brecha, no como control.", 14)
D.h("7.2 Segmentación y filtrado", 2)
D.pj("En AWS la base vive en subredes privadas sin ruta a Internet y solo acepta 5432 desde el SG web; en V2 las instancias solo aceptan 80 desde el SG del ALB. En OCI la VM de recuperación vive en una subred privada; la entrada 443 pública solo existe durante T3 y se midió que **solo 443 es alcanzable** (22, 80, 3000, 5432, 8000 y 8443 no) en dos mediciones. En Azure el NSG solo admite 22 y 443 desde la IP /32 de la operadora y UFW refuerza el filtrado; puertos 80, 3000, 5432, 10050 y 10051 no alcanzables desde fuera.")
D.h("7.3 Cifrado y protección de credenciales", 2)
D.table(["Ámbito", "Control", "Evidencia"], [
    ["Reposo AWS", "RDS y EBS cifrados (KMS); S3 SSE-S3; snapshots cifrados", E("docs/evidencias/multicloud/aws/20261028-auditoria-solo-lectura/resultado.md")],
    ["Respaldos", "CMS AES-256 con clave pública; clave privada independiente y fuera de AWS; SHA-256", E("docs/evidencias/multicloud/aws/20261023-respaldo-0008/resultado.md")],
    ["Entradas QR", "token cifrado (Fernet) con hash en BD; validación atómica", E("docs/evidencias/EV10/README.md")],
    ["Tránsito", "TLS 1.3/1.2 en ALB, HSTS; `verify-full` a RDS; TLS verificado en todos los clientes del failover", f"{E('docs/evidencias/20261104-fase-c-d-v2/resultado.md')}, {E('backend/app/failover/tlsctx.py')}"],
    ["Contraseñas", "Argon2id; 5 fallos / 15 min; sesiones opacas `HttpOnly`/`Secure`", E("docs/evidencias/EV10/README.md")],
    ["Secretos", "fuera de git; Secrets Manager; Trivy de secretos en CI; tokens de T4 destruidos (solo hashes en la VM)", f"{E('docs/evidencias/ci-github-actions-20261029/resultado.md')}, {X(T4P)}"],
    ["Evidencias", "búsqueda de URL de PAR, tokens e IP en expedientes: 0 coincidencias de secretos", f"{X(T1P)}, {X(T2P)}"],
], widths=[2.6, 8.4, 4], caption="Cifrado y protección de credenciales", source="Fuente: evidencias citadas.")
D.h("7.4 Hallazgos de seguridad descubiertos por las pruebas", 2)
D.bullets([
    f"**TLS sin almacén de CA (T2, FAIL):** el Python de python.org no tenía CA cargadas y rechazó —correctamente— el certificado de DuckDNS. Se corrigió con `tlsctx.py`, que recurre a `certifi` **sin desactivar la verificación**; un certificado autofirmado sigue rechazándose ({E('backend/app/failover/tlsctx.py')}, {E('scripts/multicloud/tests/test_tls_context.py')}).",
    f"**Carrera entre hilos en el testigo:** la regresión reveló un fallo intermitente (23/35) que rompía la cadena de hashes; se corrigió con un cerrojo reentrante por instancia (35/35 en tres repeticiones) ({E('scripts/multicloud/tests/test_witness_thread_safety.py')}).",
    f"**Rollback del testigo no detectable con almacén local (T4):** origen de la barrera B-T6-1; mitigado en local con el anclaje anti-rollback (19/19), pendiente de validar en OCI (A2) ({E('backend/app/failover/anchor.py')}, {E('scripts/multicloud/tests/test_witness_anchor.py')}).",
    f"**Token de DuckDNS de alcance de cuenta:** puede modificar también el dominio de demostración; se recomienda regenerarlo en el cierre ({E('docs/evidencias/T2-20261122-resultado.md')}).",
])
D.h("7.5 Análisis de amenazas y controles", 2)
D.pj("El análisis se hace por activo: amenaza, vulnerabilidad que la habilita, control aplicado y si el control está **medido** o solo **diseñado**. Se resumen las amenazas de mayor impacto para el negocio de entradas.")
D.table(["Activo", "Amenaza", "Vulnerabilidad", "Control", "Estado y evidencia"], [
    ["Servidor web", "Saturación por ráfagas de inicio de sesión", "Argon2id reserva ≈ 64 MiB por hash", "semáforo `ARGON2_MAX_CONCURRENT`, ASG", "medido en local: 50 simultáneos pasan de 3 OOM y p95 25 s a 0 errores y p95 1,7 s; repetición en AWS pendiente"],
    ["Servidor web", "Caída de una instancia", "instancia única (V1)", "ALB + ASG con health check ELB", f"medido: T5 {X(T5P)}"],
    ["Servidor web", "Acceso por administración remota", "SSH o puertos de gestión expuestos", "sin SSH en AWS (SSM); NSG /32 + UFW en Azure; Bastion en OCI", f"medido: {E('docs/evidencias/multicloud/azure/20261028-vm/acceso-https-y-puertos.txt')}"],
    ["Servidor web", "Explotación de dependencias", "CVE en librerías", "Trivy en CI; `cryptography` 49.0.0 → 50.0.0", f"medido: {E('docs/evidencias/ci-github-actions-20261029/resultado.md')}"],
    ["Base de datos", "Falla de instancia o zona", "Single-AZ (V1)", "Multi-AZ, PITR, snapshots", f"medido: ≈ 14 s, huella idéntica {E('docs/evidencias/multicloud/aws/20261023-rds-multiaz/failover/resultado.md')}"],
    ["Base de datos", "Sobreventa por concurrencia", "condiciones de carrera", "bloqueo de fila + idempotencia", f"medido: 132 = 132 = 132 {E('docs/evidencias/EV11/resultado-2026-10-09.md')}; 4 concurrentes en OCI {X(T3P)}"],
    ["Base de datos", "Doble escritor en un failover", "dos nubes aceptan escrituras", "lease con época, compuerta y vallado", f"LOCAL (G5, 0 violaciones); en nube BLOCKED {E('docs/evidencias/T6-local/g5-exhaustivo-len5.txt')}"],
    ["Credenciales", "Secretos en repositorio o evidencias", "claves en código o capturas", "secretos fuera de git; Trivy de secretos; búsqueda en expedientes", f"medido: 0 coincidencias {X(T1P)}, {X(T2P)}"],
    ["Credenciales", "Fuerza bruta", "contraseñas débiles", "Argon2id, 5 fallos/15 min", "medido en local; **sin MFA** (residual)"],
    ["Respaldos", "Fuga o alteración del respaldo", "respaldo en claro o en la misma cuenta", "CMS AES-256, clave independiente, OCI sin sobrescritura", f"medido: SHA-256 y restauración {X(T3P)}"],
    ["Información", "Reutilización o falsificación de QR", "token predecible o reutilizable", "token aleatorio, hash en BD, validación atómica", f"medido: 2 simultáneas → 1 aceptación {E('docs/evidencias/EV10/README.md')}"],
    ["Operación", "Testigo retrocedido (rollback)", "almacén local restaurable", "anclaje anti-rollback firmado", f"LOCAL 19/19; en OCI BLOCKED (A2) {E('scripts/multicloud/tests/test_witness_anchor.py')}"],
    ["Cuenta", "Gasto no previsto", "recursos olvidados; RDS se reinicia a los 7 días", "ventanas, watchdog, apagado automático, verificación de limpieza", f"medido en cada T; costo total ≈ USD 0,95 {X(T5P, 'capturas/limpieza.json')}"],
], widths=[2, 3, 3, 3.6, 4.4], caption="Amenazas, vulnerabilidades y controles por activo", source="Fuente: `docs/entregable2/informe-entregable2.md` §08 actualizado con los expedientes T1–T6.", size=8)
D.h("7.6 Riesgos residuales", 2)
D.table(["Riesgo", "Impacto", "Tratamiento"], [
    ["`LabRole` amplio e inmodificable", "medio", "compensado con SG→SG, sin SSH, cifrado y roles de PostgreSQL; diseño de rol mínimo portable no implementable en Academy"],
    ["Sin trail de CloudTrail", "medio", "comprobado; propuesta de trail a S3 con retención (no aplicada)"],
    ["Sin MFA en la aplicación", "medio", "Argon2id y límite de intentos; MFA queda como trabajo futuro (NexoOps sí usa OTP)"],
    ["EC2 con IPv4 pública (sin NAT)", "bajo-medio", "SG cerrado al ALB; hallazgo de Trivy aceptado por costo"],
    ["Protección contra borrado de la RDS desactivada", "medio", "snapshots manuales cifrados; activar en un entorno real"],
    ["Custodia humana de la clave de recuperación", "alto si se pierde", "copia protegida con frase y dos proveedores externos verificados"],
], widths=[5, 2, 8], caption="Riesgos residuales de seguridad", source=f"Fuente: `docs/entregable2/informe-entregable2.md` §19; {E('docs/evidencias/20261122-copia-externa-respaldo/resultado.md')}.")

# =====================================================================================
D.h("VIII. Alta disponibilidad y escalabilidad (T5)", 1)
D.h("8.1 Antecedentes medidos antes de T5", 2)
D.pj(f"El 22-oct-2026 la V2 (2 EC2) ya había mostrado detección de un destino no sano en 20,0 s y reemplazo por el ASG en ≈ 2,5 min, con 25 respuestas 502 de 275 durante la detección ({E('docs/evidencias/tolerancia-fallos-v2-20261022/resultado.md')}, {E('docs/evidencias/tolerancia-fallos-v2-20261022-b/resultado.md')}); el escalado 2→3→2 por CPU ({E('docs/evidencias/escalado-v2-20261022/resultado.md')}); y el failover Multi-AZ forzado de la RDS dejó PostgreSQL sin respuesta ≈ 14 s con huella de datos idéntica ({E('docs/evidencias/multicloud/aws/20261023-rds-multiaz/failover/resultado.md')}).")
D.figure(CAP + "aws/11-rds-failover-22oct.png", "Consola RDS: eventos del failover Multi-AZ solicitado por el usuario (22-oct, hora UTC−5)",
         f"Fuente: captura auténtica de consola AWS (copia redactada); ID {E('docs/evidencias/capturas/aws/11-rds-failover-22oct.png')}. Explicación: «Multi-AZ instance failover started/completed» en ≈ 1 min entre eventos; la indisponibilidad medida por sonda fue ≈ 14 s.", 14.5)
D.h("8.2 Diseño de la prueba T5", 2)
D.pj("T5 mide la caída controlada de una EC2 (se detiene su API; la instancia sigue viva y Nginx devuelve 502) con tráfico constante de 5 solicitudes/s desde 4 clientes, conexión nueva por solicitud y ruta al azar entre `/api/events` y `/healthz`; línea base de 25 s, retención de 60 s y cola de 15 s tras recuperar. El denominador de la disponibilidad son **todas** las solicitudes `/healthz` desde T0 hasta 15 s después de recuperar; los 502, *timeouts* y errores de conexión cuentan como fallos. Azure observa con el recolector (60 s) y con una sonda rápida de 5 s.")
cr5 = json.load(open(f"{REPO}/work/evidencias/{T5P}/resultado.json"))["criterios"]
cr5f = {c["id"]: c for c in json.load(open(f"{REPO}/work/evidencias/{T5F}/resultado.json"))["criterios"]}
D.table(["Criterio (escrito antes)", "Regla", "Intento 1 (2 EC2)", "Intento 3 (6 EC2)"],
        [[c["id"], c["regla"], f"{str(cr5f[c['id']]['valor'])[:40]} → {cr5f[c['id']]['resultado']}", f"{str(c['valor'])[:40]} → {c['resultado']}"] for c in cr5],
        widths=[4.2, 2, 4.4, 4.4], caption="Criterios de T5 y valores medidos en los intentos 1 y 3",
        source=f"Fuente: `resultado.json` de {X(T5F)} y {X(T5P)}; criterios {E('ops_center/criterios/T5.json')}.", size=8)
D.h("8.3 Intento 1: FAIL honesto con 2 instancias", 2)
D.pj(f"El 23-nov 00:31Z, con 2 EC2 en us-east-1a/b, la API se detuvo en una instancia a +28,8 s; el ALB la marcó no sana a +53,7 s (**24,9 s**); el ASG la terminó y lanzó otra; hubo 2 destinos sanos a +188,6 s (**159,8 s**). Se cumplieron 8 de 9 criterios; la disponibilidad de `/healthz` fue **95,21 %** (457/480). **Causa medida:** durante los 24,9 s de detección el ALB siguió enviando ≈ 50 % de las solicitudes a la instancia defectuosa: 56 respuestas 502, confirmadas por CloudWatch (`HTTPCode_Target_5XX` = 56; `HTTPCode_ELB_5XX` = 0). Con salud de 10 s × 2 y una ventana de ≈ 205 s, la fracción esperada de fallos es ≈ 0,5 × 24,9 / 205 ≈ 6 %: es un **límite del mecanismo**, no un defecto de configuración ({E('docs/evidencias/T5-20261123-intento1-resultado.md')}).")
D.h("8.4 Intento 2: abortado por la SCP de AWS Academy", 2)
D.pj(f"La variante C (6 instancias, *health check* 5 s/3 s) se aplicó con un plan revisado (3 crear, 8 modificar, 0 destruir). A las 01:44:28Z `UpdateAutoScalingGroup` devolvió **403 «explicit deny in a service control policy»**: el ASG no pudo pasar a mín 6 / máx 7. Se priorizó la limpieza (ASG 0, ALB eliminado, RDS detenida verificada en 342 s, Azure desasignada). No hubo tráfico ni fallo inyectado: **no es un resultado de los criterios** ({E('docs/evidencias/T5-20261123-intento2-abortado.md')}). En el intento 3 se constató que la SCP permite máximo 6 y deniega 7.")
D.h("8.5 Intento 3: PASS 9/9 con 6 instancias", 2)
D.pj(f"Con 6 EC2 (3 + 3 en dos zonas, reparto de 15–17 % por instancia), la API se detuvo a las 02:14:29,123Z; el ALB marcó la instancia no sana a las 02:14:38,723Z (**9,6 s**); el ASG registró «Terminating …5d3b1» y «Launching …f2286»; hubo **6 destinos sanos** a las 02:16:34,123Z (**125,0 s**). De 396 sondeos `/healthz` fallaron 2 (**99,49 %**; el 99 % admitía como máximo 3). Sobre todo el tráfico, 816/824 (**99,03 %**). CloudWatch: `HTTPCode_Target_5XX` = 9, `HTTPCode_ELB_5XX` = 0, `HealthyHostCount` mínimo 5. La sonda de 5 s desde Azure **capturó** el incidente (muestra 02:14:37,412Z con 1 de 6 solicitudes en 502) sin fallos inexplicados ({X(T5P, 'capturas/resultado.json')}, {X(T5P, 'capturas/azure.json')}).")
D.figure(G + "g01-t5-disponibilidad.png", "T5: disponibilidad medida por intento frente al umbral de 99 %",
         f"Fuente: gráfico generado a partir de datos reales de los expedientes {X(T5F, 'capturas/resultado.json')} y {X(T5P, 'capturas/resultado.json')}, 23-nov-2026. Explicación: el criterio usa `/healthz`; la barra gris (todo el tráfico) se informa como dato complementario.", 15.5)
D.figure(G + "g02-t5-cronologia.png", "T5: tiempos de detección y de recuperación de capacidad en los intentos 1 y 3",
         f"Fuente: gráfico generado a partir de datos reales (`events` de ambos expedientes T5); IDs {X(T5F, 'capturas/resultado.json')}, {X(T5P, 'capturas/resultado.json')}. Explicación: el health check de 5 s × 2 reduce la detección de 24,9 s a 9,6 s y la proporción de tráfico afectado de 1/2 a 1/6.", 15.5)
D.figure(G + "g03-t5-cloudwatch.png", "T5: HealthyHostCount y UnHealthyHostCount por minuto (CloudWatch) en ambos intentos",
         f"Fuente: gráfico generado a partir de las métricas de CloudWatch exportadas por el recolector a los expedientes T5 ({X(T5F, 'capturas/resultado.json')}, {X(T5P, 'capturas/resultado.json')}). No es una captura de consola. Explicación: con 2 EC2 la capacidad cae a 1 destino durante 3 minutos; con 6, a 5.", 15.5)
D.h("8.6 Por qué 6 instancias: modelo contrafactual previo al intento 3", 2)
D.pj(f"Tras el FAIL del intento 1 se analizó el mecanismo sin tocar la nube: el ALB enruta a todo destino no marcado `unhealthy`, y su estado solo cambia por comprobaciones **activas** (mínimo 5 s × 2); un fallo rápido (502 inmediato) no tiene otra señal pasiva. Con las muestras reales del intento 1 se estimó la disponibilidad que habría resultado con N destinos y un retraso D hasta dejar de enrutar a la víctima. **Es una estimación reproducible (`scripts/ops/t5_contrafactual.py`), no una medición** ({E('docs/evidencias/T5-ANALISIS-Y-PROPUESTA-2-INTENTO.md')}).")
D.table(["N destinos \\ D (s)", "22 (observado)", "12", "10", "8", "5"], [
    ["2", "**95,21 % (medido)**", "97,50", "97,71", "98,12", "98,54"], ["3", "96,81", "98,33", "98,47", "98,75", "99,03"],
    ["4", "97,60", "98,75", "98,85", "99,06", "99,27"], ["6", "98,40", "**99,17**", "**99,24**", "99,38", "99,51"], ["8", "98,80", "99,38", "99,43", "99,53", "99,64"],
], widths=[3, 2.6, 2, 2, 2, 2], caption="Disponibilidad ESTIMADA de /healthz por número de destinos y retraso de detección (contrafactual, no medición)", source=f"Fuente: `docs/evidencias/T5-ANALISIS-Y-PROPUESTA-2-INTENTO.md` §3 ({E('docs/evidencias/T5-ANALISIS-Y-PROPUESTA-2-INTENTO.md')}).")
D.pj("La conclusión del modelo fue que con N = 2 el 99 % exigiría dejar de enrutar en ≤ 2,5 s, imposible con comprobaciones activas; con N = 6 y health check de 5 s el resultado quedaba **en el límite** (≈ 99,2 % estimado), es decir, incierto. Se descartaron explícitamente los atajos que «mejoran el número sin mejorar el servicio»: reintentos del cliente, ampliar la ventana, cambiar el denominador, excluir los 502 o desregistrar la instancia al detener el servicio (que convertiría la prueba en un no-evento). El resultado medido después (99,49 %) quedó dentro del rango estimado, pero se trata como una sola observación.")
D.h("8.7 Interpretación y límites", 2)
D.bullets([
    "**Una sola ejecución:** el 99,49 % es un resultado estadístico de una ejecución; el modelo previo daba ≈ 45–60 % de probabilidad de PASS. No se infiere un SLA; el FAIL de 2 instancias se cita siempre junto al PASS.",
    "**Qué lo explica:** detección activa de 9,6 s y 1/6 del tráfico afectado (8 errores frente a 56). **No** se atribuye a la mitigación de anomalías (ATW): no hay evidencia de que acortara nada.",
    "**Tipo de fallo:** parada controlada del servicio, el caso más benigno; la **caída abrupta de una instancia no se midió**.",
    "**Datos:** tráfico de solo lectura; 32 eventos y huella del catálogo idéntica antes/después; **no** se probó una escritura durante la sustitución.",
    "**Arquitectura resultante:** se documentan dos puntos de operación (económico y alta disponibilidad, Tabla 11); con 2 instancias el criterio de 99 % no es alcanzable con este mecanismo.",
    f"**Escalabilidad:** el único tope medido es 50 usuarios simultáneos (78 req/s, 0 errores 5xx en 35 366 solicitudes); los escalones de 100 a 5 000 usuarios son proyección ({E('docs/evidencias/medicion-v2-20261022/resultado.md')}).",
])

# =====================================================================================
D.h("IX. Respaldo, recuperación, RTO y RPO", 1)
D.h("9.1 Estrategia de respaldo", 2)
D.table(["Qué", "Frecuencia", "Ubicación", "Retención", "Evidencia"], [
    ["Copias automáticas y PITR de RDS", "continua/diaria", "AWS (misma región)", "7 días", E("docs/evidencias/capturas/aws/A5-RDS-Retencion-Cifrado.png")],
    ["Snapshots manuales cifrados", "bajo demanda", "AWS", "hasta borrarlos", E("docs/evidencias/capturas/aws/A4-RDS-Instantaneas.png")],
    ["Volcado lógico `pg_dump` + CMS AES-256", "por ventana (no programado)", "S3, OCI y copia local", "S3 versionado; OCI versionado", E("docs/evidencias/multicloud/aws/20261023-respaldo-0008/resultado.md")],
    ["Paquete de reconstrucción cifrado (código + datos + `work/`)", "puntual (22-nov)", "Google Drive y OneDrive UPeU", "custodia de la autora", E("docs/evidencias/20261122-copia-externa-respaldo/resultado.md")],
    ["Claves de entradas QR", "al rotarlas", "fuera de AWS y del repo", "custodia", E("docs/evidencias/EV07/README.md")],
], widths=[4.6, 2.4, 3, 2.4, 2.6], caption="Estrategia de respaldo", source="Fuente: evidencias citadas.")
D.evbox(E("docs/evidencias/20261122-copia-externa-respaldo/resultado.md"), "Copia externa del respaldo verificada en dos proveedores",
        "Archivo CMS AES-256 de 399 524 048 B con SHA-256 `5b201c80…dcfdc5f3fffd`… verificado de forma independiente en Google Drive y OneDrive: tamaño, hash, igualdad byte a byte, descifrado, partes íntegras, `git bundle verify` y clonado (136 commits). Veredicto **PASÓ** en ambos. Incidente de limpieza documentado y corregido.")
D.h("9.2 Recuperación de datos en AWS (PITR)", 2)
D.pj(f"R01 restauró la RDS a un punto en el tiempo en una instancia **nueva y privada** (nunca sobre la original), verificó la huella (seis tablas, propietarios de reservas, entradas descifrables) y obtuvo datos verificados a los **21 min 4 s** con un RPO demostrado de **3 min 32 s** ({E('docs/evidencias/EV07/resultado-restauracion-2026-10-10.md')}). La recuperación completa del servicio **en AWS** (aplicación + DNS + HTTPS) quedó incompleta el 12-oct y se declara así ({E('docs/evidencias/EV07/resultado-recuperacion-completa-incompleta-2026-10-12.md')}).")
D.h("9.3 Reconstrucción histórica en OCI (23-oct)", 2)
D.pj(f"Primera reconstrucción completa en OCI: aprovisionamiento 59 s, datos verificados a los 23 min 27 s, aplicación sirviendo a los 24 min 53 s y **14/14 pruebas a los 32 min 42 s** con huella 10/10 idéntica; acceso por túnel de Bastion, sin DNS público ({E('docs/evidencias/multicloud/oci/20261023-recuperacion-aplicacion/resultado.md')}).")
D.h("9.4 T3: reconstrucción en OCI con tres intentos", 2)
D.table(["Intento", "Ventana UTC", "Veredicto", "Causa / resultado", "Corrección aplicada", "Expediente"], [
    ["1", "15:06–15:45", "FAIL (4/19; aborto)", "`dnf` cargó metadatos de todos los repositorios en una VM de 945 MB y 1/8 OCPU; `sshd` dejó de responder > 23 min (saturación, sin OOM)", "`safe-dnf.sh` (repos mínimos, cgroup 640 MB, prioridad mínima, 25 min); swap ≥ 2 GB; recolector no cuenta RTO abortado", f"{X(T3A)} (y duplicado {X(T3D)})"],
    ["2", "15:52–16:40", "FAIL (18/19)", "OOM-killer sobre `dnf-makecache.service` del SO (16:21:41Z); además frase de clave mal escrita, `known_hosts` y reinicio de Nginx (corregidos)", "`quiesce-vm.sh` neutraliza temporizadores del SO; 3 pruebas nuevas", X(T3B)],
    ["3", "16:52–17:26", "PASS (19/19)", "fase A 649 s; 136/136; 10 huellas; humo 11/11; 5×403; fase B 23/23; solo 443 alcanzable; OOM 0", "kdump liberado en caliente (MemAvailable 250→714 MB) con autorización", X(T3P)],
], widths=[1.2, 2, 2, 4.8, 4, 2.2], caption="T3: intentos, causas raíz y correcciones", source="Fuente: `docs/evidencias/T3-20261122-intento{1,2,3}-resultado.md` y expedientes citados.", color_col=2, size=8)
D.figure(G + "g04-t3-etapas.png", "T3 intento 3: duración de cada etapa de la reconstrucción en OCI",
         f"Fuente: gráfico generado a partir de datos reales de `capturas/etapas.json` ({X(T3P, 'capturas/etapas.json')}). Explicación: PostgreSQL e instalación de la app concentran el 74 % del tiempo en la forma Micro; es tiempo de reconstrucción, no el RTO de un failover.", 15)
D.h("9.5 RTO y RPO: lo medido y lo no medido", 2)
D.pj(f"Se distinguen tres magnitudes que **no deben sumarse**: (A) recuperación dentro de AWS, (B) reconstrucción en OCI desde respaldo y (C) failover AWS→OCI. Las definiciones oficiales (criterios de T6, {E('ops_center/criterios/T6.json')}) son: **RTO** = desde la inyección del fallo hasta la verificación del nuevo escritor (umbral 3600 s); **RPO** = edad del respaldo usado (umbral 5400 s), sin perder reservas confirmadas.")
D.table(["Clase", "Evento", "Tiempo medido", "Pérdida de datos", "Evidencia"], [
    ["A · AWS", "Caída controlada de 1 EC2 con 6 EC2 (T5-3)", "detección 9,6 s; capacidad 125,0 s", "ninguna (solo lectura)", X(T5P)],
    ["A · AWS", "Caída controlada de 1 EC2 con 2 EC2 (T5-1)", "24,9 s; 159,8 s", "ninguna (solo lectura)", X(T5F)],
    ["A · AWS", "Failover RDS Multi-AZ forzado (23-oct)", "≈ 14 s sin respuesta", "huella idéntica", E("docs/evidencias/multicloud/aws/20261023-rds-multiaz/failover/resultado.md")],
    ["A · AWS", "PITR a instancia nueva (R01)", "21 min 4 s", "RPO 3 min 32 s", E("docs/evidencias/EV07/resultado-restauracion-2026-10-10.md")],
    ["B · OCI", "T3 intento 3, fase A", "649 s (apply 58 s aparte)", "RPO = edad del respaldo C-04 (puntual)", X(T3P)],
    ["B · OCI", "Reconstrucción del 23-oct", "32 min 42 s", "huella 10/10", E("docs/evidencias/multicloud/oci/20261023-recuperacion-aplicacion/resultado.md")],
    ["C · Failover", "AWS→OCI (T6)", "**NOT_TESTED**", "**NOT_TESTED**", E("docs/evidencias/T6-20261123-estado-local.md")],
], widths=[2, 5, 3.4, 3, 2.6], caption="RTO/RPO: tiempos medidos por clase (sin sumar piezas)", source="Fuente: `docs/entrega-final/05-RTO-RPO.md` contrastado con los expedientes citados.", color_col=3)
D.pj("**RPO del failover hoy:** sin un respaldo fresco, la edad del último respaldo restaurable superaría ampliamente el umbral de 5400 s, por lo que el criterio **fallaría** si T6 se ejecutara sin el procedimiento previo. El procedimiento preparado (no ejecutado) es: congelar escrituras con la compuerta en `enforce` → comprobar que no quedan transacciones abiertas → `backup_cycle.py` con cifrado CMS → verificar SHA-256 y descifrado → restaurar en OCI por la ruta de T3 → comparar huellas (`fingerprint.sql`).")

D.h("9.6 Por qué la reconstrucción de T3 no es el RTO del failover", 2)
D.pj("Los 649 s de T3 miden **reconstruir** la aplicación desde un respaldo en una VM nueva. Un failover real añadiría pasos que T3 no contiene y omitiría otros que T3 sí contiene, por lo que ninguna suma de piezas es un RTO válido:")
D.bullets([
    "**Pasos que faltan en T3:** detección por quórum de sondas, congelación de escrituras en AWS con la compuerta, respaldo final con verificación, espera del TTL del lease anterior, adquisición del lease con época nueva, habilitación del standby con la compuerta en `enforce`, cambio de DNS (≈ 62 s medido en T2) y verificación por efecto de que AWS ya no confirma escrituras.",
    "**Pasos de T3 que podrían no estar en el failover:** el `terraform apply` y la instalación de PostgreSQL y de la aplicación (≈ 480 s de los 649 s) desaparecen si el standby se mantiene construido antes del incidente; esa decisión debe fijarse en el criterio de T6 antes de ejecutarlo.",
    "**RPO:** T3 restauró un respaldo puntual (C-04 del 19-nov); su antigüedad no representa la pérdida de datos de un failover, que depende del respaldo final tomado tras congelar las escrituras.",
])
D.pj("Por estas razones el informe mantiene separadas la recuperación de T3 (medida, PASS) y el failover de T6 (BLOCKED, sin RTO ni RPO), tal como exige la definición oficial de `ops_center/criterios/T6.json`.")

# =====================================================================================
D.h("X. Monitoreo, observabilidad y NexoOps", 1)
D.h("10.1 Métricas, paneles, registros y alarmas", 2)
D.table(["Fuente", "Qué mide", "Umbral / acción", "Demostración"], [
    ["CloudWatch (AWS)", "CPU EC2, destinos sanos, 5xx, latencia, conexiones RDS; logs API/Nginx 7 días", "5 alarmas V1 + SNS; alarmas V2 con el ALB", f"correos ALARM/OK {E('docs/evidencias/20261104-fase-d-notificacion-v2/correos-alarm-ok.png')}; CPU real {E('docs/evidencias/20261104-p2-cpu-real/resultado.md')}"],
    ["Zabbix (Azure)", "`/healthz`, `/api/events`, certificado, CPU/memoria/disco/agente", "3 fallos seguidos → problema", f"detectó AWS caído (T4) {X(T4P)}"],
    ["Recolector de sondas", "estado de AWS/OCI/Azure cada 60 s (y sonda rápida de 5 s en T5)", "métrica personalizada → `alerta-nexo-sonda`", f"T4: 38 ciclos; T5: incidente capturado {X(T5P)}"],
    ["Azure Monitor", "CPU, memoria, disponibilidad de la VM; métrica de la sonda", "alertas Sev1/Sev2 → grupo de acciones (correo)", f"{E('docs/evidencias/capturas/azure/B3-Azure-Alerta-CPU-Activacion.png')}, {X(T4P)}"],
    ["Grafana", "paneles de Azure Monitor y Zabbix", "visualización", E("docs/evidencias/20261105-azure-ventana2/grafana-azure-vm-historico-20261104.png")],
    ["Centro de operaciones + testigo", "estado consolidado, auditoría encadenada", "solo lectura; sin ejecución", X(T4P)],
], widths=[3, 5, 3.5, 4], caption="Componentes de monitoreo y su demostración", source="Fuente: evidencias citadas.")
D.h("10.2 T4: centro de operaciones en Azure (PASS 18/18)", 2)
D.pj(f"En una ventana de 55 min (18:43–19:38Z del 22-nov; ≈ USD 0,21 estimado) se midió: **38 ciclos** del recolector en 2315 s con hueco máximo de 67 s, con AWS en ERROR real (el demo estaba caído), OCI en ADVERTENCIA «en espera» y Azure OK — nada simulado. La cadena de alerta fue real: fallo del host de prueba → problema de Zabbix 19:01:25Z → métrica publicada 19:01:26Z → `alerta-nexo-sonda` **Fired 19:03:19Z** (resuelta 19:10:19Z) → correo «Fired:Sev2 Azure Monitor Alert…» confirmado por la propietaria (segunda activación 19:28:28Z coherente con la hora de Gmail). El panel superó 18 pruebas de autorización y el testigo 10/10 + 27 pruebas del perfil Azure sin privilegios. Huellas de Grafana, Zabbix, UFW y NSG idénticas antes/después; 0 OOM ({X(T4P)}).")
D.evbox(f"{X(T4P, 'capturas/alerta.json')}, {X(T4P, 'capturas/correo.json')}", "Cadena de alerta real de T4",
        "Límite declarado: la **cabecera** del correo no se verificó (solo asunto y hora). Los «No data» de latencia/TLS en Grafana se explican por AWS apagado (ítems no soportados por *timeout*); un **control positivo** (destino que responde) dio latencia 0,61 s y TLS a 74 días.")
D.h("10.3 Observación de T5 desde Azure", 2)
D.pj(f"En el intento 1 las sondas de 60 s **no** capturaron el episodio de 22 s (todo «OK»), lo que se registró como limitación. Para el intento 3 se añadió una sonda de 5 s con ≥ 5 min de línea base: capturó la muestra fallida dentro de la ventana del generador, con hueco máximo de 5,0 s y 0 fallos inexplicados; relojes: Mac vs NTP −0,03 s; Azure vs Mac +0,80 s (±0,85 s) ({X(T5P, 'capturas/relojes.json')}).")
D.h("10.4 NexoOps (T7): portal de operaciones", 2)
D.pj(f"NexoOps es un portal web de operaciones (FastAPI + estático) para el rol `SUPER_ADMIN_TI`, con inicio de sesión por contraseña Argon2id + **OTP por correo** (probado con Gmail SMTP 465 por la propietaria), sesiones con cookies limitadas a la subruta, integraciones de **solo lectura** con Grafana y Zabbix, un asistente que cita evidencia y acciones seguras sin ejecución remota. Se diseñó para publicarse en `/nexoops/` detrás del Nginx HTTPS existente en la VM de Azure, con servicio systemd endurecido, instalador con respaldo y reversión, y secretos en un archivo 0600 del usuario `nexoops` ({E('../NexoEventos-codex-t7-t8/docs/codex/ARQUITECTURA-T7.md')}).")
D.table(["Aspecto", "Estado", "Evidencia"], [
    ["Suite automatizada NexoOps", "**PASS local: 68 passed** (re-ejecutada para este informe el 23-nov 04:49Z en `310279c`)", NXO],
    ["Autenticación OTP, base path, acciones seguras, puertos de despliegue", "PASS local", f"{E('../NexoEventos-codex-t7-t8/nexoops/tests/test_auth_http.py')}, {E('../NexoEventos-codex-t7-t8/nexoops/tests/test_base_path.py')}, {E('../NexoEventos-codex-t7-t8/nexoops/tests/test_deploy_ports.py')}"],
    ["Integración con Zabbix 7.0 real", "parcial: el commit `99719d6` declara verificación contra la API real en Azure (sin expediente)", "indirecta"],
    ["Despliegue en la VM de Azure (A1)", "**NOT_TESTED / incompleto**: servicio no arrancado al cierre", A1],
    ["Criterios `ops_center/criterios/T7.json`", "0 cumplidos en nube (definen un flujo operativo desde Azure distinto del alcance de NexoOps)", E("ops_center/criterios/T7.json")],
], widths=[4.5, 7, 3.5], caption="Estado de NexoOps (T7)", source="Fuente: worktree `NexoEventos-codex-t7-t8` (solo lectura) y nota de estado de A1.", color_col=1)
D.evbox(A1, "Hallazgos del despliegue A1 (en curso)",
        "(1) NexoOps estaba configurado en el **puerto 8760**, que ya usa el testigo: `/nexoops/healthz` devolvía el 200 **del testigo**, un **falso positivo** de salud. (2) El usuario `nexoops` no podía leer `/var/lib/ops-center`; se añadió un espejo de solo lectura (`nexoops-feed.sh/.service/.timer`). Ambos cambios están **sin commit** en `codex/t7-t8` y no se modificaron aquí. Evidencia indirecta: no hay expediente ni capturas fechadas.")

# =====================================================================================
D.h("XI. Infraestructura como código", 1)
D.h("11.1 Organización del código", 2)
D.table(["Módulo raíz", "Proveedor", "Archivos .tf", "Líneas", "Bloques resource", "Contenido"], [
    ["`infra/aws`", "AWS", "9", "797", "44", "V1: VPC, subredes, SG, EC2, RDS, S3, CloudWatch, SNS, CloudTrail (propuesta)"],
    ["`infra/aws-v2`", "AWS", "9", "803", "28", "V2: ALB, listeners, TG, launch template, ASG, alarmas, panel"],
    ["`infra/aws-recovery`", "AWS", "4", "279", "11", "contingencia EC2 + RDS (no desplegado)"],
    ["`infra/oci`", "OCI", "16", "910", "34", "módulos iam, lease, network, public_entry, recovery, storage"],
    ["`infra/azure`", "Azure", "12", "672", "17", "módulos network, vm, monitor, budget"],
    ["`infra/gcp`", "GCP", "1", "7", "0", "solo `versions.tf` (no usado)"],
], widths=[2.6, 1.6, 1.6, 1.4, 1.8, 6.5], caption="Módulos Terraform del repositorio", source="Fuente: recuento sobre `infra/**/*.tf` (este informe); cada archivo figura en el inventario con su SHA-256 (EV-T0-1xx).")
D.h("11.2 Prácticas de reproducibilidad y seguridad del cambio", 2)
D.bullets([
    f"**Planes revisados por escenario:** `test_v2_plan_review.py` y los revisores de plan (`t5c`) bloquean planes que no coinciden con lo autorizado (p. ej. destrucciones no previstas) ({E('backend/tests/test_v2_plan_review.py')}).",
    f"**Guardas de destrucción:** T3 exige 0 altas / 0 cambios / 11 destrucciones antes de destruir; en los tres intentos el inventario final fue idéntico al inicial ({X(T3P)}).",
    f"**Ventanas con watchdog:** `rds-window.sh` arma un temporizador que detiene la RDS si la ventana falla ({E('scripts/v2-ops/rds-window.sh')}).",
    f"**Validación estática:** `terraform fmt`/`validate`, 29 comprobaciones de seguridad IaC y Trivy de configuración en CI (31 ejecuciones, 30 exitosas) ({E('docs/evidencias/EV09/README.md')}, {E('docs/evidencias/ci-github-actions-20261029/resultado.md')}).",
    "**Secretos fuera del código:** solo `terraform.tfvars.example`; los `tfstate` y planes binarios se guardan fuera de git (`work/`), modo 0600.",
])
D.h("11.3 Desviaciones conocidas", 2)
D.bullets([
    "El ALB se elimina por API en la limpieza (ahorro): el estado de `aws-v2` queda desfasado y el siguiente plan lo recrea (escenario «resume» revisado).",
    "La RDS de producción no está en el estado de `aws-v2` (se gestiona desde `infra/aws`).",
    "El software de las VM (Zabbix, Grafana, NexoOps, testigo) se instala con scripts/Ansible y cloud-init, no con Terraform.",
])

# =====================================================================================
D.h("XII. Pruebas técnicas T1–T8", 1)
D.h("12.0 Metodología operativa de las ventanas cloud", 2)
D.pj("Todas las pruebas en nube siguieron el mismo ciclo, documentado antes de la primera operación real. El objetivo era que ninguna prueba pudiera dejar recursos encendidos, cambiar producción por error o presentar un resultado que no se midió.")
D.table(["Paso", "Qué se hace", "Control que aporta", "Evidencia"], [
    ["1. Tarjeta de autorización", "alcance, recursos afectados, costo máximo, riesgos, reversión, criterios de aceptación y limpieza", "nada se ejecuta sin una frase literal de la propietaria", f"{E('docs/evidencias/T3-TARJETA-AUTORIZACION.md')}, {E('docs/evidencias/T5-TARJETA-AUTORIZACION.md')}"],
    ["2. Criterios previos", "umbrales en `ops_center/criterios/Tn.json`", "no se puede ajustar el criterio al resultado", E("ops_center/criterios/T5.json")],
    ["3. Prechequeo de solo lectura", "inventario previo, sesión viva, plan de Terraform revisado por escenario", "detecta desvíos antes de gastar", f"{E('docs/evidencias/VENTANA-UNICA-AWS.md')}, {E('backend/tests/test_v2_plan_review.py')}"],
    ["4. Ejecución instrumentada", "recolector con marcas UTC en ms (`events.jsonl`)", "cronología verificable", X(T5P, "events.jsonl")],
    ["5. Limpieza verificada", "ASG 0, ALB eliminado, RDS detenida, VM desasignada, PAR revocados; inventario posterior", "el costo queda acotado", X(T5P, "capturas/limpieza.json")],
    ["6. Veredicto y manifiesto", "`resultado.json` + `MANIFIESTO.sha256`; un FAIL se conserva", "integridad e historia honesta", X(T5F, "MANIFIESTO.sha256")],
    ["7. Corrección local", "causa raíz, prueba de regresión, nueva autorización", "no se repite a ciegas", E("scripts/multicloud/tests/test_probe_race_path.py")],
], widths=[2.8, 5, 3.6, 3.6], caption="Ciclo operativo de cada prueba en nube", source="Fuente: `docs/evidencias/PLAN-PRUEBAS-OBLIGATORIAS-CLOUD.md`, `VENTANA-UNICA-AWS.md` y tarjetas citadas.", size=8.5)
D.pj("Cada prueba se presenta con su objetivo, criterios previos, procedimiento, resultado, fallos y correcciones, evidencias y limitaciones. La figura siguiente muestra el recuento de criterios de los 11 expedientes reales, incluidos los fallidos.")
D.figure(G + "g06-criterios-expedientes.png", "Criterios CUMPLE / NO_CUMPLE / SIN_MEDIR por expediente real",
         "Fuente: gráfico generado a partir de los 11 `work/evidencias/T*/resultado.json` (datos reales). Explicación: los FAIL se conservan; el expediente T3 15:47Z es el duplicado del intento 1 con un error del recolector corregido.", 15.8)
for et, title, obj, proc, res, fallos, lim, evs in [
    ("T1", "12.1 T1 — Lease real por PAR en OCI", "Demostrar en OCI real que el almacén del lease ofrece escritura condicional atómica y que la adquisición del lease con el cliente real es exclusiva, con latencia compatible con el margen del lease.",
     "3 PAR temporales de alcance mínimo; pruebas `If-None-Match`/`If-Match`; 20 rondas CAS con 8 contendientes; 20 rondas de adquisición con `LeaseClient` (ttl 3 s, margen 0,8 s); pruebas de alcance; revocación y limpieza; lecturas previa y posterior de solo lectura.",
     "**PASS 12/12** (07:08:51–07:12:02Z): CAS 20/20 con un ganador (142 respuestas 412); adquisición 20/20 (1 ganador, 7 negativas, 0 inconclusos; épocas 2→21 sin retroceso); 0 violaciones P0–P5; PUT p50 0,370 s · p95 0,414 s · máx 0,434 s; desfase de reloj 0,802 s; 3 PAR revocados → 401; inventario 21/471 979 B intacto; costo 0.",
     "1.ª ejecución **FAIL** (07:03Z): `NameError: LR` porque el probe no importaba `lease_race`; la limpieza automática funcionó (0 PAR, 0 versiones). Corrección: import, prueba de regresión que detecta nombres globales sin definir y humo con el intérprete real de la CLI de OCI; `umask 077` en la evidencia.",
     "Latencia medida desde el equipo local (red doméstica); falta medir desde AWS y desde OCI. Demuestra el almacén y la exclusividad, no un failover.",
     [X(T1F), X(T1P), E("docs/evidencias/T1-20261122-resultado.md"), E("scripts/multicloud/tests/test_probe_race_path.py")]),
    ("T2", "12.2 T2 — Cambio de DNS de pruebas", "Demostrar el cambio A→B y la reversión B→A del subdominio de pruebas con propagación medida, protecciones negativas y auditoría.",
     "3 pruebas negativas (dominio fuera de lista blanca, sin variable de habilitación, frase errónea); plan inicial; apply A→B; verificación en 1.1.1.1, 8.8.8.8 y 9.9.9.9; segundo cambio inmediato (debe rechazarse); rollback; plan final.",
     "**PASS 13/13** (14:24:43–14:26:52Z): negativas rechazadas (código 2); propagación **62,1 s** (A→B) y **62,0 s** (B→A) frente a 180 s; segundo cambio rechazado por intervalo mínimo de 300 s sin llamar a DuckDNS; IP final = inicial; auditoría `apply` y `rollback` con hora UTC; token 0 veces en la evidencia; costo 0.",
     "1.ª ejecución **FAIL** (14:13Z) **sin ningún cambio de DNS**: el Python del entorno no tenía CA y rechazó el certificado de DuckDNS. Corrección: `tlsctx.py` (verificación nunca desactivada), 5 pruebas TLS y prerrequisito de apretón TLS en el plan. Hallazgo adicional corregido: carrera entre hilos del testigo.",
     "Propagación medida desde un solo punto con 3 resolvedores; DuckDNS admite una IP por registro y no comprueba salud. No demuestra un failover. Token de cuenta: regenerar.",
     [X(T2F), X(T2P), E("docs/evidencias/T2-20261122-resultado.md"), E("backend/app/failover/tlsctx.py")]),
    ("T3", "12.3 T3 — Recuperación y funcionamiento real en OCI", "Reconstruir en OCI, desde el respaldo cifrado, PostgreSQL y la aplicación completa, verificar integridad y funcionamiento, y destruir sin residuos.",
     "F1 plan y verificación del respaldo; F1b frase; F2 `terraform apply` (11); fase A: descarga, SHA-256, PostgreSQL, descifrado, restauración, claves, humo de solo lectura con 5 escrituras que deben dar 403; fase B: copia desechable L/E con 23 pruebas funcionales; HTTPS público; barrido de puertos; memoria; destrucción con guarda.",
     "**PASS 19/19** en el intento 3: fase A **649 s**; 136 reservas / 136 entradas; 10 huellas OK; humo 11/11; 5×403; fase B **23/23** (login con cookie Secure+HttpOnly, reserva 201, idempotencia, 409, 422, QR, 4 concurrentes con cupos 178→173); solo 443 alcanzable; 0 OOM; inventario final idéntico.",
     "Intento 1 **FAIL** (dnf sin límites satura la VM); intento 2 **FAIL 18/19** (OOM de `dnf-makecache`). Correcciones: `safe-dnf.sh`, `ensure-swap.sh`, `quiesce-vm.sh`, liberación de kdump y pruebas nuevas (ver Tabla 21).",
     "Tiempo de reconstrucción, no RTO de failover; la forma Micro es lenta para instalar; acceso por HTTPS con certificado fijado, sin DNS público.",
     [X(T3A), X(T3B), X(T3P), E("docs/evidencias/T3-20261122-intento3-resultado.md")]),
    ("T4", "12.4 T4 — Centro de operaciones en Azure", "Preparar y demostrar desde Azure la observación de las tres nubes, una alerta real con correo, el panel con autorización y el testigo, sin alterar la seguridad de la VM.",
     "Ventana única de 55 min; instalación aditiva; recolector con sondas reales; host de prueba que falla y control positivo; alerta métrica; 18 pruebas de autorización del panel; pruebas del testigo; huellas antes/después; cierre con desasignación.",
     "**PASS 18/18**: 38 ciclos/2315 s, hueco máx 67 s; alerta Fired 19:03:19Z y correo; panel 18/0; testigo 10/10 + 27; huellas idénticas; 0 OOM; mínimo 6690 MiB libres; costo ≈ USD 0,21.",
     "Incidentes resueltos dentro de la ventana: falta de `python3-venv`, include de Nginx fuera del `server` (restaurado automáticamente), prueba del testigo ejecutada como root (repetida sin privilegios), `alerta-vm-mem` por ceros de arranque.",
     "Cabecera del correo no verificada; el testigo con almacén local no detecta un prefijo restaurado (origen de B-T6-1).",
     [X(T4P), E("docs/evidencias/T4-20261122-resultado.md")]),
    ("T5", "12.5 T5 — Alta disponibilidad AWS", "Ver capítulo VIII.", "Ver §8.2.",
     "**PASS 9/9** en el intento 3 con 6 EC2: 99,49 % (394/396), detección 9,6 s, recuperación 125,0 s, sustitución real por el ASG, dos zonas, sin pérdida (solo lectura), Azure capturó el incidente, limpieza verificada, ≈ USD 0,29.",
     "Intento 1 **FAIL 8/9** (95,21 % con 2 EC2; límite del mecanismo); intento 2 **abortado** por la SCP (403). Corrección: variante de 6 instancias con health check de 5 s, dentro del máximo que permite Academy.",
     "Una ejecución; parada controlada; solo lectura; caída abrupta no medida.",
     [X(T5F), E("docs/evidencias/T5-20261123-intento2-abortado.md"), X(T5P)]),
]:
    D.h(title, 2)
    D.table(["Aspecto", "Detalle"], [["Objetivo", obj], ["Procedimiento", proc], ["Resultado", res], ["Fallos y correcciones", fallos], ["Limitaciones", lim], ["Evidencias", ", ".join(evs) + f"; criterios {E(f'ops_center/criterios/{et}.json')}"]],
            widths=[3, 12], first_bold=True, size=8.5, caption=f"Ficha de prueba {et}", source=f"Fuente: expedientes y resultados de {et} citados.")
D.evbox(X(T1P, "capturas/probe-salida.json"), "Extracto de datos crudos de T1 (probe-salida.json)",
        "`contendientes.rondas_ejecutadas=20`, `siempre_exactamente_uno=true`, `rechazos_412_total=140`; `lease_race.rondas_aprobadas=20`, `rondas_con_mas_de_un_ganador=0`, `inconclusos=0`, `exclusividad_demostrada=true`; `latencias_put_exitosos: n=22, p50=0.37, p95=0.414, max=0.434`; `par_activos_tras_revocar=0`; `estado_url_tras_revocar: lease=401, attest=401, race=401`; `limpio=true`.")
D.evbox(X(T2P, "capturas/paso-apply_b.txt"), "Extracto de datos crudos de T2 (paso-apply_b.txt)",
        "`cmd: apply · rc: 0 · t0: 2026-11-22T14:24:44.931Z · t1: 2026-11-22T14:25:48.035Z` — «IP actual (resolvedores): [oculto] · destino «b»: [oculto] · TTL supuesto: 60 s … OK: apply → [oculto]; propagación en 62.1 s». Las IP aparecen ocultas en el propio expediente.")
D.evbox(X(T3P, "capturas/etapas.json"), "Extracto de datos crudos de T3 (etapas.json)",
        "`respaldo: nexoeventos-rds-20261119T055432Z · resultado: OK · etapas: descarga 7.489, construccion 6.436, copia 34.277, postgres 288.424, instalacion_app 191.874, datos 6.845, secretos 1.696, servicio 29.454, humo 5.113 · total_s 649.304 · tipo: «tiempo observado de recuperación (NO es el RTO de un failover AWS–OCI)»`.")
D.evbox(X(T5P, "capturas/resultado.json"), "Extracto de datos crudos de T5 intento 3 (capturas/resultado.json)",
        "`events.t0_utc 02:13:59.823Z · stop_issued_at 29.3 · alb_marked_unhealthy_at 38.9 · both_healthy_again_at 154.3 · detection_after_stop_s 9.6 · capacity_restored_after_stop_s 125.0` · `client.requests 824 · ok 816 · errors 8 (502) · /healthz requests 396 errors 2` · `cloudwatch.target_5xx 9 · healthy_hosts_min [6,6,5,5,6,6]` · `asg_activities_new: Launching …f2286 / Terminating …5d3b1`.")
D.figure(G + "g05-t1-latencias.png", "T1: latencia de PUT condicional a OCI Object Storage (p50, p95, máx.)",
         f"Fuente: gráfico generado a partir de datos reales de {X(T1P, 'capturas/probe-salida.json')}. Explicación: p95 de 0,414 s frente a un umbral de 2,5 s; medido desde el equipo local.", 13)
D.figure(G + "g08-t2-propagacion.png", "T2: tiempo de propagación del cambio DNS en tres resolvedores públicos",
         f"Fuente: gráfico generado a partir de datos reales de `paso-apply_b.txt` y `paso-rollback_a_1.txt` ({X(T2P, 'capturas/paso-apply_b.txt')}, {X(T2P, 'capturas/paso-rollback_a_1.txt')}). Explicación: ≈ 1 × TTL de 60 s.", 13)
D.h("12.6 T6 — Failover real AWS→OCI: BLOCKED", 2)
D.pj("T6 exige cerrar en nube real las barreras contra el doble escritor antes de ejecutarse. Lo que existe es trabajo **local** con componentes reales del código y piezas reales sueltas (T1, T2, T3). **No se presenta ningún RTO/RPO de failover.** La recuperación medida en T3 es reconstrucción, no failover, y se mantiene separada.")
D.table(["Barrera", "Evidencia local", "Prueba real exigida", "Estado"], [
    ["B-T6-1 anclaje del testigo", "19/19 (`test_witness_anchor.py`)", "bucket OCI con retención + rollback detectado (A2)", "BLOCKED"],
    ["D1 compuerta y vallado en RDS", "`gate.py`, `pg_fence.py`, G5", "0 respuestas 201 de AWS tras perder la autoridad", "BLOCKED"],
    ["D2 sello WORM en OCI", "`seal_log.py`", "rechazo real de un sello retrocedido", "BLOCKED"],
    ["D3 lease entre nubes", "T1 real + G5", "ciclo completo con AWS y OCI", "PARCIAL (T1 PASS)"],
    ["D4 standby OCI con compuerta `enforce`", "`adapters_standby.py`", "OCI no escribe sin lease", "BLOCKED"],
    ["D5 clientes con DNS en caché", "diseño por efecto", "0 respuestas 201 desde AWS tras la toma", "BLOCKED"],
    ["D6 pausas de VM y deriva de reloj", "`test_two_db_pauses.py`", "medición con lease real", "NOT_TESTED"],
    ["D7 cancelación/aborto (T6.0)", "`test_failover_orchestrator.py`", "simulacros `dry_run` con adaptadores reales", "BLOCKED"],
    ["D8 failback manual", "`failback.py`", "ejecución medida", "BLOCKED"],
], widths=[4, 4, 5, 2], caption="Barreras de T6 (estado al 23-nov-2026)", source=f"Fuente: {E('docs/evidencias/T6-BLOQUEOS-OBLIGATORIOS.md')}, {E('docs/evidencias/T6-20261123-estado-local.md')}.", color_col=3)
D.evbox(f"{E('docs/evidencias/T6-local/g5-exhaustivo-len5.txt')}, {E('scripts/multicloud/tests/test_g5_single_writer_exhaustive.py')}", "Exploración exhaustiva G5 (LOCAL)",
        "Todas las secuencias de 5 eventos sobre 9 acciones (**59 049**) con `LeaseClient` real, almacén condicional, guarda del testigo y testigo anclado: **0 violaciones** de escritor único; el **control negativo** sí detecta el fallo inyectado. Es una prueba de modelo en local, no una ejecución en nube.")
D.h("12.7 T7 — NexoOps", 2)
D.pj(f"PASS local (68 pruebas) y despliegue en Azure **no completado** (ver §10.4 y {A1}). Los 4 criterios de `T7.json` siguen sin cumplirse en nube.")
D.h("12.8 T8 — Cierre y entrega", 2)
D.pj(f"Los 5 criterios técnicos de cierre (AWS sin recursos facturables, OCI sin temporales, Azure desasignada, tokens revocados, paquete cifrado nuevo reverificado) siguen **NOT_TESTED** porque exigen una sesión cloud de verificación ({E('ops_center/criterios/T8.json')}). La parte documental es este paquete.")
D.h("12.9 Regresión automatizada local", 2)
reg_txt = open(REG["_abs"] if REG and "_abs" in REG else OUTD + "/control-calidad/pytest-regresion.txt").read() if os.path.isfile(OUTD + "/control-calidad/pytest-regresion.txt") else ""
import re as _re
_m = _re.findall(r"(\d+) passed", reg_txt); _st = _re.findall(r"(\d+) subtests passed", reg_txt)
reg_lines = (f"backend/tests **{_m[0]} passed**; scripts/multicloud **{_m[1]} passed + {_st[0]} subtests**, 0 failed (04:49–05:03Z, `5e1fed1`)" if len(_m) >= 2 and not _re.search(r"\d+ failed", reg_txt) else "ver archivo")
D.table(["Suite", "Resultado previo (registro)", "Re-ejecución para este informe", "Evidencia"], [
    ["`scripts/multicloud`", "704 passed + 66 subtests, exit 0 (04:19Z)", reg_lines if "multicloud" in reg_txt else "ver archivo", f"{E('docs/evidencias/T6-local/regresion-final.txt')}" + (f", {REG['id']}" if REG else "")],
    ["`backend/tests`", "343 passed, exit 0", "incluida en la fila anterior", E("docs/evidencias/T6-local/regresion-final.txt")],
    ["`nexoops` (rama codex/t7-t8)", "66/66 (04:35Z)", "**68 passed** (04:49Z, 310279c)", NXO],
], widths=[3, 4, 5.5, 2.5], caption="Regresión automatizada local", source="Fuente: salidas de pytest citadas; las re-ejecuciones usan `-p no:cacheprovider` y no tocan nubes.")

# =====================================================================================
D.h("XIII. Costos y optimización", 1)
D.pj("Ningún costo de este capítulo es un extracto de facturación: AWS Academy no ofrece Cost Explorer y no hay capturas de Cost Management versionadas. Todas las cifras son **ESTIMADAS** con tarifas públicas, tal como las calculó cada expediente.")
D.table(["Ventana", "Nube", "Duración", "Estimación", "Fuente"], [
    ["T1 (2 ejecuciones)", "OCI", "≈ 20 s + 3 min", "USD 0", E("docs/evidencias/T1-20261122-resultado.md")],
    ["T2 (2 ejecuciones)", "DuckDNS", "≈ 2 min", "USD 0", E("docs/evidencias/T2-20261122-resultado.md")],
    ["T3 (3 intentos)", "OCI Always Free", "≈ 39 + 48 + 34 min", "USD 0", X(T3P)],
    ["T4", "Azure", "55 min", "≈ USD 0,21", E("docs/evidencias/T4-20261122-resultado.md")],
    ["T5 intento 1 (2 EC2)", "AWS + Azure", "≈ 42 min", "≈ USD 0,15", X(T5F, "capturas/costos.json")],
    ["T5 intento 2 (abortado)", "AWS + Azure", "≈ 19 min", "≈ USD 0,30", E("docs/evidencias/T5-20261123-intento2-abortado.md")],
    ["T5 intento 3 (6 EC2)", "AWS + Azure", "≈ 80 min (incluye el apply parcial)", "≈ USD 0,29", X(T5P, "capturas/costos.json")],
    ["**Total T1–T5**", "", "", "**≈ USD 0,95**", "suma de estimaciones"],
], widths=[3.6, 2.6, 3.6, 2.4, 3], caption="Costo estimado por ventana de prueba", source="Fuente: expedientes citados. Nota: `docs/codex/RESULTADOS-Y-COSTOS.md` cita ≈ USD 0,50 porque solo suma T4 y el PASS de T5.")
D.figure(G + "g07-costos-estimados.png", "Costo ESTIMADO por ventana de prueba frente al techo de USD 1,5",
         "Fuente: gráfico generado a partir de las estimaciones registradas en los expedientes (`costos.json` de T5) y en los informes de T4 y T5-2. No es factura.", 14.5)
D.h("13.1 Dimensionamiento", 2)
D.table(["Escenario", "Componentes", "Costo aproximado", "Resultado asociado"], [
    ["AWS económico", "2 × t3.small + ALB + RDS Multi-AZ db.t3.micro + IPv4", "≈ 0,13 USD/h", "T5: 95,21 % (FAIL del 99 %)"],
    ["AWS alta disponibilidad", "6 × t3.small + ALB + RDS + IPv4", "≈ 0,26 USD/h (peor caso)", "T5: 99,49 % (PASS, 1 ejecución)"],
    ["AWS 24×7 de referencia", "V2 completa todo el mes", "≈ USD 101,7/mes", "no viable con el crédito (Entregable 2 §18)"],
    ["OCI", "Always Free (E2.1.Micro, Object Storage ≈ 0,5 MB)", "≈ 0", "T1, T3"],
    ["Azure", "D2s_v4 solo en ventanas; desasignada con disco + IP", "≈ 0,2–0,3 USD por ventana; ≈ 0,30 USD/día desasignada", "T4, T5"],
], widths=[3.2, 5.5, 3.3, 3.5], caption="Dimensionamiento y costo horario estimado", source="Fuente: `docs/entrega-final/06-COSTOS.md` y `docs/entregable2/informe-entregable2.md` §18.")
D.pj("**Análisis.** Pasar de 2 a 6 instancias duplica el costo horario (×2, no ×3, porque ALB y RDS son fijos) y es lo que permitió alcanzar el 99 % en la prueba. En un evento real, el modo de alta disponibilidad solo se justifica durante las aperturas de venta.")
D.h("13.2 Optimizaciones aplicadas y propuestas", 2)
D.table(["Medida", "Estado", "Ahorro / efecto", "Riesgo o condición"], [
    ["Operación por ventanas con limpieza verificada (ASG 0, ALB eliminado, RDS detenida, VM desasignada)", "APLICADA", "costo total ≈ USD 0,95", "la RDS se reinicia sola a los 7 días"],
    ["Sin NAT Gateway", "APLICADA", "evita un costo fijo alto", "IPv4 pública por instancia"],
    ["OCI Always Free para recuperación", "APLICADA", "≈ 0", "forma Micro lenta"],
    ["Watchdog de RDS y apagado automático de Azure", "APLICADA", "evita olvidos", "—"],
    ["Escalado programado: 6 instancias solo en aperturas, 2 el resto", "PROPUESTA", "≈ 50 % del cómputo fuera de picos", "calendario de eventos"],
    ["Instancias Spot para parte del ASG", "PROPUESTA", "hasta ≈ 60–70 % en cómputo", "interrupciones; no probado en Academy"],
    ["Graviton (t4g)", "PROPUESTA", "≈ 20 % por instancia", "AMI ARM"],
    ["Savings Plans / reservas (entorno real)", "PROPUESTA", "30–40 %", "compromiso de 1–3 años"],
    ["Azure B-series o Zabbix apagado fuera de eventos", "PROPUESTA", "≈ 50 % de la VM", "menor observación"],
], widths=[6, 2.2, 3.4, 3.4], caption="Optimizaciones aplicadas y propuestas", source="Fuente: `docs/entrega-final/06-COSTOS.md` §3–4.")
D.pj("**Pendiente:** captura del saldo de AWS Academy y de Cost Management de Azure para convertir estimaciones en observaciones (**NOT_TESTED**).")

# =====================================================================================
D.h("XIV. Matriz de la rúbrica oficial", 1)
D.pj("Se reproducen literalmente los 14 criterios de la hoja «Rúbrica» del archivo oficial, con sus cuatro niveles y su puntaje máximo, y se contrasta cada uno con la evidencia. La columna «Nivel defendible» es la lectura honesta de la evidencia; **no es una nota** y no se suma un total. La versión completa, con todas las evidencias por criterio, está en `MATRIZ-RUBRICA-EVIDENCIAS.xlsx`.")
D.table(["#", "Criterio (literal)", "Excelente (literal)", "Bueno (literal)", "En proceso (literal)", "Deficiente (literal)", "Pts."],
        [[str(i + 1), r["criterio"].split(". ", 1)[1], r["exc"], r["bueno"], r["proc"], r["defi"], f"{r['peso']:.1f}".replace(".", ",")] for i, r in enumerate(RUBRICA)],
        widths=[0.6, 2.6, 4, 2.6, 2.4, 2.6, 0.9], caption="Rúbrica oficial: criterios, niveles y puntajes (transcripción literal)",
        source=f"Fuente: `rúbrica proyecto_qod3szrctm.xlsx`, hoja «Rúbrica» (tres copias idénticas en Descargas, SHA-256 945dec8d…8d7bae). Suma de los 14 puntajes: {SUMA:.1f}".replace(".", ",") + "; la celda I16 declara «TOTAL 20».", size=7.5)
D.evbox("rúbrica oficial (fuente externa al repositorio)", "Inconsistencia detectada en la rúbrica oficial",
        f"Los puntajes de los 14 criterios suman **{SUMA:.1f}".replace(".", ",") + " puntos**, mientras la fila final de la hoja declara «TOTAL 20». La diferencia (1,5 puntos) no se puede atribuir a ningún criterio con la información del archivo. El paquete T8 anterior (`01-MATRIZ-RUBRICA.md`) afirmaba que la suma era 20,0: esa afirmación es **incorrecta** y se corrige aquí. Se recomienda confirmar con el docente si algún puntaje está mal transcrito o si el total se reescala a 20.", kind="Evidencia")
MAT = json.load(open(f"{S}/build/matriz.json"))
D.table(["#", "Pts.", "Evidencia principal (IDs)", "Nivel defendible", "Brechas declaradas"],
        [[str(m["n"]), f"{m['peso']:.1f}".replace(".", ","), m["evid_cortas"], m["nivel"], m["brechas"]] for m in MAT],
        widths=[0.6, 0.9, 5, 2.4, 6.4], caption="Contraste de cada criterio con la evidencia", source="Fuente: `MATRIZ-RUBRICA-EVIDENCIAS.xlsx` (este paquete).", size=7.5, color_col=3)
D.pj("**Lectura global.** La fortaleza del proyecto son las pruebas reales con criterio previo y expediente, incluida la historia FAIL → corrección → PASS en T1, T2, T3 y T5. Las debilidades se concentran en los criterios 9 y 10, que dependen de T6 (no ejecutado), y en el 5 por las restricciones de AWS Academy (LabRole, sin trail) y la ausencia de MFA. El criterio 14 solo puede evaluarse en la sustentación.")

# =====================================================================================
D.h("XV. Conclusiones", 1)
D.h("15.1 Conclusiones", 2)
D.bullets([
    "La V2 eliminó los puntos únicos de falla de la V1 en cómputo y base de datos, y lo demostró con mediciones: detección de 9,6 s y recuperación de capacidad en 125 s con 6 instancias, y failover de RDS Multi-AZ de ≈ 14 s con datos idénticos.",
    "La disponibilidad del 99 % **no** es alcanzable con 2 instancias ante este tipo de fallo (95,21 %, límite del mecanismo de comprobaciones activas); sí lo fue con 6 en una ejecución (99,49 %). La arquitectura se documenta con dos modos de operación.",
    "La recuperación fuera de AWS es real: la aplicación completa se reconstruyó en OCI desde el respaldo cifrado (649 s, 136/136, 23/23 funcionales) y se destruyó sin residuos.",
    "La integración multicloud real existe por piezas (lease en OCI, DNS, reconstrucción, observación desde Azure), pero el **failover AWS→OCI no se ejecutó**: sus barreras contra el doble escritor solo están probadas en local.",
    "La disciplina de evidencia (criterios previos, manifiestos, conservación de los FAIL) permitió descubrir y corregir defectos reales —TLS sin CA, carrera entre hilos, saturación por dnf, OOM por servicios del SO— que habrían comprometido un failover real.",
    "El costo total estimado de la batería real fue ≈ USD 0,95, gracias a la operación por ventanas con limpieza verificada.",
])
D.h("15.2 Lecciones aprendidas", 2)
D.bullets([
    "Probar el camino real (intérprete, TLS, CA, red) y no solo simuladores: T1 y T2 fallaron por rutas que las pruebas locales no ejercitaban.",
    "En VM pequeñas, todo paso pesado necesita límites de tiempo y memoria; los servicios del SO también consumen recursos.",
    "Un criterio de disponibilidad debe declarar denominador, ventana y tipo de fallo; si no, se puede «aprobar» redefiniéndolo.",
    "Las políticas del proveedor (SCP de Academy) son parte de la arquitectura y deben descubrirse antes de la ventana.",
])
D.h("15.3 Pendientes y trabajo futuro", 2)
D.table(["Pendiente", "Requisito", "Estado"], [
    ["Completar A1 (NexoOps en Azure) con evidencia fechada y desasignar la VM", "autorización A1 vigente", "EN CURSO / NOT_TESTED"],
    ["A2: anclaje del testigo en OCI con retención y rollback detectado", "autorización A2", "BLOCKED"],
    ["T6.0 ensayo en seco y T6 completo (failover y failback)", "cerrar D1–D8 en nube; autorización A3", "BLOCKED"],
    ["T8: verificación de limpieza en las tres nubes y revocación de tokens (DuckDNS)", "sesión de solo lectura", "NOT_TESTED"],
    ["Capturas de saldo de Academy y Cost Management", "sesión de consola", "NOT_TESTED"],
    ["Repetir T5 con caída abrupta de instancia y tráfico de escritura", "ventana y presupuesto", "NOT_TESTED"],
    ["MFA en la aplicación y trail de CloudTrail", "desarrollo / cuenta no Academy", "DISEÑO"],
], widths=[7.5, 4.5, 3], caption="Pendientes al cierre del informe", source="Fuente: `docs/evidencias/AUTORIZACIONES-T6-T7.md`, `T6-20261123-estado-local.md`, criterios T8.", color_col=2)

# =====================================================================================
D.h("Referencias y glosario", 1)
D.h("Referencias internas", 2)
D.bullets([
    "Rúbrica oficial: «rúbrica proyecto_qod3szrctm.xlsx», hoja «Rúbrica».",
    "Expedientes reales: `work/evidencias/T1…T5-*/` (no versionados; manifiestos SHA-256).",
    "Resultados y autorizaciones: `docs/evidencias/T*-resultado.md`, `*-TARJETA-*.md`, `AUTORIZACIONES-T6-T7.md`, `REGISTRO-CIERRE-T6-T8.md`.",
    "Entregables previos: `docs/entregable2/informe-entregable2.md`, `docs/entregable3/15-informe-consolidado-entregable3.md`.",
    "Infraestructura: `infra/aws`, `infra/aws-v2`, `infra/aws-recovery`, `infra/oci`, `infra/azure`.",
    "T7: rama `codex/t7-t8` (`nexoops/`, `deploy/nexoops/`, `docs/codex/`).",
    "Inventario maestro y matriz: `docs/entrega-final/INVENTARIO-MAESTRO-EVIDENCIAS.xlsx`, `MATRIZ-RUBRICA-EVIDENCIAS.xlsx`.",
])
D.h("Glosario", 2)
D.table(["Término", "Definición"], [
    ["ALB / ASG", "Application Load Balancer / Auto Scaling Group de AWS"], ["PAR", "Pre-Authenticated Request de OCI: URL temporal con permisos sobre objetos"],
    ["CAS", "Compare-and-swap: escritura condicionada al ETag vigente (`If-Match`)"], ["Lease", "Permiso temporal y exclusivo de escritor, con época monótona"],
    ["Testigo", "Servicio que registra informes firmados en una cadena de hashes y atesta el estado"], ["CMS", "Cryptographic Message Syntax: sobre cifrado AES-256 con clave pública"],
    ["PITR", "Point-in-time recovery de RDS"], ["RTO / RPO", "Tiempo de recuperación / punto de recuperación (pérdida máxima tolerada)"],
    ["SCP", "Service Control Policy de la organización de AWS (Academy)"], ["OTP", "One-time password (código de un solo uso por correo)"],
], widths=[3, 12], caption="Glosario", source="Fuente: elaboración propia.")
D.h("Anexo A. Evidencias clave (extracto del inventario)", 2)
key = [i for i in INV if i["id"] in set(D.used)]
key = sorted({i["id"]: i for i in key}.values(), key=lambda i: (i["etapa"], i["id"]))
D.table(["ID", "Etapa", "Ruta", "Fecha UTC", "Resultado", "SHA-256 (12)"],
        [[i["id"], i["etapa"], i["ruta"], i["fecha_utc"], i["resultado"], (i["sha256"] or "—")[:12]] for i in key],
        widths=[2.1, 1, 7.3, 2.4, 2.2, 2], caption=f"Evidencias citadas en este informe ({len(key)} de {len(INV)})",
        source="Fuente: `INVENTARIO-MAESTRO-EVIDENCIAS.xlsx` (ruta completa, tipo, naturaleza, limitación y SHA-256 completo).", size=6.8)
D.pj("El control de calidad del paquete (conversión a PDF, recuento y revisión de páginas, criterios analizados, búsqueda de secretos y validez del ZIP) está en `docs/entrega-final/control-calidad/CONTROL-CALIDAD.md`.")

D.save(f"{S}/build/informe_raw.docx")
json.dump(sorted(set(D.used)), open(f"{S}/build/usados.json", "w"))
print("ok, evidencias citadas:", len(set(D.used)))
