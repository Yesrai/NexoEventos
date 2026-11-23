# ENTRADA PÚBLICA DE PRUEBA para la VM de recuperación (T3/T6). Apagada por defecto: con create = false NO se crea nada y la VCN sigue sin Internet Gateway.
# Diseño mínimo y reversible:
#   - Internet Gateway + subred PÚBLICA aparte (la subred privada actual no se toca).
#   - NSG: HTTPS (443) SOLO desde CIDR explícitos (nunca 0.0.0.0/0); SSH solo desde el endpoint de OCI Bastion (que vive en esta subred pública); NINGÚN puerto de base de datos ni de administración.
#   - Salida: solo HTTPS (443) hacia Internet (Object Storage por su URL pública, PAR del lease, testigo, DuckDNS).
# TLS: lo termina Nginx en la VM (certificado efímero con SAN de la IP/dominio de prueba: RECOVERY_TLS_SAN en install-app.sh); la VM arranca en modo SOLO LECTURA (RECOVERY_READONLY=1).
variable "create" { type = bool }
variable "compartment_id" { type = string }
variable "vcn_id" { type = string }
variable "subnet_cidr" { type = string }
variable "allowed_https_cidrs" { type = list(string) }
variable "bastion_source_cidr" { type = string }
variable "freeform_tags" { type = map(string) }

resource "oci_core_internet_gateway" "this" {
  count          = var.create ? 1 : 0
  compartment_id = var.compartment_id
  vcn_id         = var.vcn_id
  display_name   = "nexoeventos-recovery-igw-prueba"
  enabled        = true
  freeform_tags  = var.freeform_tags
}

resource "oci_core_route_table" "public" {
  count          = var.create ? 1 : 0
  compartment_id = var.compartment_id
  vcn_id         = var.vcn_id
  display_name   = "nexoeventos-recovery-public-rt-prueba"
  route_rules {
    destination       = "0.0.0.0/0"
    destination_type  = "CIDR_BLOCK"
    network_entity_id = oci_core_internet_gateway.this[0].id
    description       = "Salida/entrada de la prueba por el Internet Gateway"
  }
  freeform_tags = var.freeform_tags
}

# La subred pública NO usa la lista de seguridad por defecto de la VCN (cerrada: su única salida es hacia la subred privada). Tiene la suya: sin reglas de entrada (las gobierna el NSG) y una sola
# salida, SSH dentro de la propia subred, para que el endpoint de OCI Bastion (que vive aquí) llegue a la VM.
resource "oci_core_security_list" "public" {
  count          = var.create ? 1 : 0
  compartment_id = var.compartment_id
  vcn_id         = var.vcn_id
  display_name   = "nexoeventos-recovery-public-sl-prueba"
  egress_security_rules {
    protocol    = "6"
    destination = var.subnet_cidr
    stateless   = false
    description = "Bastion -> VM: SSH dentro de la subred pública"
    tcp_options {
      min = 22
      max = 22
    }
  }
  freeform_tags = var.freeform_tags
}

resource "oci_core_subnet" "public" {
  count                      = var.create ? 1 : 0
  compartment_id             = var.compartment_id
  vcn_id                     = var.vcn_id
  cidr_block                 = var.subnet_cidr
  display_name               = "nexoeventos-recovery-public-prueba"
  dns_label                  = "pub"
  prohibit_public_ip_on_vnic = false
  route_table_id             = oci_core_route_table.public[0].id
  security_list_ids          = [oci_core_security_list.public[0].id]
  freeform_tags              = var.freeform_tags
}

resource "oci_core_network_security_group" "public" {
  count          = var.create ? 1 : 0
  compartment_id = var.compartment_id
  vcn_id         = var.vcn_id
  display_name   = "nexoeventos-recovery-public-nsg-prueba"
  freeform_tags  = var.freeform_tags

  lifecycle {
    precondition {
      condition     = length(var.allowed_https_cidrs) > 0 && !contains(var.allowed_https_cidrs, "0.0.0.0/0") && !contains(var.allowed_https_cidrs, "::/0") && alltrue([for c in var.allowed_https_cidrs : can(cidrhost(c, 0))])
      error_message = "La entrada pública exige al menos un CIDR de origen explícito (p. ej. tu IP /32 y la del sondeador) y prohíbe 0.0.0.0/0 y ::/0."
    }
  }
}

resource "oci_core_network_security_group_security_rule" "https_in" {
  for_each                  = var.create ? toset(var.allowed_https_cidrs) : toset([])
  network_security_group_id = oci_core_network_security_group.public[0].id
  direction                 = "INGRESS"
  protocol                  = "6"
  source                    = each.value
  source_type               = "CIDR_BLOCK"
  description               = "HTTPS de prueba desde un origen autorizado"
  tcp_options {
    destination_port_range {
      min = 443
      max = 443
    }
  }
}

resource "oci_core_network_security_group_security_rule" "ssh_from_bastion_subnet" {
  count                     = var.create ? 1 : 0
  network_security_group_id = oci_core_network_security_group.public[0].id
  direction                 = "INGRESS"
  protocol                  = "6"
  source                    = var.bastion_source_cidr
  source_type               = "CIDR_BLOCK"
  description               = "SSH solo desde el endpoint de OCI Bastion (misma subred pública)"
  tcp_options {
    destination_port_range {
      min = 22
      max = 22
    }
  }
}

resource "oci_core_network_security_group_security_rule" "https_out" {
  count                     = var.create ? 1 : 0
  network_security_group_id = oci_core_network_security_group.public[0].id
  direction                 = "EGRESS"
  protocol                  = "6"
  destination               = "0.0.0.0/0"
  destination_type          = "CIDR_BLOCK"
  description               = "Solo HTTPS saliente (Object Storage, PAR, testigo, DuckDNS)"
  tcp_options {
    destination_port_range {
      min = 443
      max = 443
    }
  }
}

output "subnet_id" { value = var.create ? oci_core_subnet.public[0].id : null }
output "nsg_id" { value = var.create ? oci_core_network_security_group.public[0].id : null }
output "internet_gateway_id" { value = var.create ? oci_core_internet_gateway.this[0].id : null }
