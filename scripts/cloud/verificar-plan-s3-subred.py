#!/usr/bin/env python3
"""Condición de parada para la Fase A (lifecycle de S3 + subred de V1). Lee SOLO el JSON de un plan (`terraform show -json <plan>`) y exige exactamente:
0 creaciones, 0 destrucciones/reemplazos y 2 actualizaciones in situ:
  - aws_s3_bucket_lifecycle_configuration.private: solo cambia la regla (prefijo -> backups/database/; días -> el valor de RETENCION, 365 por defecto);
  - aws_subnet.public_a: SOLO map_public_ip_on_launch true -> false.
Cualquier otro recurso (EC2, RDS, bucket, versionado, cifrado, alarmas, SNS...) con cambios hace fallar la comprobación. No usa la nube.
Con --solo-subred (Fase A2) exige UNA sola actualización: aws_subnet.public_a con map_public_ip_on_launch true -> false y nada más.
Con --solo-s3 (Fase A1) exige UNA sola actualización (el lifecycle) y rechaza cualquier cambio en la subred.
Uso: terraform -chdir=infra/aws show -json work/terraform-plans/<plan>.tfplan | python3 scripts/cloud/verificar-plan-s3-subred.py [--dias 365] [--solo-s3]
"""
import json
import sys

LIFECYCLE = "aws_s3_bucket_lifecycle_configuration.private"
SUBNET = "aws_subnet.public_a"


def _rule(after: dict) -> dict:
    rules = after.get("rule") or []
    return rules[0] if len(rules) == 1 else {}


def _check_subnet(sn: dict) -> list[str]:
    before, after = sn["before"] or {}, sn["after"] or {}
    changed = {k for k in set(before) | set(after) if before.get(k) != after.get(k)}
    if changed != {"map_public_ip_on_launch"} or before.get("map_public_ip_on_launch") is not True or after.get("map_public_ip_on_launch") is not False:
        return [f"la subred cambia más que map_public_ip_on_launch true -> false: {sorted(changed)}"]
    return []


def verify(plan: dict, dias: int = 365, solo_s3: bool = False, solo_subred: bool = False) -> list[str]:
    problems: list[str] = []
    updates: dict[str, dict] = {}
    for rc in plan.get("resource_changes", []):
        actions = rc["change"]["actions"]
        if actions in (["no-op"], ["read"]):
            continue
        address = rc["address"]
        if "delete" in actions:
            problems.append(f"destrucción o reemplazo: {address} {actions}")
        elif actions == ["update"]:
            updates[address] = rc["change"]
        else:
            problems.append(f"acción inesperada: {address} {actions}")
    esperado = {SUBNET} if solo_subred else ({LIFECYCLE} if solo_s3 else {LIFECYCLE, SUBNET})
    if set(updates) != esperado:
        problems.append(f"actualizaciones distintas de las previstas: {sorted(updates)}")
        return problems
    if solo_subred:
        return problems + _check_subnet(updates[SUBNET])
    lc = updates[LIFECYCLE]
    rule = _rule(lc["after"] or {})
    pref = ((rule.get("filter") or [{}])[0] or {}).get("prefix")
    exp = ((rule.get("expiration") or [{}])[0] or {}).get("days")
    nonc = ((rule.get("noncurrent_version_expiration") or [{}])[0] or {}).get("noncurrent_days")
    if pref != "backups/database/":
        problems.append(f"prefijo del lifecycle inesperado: {pref!r}")
    if exp != dias or nonc != dias:
        problems.append(f"retención inesperada: actual={exp} no vigentes={nonc} (se esperaban {dias})")
    if (lc["after"] or {}).get("bucket") != (lc["before"] or {}).get("bucket"):
        problems.append("el lifecycle cambiaría de bucket")
    if solo_s3:
        return problems
    return problems + _check_subnet(updates[SUBNET])


def main() -> int:
    dias = int(sys.argv[sys.argv.index("--dias") + 1]) if "--dias" in sys.argv else 365
    plan = json.load(sys.stdin)
    problems = verify(plan, dias, "--solo-s3" in sys.argv, "--solo-subred" in sys.argv)
    c = {"crear": 0, "actualizar": 0, "destruir": 0}
    for rc in plan.get("resource_changes", []):
        a = rc["change"]["actions"]; c["crear"] += a == ["create"]; c["actualizar"] += a == ["update"]; c["destruir"] += "delete" in a
    print(f"Plan: {c['crear']} a crear, {c['actualizar']} a actualizar, {c['destruir']} a destruir")
    for p in problems:
        print("FALLO:", p)
    print("RESULTADO:", "CORRECTO: coincide con lo previsto" if not problems else "NO APLICAR")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
