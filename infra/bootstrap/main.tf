# Run once per AWS account (make bootstrap). Local state, git-ignored: the
# resources are found again by name, never through this state.

terraform {
  required_version = ">= 1.12.0"
  required_providers {
    aws = { source = "hashicorp/aws", version = "6.66.0" }
  }
}

variable "region" {
  type = string
}

provider "aws" {
  region = var.region
  default_tags {
    tags = { Project = "code-review-agentcore-temporal" }
  }
}

data "aws_caller_identity" "current" {}

locals {
  name = "code-review-agentcore-temporal"
}

resource "aws_kms_key" "state" {
  description             = "OpenTofu state encryption for ${local.name}"
  enable_key_rotation     = true
  deletion_window_in_days = 7
  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_kms_alias" "state" {
  name          = "alias/${local.name}-tfstate"
  target_key_id = aws_kms_key.state.key_id
}

resource "aws_s3_bucket" "state" {
  bucket = "${local.name}-tfstate-${data.aws_caller_identity.current.account_id}"
  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_s3_bucket_versioning" "state" {
  bucket = aws_s3_bucket.state.id
  versioning_configuration {
    status = "Enabled"
  }
}
