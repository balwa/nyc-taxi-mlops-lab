# SageMaker notebook instance for exploration (S2): ml.t3.medium with LabRole, inside the VPC so it
# reaches MLflow on the platform host, and with your public repo cloned into ~/SageMaker on create.
#
# On every start, a lifecycle script writes the lab's settings to ~/SageMaker/.lab.env (the notebook's
# first cell reads it), installs notebooks/requirements.txt in the background, and logs whether MLflow
# answers. That log is in CloudWatch: /aws/sagemaker/NotebookInstances, stream <name>/LifecycleConfigOnStart.
#
# Learner Lab: instance types ml.t3.medium..xlarge, at most 2 notebooks. Stop it at night
# (aws sagemaker stop-notebook-instance): a session refresh does not restart it.

terraform {
  required_version = ">= 1.11"
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 6.0" }
  }
}

variable "name" {
  type    = string
  default = "lab"
}

variable "instance_type" {
  type    = string
  default = "ml.t3.medium"
}

variable "subnet_id" {
  type = string
}

variable "repo_url" {
  type        = string
  description = "Public HTTPS URL of the lab repo, cloned into ~/SageMaker/<repo> when the notebook is created."
}

variable "env" {
  type        = map(string)
  description = "Settings written to ~/SageMaker/.lab.env, e.g. MLFLOW_TRACKING_URI, REDSHIFT_CLUSTER_ID."
}

data "aws_caller_identity" "me" {}
data "aws_subnet" "this" { id = var.subnet_id }

locals {
  repo_dir = trimsuffix(basename(var.repo_url), ".git")
  env_file = join("\n", [for k, v in merge(var.env, { LAB_REPO_DIR = "/home/ec2-user/SageMaker/${local.repo_dir}" }) : "${k}=${v}"])
}

resource "aws_security_group" "this" {
  name_prefix = "${var.name}-notebook-"
  vpc_id      = data.aws_subnet.this.vpc_id
  description = "SageMaker notebook: no ingress; reaches MLflow, Redshift Data API and S3"
}

resource "aws_vpc_security_group_egress_rule" "all" {
  security_group_id = aws_security_group.this.id
  ip_protocol       = "-1"
  cidr_ipv4         = "0.0.0.0/0"
}

resource "aws_sagemaker_notebook_instance_lifecycle_configuration" "this" {
  name = "${var.name}-notebook"
  on_start = base64encode(<<-EOT
    #!/bin/bash
    set -eu
    cat > /home/ec2-user/SageMaker/.lab.env <<'ENV'
    ${local.env_file}
    ENV
    chown ec2-user:ec2-user /home/ec2-user/SageMaker/.lab.env
    # Background: lifecycle scripts must finish within 5 minutes.
    sudo -u ec2-user -i nohup bash -c 'source /home/ec2-user/anaconda3/bin/activate python3 && pip install -q -r /home/ec2-user/SageMaker/${local.repo_dir}/notebooks/requirements.txt' \
      > /home/ec2-user/SageMaker/.lab-setup.log 2>&1 &
    echo "lab: MLflow health $(curl -s -o /dev/null -w '%%{http_code}' -m 10 ${lookup(var.env, "MLFLOW_TRACKING_URI", "http://localhost:5000")}/health || echo unreachable)"
    EOT
  )
}

resource "aws_sagemaker_notebook_instance" "this" {
  name                    = var.name
  instance_type           = var.instance_type
  role_arn                = "arn:aws:iam::${data.aws_caller_identity.me.account_id}:role/LabRole"
  subnet_id               = var.subnet_id
  security_groups         = [aws_security_group.this.id]
  direct_internet_access  = "Enabled"
  default_code_repository = var.repo_url
  lifecycle_config_name   = aws_sagemaker_notebook_instance_lifecycle_configuration.this.name
  volume_size             = 10
  root_access             = "Disabled"

  instance_metadata_service_configuration {
    minimum_instance_metadata_service_version = "2"
  }
}

output "name" {
  value = aws_sagemaker_notebook_instance.this.name
}

output "security_group_id" {
  value = aws_security_group.this.id
}
