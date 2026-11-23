#!/usr/bin/env python3
"""Auditoría de SOLO LECTURA de AWS (estado de RDS y riesgo de reinicio automático, recursos que cuestan, IAM, red, cifrado, CloudTrail, logs y alarmas).
Garantías en CÓDIGO (no solo en la intención): toda llamada pasa por `guard()`, que solo admite operaciones describe-/get-/list- de una lista blanca de servicios y RECHAZA cualquier inicio, parada,
reinicio, modificación, borrado, creación, lectura de secretos u objetos y Cost Explorer (`ce`: cada consulta tiene cargo). No inicia el laboratorio ni usa credenciales distintas de las del perfil.
Si la sesión no está activa (token caducado) termina con un mensaje; no reintenta. Los identificadores (cuenta, ARN, IP, ID de recursos, correos) se enmascaran ANTES de guardar el resumen.
Uso: readonly-audit.py [--profile nexoeventos-lab] [--region us-east-1] [--out docs/evidencias/multicloud/aws/AAAAMMDD-solo-lectura] [--dry-run] [--selftest]"""
import argparse, datetime as dt, json, os, pathlib, re, subprocess, sys

ap = argparse.ArgumentParser(); ap.add_argument("--profile", default="nexoeventos-lab"); ap.add_argument("--region", default="us-east-1")
ap.add_argument("--out"); ap.add_argument("--dry-run", action="store_true"); ap.add_argument("--selftest", action="store_true"); a = ap.parse_args()
ROOT = pathlib.Path(__file__).resolve().parents[2]
ALLOWED_SERVICES = {"sts", "rds", "ec2", "elbv2", "autoscaling", "cloudwatch", "cloudtrail", "iam", "s3api", "secretsmanager", "logs", "acm", "budgets"}
DENY_OPS = {"get-object", "get-object-attributes", "get-secret-value", "get-parameter", "get-parameters", "get-password-data", "get-console-output", "get-console-screenshot", "get-session-token",
            "get-federation-token", "get-credential-report", "get-login-profile", "get-access-key-last-used", "get-certificate"}
DENY_WORDS = re.compile(r"(start|stop|reboot|modify|create|delete|put|update|terminate|run-|attach|detach|associate|disassociate|enable|disable|restore|promote|failover|import|export|send|invoke|tag|untag|set-|register|deregister|cancel|purchase|release|allocate|revoke|authorize|reset)")

READ_ONLY_EXCEPTIONS = {"list-attached-role-policies"}  # lectura pura; el nombre contiene "attach"


def guard(service, op):
    if service == "ce": raise PermissionError("Cost Explorer (ce) tiene cargo por consulta: requiere autorización explícita")
    if service not in ALLOWED_SERVICES: raise PermissionError(f"servicio no permitido: {service}")
    if op in DENY_OPS or (op not in READ_ONLY_EXCEPTIONS and DENY_WORDS.search(op)): raise PermissionError(f"operación no permitida (no es de solo lectura): {service} {op}")
    if not op.startswith(("describe-", "get-", "list-")) and not (service == "sts" and op == "get-caller-identity"): raise PermissionError(f"operación no admitida: {service} {op}")


def mask(t):
    t = re.sub(r"arn:aws[a-z-]*:([a-z0-9-]+):([a-z0-9-]*):\d{12}:", r"arn:aws:\1:\2:<cuenta>:", t)
    t = re.sub(r"(?<!\d)\d{12}(?!\d)", "<cuenta>", t)
    t = re.sub(r"\b(i|vol|snap|ami|eni|sg|subnet|vpc|eipalloc|nat|vpce)-[0-9a-f]{8,17}\b", lambda m: f"{m.group(1)}-…{m.group(0)[-4:]}", t)
    t = re.sub(r"(?<![\d.])\d{1,3}(\.\d{1,3}){3}(?![\d.])", "<ip>", t)
    t = re.sub(r"[\w.+-]+@[\w-]+\.[a-z]{2,}", "<correo>", t)
    t = re.sub(r"[a-z0-9-]+\.[a-z0-9]+\.[a-z0-9-]+\.rds\.amazonaws\.com", "<endpoint-rds>", t)
    return t


def aws(*args):
    guard(args[0], args[1])
    r = subprocess.run(["aws", "--profile", a.profile, "--region", a.region, *args, "--output", "json"], capture_output=True, text=True)
    if r.returncode:
        err = mask(r.stderr.strip())[-260:]
        return {"_error": err}
    return json.loads(r.stdout or "{}")


def iso(t): return dt.datetime.fromisoformat(t.replace("Z", "+00:00")) if isinstance(t, str) else t


if a.selftest:
    for s, o in [("rds", "describe-db-instances"), ("sts", "get-caller-identity"), ("cloudtrail", "describe-trails"), ("s3api", "get-bucket-encryption")]: guard(s, o)
    for s, o in [("rds", "stop-db-instance"), ("rds", "start-db-instance"), ("ec2", "start-instances"), ("ec2", "terminate-instances"), ("rds", "reboot-db-instance"), ("s3api", "get-object"),
                 ("secretsmanager", "get-secret-value"), ("ce", "get-cost-and-usage"), ("iam", "create-user"), ("ssm", "describe-instance-information"), ("cloudwatch", "put-metric-alarm"), ("rds", "modify-db-instance")]:
        try: guard(s, o); raise SystemExit(f"FALLO: debió rechazar {s} {o}")
        except PermissionError: pass
    m = mask("arn:aws:iam::123456789012:role/LabRole i-0123456789abcdef0 10.20.1.5 yo@ejemplo.com nexo.cabc123.us-east-1.rds.amazonaws.com cuenta 123456789012")
    assert "123456789012" not in m and "0123456789abcdef0" not in m and "10.20.1.5" not in m and "yo@ejemplo.com" not in m and "rds.amazonaws.com" not in m, m
    print("selftest OK (la guarda rechaza 12 operaciones de escritura/costo y admite las de lectura; el enmascarado oculta cuenta, IDs, IP, correo y endpoint)"); sys.exit(0)

PLAN = ["sts get-caller-identity", "rds describe-db-instances", "rds describe-events (14 días)", "rds describe-db-snapshots", "ec2 describe-instances / volumes / snapshots / images / addresses / nat-gateways / vpc-endpoints",
        "elbv2 describe-load-balancers", "autoscaling describe-auto-scaling-groups", "s3api list-buckets + get-bucket-versioning/encryption/public-access-block/lifecycle", "secretsmanager list-secrets (sin valores)",
        "cloudwatch describe-alarms / list-dashboards", "logs describe-log-groups", "cloudtrail describe-trails / get-trail-status", "iam get-role (rol de laboratorio) / list-attached-role-policies / get-instance-profile", "acm list-certificates"]
if a.dry_run:
    print("Llamadas previstas (todas de solo lectura; ninguna inicia, detiene ni modifica nada):"); [print(" -", p) for p in PLAN]; print("Excluido por costo: Cost Explorer (ce)."); sys.exit(0)

who = aws("sts", "get-caller-identity")
if "_error" in who:
    print("SIN SESIÓN ACTIVA:", who["_error"]); print("No se intentó nada más. Necesita iniciar el laboratorio de AWS Academy y renovar las credenciales (autorización de la propietaria)."); sys.exit(2)
R = {"generado_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "sesion": "activa (identidad enmascarada)", "region": a.region}
now = dt.datetime.now(dt.timezone.utc)

# --- RDS: estado y riesgo de reinicio automático
dbs = aws("rds", "describe-db-instances").get("DBInstances", [])
R["rds"] = [{"estado": d["DBInstanceStatus"], "clase": d["DBInstanceClass"], "motor": f'{d["Engine"]} {d["EngineVersion"]}', "multi_az": d["MultiAZ"], "almacenamiento_gib": d["AllocatedStorage"], "tipo_almacenamiento": d.get("StorageType"),
             "cifrada": d["StorageEncrypted"], "publica": d["PubliclyAccessible"], "retencion_backups_dias": d["BackupRetentionPeriod"], "proteccion_borrado": d["DeletionProtection"], "autoescalado_almacenamiento": "MaxAllocatedStorage" in d} for d in dbs]
ev = aws("rds", "describe-events", "--source-type", "db-instance", "--duration", "20160").get("Events", [])
ev_s = sorted(((iso(e["Date"]), e["Message"]) for e in ev), key=lambda x: x[0])
R["rds_eventos_relevantes"] = [{"fecha_utc": d.isoformat(timespec="seconds"), "mensaje": mask(m)} for d, m in ev_s if re.search(r"stopped|started|shutdown|failover|Multi-AZ|automatically", m, re.I)][-14:]
stops = [d for d, m in ev_s if re.search(r"DB instance stopped|shutdown", m, re.I)]; starts = [d for d, m in ev_s if re.search(r"DB instance started", m, re.I)]
R["rds_riesgo_reinicio"] = {"ultima_parada_utc": stops[-1].isoformat(timespec="seconds") if stops else None, "ultimo_inicio_utc": starts[-1].isoformat(timespec="seconds") if starts else None}
if dbs and dbs[0]["DBInstanceStatus"] == "stopped" and stops and (not starts or stops[-1] > starts[-1]):
    lim = stops[-1] + dt.timedelta(days=7); R["rds_riesgo_reinicio"].update({"reinicio_automatico_estimado_utc": lim.isoformat(timespec="seconds"), "horas_restantes": round((lim - now).total_seconds() / 3600, 1),
        "nota": "AWS reinicia una RDS tras 7 días consecutivos detenida; la hora exacta puede variar. Los eventos solo cubren 14 días."})
snaps = aws("rds", "describe-db-snapshots").get("DBSnapshots", [])
R["rds_snapshots"] = {"manuales": sum(1 for s in snaps if s["SnapshotType"] == "manual"), "automaticos": sum(1 for s in snaps if s["SnapshotType"] == "automated"), "gib_total": sum(s.get("AllocatedStorage", 0) for s in snaps)}
# --- cómputo y almacenamiento que cuestan
ins = [i for r in aws("ec2", "describe-instances").get("Reservations", []) for i in r["Instances"]]
R["ec2"] = [{"id": mask(i["InstanceId"]), "estado": i["State"]["Name"], "tipo": i["InstanceType"], "imdsv2_obligatorio": i.get("MetadataOptions", {}).get("HttpTokens") == "required"} for i in ins]
vols = aws("ec2", "describe-volumes").get("Volumes", []); R["ebs"] = {"volumenes": len(vols), "gib": sum(v["Size"] for v in vols), "todos_cifrados": all(v["Encrypted"] for v in vols) if vols else None}
sn = aws("ec2", "describe-snapshots", "--owner-ids", "self").get("Snapshots", []); R["ebs_snapshots"] = {"cantidad": len(sn), "gib": sum(s["VolumeSize"] for s in sn)}
R["amis_propias"] = len(aws("ec2", "describe-images", "--owners", "self").get("Images", []))
R["ip_elasticas"] = len(aws("ec2", "describe-addresses").get("Addresses", [])); R["nat_gateways_activos"] = sum(1 for n in aws("ec2", "describe-nat-gateways").get("NatGateways", []) if n["State"] in ("available", "pending"))
R["vpc_endpoints"] = len(aws("ec2", "describe-vpc-endpoints").get("VpcEndpoints", []))
R["balanceadores"] = len(aws("elbv2", "describe-load-balancers").get("LoadBalancers", [])); R["auto_scaling_groups"] = len(aws("autoscaling", "describe-auto-scaling-groups").get("AutoScalingGroups", []))
# --- S3 y secretos
bk = [b["Name"] for b in aws("s3api", "list-buckets").get("Buckets", [])]; R["s3"] = []
for b in bk:
    g = lambda op: aws("s3api", op, "--bucket", b)
    pab = g("get-public-access-block").get("PublicAccessBlockConfiguration", {}); enc = g("get-bucket-encryption"); ver = g("get-bucket-versioning"); lc = g("get-bucket-lifecycle-configuration")
    R["s3"].append({"bucket": "<bucket-" + str(bk.index(b) + 1) + ">", "bloqueo_publico_total": bool(pab) and all(pab.values()), "cifrado": [r["ApplyServerSideEncryptionByDefault"]["SSEAlgorithm"] for r in enc.get("ServerSideEncryptionConfiguration", {}).get("Rules", [])] or None,
                    "versionado": ver.get("Status"), "reglas_de_ciclo_de_vida": len(lc.get("Rules", [])) if "_error" not in lc else 0})
R["secretos"] = {"cantidad": len(aws("secretsmanager", "list-secrets").get("SecretList", [])), "nota": "solo metadatos; los valores no se leen"}
# --- monitoreo, logs, CloudTrail
R["alarmas"] = [{"nombre": x["AlarmName"], "estado": x["StateValue"], "acciones": len(x.get("AlarmActions", []))} for x in aws("cloudwatch", "describe-alarms").get("MetricAlarms", [])]
R["paneles_cloudwatch"] = len(aws("cloudwatch", "list-dashboards").get("DashboardEntries", []))
R["log_groups"] = [{"nombre": g["logGroupName"], "retencion_dias": g.get("retentionInDays"), "bytes": g.get("storedBytes")} for g in aws("logs", "describe-log-groups").get("logGroups", [])]
tr = aws("cloudtrail", "describe-trails"); R["cloudtrail"] = {"consulta": "denegada o con error" if "_error" in tr else "ok", "detalle": tr.get("_error", None)}
if "_error" not in tr:
    R["cloudtrail"]["trails"] = []
    for t in tr.get("trailList", []):
        st = aws("cloudtrail", "get-trail-status", "--name", t["TrailARN"]); R["cloudtrail"]["trails"].append({"multi_region": t.get("IsMultiRegionTrail"), "validacion_de_archivos": t.get("LogFileValidationEnabled"), "registrando": st.get("IsLogging")})
# --- IAM del laboratorio
role = aws("iam", "get-role", "--role-name", "LabRole"); R["iam_labrole"] = {"consulta": "denegada o con error" if "_error" in role else "ok", "detalle": role.get("_error")}
if "_error" not in role:
    R["iam_labrole"]["politicas_adjuntas"] = [p["PolicyName"] for p in aws("iam", "list-attached-role-policies", "--role-name", "LabRole").get("AttachedPolicies", [])]
prof = aws("iam", "get-instance-profile", "--instance-profile-name", "LabInstanceProfile"); R["iam_instance_profile"] = "denegada o con error" if "_error" in prof else {"roles": [r["RoleName"] for r in prof["InstanceProfile"].get("Roles", [])]}
R["acm"] = [{"estado": c["Status"], "vence_utc": iso(c["NotAfter"]).isoformat(timespec="seconds") if c.get("NotAfter") else None} for c in aws("acm", "list-certificates").get("CertificateSummaryList", [])]

out = pathlib.Path(a.out or ROOT / "work/aws-readonly" / dt.date.today().strftime("%Y%m%d")); out.mkdir(parents=True, exist_ok=True)
txt = mask(json.dumps(R, indent=1, ensure_ascii=False)); (out / "resumen-solo-lectura.json").write_text(txt + "\n"); os.chmod(out / "resumen-solo-lectura.json", 0o600)
print(txt[:3500]); print("→", out)
