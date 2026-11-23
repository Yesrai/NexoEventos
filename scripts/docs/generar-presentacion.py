#!/usr/bin/env python3
"""Genera la presentación del Entregable 2 con python-pptx a partir de las evidencias del repositorio."""
import pathlib
from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from PIL import Image
R = pathlib.Path(__file__).resolve().parents[2]
D = R / "docs/entregable2"; C = R / "docs/evidencias/capturas/aws"
NAVY, GREY, RED, GREEN = RGBColor(0x12, 0x35, 0x5B), RGBColor(0x55, 0x55, 0x55), RGBColor(0xB0, 0x2A, 0x2A), RGBColor(0x1E, 0x7B, 0x3A)
prs = Presentation(); prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)
def slide(title, notes=""):
    s = prs.slides.add_slide(prs.slide_layouts[6])
    tb = s.shapes.add_textbox(Inches(0.5), Inches(0.3), Inches(12.3), Inches(0.9)); p = tb.text_frame.paragraphs[0]
    p.text = title; p.font.size = Pt(30); p.font.bold = True; p.font.color.rgb = NAVY
    s.notes_slide.notes_text_frame.text = notes
    return s
def bullets(s, items, x=0.6, y=1.4, w=12.0, h=5.5, size=20):
    tf = s.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h)).text_frame; tf.word_wrap = True
    for i, it in enumerate(items):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        col = None
        if it.startswith("✔ "): col = GREEN
        elif it.startswith("✘ "): col = RED
        p.text = it; p.font.size = Pt(size); p.space_after = Pt(8)
        if col: p.font.color.rgb = col
def image(s, path, x, y, w, h, caption=None):
    im = Image.open(path); r = min(w / im.width, h / im.height); pw, ph = im.width * r, im.height * r
    s.shapes.add_picture(str(path), Inches(x + (w - pw) / 2), Inches(y), Inches(pw), Inches(ph))
    if caption:
        tf = s.shapes.add_textbox(Inches(x), Inches(y + ph + 0.05), Inches(w), Inches(0.6)).text_frame; tf.word_wrap = True
        tf.paragraphs[0].text = caption; tf.paragraphs[0].font.size = Pt(12); tf.paragraphs[0].font.color.rgb = GREY
def table(s, rows, x, y, w, colw, size=14):
    t = s.shapes.add_table(len(rows), len(rows[0]), Inches(x), Inches(y), Inches(w), Inches(0.45 * len(rows))).table
    for j, cw in enumerate(colw): t.columns[j].width = Inches(cw)
    for i, row in enumerate(rows):
        for j, v in enumerate(row):
            c = t.cell(i, j); c.text = v
            for p in c.text_frame.paragraphs: p.font.size = Pt(size); p.font.bold = (i == 0)

s = slide("NexoEventos — Entregable 2", "Presentación. Datos de portada (autora, equipo, docente, fecha) los completa la autora.")
bullets(s, ["Seguridad, optimización, escalabilidad y resiliencia (Arquitectura V2)", "Cloud Computing · Proyecto Integrador · UPeU", "[Autora / Equipo / Docente / Fecha: completar]", "", "Regla de la exposición: se distingue siempre lo MEDIDO, lo PROYECTADO y lo NO PROBADO."], y=2.2, size=24)

s = slide("El problema y el alcance", "Plataforma de reservas de entradas con QR. Sin sobreventa. FastAPI + PostgreSQL, React. AWS Academy como producción.")
bullets(s, ["Reservas de entradas con QR: aperturas masivas, sin sobreventa", "V1: una EC2 + RDS Single-AZ + S3 (AWS Academy)", "V2: ALB + Auto Scaling 2–3 EC2 en 2 zonas + RDS Multi-AZ", "Multicloud: AWS producción · OCI recuperación · Azure observabilidad", "Restricción real: AWS Academy (IAM no modificable, sesiones temporales, presupuesto limitado)"])

s = slide("Arquitectura V1 → V2", "V1 tenía dos puntos únicos de fallo: la EC2 y la base Single-AZ. V2 los elimina con ALB, Auto Scaling y Multi-AZ.")
image(s, D / "diagramas/v1-arquitectura.png", 0.3, 1.3, 6.3, 5.6, "V1: EC2 única + RDS Single-AZ")
image(s, D / "diagramas/v2-arquitectura.png", 6.7, 1.3, 6.3, 5.6, "V2: ALB + ASG 2–3 EC2 (2 zonas) + RDS Multi-AZ")

s = slide("Evolución medida V1 vs V2", "Mismo generador de carga, hasta 50 usuarios. V2 está destruida: se conserva la evidencia, no el servicio.")
table(s, [["Métrica (50 usuarios)", "V1", "V2"], ["p95 de latencia", "288 ms", "190 ms"], ["CPU por instancia", "39,4 %", "20 %"], ["Errores 5xx", "—", "0 en 35 366 solicitudes"], ["Reparto entre instancias", "n/a", "50 % / 50 %"]], 0.8, 1.6, 11.5, [4.5, 3.0, 4.0], 18)
bullets(s, ["Medido solo hasta 50 usuarios simultáneos. 100–5 000 usuarios: PROYECCIÓN."], y=5.0, size=18)

s = slide("Multicloud", "AWS produce, OCI recupera, Azure observa. Cada nube cumple una función distinta; no hay conmutación automática.")
image(s, D / "diagramas/v2-multicloud.png", 0.8, 1.3, 11.7, 5.6)

s = slide("Seguridad AWS: lo verificado", "Verificado por API el 28/29-oct y con capturas de consola. Lo ausente se declara.")
bullets(s, ["✔ RDS cifrada, no pública, Multi-AZ, TLS obligatorio (rds.force_ssl=1), copias 7 días",
            "✔ EBS cifrado · IMDSv2 obligatorio · S3 privado, cifrado y versionado",
            "✔ SG web: 80/443 de entrada, sin SSH · SG base: 5432 solo desde el SG web · subredes de datos sin ruta a Internet",
            "✔ 0 usuarios IAM; LabRole (Academy) con 7 políticas; 3 no legibles",
            "✘ Sin trail de CloudTrail · alarma sin acciones · RDS sin protección contra borrado · sin MFA en la app",
            "✘ Permisos efectivos de LabRole no comprobados"], size=19)

s = slide("Evidencia: configuración de red", "Capturas auténticas con datos sensibles ocultos.")
image(s, C / "05-web-sg-entrada.png", 0.3, 1.3, 6.4, 4.5, "SG web: entrada 443/80, sin puerto 22")
image(s, C / "04-web-sg-salida.png", 6.8, 1.3, 6.2, 4.5, "SG web: salida DNS, HTTPS y 5432")

s = slide("Escalabilidad: secuencia observada", "La gráfica demuestra la secuencia de instancias; no asocia un número de usuarios al cambio.")
image(s, C / "06-asg-escalabilidad.png", 0.5, 1.3, 7.6, 5.3, "CloudWatch · GroupInServiceInstances · 22-oct · 14:00–18:00 UTC")
bullets(s, ["0 → 2 → 3 → 2 → 0 instancias", "Alarma de CPU a los 8 min 6 s; tercera instancia sana en ≈ 9 min", "El escalado reactivo es lento: para aperturas masivas hace falta capacidad precalentada", "Medido ≤ 50 usuarios; ≥ 100: proyección"], x=8.3, y=1.5, w=4.7, size=17)

s = slide("Tolerancia a fallos: qué se probó", "Ser explícita: A–D medidos; E y F NO ejecutados.")
table(s, [["Caso", "Estado", "Resultado"], ["A. Fallo de proceso en una instancia", "Medido", "Detección 20,0 s; 25/275 con 502"], ["B. Destino no sano en el ALB", "Medido", "Sanos 2 → 1 → 2"], ["C. Sustitución por Auto Scaling", "Medido", "≈ 2,5 min"], ["D. Failover RDS Multi-AZ", "Medido", "≈ 14 s; datos idénticos"], ["E. Caída completa de una zona", "NO ejecutado", "—"], ["F. AWS FIS", "NO ejecutado", "—"]], 0.6, 1.5, 12.1, [5.2, 2.4, 4.5], 17)

s = slide("Evidencia de los fallos del 22-oct", "Las gráficas muestran los hechos; la recuperación se sustenta en los registros de prueba. UnHealthy no se ve en la repetición de las 16:38: límite declarado.")
image(s, C / "07-alb-errores-5xx.png", 0.3, 1.3, 4.3, 3.2, "5xx: 25 (16:03) y 40 (16:38)")
image(s, C / "08-alb-healthy-hosts.png", 4.5, 1.3, 4.3, 3.2, "Destinos sanos: 2 → 1 → 2")
image(s, C / "11-rds-failover-22oct.png", 8.8, 1.3, 4.3, 3.2, "Eventos RDS: failover solicitado y completado")
bullets(s, ["La gráfica de 5xx no prueba por sí sola la recuperación: se contrasta con los registros de las pruebas", "Eventos RDS en hora local (UTC−5): 22-oct 20:08 = 23-oct 01:08Z"], y=5.2, size=17)

s = slide("Observabilidad multicloud", "El correo recibido en la verificación del receptor NO es una entrega de alerta.")
bullets(s, ["✔ Azure Monitor: alerta de CPU disparada y resuelta (detección a los 17 min 54 s)",
            "✔ Zabbix + Grafana en Azure: detectaron AWS V1 apagado y la carga de CPU",
            "✔ Receptor de correo del grupo de acción verificado",
            "✘ Entrega real de un correo de alerta: NO demostrada (la prueba devolvió «Free subscription not supported»)",
            "✘ Alertas de memoria y disponibilidad: creadas, nunca disparadas",
            "AWS: 40 series originales de CloudWatch recuperadas (RDS/ALB/ASG a 60 s; EC2 a 300 s)"], size=19)

s = slide("Respaldo y recuperación", "OCI recupera la aplicación completa; en AWS la recuperación completa con DNS y HTTPS no está acreditada.")
table(s, [["Prueba", "Resultado"], ["PITR de la RDS (R01)", "Datos en 21 min 4 s · RPO 3 min 32 s"], ["Respaldo cifrado CMS → OCI", "SHA-256 coincide · descifra a PGDMP"], ["Aplicación completa en OCI", "14/14 pruebas · 32 min 42 s · huella 10/10"], ["Recuperación completa en AWS", "NO acreditada (12-oct incompleta)"], ["Respaldo programado", "NO existe (solo por ventana)"]], 0.8, 1.6, 11.7, [5.2, 6.5], 18)

s = slide("DevOps: lo que existe", "No hay despliegue continuo: el pipeline construye y prueba. Los despliegues fueron manuales con Terraform y Ansible.")
bullets(s, ["✔ Git con historial de commits por cambio y evidencia", "✔ Terraform: aws, aws-v2, aws-recovery, oci, azure, gcp (validate OK; 29 comprobaciones de seguridad de IaC)", "✔ Ansible: monitoreo Zabbix/Grafana y recuperación", "✔ CI (GitHub Actions): backend pytest+PostgreSQL 18, frontend, imagen Docker + Trivy, Trivy del repositorio", "✔ Pruebas: backend 44/44, frontend 33/33", "✘ Sin despliegue continuo (CD); el pipeline no usa credenciales de nube"], size=19)

s = slide("Costes y riesgos residuales", "Presupuestos solo avisan, no frenan el gasto.")
bullets(s, ["Costes por ventana acotada; recursos apagados entre pruebas (RDS reiniciada por ciclo start-stop el 28-oct)", "Riesgo: la RDS se reinicia sola a los 7 días detenida (próximo ≈ 4-nov)", "Riesgo: AWS Academy puede encender la EC2 al reiniciar el laboratorio", "Residuales: región única, zona completa no probada, certificado ACM vence 1-ene-2027, LabRole amplio", "Costes reales facturados: no verificados (sin Cost Explorer)"], size=19)

s = slide("Conclusiones", "Cerrar con honestidad: qué mejoró, qué no se probó.")
bullets(s, ["V2 elimina los dos SPOF de V1, medido: detección 20 s, reemplazo ≈ 2,5 min, failover ≈ 14 s", "Datos fuera de una sola cuenta: recuperación completa en OCI en 32 min 42 s", "Seguridad verificada por API y consola, con ausencias declaradas", "NO probado: caída de zona, FIS, carga > 50 usuarios, entrega real de correo, recuperación completa en AWS", "Siguiente: respaldo programado, CloudTrail, acciones en alarmas, MFA"], size=20)
out = D / "presentacion/NexoEventos-Entregable2.pptx"; prs.save(out); print(out, len(prs.slides))
