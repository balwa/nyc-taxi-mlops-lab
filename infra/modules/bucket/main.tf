# A private S3 bucket, created and deleted by the AWS CLI.
#
# Not aws_s3_bucket: its read calls GetBucketObjectLockConfiguration, which a Learner Lab SCP
# denies, and the AWS provider treats that as fatal (scripts/verify finding, Oct 2026).
# The CLI creates the bucket, or adopts it if it already exists in this account, and
# `terraform destroy` empties and deletes it.

terraform {
  required_version = ">= 1.11"
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 6.0" }
  }
}

variable "name" {
  type        = string
  description = "Prefix; the account id is appended so the name is globally unique."
}

variable "tags" {
  type    = map(string)
  default = { project = "mlops-lab" }
}

data "aws_caller_identity" "me" {}

locals {
  bucket  = "${var.name}-${data.aws_caller_identity.me.account_id}"
  tagging = jsonencode({ TagSet = [for k, v in var.tags : { Key = k, Value = v }] })
}

resource "terraform_data" "bucket" {
  input = local.bucket

  provisioner "local-exec" {
    command = <<-EOT
      set -e
      aws s3api head-bucket --bucket ${self.input} 2>/dev/null || aws s3api create-bucket --bucket ${self.input} --region us-east-1 >/dev/null
      aws s3api put-public-access-block --bucket ${self.input} --public-access-block-configuration \
        BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true
      aws s3api put-bucket-tagging --bucket ${self.input} --tagging '${local.tagging}'
    EOT
  }

  provisioner "local-exec" {
    when    = destroy
    command = "aws s3 rb s3://${self.input} --force"
  }
}

output "name" {
  value = terraform_data.bucket.output
}

output "arn" {
  value = "arn:aws:s3:::${terraform_data.bucket.output}"
}
