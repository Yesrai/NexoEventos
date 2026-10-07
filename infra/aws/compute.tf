data "aws_iam_instance_profile" "app" {
  name = var.instance_profile_name
}

resource "aws_instance" "app" {
  ami                         = var.ec2_ami_id
  instance_type               = var.ec2_instance_type
  subnet_id                   = aws_subnet.public_a.id
  vpc_security_group_ids      = [aws_security_group.web.id]
  associate_public_ip_address = true
  iam_instance_profile        = data.aws_iam_instance_profile.app.name
  monitoring                  = false
  metadata_options {
    http_endpoint = "enabled"
    http_tokens   = "required"
  }
  root_block_device {
    volume_type           = "gp3"
    volume_size           = var.ec2_root_volume_gib
    encrypted             = true
    delete_on_termination = true
  }
  tags = { Name = "${local.name_prefix}-app" }
}
