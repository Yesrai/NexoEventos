#!/usr/bin/env python3
"""Comprobaciones estáticas (sin AWS ni credenciales) de las reglas de seguridad de infra/aws-v2. Uso: python3 infra/aws-v2/tests/check_security.py"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
tf = {p.name: p.read_text() for p in ROOT.glob("*.tf")}
allt = "\n".join(tf.values())


def block(name: str, kind: str = "resource") -> str:
    m = re.search(rf'{kind} "[^"]+" "{name}" \{{(.*?)\n\}}\n', allt, re.S)
    assert m, f"no existe {name}"
    return m.group(1)


errors = []
def check(ok: bool, msg: str) -> None:
    print(("OK    " if ok else "FALLÓ ") + msg)
    if not ok:
        errors.append(msg)

# 1) Solo el ALB acepta tráfico de Internet.
open_rules = re.findall(r'resource "aws_vpc_security_group_ingress_rule" "(\w+)" \{(.*?)\n\}', allt, re.S)
public = sorted(n for n, body in open_rules if '"0.0.0.0/0"' in body or '"::/0"' in body)
check(public == ["alb_http", "alb_https"], f"Entradas abiertas a Internet solo en el ALB (80 y 443): {public}")
web_in = [(n, b) for n, b in open_rules if "aws_security_group.web.id" in b.split("security_group_id")[1].split("\n")[0]]
check(len(web_in) == 1 and "referenced_security_group_id = aws_security_group.alb.id" in web_in[0][1] and "from_port                    = 80" in web_in[0][1],
      "Las instancias solo aceptan el puerto 80 y solo desde el grupo de seguridad del ALB")
check(not re.search(r"from_port\s*=\s*22\b", allt), "Sin SSH (puerto 22) en ninguna regla")
db_in = [b for n, b in open_rules if "data.aws_security_group.database.id" in b]
check(len(db_in) == 1 and "aws_security_group.web.id" in db_in[0], "La base solo recibe una regla nueva y desde las instancias de V2")
# 2) Instancias.
lt = block("web", "resource").split("resource")[0] if False else re.search(r'resource "aws_launch_template" "web" \{(.*?)\n\}\n', allt, re.S).group(1)
check('http_tokens                 = "required"' in lt, "IMDSv2 obligatorio")
check("encrypted             = true" in lt, "Volumen raíz cifrado")
check("associate_public_ip_address = true" in lt and "map_public_ip_on_launch = false" in tf["network.tf"], "La IP pública se pide por instancia en el launch template; la subred no la asigna por defecto (AWS-0164)")
check("vpc_security_group_ids" not in lt and "security_groups             = [aws_security_group.web.id]" in lt, "El launch template conserva el grupo de seguridad de las instancias")
check("user_data" in lt and "secret_string" not in allt and "password" not in allt.lower().replace("passwords", ""), "Sin secretos ni contraseñas en el código (solo el nombre del secreto)")
# 3) Auto Scaling / ALB.
asg = re.search(r'resource "aws_autoscaling_group" "web" \{(.*?)\n\}\n', allt, re.S).group(1)
check('health_check_type         = "ELB"' in asg and "var.asg_min >= 2" in asg, "ASG con health check ELB y mínimo de 2 instancias")
check(len(re.findall(r"data\.aws_availability_zones", tf["network.tf"])) >= 1 and "aws_subnet.public_b.id" in asg and "data.aws_subnet.public_a.id" in asg, "ASG distribuido en dos subredes (zonas) distintas")
check('var.ami_includes_livez ? "/livez" : "/healthz"' in tf["alb.tf"] and 'health_check_type         = "ELB"' in tf["compute.tf"], "El health check del ALB es de liveness (/livez) solo si la AMI lo incluye (ami_includes_livez), si no /healthz; el ASG usa el de ELB")
check(re.search(r'variable "ami_includes_livez" \{.*?default\s*=\s*false', tf["variables.tf"], re.S) is not None, "ami_includes_livez es false por defecto: una AMI antigua nunca recibe /livez (evita la falsa salud por try_files)")
check('"/livez"' in tf["alb.tf"] and 'type    = "lb_cookie"' in tf["alb.tf"] and "enabled = false" in tf["alb.tf"], "Health check /livez y sin afinidad de sesión")
check("ASGAverageCPUUtilization" in tf["compute.tf"], "Política de escalado medible por CPU")
check("drop_invalid_header_fields = true" in tf["alb.tf"] and "TLS13-1-2" in tf["alb.tf"], "ALB con política TLS 1.2/1.3 y cabeceras inválidas descartadas")
sys.exit(1 if errors else 0)
