terraform {
  required_version = ">= 1.12.0"
  required_providers {
    aws        = { source = "hashicorp/aws", version = "6.66.0" }
    random     = { source = "hashicorp/random", version = "3.9.1" }
    archive    = { source = "hashicorp/archive", version = "2.8.1" }
    cloudflare = { source = "cloudflare/cloudflare", version = "5.26.0" }
  }

  # bucket and region come from `tofu init -backend-config=...` (make infra-init).
  backend "s3" {
    key          = "aws/terraform.tfstate"
    use_lockfile = true
    encrypt      = true
  }

  encryption {
    key_provider "aws_kms" "state" {
      kms_key_id = "alias/temporal-agentcore-review-demo-tfstate"
      region     = var.region
      key_spec   = "AES_256"
    }
    method "aes_gcm" "state" {
      keys = key_provider.aws_kms.state
    }
    state {
      method   = method.aes_gcm.state
      enforced = true
    }
    plan {
      method   = method.aes_gcm.state
      enforced = true
    }
  }
}

provider "aws" {
  region = var.region
  default_tags {
    tags = { Project = "temporal-agentcore-review-demo" }
  }
}

# Reads CLOUDFLARE_API_TOKEN from the environment; only used with a custom domain (dns.tf).
provider "cloudflare" {}
