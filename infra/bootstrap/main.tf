# Run once per AWS account (make bootstrap). Local state, git-ignored: the
# resources are found again by name, never through this state.

terraform {
  required_version = ">= 1.12.0"
  required_providers {
    aws = { source = "hashicorp/aws", version = "6.66.0" }
  }
}

variable "region" {
  type    = string
  default = "ca-central-1"
}

provider "aws" {
  region = var.region
  default_tags {
    tags = { Project = "temporal-agentic-review" }
  }
}

data "aws_caller_identity" "current" {}

locals {
  name = "temporal-agentic-review"
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

resource "aws_s3_bucket_public_access_block" "state" {
  bucket                  = aws_s3_bucket.state.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "state" {
  bucket = aws_s3_bucket.state.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = aws_kms_key.state.arn
    }
    bucket_key_enabled = true
  }
}

output "state_bucket" {
  value = aws_s3_bucket.state.bucket
}

output "kms_alias" {
  value = aws_kms_alias.state.name
}
