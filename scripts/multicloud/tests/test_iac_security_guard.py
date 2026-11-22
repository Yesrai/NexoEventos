"""Pruebas de MUTACIÓN del verificador de seguridad IaC (check-iac-security.py): sobre una COPIA temporal del repositorio, cada debilitamiento (en el módulo opcional de entrada pública y en los demás módulos
de OCI) debe hacer que el verificador FALLE; el árbol sin tocar debe pasar. Demuestra que la excepción de la entrada pública opcional no relajó el resto. Sin nube."""
import shutil, subprocess, sys, tempfile, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
COPY = ["infra", "ansible/roles", "scripts/cloud", "scripts/observability", "scripts/multicloud/check-iac-security.py"]


def make_tree(tmp: Path):
    for rel in COPY:
        src, dst = ROOT / rel, tmp / rel; dst.parent.mkdir(parents=True, exist_ok=True)
        (shutil.copytree(src, dst, ignore=shutil.ignore_patterns(".terraform", "*.tfstate*", "*.tfplan", "__pycache__")) if src.is_dir() else shutil.copy(src, dst))


def run_checker(tmp: Path):
    r = subprocess.run([sys.executable, str(tmp / "scripts/multicloud/check-iac-security.py")], capture_output=True, text=True, timeout=120)
    return r.returncode, r.stdout + r.stderr


def mutate(tmp: Path, rel: str, old: str, new: str, count=1):
    p = tmp / rel; s = p.read_text(); assert old in s, f"la mutación no aplica: «{old[:50]}» no está en {rel}"; p.write_text(s.replace(old, new, count))


def append(tmp: Path, rel: str, text: str):
    p = tmp / rel; p.write_text(p.read_text() + text)


MUTACIONES = {
    "IGW fuera del módulo opcional": lambda t: append(t, "infra/oci/modules/network/main.tf", '\nresource "oci_core_internet_gateway" "x" {\n  compartment_id = var.compartment_id\n  vcn_id = oci_core_vcn.this.id\n}\n'),
    "regla de entrada abierta al mundo en el módulo opcional": lambda t: mutate(t, "infra/oci/modules/public_entry/main.tf", "source                    = each.value", 'source                    = "0.0.0.0/0"'),
    "se elimina la precondición que prohíbe 0.0.0.0/0": lambda t: mutate(t, "infra/oci/modules/public_entry/main.tf", '!contains(var.allowed_https_cidrs, "0.0.0.0/0") && ', ""),
    "puerto de base de datos expuesto en la entrada pública": lambda t: append(t, "infra/oci/modules/public_entry/main.tf", '\nresource "oci_core_network_security_group_security_rule" "db" {\n  direction = "INGRESS"\n  tcp_options {\n    destination_port_range {\n      min = 5432\n      max = 5432\n    }\n  }\n}\n'),
    "la entrada pública queda encendida por defecto": lambda t: mutate(t, "infra/oci/variables.tf", 'description = "false por defecto. true crea Internet Gateway', 'description = "x. true crea Internet Gateway') or mutate(t, "infra/oci/variables.tf", "  default     = false\n}\n\nvariable \"public_subnet_cidr\"", "  default     = true\n}\n\nvariable \"public_subnet_cidr\""),
    "la VM recibe IP pública fija": lambda t: mutate(t, "infra/oci/modules/recovery/main.tf", "assign_public_ip = var.assign_public_ip\n    nsg_ids", "assign_public_ip = true\n    nsg_ids"),
    "la subred PRIVADA admite IP pública": lambda t: mutate(t, "infra/oci/modules/network/main.tf", "prohibit_public_ip_on_vnic = true", "prohibit_public_ip_on_vnic = false"),
    "el IGW deja de ser condicional": lambda t: mutate(t, "infra/oci/modules/public_entry/main.tf", 'resource "oci_core_internet_gateway" "this" {\n  count          = var.create ? 1 : 0', 'resource "oci_core_internet_gateway" "this" {\n  count          = 1'),
    "el uploader puede borrar objetos (IAM de OCI)": lambda t: append(t, "infra/oci/modules/iam/main.tf", '\n# OBJECT_DELETE\n'),
    "NAT habilitado por defecto": lambda t: mutate(t, "infra/oci/variables.tf", 'variable "enable_nat_gateway" {', 'variable "enable_nat_gateway" {\n  # mutación\n') or mutate(t, "infra/oci/variables.tf", "default     = false", "default     = true"),
    "el bucket deja de ser privado": lambda t: mutate(t, "infra/oci/modules/storage/main.tf", "NoPublicAccess", "ObjectRead"),
}


class MutacionIaC(unittest.TestCase):
    def test_el_arbol_sin_tocar_pasa(self):
        with tempfile.TemporaryDirectory() as d:
            t = Path(d); make_tree(t); code, out = run_checker(t); self.assertEqual(code, 0, out[-600:])

    def test_cada_debilitamiento_hace_fallar_el_verificador(self):
        sobreviven = []
        for nombre, mut in MUTACIONES.items():
            with tempfile.TemporaryDirectory() as d:
                t = Path(d); make_tree(t)
                try: mut(t)
                except AssertionError as e: self.fail(f"[{nombre}] {e}")
                code, out = run_checker(t)
                if code == 0: sobreviven.append(nombre)
        self.assertEqual(sobreviven, [], f"mutaciones que el verificador NO detecta: {sobreviven}")


if __name__ == "__main__":
    unittest.main()
