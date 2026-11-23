#!/usr/bin/env python3
"""Detalle de seguridad de AWS (solo lectura): documentos de políticas de LabRole, parámetros TLS de RDS, metadatos de EC2/EBS/S3 y alarma.
Guarda: solo operaciones describe/get/list; sin lectura de secretos ni objetos; sin Cost Explorer. Enmascara cuenta, ARN, IDs, claves KMS y nombres de bucket."""
import json, re, subprocess, sys, pathlib
ALLOWED = {"iam", "rds", "ec2", "s3api", "cloudwatch", "sts"}
DENY = {"get-secret-value", "get-object", "get-parameter", "get-parameters", "get-password-data", "get-console-output", "get-credential-report", "get-login-profile"}
def aws(svc, op, *a):
    if svc not in ALLOWED or not op.startswith(("describe-", "get-", "list-")) or op in DENY:
        raise PermissionError(f"no permitido: {svc} {op}")
    r = subprocess.run(["aws", svc, op, *a, "--output", "json"], capture_output=True, text=True)
    if r.returncode: return {"_error": re.sub(r"user\d+=\S+", "<usuario>", re.sub(r"\b\d{12}\b", "<cuenta>", r.stderr.strip().split("\n")[-1]))[:160]}
    return json.loads(r.stdout or "{}")
def mask(x):
    x = re.sub(r"user\d+=[^\s/\"]+", "<usuario>", x)
    x = re.sub(r"\b\d{12}\b", "<cuenta>", x)
    x = re.sub(r"\b(i|sg|vol|subnet|vpc|snap|ami)-[0-9a-f]{6,}", lambda m: m.group(1) + "-…" + m.group(0)[-4:], x)
    x = re.sub(r"arn:aws[a-z-]*:kms:[^\"\s]+", "<arn-kms>", x)
    x = re.sub(r"nexoeventos-academy-[a-z0-9-]*\d{6,}[a-z0-9-]*", "<bucket>", x)
    return x
def summarize_policy(doc):
    st = doc.get("Statement", []); st = st if isinstance(st, list) else [st]
    out = {"sentencias": len(st), "allow": 0, "deny": 0, "accion_comodin_total": False, "recurso_comodin": False, "servicios": set(), "n_acciones": 0}
    for s in st:
        out["allow" if s.get("Effect") == "Allow" else "deny"] += 1
        acts = s.get("Action", []) or s.get("NotAction", []); acts = [acts] if isinstance(acts, str) else acts
        res = s.get("Resource", []); res = [res] if isinstance(res, str) else res
        if s.get("Effect") == "Allow":
            if "*" in acts: out["accion_comodin_total"] = True
            if "*" in res: out["recurso_comodin"] = True
        out["n_acciones"] += len(acts)
        for a in acts: out["servicios"].add(a.split(":")[0])
    out["servicios"] = sorted(out["servicios"])[:40]
    return out
R = {}
role = aws("iam", "get-role", "--role-name", "LabRole")
if "Role" in role:
    r = role["Role"]
    trust = r.get("AssumeRolePolicyDocument", {}).get("Statement", [])
    R["labrole"] = {"max_sesion_s": r.get("MaxSessionDuration"), "limite_de_permisos": bool(r.get("PermissionsBoundary")),
                    "confianza": [mask(json.dumps(s.get("Principal"))) for s in trust]}
else: R["labrole"] = role
R["inline"] = aws("iam", "list-role-policies", "--role-name", "LabRole").get("PolicyNames", [])
pols = []
for p in aws("iam", "list-attached-role-policies", "--role-name", "LabRole").get("AttachedPolicies", []):
    name = re.sub(r"^c\w+l\d+t\dw<?\w*>?-", "", p["PolicyName"]); name = re.sub(r"^c[0-9a-z]+l[0-9]+t[0-9]w[0-9]*-", "", name); name = re.sub(r"-[A-Za-z0-9]{8,}$", "", name)
    meta = aws("iam", "get-policy", "--policy-arn", p["PolicyArn"])
    ver = meta.get("Policy", {}).get("DefaultVersionId")
    doc = aws("iam", "get-policy-version", "--policy-arn", p["PolicyArn"], "--version-id", ver) if ver else {}
    d = doc.get("PolicyVersion", {}).get("Document")
    pols.append({"nombre": mask(name), "gestionada_por_aws": ":aws:policy/" in p["PolicyArn"], **(summarize_policy(d) if d else {"_error": "documento no legible"})})
R["politicas"] = pols
R["usuarios_iam"] = {"consulta": "denegada" if "_error" in (u := aws("iam", "list-users")) else len(u.get("Users", []))}
R["grupos_iam"] = {"consulta": "denegada" if "_error" in (g := aws("iam", "list-groups")) else len(g.get("Groups", []))}
db = aws("rds", "describe-db-instances", "--db-instance-identifier", "nexoeventos-academy-postgres").get("DBInstances", [{}])[0]
R["rds"] = {k: db.get(k) for k in ["StorageEncrypted", "PubliclyAccessible", "MultiAZ", "BackupRetentionPeriod", "PreferredBackupWindow", "PreferredMaintenanceWindow", "DeletionProtection", "IAMDatabaseAuthenticationEnabled",
            "PerformanceInsightsEnabled", "MonitoringInterval", "AutoMinorVersionUpgrade", "CACertificateIdentifier", "CopyTagsToSnapshot", "StorageType", "MaxAllocatedStorage", "AllocatedStorage"]}
R["rds"]["kms"] = "clave presente" if db.get("KmsKeyId") else "sin clave"
R["rds"]["grupo_parametros"] = [pg["DBParameterGroupName"] for pg in db.get("DBParameterGroups", [])]
R["rds"]["subredes_del_grupo"] = len(db.get("DBSubnetGroup", {}).get("Subnets", []))
pgn = (db.get("DBParameterGroups") or [{}])[0].get("DBParameterGroupName")
if pgn:
    pr = aws("rds", "describe-db-parameters", "--db-parameter-group-name", pgn, "--query", "Parameters[?ParameterName=='rds.force_ssl'].[ParameterName,ParameterValue,Source]")
    R["rds"]["rds.force_ssl"] = pr if isinstance(pr, list) else pr
ins = aws("ec2", "describe-instances", "--filters", "Name=tag:Name,Values=nexoeventos-academy-app").get("Reservations", [{}])[0].get("Instances", [{}])[0]
R["ec2"] = {"estado": ins.get("State", {}).get("Name"), "metadatos": ins.get("MetadataOptions"), "monitoreo_detallado": ins.get("Monitoring", {}).get("State"),
            "perfil_de_instancia": bool(ins.get("IamInstanceProfile")), "ip_publica_asignada": bool(ins.get("PublicIpAddress")) or bool(ins.get("NetworkInterfaces", [{}])[0].get("Association")),
            "sg_adjuntos": len(ins.get("SecurityGroups", []))}
R["ebs_cifrado_por_defecto"] = aws("ec2", "get-ebs-encryption-by-default").get("EbsEncryptionByDefault")
bk = next((b["Name"] for b in aws("s3api", "list-buckets").get("Buckets", []) if b["Name"].startswith("nexoeventos-academy-")), None)
if bk:
    pol = aws("s3api", "get-bucket-policy", "--bucket", bk)
    s3 = {"politica_de_bucket": "ausente" if "_error" in pol else "presente"}
    if "Policy" in pol:
        d = json.loads(pol["Policy"]); s3["resumen_politica"] = [{"efecto": s.get("Effect"), "accion": s.get("Action"), "condicion": mask(json.dumps(s.get("Condition", {})))} for s in d.get("Statement", [])]
    lc = aws("s3api", "get-bucket-lifecycle-configuration", "--bucket", bk).get("Rules", [])
    s3["ciclo_de_vida"] = [{"estado": r.get("Status"), "expira_dias": r.get("Expiration", {}).get("Days"), "prefijo": (r.get("Filter") or {}).get("Prefix")} for r in lc]
    R["s3"] = s3
al = aws("cloudwatch", "describe-alarms").get("MetricAlarms", [])
R["alarmas"] = [{"nombre": a["AlarmName"], "metrica": a.get("MetricName"), "estadistico": a.get("Statistic"), "periodo_s": a.get("Period"), "periodos_eval": a.get("EvaluationPeriods"),
                 "umbral": a.get("Threshold"), "comparacion": a.get("ComparisonOperator"), "estado": a.get("StateValue"), "acciones_alarma": len(a.get("AlarmActions", [])), "tratamiento_datos_faltantes": a.get("TreatMissingData")}
                for a in al if a["AlarmName"].startswith("nexoeventos")]
out = pathlib.Path(sys.argv[1]); out.mkdir(parents=True, exist_ok=True)
t = mask(json.dumps(R, indent=2, ensure_ascii=False, default=list)); (out / "detalle-seguridad.json").write_text(t + "\n"); print(t)
