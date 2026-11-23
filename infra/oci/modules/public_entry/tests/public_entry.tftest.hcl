# Pruebas del módulo de entrada pública con un proveedor SIMULADO (mock_provider): no se llama a OCI ni se crea nada remoto.
mock_provider "oci" {}

variables {
  compartment_id      = "ocid1.compartment.oc1..mock"
  vcn_id              = "ocid1.vcn.oc1..mock"
  subnet_cidr         = "10.60.2.0/24"
  bastion_source_cidr = "10.60.2.0/24"
  freeform_tags       = {}
}

run "apagado_por_defecto_no_crea_nada" {
  command = apply
  variables {
    create              = false
    allowed_https_cidrs = []
  }
  assert {
    condition     = output.subnet_id == null && output.nsg_id == null && output.internet_gateway_id == null
    error_message = "con create=false no debe existir ninguna salida de recursos"
  }
}

run "con_origen_explicito_crea_igw_subred_y_reglas_minimas" {
  command = apply
  variables {
    create              = true
    allowed_https_cidrs = ["203.0.113.5/32", "198.51.100.7/32"]
  }
  assert {
    condition     = output.subnet_id != null && output.nsg_id != null && output.internet_gateway_id != null
    error_message = "con create=true deben existir IGW, subred y NSG"
  }
  assert {
    condition     = oci_core_subnet.public[0].prohibit_public_ip_on_vnic == false
    error_message = "la subred de prueba debe admitir IP pública"
  }
  assert {
    condition     = length(oci_core_network_security_group_security_rule.https_in) == 2 && alltrue([for r in oci_core_network_security_group_security_rule.https_in : r.direction == "INGRESS" && r.tcp_options[0].destination_port_range[0].min == 443 && r.tcp_options[0].destination_port_range[0].max == 443])
    error_message = "una regla HTTPS (443) por origen autorizado, y solo 443"
  }
  assert {
    condition     = alltrue([for r in oci_core_network_security_group_security_rule.https_in : r.source != "0.0.0.0/0"])
    error_message = "ninguna regla de entrada puede abrirse al mundo"
  }
  assert {
    condition     = oci_core_network_security_group_security_rule.ssh_from_bastion_subnet[0].source == "10.60.2.0/24" && oci_core_network_security_group_security_rule.ssh_from_bastion_subnet[0].tcp_options[0].destination_port_range[0].min == 22
    error_message = "SSH solo desde el endpoint de OCI Bastion (misma subred pública), nunca desde Internet"
  }
  assert {
    condition     = oci_core_network_security_group_security_rule.https_out[0].direction == "EGRESS" && oci_core_network_security_group_security_rule.https_out[0].tcp_options[0].destination_port_range[0].min == 443 && oci_core_network_security_group_security_rule.https_out[0].tcp_options[0].destination_port_range[0].max == 443
    error_message = "la única salida permitida es HTTPS"
  }
}

run "la_subred_publica_tiene_su_propia_lista_de_seguridad_sin_entradas_y_solo_ssh_interno_de_salida" {
  command = apply
  variables {
    create              = true
    allowed_https_cidrs = ["203.0.113.5/32"]
  }
  assert {
    condition     = length(oci_core_security_list.public[0].ingress_security_rules) == 0
    error_message = "la lista de seguridad de la subred pública no debe tener reglas de entrada"
  }
  assert {
    condition     = length(oci_core_security_list.public[0].egress_security_rules) == 1 && one(oci_core_security_list.public[0].egress_security_rules).destination == "10.60.2.0/24" && one(oci_core_security_list.public[0].egress_security_rules).tcp_options[0].min == 22 && one(oci_core_security_list.public[0].egress_security_rules).tcp_options[0].max == 22
    error_message = "la única salida es SSH hacia la propia subred pública (Bastion -> VM)"
  }
  assert {
    condition     = contains(oci_core_subnet.public[0].security_list_ids, oci_core_security_list.public[0].id)
    error_message = "la subred pública debe usar su propia lista de seguridad"
  }
}

# Reversibilidad: el MISMO estado pasa de «creado» a «destruido» solo con create = false (es lo que ejecuta la destrucción de T3): no queda NINGÚN recurso del módulo.
run "ciclo_1_crear" {
  command = apply
  variables {
    create              = true
    allowed_https_cidrs = ["203.0.113.5/32", "198.51.100.7/32"]
  }
  assert {
    condition     = length(oci_core_network_security_group_security_rule.https_in) == 2 && length(oci_core_internet_gateway.this) == 1 && length(oci_core_subnet.public) == 1
    error_message = "tras crear deben existir IGW, subred y las dos reglas de entrada"
  }
}

run "ciclo_2_destruir_con_create_false_no_deja_nada" {
  command = apply
  variables {
    create              = false
    allowed_https_cidrs = ["203.0.113.5/32", "198.51.100.7/32"]
  }
  assert {
    condition     = length(oci_core_internet_gateway.this) == 0 && length(oci_core_route_table.public) == 0 && length(oci_core_security_list.public) == 0 && length(oci_core_subnet.public) == 0 && length(oci_core_network_security_group.public) == 0 && length(oci_core_network_security_group_security_rule.https_in) == 0 && length(oci_core_network_security_group_security_rule.ssh_from_bastion_subnet) == 0 && length(oci_core_network_security_group_security_rule.https_out) == 0
    error_message = "tras destruir no puede quedar ningún recurso del módulo"
  }
  assert {
    condition     = output.subnet_id == null && output.nsg_id == null && output.internet_gateway_id == null
    error_message = "las salidas deben volver a null"
  }
}

run "ciclo_3_se_puede_reconstruir_tras_destruir" {
  command = apply
  variables {
    create              = true
    allowed_https_cidrs = ["203.0.113.5/32"]
  }
  assert {
    condition     = length(oci_core_internet_gateway.this) == 1 && length(oci_core_network_security_group_security_rule.https_in) == 1 && output.subnet_id != null
    error_message = "la reconstrucción tras destruir debe funcionar con los mismos recursos"
  }
}

run "rechaza_abrir_al_mundo" {
  command = plan
  variables {
    create              = true
    allowed_https_cidrs = ["0.0.0.0/0"]
  }
  expect_failures = [oci_core_network_security_group.public]
}

run "rechaza_entrada_sin_origenes" {
  command = plan
  variables {
    create              = true
    allowed_https_cidrs = []
  }
  expect_failures = [oci_core_network_security_group.public]
}

run "rechaza_cidr_invalido" {
  command = plan
  variables {
    create              = true
    allowed_https_cidrs = ["no-es-un-cidr"]
  }
  expect_failures = [oci_core_network_security_group.public]
}
