resource "aws_db_subnet_group" "main" {
  name       = "${local.name_prefix}-db-subnets"
  subnet_ids = [aws_subnet.db_private_a.id, aws_subnet.db_private_b.id]
  tags       = { Name = "${local.name_prefix}-db-subnets" }
}

resource "aws_db_instance" "postgres" {
  identifier                   = "${local.name_prefix}-postgres"
  engine                       = "postgres"
  instance_class               = var.db_instance_class
  allocated_storage            = var.db_allocated_storage_gib
  max_allocated_storage        = var.db_allocated_storage_gib
  storage_type                 = "gp2"
  storage_encrypted            = true
  db_name                      = "nexoeventos"
  username                     = "nexoeventos_admin"
  manage_master_user_password  = true
  db_subnet_group_name         = aws_db_subnet_group.main.name
  vpc_security_group_ids       = [aws_security_group.database.id]
  publicly_accessible          = false
  multi_az                     = false
  backup_retention_period      = var.backup_retention_days
  copy_tags_to_snapshot        = true
  deletion_protection          = false
  skip_final_snapshot          = false
  final_snapshot_identifier    = var.final_snapshot_identifier
  apply_immediately            = false
  auto_minor_version_upgrade   = true
  monitoring_interval          = 0
  performance_insights_enabled = false
  tags                         = { Name = "${local.name_prefix}-postgres" }
}
