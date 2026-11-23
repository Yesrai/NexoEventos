"""AWS: consultas de SOLO LECTURA (describe_*) con boto3 y credenciales de mínimo privilegio del entorno del servicio (rol/perfil de solo lectura). Sin boto3, sin región o sin credenciales ⇒
«not_configured»/«unavailable». No se llama a ninguna API de escritura (la lista blanca de métodos está en ALLOWED). Probado aquí SOLO con un cliente simulado; no se ejecutó contra AWS."""
from __future__ import annotations

from . import envelope

SRC = "AWS API (solo lectura)"
ALLOWED = {("ec2", "describe_instances"), ("autoscaling", "describe_auto_scaling_groups"), ("autoscaling", "describe_scaling_activities"), ("elbv2", "describe_load_balancers"),
           ("rds", "describe_db_instances"), ("cloudwatch", "describe_alarms")}


class Aws:
    def __init__(self, cfg, client_factory=None):
        self.c, self.factory = cfg, client_factory

    def _client(self, svc):
        if self.factory:
            return self.factory(svc)
        import boto3
        return boto3.client(svc, region_name=self.c.aws_region)

    def _call(self, svc, op, **kw):
        if (svc, op) not in ALLOWED:
            raise PermissionError("operación AWS no permitida")
        return getattr(self._client(svc), op)(**kw)

    def _guard(self, fn):
        if not self.c.aws_region and not self.factory:
            return envelope(SRC, "not_configured", detail="NEXOOPS_AWS_REGION sin definir")
        try:
            return envelope(SRC, "ok", fn())
        except ImportError:
            return envelope(SRC, "not_configured", detail="boto3 no instalado en este servidor")
        except Exception as e:  # noqa: BLE001
            return envelope(SRC, "unavailable", detail=f"AWS no respondió ({type(e).__name__})")

    def summary(self):
        def f():
            ec2 = [i for r in self._call("ec2", "describe_instances", Filters=[{"Name": "tag:Project", "Values": ["nexoeventos"]}])["Reservations"] for i in r["Instances"]]
            asg = self._call("autoscaling", "describe_auto_scaling_groups", **({"AutoScalingGroupNames": self.c.aws_asg_names} if self.c.aws_asg_names else {}))["AutoScalingGroups"]
            lb = self._call("elbv2", "describe_load_balancers")["LoadBalancers"]
            rds = self._call("rds", "describe_db_instances")["DBInstances"]
            al = self._call("cloudwatch", "describe_alarms", StateValue="ALARM")["MetricAlarms"]
            return {"ec2": [{"id": i["InstanceId"], "state": i["State"]["Name"], "type": i["InstanceType"]} for i in ec2][:50],
                    "asg": [{"name": g["AutoScalingGroupName"], "desired": g["DesiredCapacity"], "min": g["MinSize"], "max": g["MaxSize"], "in_service": sum(1 for x in g["Instances"] if x["LifecycleState"] == "InService")} for g in asg],
                    "alb": [{"name": b["LoadBalancerName"], "state": b["State"]["Code"]} for b in lb],
                    "rds": [{"id": d["DBInstanceIdentifier"], "status": d["DBInstanceStatus"], "multi_az": d.get("MultiAZ", False)} for d in rds],
                    "alarms_in_alarm": [{"name": a["AlarmName"], "reason": str(a.get("StateReason", ""))[:160]} for a in al][:30]}
        return self._guard(f)

    def asg_activities(self, name: str):
        def f():
            rows = self._call("autoscaling", "describe_scaling_activities", AutoScalingGroupName=name, MaxRecords=20)["Activities"]
            return {"asg": name, "activities": [{"at": str(a.get("StartTime"))[:19], "status": a["StatusCode"], "cause": str(a.get("Description", ""))[:160]} for a in rows]}
        return self._guard(f)
