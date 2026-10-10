# Redshift ra3.large for the warehouse (Learner Lab allows ra3.large, at most 2 nodes).
#
# Clients use the Redshift Data API with temporary credentials for a named database user
# (`--db-user`, GetClusterCredentials as LabRole), so nothing needs the admin password: it's
# generated as an ephemeral value, sent write-only, and stored nowhere. No ingress either: the
# Data API doesn't connect to the cluster's port. LabRole is attached and set as the default
# role, so COPY and UNLOAD can say `IAM_ROLE default`.
#
# Pause it at night (aws redshift pause-cluster): a paused cluster bills storage only.

terraform {
  required_version = ">= 1.11"
  required_providers {
    aws    = { source = "hashicorp/aws", version = "~> 6.0" }
    random = { source = "hashicorp/random", version = "~> 3.7" }
  }
}

variable "name" {
  type    = string
  default = "lab"
}

variable "nodes" {
  type    = number
  default = 1
  validation {
    condition     = var.nodes >= 1 && var.nodes <= 2
    error_message = "Learner Lab allows at most 2 ra3.large nodes."
  }
}

variable "database" {
  type    = string
  default = "lab"
}

variable "admin_user" {
  type    = string
  default = "labadmin"
}

variable "subnet_ids" {
  type = list(string)
}

variable "availability_zone" {
  type    = string
  default = null
}

data "aws_caller_identity" "me" {}
data "aws_subnet" "first" { id = var.subnet_ids[0] }

locals {
  # Referenced by ARN: creating roles is denied, and reading IAM may be.
  lab_role_arn = "arn:aws:iam::${data.aws_caller_identity.me.account_id}:role/LabRole"
}

ephemeral "random_password" "admin" {
  length      = 32
  special     = false
  min_upper   = 1
  min_lower   = 1
  min_numeric = 1
}

resource "aws_redshift_subnet_group" "this" {
  name       = var.name
  subnet_ids = var.subnet_ids
}

resource "aws_security_group" "this" {
  name_prefix = "${var.name}-redshift-"
  vpc_id      = data.aws_subnet.first.vpc_id
  description = "Redshift: no ingress (clients use the Data API); egress for COPY and UNLOAD"
}

resource "aws_vpc_security_group_egress_rule" "all" {
  security_group_id = aws_security_group.this.id
  ip_protocol       = "-1"
  cidr_ipv4         = "0.0.0.0/0"
}

resource "aws_redshift_cluster" "this" {
  cluster_identifier         = var.name
  node_type                  = "ra3.large"
  cluster_type               = var.nodes == 1 ? "single-node" : "multi-node"
  number_of_nodes            = var.nodes
  database_name              = var.database
  master_username            = var.admin_user
  master_password_wo         = ephemeral.random_password.admin.result
  master_password_wo_version = 1
  cluster_subnet_group_name  = aws_redshift_subnet_group.this.name
  vpc_security_group_ids     = [aws_security_group.this.id]
  availability_zone          = var.availability_zone
  publicly_accessible        = false
  encrypted                  = true
  iam_roles                  = [local.lab_role_arn]
  default_iam_role_arn       = local.lab_role_arn
  skip_final_snapshot        = true
}

output "cluster_id" {
  value = aws_redshift_cluster.this.cluster_identifier
}

output "database" {
  value = aws_redshift_cluster.this.database_name
}

output "admin_user" {
  value = aws_redshift_cluster.this.master_username
}
