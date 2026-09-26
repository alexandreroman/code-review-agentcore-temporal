terraform {
  required_version = ">= 1.12.0"
  required_providers {
    aws    = { source = "hashicorp/aws", version = "6.66.0" }
    github = { source = "integrations/github", version = "6.13.0" }
  }

  # bucket and region come from `tofu init -backend-config=...` (make infra-init).
  backend "s3" {
    key          = "github/terraform.tfstate"
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

variable "region" {
  type    = string
  default = "ca-central-1"
}

variable "github_owner" {
  type = string
}

variable "demo_repo" {
  type    = string
  default = "agentcore-review-demo-app"
}

provider "aws" {
  region = var.region
  default_tags {
    tags = { Project = "temporal-agentcore-review-demo" }
  }
}

# The token comes from GITHUB_TOKEN (make github passes `gh auth token`).
provider "github" {
  owner = var.github_owner
}

data "aws_secretsmanager_secret_version" "github_app" {
  secret_id = "temporal-agentcore-review-demo/github-app"
}

locals {
  app = jsondecode(data.aws_secretsmanager_secret_version.github_app.secret_string)
}

# Public: a ruleset on a private repository needs a paid plan, and the
# audience sees the repository. Its content comes from its own history (plan 5).
resource "github_repository" "demo" {
  name                   = var.demo_repo
  description            = "Demo application reviewed by Agentic Code Review with AgentCore x Temporal"
  visibility             = "public"
  has_issues             = false
  has_projects           = false
  has_wiki               = false
  delete_branch_on_merge = true
  lifecycle {
    prevent_destroy = true
  }
}

resource "github_repository_ruleset" "main" {
  name        = "main"
  repository  = github_repository.demo.name
  target      = "branch"
  enforcement = "active"

  conditions {
    ref_name {
      include = ["~DEFAULT_BRANCH"]
      exclude = []
    }
  }

  rules {
    deletion         = true
    non_fast_forward = true
    required_status_checks {
      strict_required_status_checks_policy = false
      required_check {
        context        = "AI Review"
        integration_id = local.app.app_id
      }
    }
  }

  # Admins may merge over a red check (traced by the workflow); the app force-pushes main during a reset.
  bypass_actors {
    actor_id    = 5
    actor_type  = "RepositoryRole"
    bypass_mode = "always"
  }
  bypass_actors {
    actor_id    = local.app.app_id
    actor_type  = "Integration"
    bypass_mode = "always"
  }
}

resource "github_actions_secret" "app_client_id" {
  repository  = github_repository.demo.name
  secret_name = "APP_CLIENT_ID"
  value       = local.app.client_id
}

resource "github_actions_secret" "app_private_key" {
  repository  = github_repository.demo.name
  secret_name = "APP_PRIVATE_KEY"
  value       = local.app.private_key
}

output "repo_full_name" {
  value = github_repository.demo.full_name
}

output "repo_url" {
  value = github_repository.demo.html_url
}

output "app_slug" {
  value = local.app.slug
  # The whole github_app secret is sensitive, even though the slug and the
  # app ID are not: OpenTofu propagates sensitivity from local.app as a whole.
  sensitive = true
}

output "app_id" {
  value     = local.app.app_id
  sensitive = true
}
