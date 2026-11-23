variable "compartment_id" { type = string }
variable "vcn_cidr" { type = string }
variable "subnet_cidr" { type = string }
variable "enable_nat_gateway" { type = bool }
variable "app_https_enabled" { type = bool }
variable "freeform_tags" { type = map(string) }

data "oci_core_services" "all" {
  filter {
    name   = "name"
    values = ["All .* Services In Oracle Services Network"]
    regex  = true
  }
}

resource "oci_core_vcn" "this" {
  compartment_id = var.compartment_id
  cidr_blocks    = [var.vcn_cidr]
  display_name   = "nexoeventos-recovery-vcn"
  dns_label      = "nexorec"
  freeform_tags  = var.freeform_tags
}

# Sin Internet Gateway: ningún recurso es alcanzable desde Internet. Object Storage se alcanza por el Service Gateway.
# La lista de seguridad por defecto de la VCN trae SSH/ICMP desde 0.0.0.0/0 y salida total. Se vacía: el tráfico permitido lo definen solo las reglas del NSG.
resource "oci_core_default_security_list" "lockdown" {
  manage_default_resource_id = oci_core_vcn.this.default_security_list_id
  display_name               = "nexoeventos-recovery-default-sl-sin-reglas"
  freeform_tags              = var.freeform_tags

  # Único hueco: el endpoint privado de OCI Bastion está en esta subred y su tráfico saliente hacia la VM pasa por esta lista. Sin entrada ni salida a Internet.
  egress_security_rules {
    protocol    = "6"
    destination = var.subnet_cidr
    stateless   = false
    description = "Bastion -> VM: SSH dentro de la subred privada"
    tcp_options {
      min = 22
      max = 22
    }
  }

  dynamic "egress_security_rules" {
    for_each = var.app_https_enabled ? [1] : []
    content {
      protocol    = "6"
      destination = var.subnet_cidr
      stateless   = false
      description = "Bastion -> VM: HTTPS dentro de la subred privada"
      tcp_options {
        min = 443
        max = 443
      }
    }
  }
}

resource "oci_core_service_gateway" "this" {
  compartment_id = var.compartment_id
  vcn_id         = oci_core_vcn.this.id
  display_name   = "nexoeventos-recovery-sgw"
  services {
    service_id = data.oci_core_services.all.services[0].id
  }
  freeform_tags = var.freeform_tags
}

resource "oci_core_nat_gateway" "this" {
  count          = var.enable_nat_gateway ? 1 : 0
  compartment_id = var.compartment_id
  vcn_id         = oci_core_vcn.this.id
  display_name   = "nexoeventos-recovery-nat"
  freeform_tags  = var.freeform_tags
}

resource "oci_core_route_table" "private" {
  compartment_id = var.compartment_id
  vcn_id         = oci_core_vcn.this.id
  display_name   = "nexoeventos-recovery-private-rt"
  route_rules {
    destination       = data.oci_core_services.all.services[0].cidr_block
    destination_type  = "SERVICE_CIDR_BLOCK"
    network_entity_id = oci_core_service_gateway.this.id
    description       = "Object Storage por el Service Gateway"
  }
  dynamic "route_rules" {
    for_each = var.enable_nat_gateway ? [1] : []
    content {
      destination       = "0.0.0.0/0"
      destination_type  = "CIDR_BLOCK"
      network_entity_id = oci_core_nat_gateway.this[0].id
      description       = "Solo para instalar paquetes durante el simulacro"
    }
  }
  freeform_tags = var.freeform_tags
}

resource "oci_core_subnet" "private" {
  compartment_id             = var.compartment_id
  vcn_id                     = oci_core_vcn.this.id
  cidr_block                 = var.subnet_cidr
  display_name               = "nexoeventos-recovery-private"
  dns_label                  = "priv"
  prohibit_public_ip_on_vnic = true
  route_table_id             = oci_core_route_table.private.id
  freeform_tags              = var.freeform_tags
}

resource "oci_core_network_security_group" "recovery" {
  compartment_id = var.compartment_id
  vcn_id         = oci_core_vcn.this.id
  display_name   = "nexoeventos-recovery-nsg"
  freeform_tags  = var.freeform_tags
}

# Entrada: solo SSH desde la propia subred (OCI Bastion). Salida: HTTPS a los servicios de Oracle (y a Internet únicamente con NAT habilitado).
resource "oci_core_network_security_group_security_rule" "ssh_from_subnet" {
  network_security_group_id = oci_core_network_security_group.recovery.id
  direction                 = "INGRESS"
  protocol                  = "6"
  source                    = var.subnet_cidr
  source_type               = "CIDR_BLOCK"
  description               = "SSH desde OCI Bastion (misma subred)"
  tcp_options {
    destination_port_range {
      min = 22
      max = 22
    }
  }
}

# Demostración de la aplicación: el acceso HTTPS llega solo por una sesión de reenvío de puerto de OCI Bastion (origen: la propia subred). Sin entrada pública.
resource "oci_core_network_security_group_security_rule" "https_from_subnet" {
  count                     = var.app_https_enabled ? 1 : 0
  network_security_group_id = oci_core_network_security_group.recovery.id
  direction                 = "INGRESS"
  protocol                  = "6"
  source                    = var.subnet_cidr
  source_type               = "CIDR_BLOCK"
  description               = "HTTPS (Nginx) desde OCI Bastion, misma subred"
  tcp_options {
    destination_port_range {
      min = 443
      max = 443
    }
  }
}

resource "oci_core_network_security_group_security_rule" "https_to_oracle_services" {
  network_security_group_id = oci_core_network_security_group.recovery.id
  direction                 = "EGRESS"
  protocol                  = "6"
  destination               = data.oci_core_services.all.services[0].cidr_block
  destination_type          = "SERVICE_CIDR_BLOCK"
  description               = "Object Storage"
  tcp_options {
    destination_port_range {
      min = 443
      max = 443
    }
  }
}

resource "oci_core_network_security_group_security_rule" "https_to_internet" {
  count                     = var.enable_nat_gateway ? 1 : 0
  network_security_group_id = oci_core_network_security_group.recovery.id
  direction                 = "EGRESS"
  protocol                  = "6"
  destination               = "0.0.0.0/0"
  destination_type          = "CIDR_BLOCK"
  description               = "Paquetes (solo con NAT, durante el simulacro)"
  tcp_options {
    destination_port_range {
      min = 443
      max = 443
    }
  }
}

output "private_subnet_id" { value = oci_core_subnet.private.id }
output "nsg_id" { value = oci_core_network_security_group.recovery.id }
output "vcn_id" { value = oci_core_vcn.this.id }
