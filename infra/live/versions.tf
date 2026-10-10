terraform {
  required_version = ">= 1.11"

  # Partial config: infra/bootstrap/state-bucket.sh creates the state bucket and writes backend.hcl.
  #   terraform init -backend-config=backend.hcl
  backend "s3" {}

  required_providers {
    aws    = { source = "hashicorp/aws", version = "~> 6.0" }
    random = { source = "hashicorp/random", version = "~> 3.7" }
  }
}

provider "aws" {
  region = "us-east-1"
  default_tags {
    tags = { project = "mlops-lab" }
  }
}
