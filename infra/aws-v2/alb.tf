resource "aws_lb" "main" {
  name                       = "${local.v2_prefix}-alb"
  load_balancer_type         = "application"
  internal                   = false
  security_groups            = [aws_security_group.alb.id]
  subnets                    = [data.aws_subnet.public_a.id, aws_subnet.public_b.id]
  idle_timeout               = 60
  drop_invalid_header_fields = true
  enable_deletion_protection = var.alb_deletion_protection
  tags                       = { Name = "${local.v2_prefix}-alb" }
}

resource "aws_lb_target_group" "web" {
  name                          = "${local.v2_prefix}-tg"
  port                          = 80
  protocol                      = "HTTP"
  vpc_id                        = data.aws_vpc.v1.id
  deregistration_delay          = 30
  load_balancing_algorithm_type = "least_outstanding_requests" # reparte mejor cuando las solicitudes tardan distinto (login con Argon2)

  health_check {
    protocol            = "HTTP"
    path                = "/livez" # Nginx -> FastAPI /health (liveness, SIN PostgreSQL); /healthz (readiness con BD) queda para monitoreo externo
    matcher             = "200"
    interval            = 10
    timeout             = 5
    healthy_threshold   = 2
    unhealthy_threshold = 2
  }

  # Las sesiones viven en PostgreSQL: no se necesita afinidad.
  stickiness {
    type    = "lb_cookie"
    enabled = false
  }
  tags = { Name = "${local.v2_prefix}-tg" }
}

resource "aws_lb_listener" "https" {
  load_balancer_arn = aws_lb.main.arn
  port              = 443
  protocol          = "HTTPS"
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"
  certificate_arn   = var.certificate_arn

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.web.arn
  }
}

resource "aws_lb_listener" "http_redirect" {
  load_balancer_arn = aws_lb.main.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type = "redirect"
    redirect {
      port        = "443"
      protocol    = "HTTPS"
      status_code = "HTTP_301"
    }
  }
}
