#!/usr/bin/env python3
"""Auditoría ESTÁTICA (no ejecuta nada de nube) del script de solo lectura de AWS.
Comprueba: (1) toda llamada a `aws` usa una acción de consulta (describe-*, get-caller-identity; simulate-principal-policy solo en la sección opcional `permisos`);
(2) ninguna palabra de modificación en el código (los nombres de acción IAM del bloque --action-names se excluyen: son texto que se SIMULA, no comandos);
(3) ningún instalador, escritura de archivos ni lectura de ~/.aws; (4) el filtro de salida oculta lo sensible (prueba local con ejemplos, sin red);
(5) tabla de permisos IAM que necesita cada llamada.
Uso: python3 scripts/multicloud/auditar-solo-lectura-aws.py scripts/multicloud/viabilidad-readonly-aws.sh"""
import re, subprocess, sys
from pathlib import Path

path = Path(sys.argv[1]); text = path.read_text()
code = [l for l in text.splitlines() if l.strip() and not l.lstrip().startswith("#")]
fails = []
IAM = {("elbv2", "describe-listeners"): "elasticloadbalancing:DescribeListeners", ("elbv2", "describe-rules"): "elasticloadbalancing:DescribeRules", ("elbv2", "describe-target-groups"): "elasticloadbalancing:DescribeTargetGroups",
       ("elbv2", "describe-target-health"): "elasticloadbalancing:DescribeTargetHealth", ("elbv2", "describe-load-balancer-attributes"): "elasticloadbalancing:DescribeLoadBalancerAttributes",
       ("ec2", "describe-network-interfaces"): "ec2:DescribeNetworkInterfaces", ("ec2", "describe-launch-templates"): "ec2:DescribeLaunchTemplates", ("ec2", "describe-images"): "ec2:DescribeImages", ("ec2", "describe-snapshots"): "ec2:DescribeSnapshots",
       ("acm", "list-certificates"): "acm:ListCertificates", ("rds", "describe-db-snapshots"): "rds:DescribeDBSnapshots", ("rds", "describe-db-instance-automated-backups"): "rds:DescribeDBInstanceAutomatedBackups",
       ("rds", "describe-pending-maintenance-actions"): "rds:DescribePendingMaintenanceActions", ("s3api", "list-buckets"): "s3:ListAllMyBuckets", ("s3api", "list-objects-v2"): "s3:ListBucket",
       ("cloudwatch", "describe-alarms"): "cloudwatch:DescribeAlarms", ("secretsmanager", "list-secrets"): "secretsmanager:ListSecrets", ("logs", "describe-log-groups"): "logs:DescribeLogGroups",
       ("sts", "get-caller-identity"): "(ninguno: no requiere permiso)", ("ec2", "describe-instances"): "ec2:DescribeInstances", ("autoscaling", "describe-auto-scaling-groups"): "autoscaling:DescribeAutoScalingGroups",
       ("elbv2", "describe-load-balancers"): "elasticloadbalancing:DescribeLoadBalancers", ("ec2", "describe-nat-gateways"): "ec2:DescribeNatGateways", ("ec2", "describe-addresses"): "ec2:DescribeAddresses",
       ("ec2", "describe-volumes"): "ec2:DescribeVolumes", ("rds", "describe-db-instances"): "rds:DescribeDBInstances", ("rds", "describe-events"): "rds:DescribeEvents",
       ("rds", "describe-db-parameter-groups"): "rds:DescribeDBParameterGroups", ("rds", "describe-db-engine-versions"): "rds:DescribeDBEngineVersions", ("rds", "describe-db-parameters"): "rds:DescribeDBParameters",
       ("ec2", "describe-vpcs"): "ec2:DescribeVpcs", ("ec2", "describe-subnets"): "ec2:DescribeSubnets", ("ec2", "describe-route-tables"): "ec2:DescribeRouteTables",
       ("ec2", "describe-security-groups"): "ec2:DescribeSecurityGroups", ("ec2", "describe-vpn-gateways"): "ec2:DescribeVpnGateways", ("iam", "simulate-principal-policy"): "iam:SimulatePrincipalPolicy (solo sección opcional `permisos`)"}

print(f"Archivo: {path}  ·  {len(code)} líneas de código")
print("\n[1] Llamadas a la CLI de AWS (servicio acción → permiso IAM necesario):")
calls = []
for l in code:
    if l.lstrip().startswith(("run()", "raw()")):
        continue
    m = re.search(r'(?:^|[\s=($;]|echo "[^"]*";\s*)(?:run|raw)\s+([a-z0-9]+)\s+([a-z0-9-]+)', l)
    if m:
        calls.append(m.groups())
for s, a in calls:
    ok = a.startswith(("describe-", "list-")) or (s, a) in (("sts", "get-caller-identity"), ("iam", "simulate-principal-policy"))
    print(f"   {'OK ' if ok else 'MAL'} aws {s} {a:<32} → {IAM.get((s, a), '??')}")
    if not ok:
        fails.append(f"acción no consultiva: {s} {a}")
    if (s, a) not in IAM:
        fails.append(f"llamada sin permiso documentado: {s} {a}")
direct = [l.strip() for l in code if re.search(r'(^|[;&|(]|\s)aws\s', l) and not re.search(r'(run|raw)\(\)', l) and not l.strip().startswith(("command -v", "abortar()", "echo", "[["))]
print("   (llamadas directas a `aws` fuera de run/raw:", len(direct), ")")
for d in direct:
    print("     ", d[:110]); fails.append("llamada directa a aws: " + d[:60])

print("\n[2] Palabras de modificación en el código (no comentarios; sin los nombres de acción IAM simulados):")
forbidden = r'\b(create|update|delete|launch|start|stop|terminate|reboot|reset|attach|detach|move|change|import|export|put|post|patch|configure|sso|generate|rotate|upload|download|copy|restore|rename|remove|add|activate|cancel|authorize|allocate|associate|register|run-instances|modify|revoke|invoke|tag|enable|disable|replace|apply|set)\b'
hits = []
in_actions = False
for l in code:
    if l.strip().startswith("set -uo pipefail"):
        continue                                   # opción del propio shell, no una orden de AWS
    if "--action-names" in l:
        in_actions = True
        l = l.split("--action-names")[0]
    elif in_actions and re.match(r'\s+(rds|ec2|s3|secretsmanager|iam):', l.lstrip() + ""):
        continue
    elif in_actions and l.lstrip().startswith("--query"):
        in_actions = False
    if l.strip().startswith(("echo", "abortar()")):
        l = re.sub(r'"[^"]*"', '""', l)
    l2 = re.sub(r"'[^']*'", "''", l)       # los textos entre comillas simples (consultas JMESPath) no son comandos
    l2 = re.sub(r'\b(describe|list)-[a-z0-9-]+', 'ACCION_DE_CONSULTA', l2)   # los nombres de acciones de consulta (p. ej. describe-launch-templates) no son órdenes de lanzar
    l2 = re.sub(r'"[^"$]*"', '""', l2)
    for m in re.finditer(forbidden, l2):
        hits.append((m.group(1), l.strip()[:90]))
print("   ", "ninguna" if not hits else hits)
fails += [f"palabra prohibida {w}" for w, _ in hits]

print("\n[3] Instaladores, escritura de archivos, otras herramientas y lectura de credenciales locales:")
bad_tools = r'\b(pip3?|brew|apt|yum|dnf|curl|wget|sudo|rm|mv|cp|tee|eval|chmod|chown|ssh|scp|git|terraform|oci|az|docker|python3?)\b'
bt = [(m.group(1), l.strip()[:80]) for l in code for m in re.finditer(bad_tools, re.sub(r"'[^']*'|\"[^\"]*\"", "''", l))]
print("   herramientas no permitidas:", "ninguna" if not bt else bt)
fails += [f"herramienta {t}" for t, _ in bt]
def sin_textos(l): return re.sub(r"'[^']*'|\"[^\"]*\"", "''", l)
redirs = [l.strip()[:80] for l in code if re.search(r'(?<![0-9&])>(?![&])', sin_textos(l)) and '/dev/null' not in l]
print("   redirecciones de salida a archivos:", "ninguna" if not redirs else redirs)
fails += ["redirección a archivo: " + r for r in redirs]
creds = [l.strip()[:90] for l in code if re.search(r'~/\.aws|\.aws/|credentials|AWS_SECRET|AWS_ACCESS|AWS_SESSION', re.sub(r'\[\[ -n "\$\{AWS_ACCESS_KEY_ID:-\}" \]\]', '', l))]  # solo se admite comprobar si la variable existe
print("   lecturas de ~/.aws o de claves en variables:", "ninguna" if not creds else creds)
fails += ["acceso a credenciales: " + c for c in creds]
used = sorted(set(re.findall(r'\b(aws|env|sed|printf|command|read|echo|exit|tail)\b', "\n".join(code))))
print("   programas usados:", ", ".join(used))

print("\n[4] Prueba local del filtro de salida (sin red), con datos sensibles de ejemplo:")
fn = re.search(r'mask\(\) \{\n(.*?)\n\}', text, re.S).group(1)
script = "set -u\nmask() {\n" + fn + "\n}\nmask\n"
samples = [
    "arn:aws:sts::123456789012:assumed-role/voclabs/user4567890=Nombre_Apellido",
    "An error occurred (ExpiredToken): The security token included in the request is expired",
    "AccessKeyId ASIAIOSFODNN7EXAMPLE y AKIAIOSFODNN7EXAMPLE",
    "aws_secret_access_key = wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
    "SessionToken: IQoJb3JpZ2luX2VjEJr//////////wEaCXVzLWVhc3QtMSJHMEUCIQDExampleExampleExampleExample",
    "i-0123456789abcdef0 vpc-0a1b2c3d4e5f60718 subnet-0123456789abcdef0 igw-0abc123def456789a",
    "IP 54.210.33.99 correo persona@correo.com cuenta 210987654321",
    "-----BEGIN RSA PRIVATE KEY-----",
    "+---------------+",
]
leaks = []
for s in samples:
    o = subprocess.run(["bash", "-c", script], input=s + "\n", capture_output=True, text=True).stdout.strip()
    print(f"   {s[:60]:<60} -> {o[:70] or '(línea eliminada)'}")
    for secret in ("123456789012", "4567890", "ASIAIOSFODNN7", "AKIAIOSFODNN7", "wJalrXUtn", "IQoJb3Jp", "0123456789abcdef0", "0a1b2c3d4e5f60718", "54.210.33.99", "persona@correo.com", "210987654321", "PRIVATE KEY", "voclabs/user"):
        if secret in o:
            leaks.append(secret)
if leaks:
    fails.append("el filtro deja pasar: " + ", ".join(sorted(set(leaks))))

print("\nRESULTADO:", "APTO: solo consultas, sin instalación ni escritura, salida filtrada" if not fails else "NO APTO: " + "; ".join(fails))
sys.exit(0 if not fails else 1)
