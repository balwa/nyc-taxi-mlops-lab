# One lab host: AL2023 (arch picked from the instance type), LabInstanceProfile, Docker + Compose,
# a `runner` user ready for the self-hosted GitHub runner, optional Elastic IP. No SSH key, no
# port 22: shell access is SSM Session Manager.

data "aws_ec2_instance_type" "this" {
  instance_type = var.instance_type
}

locals {
  arch = contains(data.aws_ec2_instance_type.this.supported_architectures, "arm64") ? "arm64" : "x86_64"
}

data "aws_ssm_parameter" "al2023" {
  name = "/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-${local.arch}"
}

resource "aws_instance" "this" {
  ami                    = data.aws_ssm_parameter.al2023.insecure_value
  instance_type          = var.instance_type
  subnet_id              = var.subnet_id
  vpc_security_group_ids = var.security_group_ids
  iam_instance_profile   = "LabInstanceProfile"

  metadata_options {
    http_tokens = "required"
    # 2 hops so containers (MLflow, Dagster runs) can reach instance-profile credentials.
    http_put_response_hop_limit = 2
  }

  root_block_device {
    volume_type = "gp3"
    volume_size = var.root_volume_gb
  }

  user_data = templatefile("${path.module}/user-data.sh.tftpl", {
    role            = var.role
    compose_version = var.compose_version
  })

  tags = { Name = "lab-${var.role}", role = var.role }

  lifecycle {
    # A new AL2023 AMI or a user-data tweak must never replace a host in the middle of the lab.
    ignore_changes = [ami, user_data]
  }
}

resource "aws_eip" "this" {
  count    = var.elastic_ip ? 1 : 0
  domain   = "vpc"
  instance = aws_instance.this.id
  tags     = { Name = "lab-${var.role}" }
}
