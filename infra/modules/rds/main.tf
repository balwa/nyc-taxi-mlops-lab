# One Postgres instance for the Dagster, MLflow and pgvector databases.
# db.t4g.medium by default: micro allows only 79 connections (scripts/verify 07).
# Learner Lab: burstable classes, gp2 storage up to 100 GB, no enhanced monitoring.
#
# The master password is generated as an ephemeral value and sent with write-only arguments, so
# it never lands in Terraform state or plan output. Read it from the Secrets Manager secret.

terraform {
  required_version = ">= 1.11"
  required_providers {
    aws    = { source = "hashicorp/aws", version = "~> 6.0" }
    random = { source = "hashicorp/random", version = "~> 3.7" }
  }
}

variable "instance_class" {
  type    = string
  default = "db.t4g.medium"
}

variable "engine_version" {
  type    = string
  default = "17"
}

variable "subnet_ids" {
  type = list(string)
}

variable "security_group_ids" {
  type = list(string)
}

variable "secret_name" {
  type    = string
  default = "lab/rds"
}

ephemeral "random_password" "master" {
  length  = 32
  special = false
}

resource "aws_db_subnet_group" "this" {
  name       = "lab"
  subnet_ids = var.subnet_ids
}

resource "aws_db_instance" "this" {
  identifier                   = "lab"
  engine                       = "postgres"
  engine_version               = var.engine_version
  instance_class               = var.instance_class
  allocated_storage            = 20
  storage_type                 = "gp2"
  db_name                      = "lab"
  username                     = "labadmin"
  password_wo                  = ephemeral.random_password.master.result
  password_wo_version          = 1
  db_subnet_group_name         = aws_db_subnet_group.this.name
  vpc_security_group_ids       = var.security_group_ids
  publicly_accessible          = false
  multi_az                     = false
  backup_retention_period      = 0
  monitoring_interval          = 0
  performance_insights_enabled = false
  deletion_protection          = false
  skip_final_snapshot          = true
  apply_immediately            = true
}

resource "aws_secretsmanager_secret" "master" {
  name                    = var.secret_name
  recovery_window_in_days = 0
}

resource "aws_secretsmanager_secret_version" "master" {
  secret_id = aws_secretsmanager_secret.master.id
  secret_string_wo = jsonencode({
    username = "labadmin"
    password = ephemeral.random_password.master.result
    host     = aws_db_instance.this.address
    port     = aws_db_instance.this.port
    dbname   = "lab"
  })
  secret_string_wo_version = 1
}

output "endpoint" {
  value = aws_db_instance.this.address
}

output "secret_arn" {
  value = aws_secretsmanager_secret.master.arn
}
