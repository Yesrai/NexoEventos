#!/usr/bin/env python3
"""Comprobaciones estáticas de seguridad de infra/oci e infra/azure (sin nubes ni credenciales). Uso: python3 scripts/multicloud/check-iac-security.py"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
errors = []


def check(ok: bool, msg: str) -> None:
    print(("OK    " if ok else "FALLÓ ") + msg)
    if not ok:
        errors.append(msg)


def read(d: str) -> str:
    return "\n".join(p.read_text() for p in sorted((ROOT / d).rglob("*.tf")))


oci, az = read("infra/oci"), read("infra/azure")
oci_vars = (ROOT / "infra/oci/variables.tf").read_text()
check('access_type    = "NoPublicAccess"' in oci and 'versioning     = "Enabled"' in oci, "OCI: bucket privado y versionado")
check("assign_public_ip = false" in oci and "prohibit_public_ip_on_vnic = true" in oci, "OCI: VM y subred sin IP pública")
check("oci_core_internet_gateway" not in oci, "OCI: sin Internet Gateway")
check(not re.search(r'source\s*=\s*"0\.0\.0\.0/0"', oci), "OCI: ninguna regla de entrada abierta a Internet")
check('default     = false' in re.search(r'variable "create_recovery_vm".*?\n\}', oci_vars, re.S).group(0) and 'default     = false' in re.search(r'variable "enable_nat_gateway".*?\n\}', oci_vars, re.S).group(0), "OCI: VM y NAT desactivados por defecto")
check("manage objects" in oci and "OBJECT_CREATE" in oci and "OBJECT_DELETE" not in oci and "manage all-resources" not in oci, "OCI: política de mínimo privilegio (sin borrar ni administrar)")
check(re.search(r'source_address_prefix\s*=\s*var\.admin_cidr', az) is not None, "Azure: SSH y HTTPS solo desde admin_cidr (las reglas «Allow» de entrada no usan orígenes abiertos: ver comprobación siguiente)")
check('!= "0.0.0.0/0"' in az, "Azure: admin_cidr no admite 0.0.0.0/0")
check('disable_password_authentication = true' in az, "Azure: VM solo con clave SSH")
check(re.search(r'variable "create_monitoring_vm".*?default\s*=\s*false', az, re.S) is not None, "Azure: VM desactivada por defecto")
check('azurerm_dev_test_global_vm_shutdown_schedule' in az and 'timezone              = "UTC"' in az and 'var.shutdown_time_utc != ""' in az, "Azure: apagado automático (desasigna la VM) obligatorio mientras exista la VM, en UTC y sin hora por defecto")
check('webhook_url' not in az and 'email ' not in az.split('azurerm_dev_test_global_vm_shutdown_schedule')[1].split('module "budget"')[0], "Azure: el apagado automático no lleva correo ni webhook en el código")
check('boot_diagnostics {}' in az, "Azure: diagnóstico de arranque gestionado (sin cuenta de almacenamiento)")
check('contains(["southcentralus"' in az and 'resource_provider_registrations = "none"' in az, "Azure: regiones permitidas y sin registro automático de proveedores")
check("azurerm_consumption_budget_subscription" in az, "Azure: presupuesto con alertas")
# --- Azure: NSG, identidad y VM (observabilidad) ---
net = (ROOT / "infra/azure/modules/network/main.tf").read_text(); vm = (ROOT / "infra/azure/modules/vm/main.tf").read_text(); root_az = (ROOT / "infra/azure/main.tf").read_text()
check('name                       = "deny-all-inbound"' in net and 'access                     = "Deny"' in net, "Azure: denegación explícita de toda la entrada")
check('name                       = "deny-internet-out"' in net and 'destination_address_prefix = "Internet"' in net, "Azure: salida a Internet denegada salvo 80/443 y NTP (mínimo privilegio)")
check(not re.search(r'direction\s*=\s*"Inbound"\s*\n\s*access\s*=\s*"Allow"[^}]*source_address_prefix\s*=\s*"(\*|Internet|0\.0\.0\.0/0)"', net), "Azure: ninguna regla de entrada permite origen abierto")
check("zabbix_agent_source_cidrs" in net and 'destination_port_range     = "10051"' in net and "length(var.zabbix_agent_source_cidrs) == 0 ? []" in net, "Azure: puerto 10051 solo si se autorizan IPs de agentes")
check('type = "SystemAssigned"' in vm and "secure_boot_enabled             = true" in vm and "vtpm_enabled                    = true" in vm and "allow_extension_operations      = false" in vm, "Azure: VM con Trusted Launch, identidad administrada y sin extensiones")
check('role_definition_name             = "Monitoring Reader"' in root_az and not re.search(r'role_definition_name\s*=\s*"(Owner|Contributor)', root_az), "Azure: identidad de la VM solo con «Monitoring Reader»")
check("azurerm_monitor_action_group" in az and "azurerm_monitor_metric_alert" in az, "Azure: grupo de acción y alertas de Azure Monitor")
# --- Azure: la salida a Internet se limita a 80/443 (TCP) y NTP (UDP/123); el DNS sale por el resolvedor de Azure (168.63.129.16) ---
check('name                       = "allow-ntp-out"' in net and 'protocol                   = "Udp"' in net and 'destination_port_ranges    = ["123"]' in net and '"53"' not in net,
      "Azure: la regla de salida de NTP es solo UDP/123 y no abre el puerto 53 a Internet")
check('destination_address_prefix = "168.63.129.16/32"' in net, "Azure: DNS y agente por la dirección de plataforma de Azure")
aws_vars = (ROOT / "infra/aws/variables.tf").read_text(); aws_s3 = (ROOT / "infra/aws/storage_observability.tf").read_text()
check('expiration { days = var.s3_backup_retention_days }' in aws_s3 and "var.backup_retention_days" not in aws_s3 and "s3_backup_retention_days >= 30" in aws_vars,
      "AWS: la caducidad de los respaldos en S3 no depende de la retención de RDS (7 días) y es de al menos 30 días")
# --- AWS: CloudTrail opcional (desactivado por defecto) y guardia de la AMI con /livez ---
ct = (ROOT / "infra/aws/cloudtrail.tf").read_text()
check(re.search(r'variable "enable_cloudtrail" \{.*?default\s*=\s*false', ct, re.S) is not None, "AWS: enable_cloudtrail es false por defecto (no se crea ningún trail sin decidirlo)")
ct_resources = re.findall(r'^(?:resource|data) "[^"]+" "[^"]+" \{\n\s+count\s*=\s*var\.enable_cloudtrail', ct, re.M)
check(len(ct_resources) == len(re.findall(r'^(?:resource|data) "', ct, re.M)) and len(ct_resources) >= 6, "AWS: todos los recursos de CloudTrail dependen de enable_cloudtrail (con false no se crea nada)")
check("enable_log_file_validation    = true" in ct and "block_public_policy     = true" in ct and "aws:SecureTransport" in ct and "AES256" in ct and "expiration" in ct,
      "AWS: trail con validación de integridad, bucket sin acceso público, solo TLS, cifrado y caducidad")
check("force_destroy = false" in ct, "AWS: el bucket de CloudTrail no se vacía automáticamente al destruir")
v2v = (ROOT / "infra/aws-v2/variables.tf").read_text()
check(re.search(r'variable "ami_includes_livez" \{.*?default\s*=\s*false', v2v, re.S) is not None, "AWS V2: ami_includes_livez es false por defecto (una AMI antigua no recibe /livez)")
# --- Ansible: rol de Zabbix + Grafana ---
role = ROOT / "ansible/roles/monitoring_zabbix_grafana"
rtxt = "\n".join(p.read_text() for p in sorted(role.rglob("*")) if p.is_file() and p.suffix in (".yml", ".j2", ".sh", ".php", ".yaml"))
check("ufw default {{ item }}" in rtxt and '"deny incoming"' in rtxt and "monitoring_admin_cidr" in rtxt, "Ansible: UFW deniega la entrada y abre solo desde la IP del operador")
check("PasswordAuthentication no" in rtxt and "PermitRootLogin no" in rtxt, "Ansible: SSH solo con clave y sin root")
check("http_addr = 127.0.0.1" in rtxt and "cookie_secure = true" in rtxt and "$__file{" in rtxt and "[auth.anonymous]\nenabled = false" in rtxt.replace("\r", ""), "Ansible: Grafana en localhost, cookies seguras, sin acceso anónimo y contraseña por archivo")
check("listen 443 ssl" in rtxt and "listen 80" not in rtxt and "Strict-Transport-Security" in rtxt, "Ansible: Nginx solo HTTPS con HSTS")
check("ansible.builtin.password" in rtxt and not re.search(r"(admin|db|ro)_?pass(word)?\s*:\s*['\"]?[A-Za-z0-9]{8,}", (role / "defaults/main.yml").read_text()), "Ansible: contraseñas generadas en la estación de control, no en el repositorio")
check("grafana-ro" in (ROOT / "scripts/observability/zabbix_configure.py").read_text() and '"gui_access": gui' in (ROOT / "scripts/observability/zabbix_configure.py").read_text(), "Zabbix: usuarios de API de mínimo privilegio sin interfaz web")
check(not re.search(r'(password|secret|private_key|api_key)\s*=\s*"[^"]{6,}"', oci + az, re.I) and "BEGIN PRIVATE" not in oci + az, "Sin secretos ni claves en el código")
sys.exit(1 if errors else 0)
