# A Secrets Manager secret *container*. Its value is put out of band so it never sits in
# Terraform state, e.g.:
#   aws secretsmanager put-secret-value --secret-id lab/wiki --secret-string file://wiki.json
# Services read the latest version on every use, so a rotation (gameday E7) needs no redeploy.

terraform {
  required_version = ">= 1.11"
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 6.0" }
  }
}

variable "name" {
  type = string
}

variable "description" {
  type    = string
  default = ""
}

resource "aws_secretsmanager_secret" "this" {
  name                    = var.name
  description             = var.description
  recovery_window_in_days = 0
}

output "arn" {
  value = aws_secretsmanager_secret.this.arn
}

output "name" {
  value = aws_secretsmanager_secret.this.name
}
