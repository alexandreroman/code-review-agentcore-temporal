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
  }

  encryption {
    key_provider "aws_kms" "state" {
      kms_key_id = "alias/code-review-agentcore-temporal-tfstate"
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
  type = string
}

variable "github_owner" {
  type = string
}

variable "demo_repo" {
  type = string
}

# The rulesets name the app as a bypass actor, which GitHub accepts only
# once the app is installed on the repository; `make github` sets this.
variable "app_installed" {
  type    = bool
  default = false
}

provider "aws" {
  region = var.region
}

# The token comes from GITHUB_TOKEN (make github passes `gh auth token`).
provider "github" {
  owner = var.github_owner
}

data "aws_secretsmanager_secret_version" "github_app" {
  secret_id = "code-review-agentcore-temporal/github-app"
}

locals {
  app = jsondecode(data.aws_secretsmanager_secret_version.github_app.secret_string)
}

# Public: a ruleset on a private repository needs a paid plan, and the
# audience sees the repository. Its content is pushed separately (baseline
# and scenario tags).
resource "github_repository" "demo" {
  name                   = var.demo_repo
  description            = "Demo application reviewed by Code Review with AgentCore x Temporal"
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
  count       = var.app_installed ? 1 : 0
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
      required_check {
        context        = "AI Review"
        integration_id = local.app.app_id
      }
    }
  }

  # Admins may merge over a red check (traced by the workflow); the app force-pushes main during a reset.
  bypass_actors {
    actor_id    = 5 # the built-in repository Admin role
    actor_type  = "RepositoryRole"
    bypass_mode = "always"
  }
  bypass_actors {
    actor_id    = local.app.app_id
    actor_type  = "Integration"
    bypass_mode = "always"
  }
}

# The scenario tags anchor the review batches: once pushed they must not move,
# so a reset cannot silently change the demo.
resource "github_repository_ruleset" "tags" {
  count       = var.app_installed ? 1 : 0
  name        = "tags"
  repository  = github_repository.demo.name
  target      = "tag"
  enforcement = "active"

  conditions {
    ref_name {
      include = ["refs/tags/baseline", "refs/tags/scenario/*"]
      exclude = []
    }
  }

  rules {
    update   = true
    deletion = true
  }

  bypass_actors {
    actor_id    = 5 # the built-in repository Admin role
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

output "app_slug" {
  value = nonsensitive(local.app.slug)
}
