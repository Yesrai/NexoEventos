resource "aws_launch_template" "web" {
  name_prefix            = "${local.v2_prefix}-lt-"
  image_id               = var.ami_id
  instance_type          = var.instance_type
  update_default_version = true

  iam_instance_profile { name = data.aws_iam_instance_profile.app.name }

  # La IP pública se pide aquí, por instancia (sin salida a Internet por NAT, la instancia la necesita para llegar a servicios AWS);
  # la subred ya no asigna IP pública por defecto (AWS-0164).
  network_interfaces {
    associate_public_ip_address = true
    security_groups             = [aws_security_group.web.id]
    delete_on_termination       = true
  }

  metadata_options {
    http_endpoint               = "enabled"
    http_tokens                 = "required"
    http_put_response_hop_limit = 1
  }

  credit_specification { cpu_credits = var.cpu_credits_mode }

  block_device_mappings {
    device_name = "/dev/xvda"
    ebs {
      volume_type           = "gp3"
      volume_size           = var.root_volume_gib
      encrypted             = true
      delete_on_termination = true
    }
  }

  # El arranque lee el secreto compartido con el rol de la instancia y escribe /etc/nexoeventos/backend.env (0600).
  # Aquí solo viajan el NOMBRE del secreto y parámetros no sensibles; ninguna clave pasa por Terraform ni por user_data.
  user_data = base64encode(templatefile("${path.module}/../../deploy/v2/bootstrap-instance.sh.tftpl", {
    region          = var.aws_region
    secret_name     = var.app_secret_name
    db_pool_size    = var.db_pool_size
    db_max_overflow = var.db_max_overflow
    rds_ca_url      = "https://truststore.pki.rds.amazonaws.com/${var.aws_region}/${var.aws_region}-bundle.pem"
    rds_ca_sha256   = join(",", var.rds_ca_sha256)
  }))

  tag_specifications {
    resource_type = "instance"
    tags          = { Name = "${local.v2_prefix}-app" }
  }
  tag_specifications {
    resource_type = "volume"
    tags          = { Name = "${local.v2_prefix}-app" }
  }
  tags = { Name = "${local.v2_prefix}-lt" }
}

resource "aws_autoscaling_group" "web" {
  name                = "${local.v2_prefix}-asg"
  min_size            = var.asg_min
  max_size            = var.asg_max
  desired_capacity    = var.asg_desired
  vpc_zone_identifier = [data.aws_subnet.public_a.id, aws_subnet.public_b.id]
  target_group_arns   = [aws_lb_target_group.web.arn]
  # El health check del ALB es de liveness (sin PostgreSQL): una caída de la base de datos no provoca el reemplazo de instancias sanas.
  health_check_type         = "ELB"
  health_check_grace_period = 120
  default_instance_warmup   = 120
  capacity_rebalance        = false
  termination_policies      = ["OldestInstance"]
  metrics_granularity       = "1Minute"
  enabled_metrics = [
    "GroupDesiredCapacity", "GroupInServiceInstances", "GroupPendingInstances", "GroupTerminatingInstances",
    "GroupTotalInstances", "GroupMinSize", "GroupMaxSize",
  ]

  launch_template {
    id      = aws_launch_template.web.id
    version = "$Latest"
  }

  tag {
    key                 = "Name"
    value               = "${local.v2_prefix}-app"
    propagate_at_launch = true
  }

  lifecycle {
    precondition {
      condition     = var.asg_min <= var.asg_desired && var.asg_desired <= var.asg_max && var.asg_min >= 2
      error_message = "Se requieren al menos 2 instancias (min <= deseado <= max) para repartir zonas y tolerar la caída de una."
    }
  }
}

# Política MEDIBLE: seguimiento de la CPU media del grupo (alarmas de CloudWatch gestionadas por Auto Scaling).
resource "aws_autoscaling_policy" "cpu" {
  name                      = "${local.v2_prefix}-cpu-target"
  autoscaling_group_name    = aws_autoscaling_group.web.name
  policy_type               = "TargetTrackingScaling"
  estimated_instance_warmup = 120

  target_tracking_configuration {
    predefined_metric_specification { predefined_metric_type = "ASGAverageCPUUtilization" }
    target_value = var.scale_cpu_target_pct
  }
}

resource "aws_autoscaling_policy" "requests" {
  count                     = var.scale_requests_per_target > 0 ? 1 : 0
  name                      = "${local.v2_prefix}-requests-target"
  autoscaling_group_name    = aws_autoscaling_group.web.name
  policy_type               = "TargetTrackingScaling"
  estimated_instance_warmup = 120

  target_tracking_configuration {
    predefined_metric_specification {
      predefined_metric_type = "ALBRequestCountPerTarget"
      resource_label         = "${aws_lb.main.arn_suffix}/${aws_lb_target_group.web.arn_suffix}"
    }
    target_value = var.scale_requests_per_target
  }
}
