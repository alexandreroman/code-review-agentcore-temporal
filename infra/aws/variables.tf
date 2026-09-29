variable "region" {
  type = string
}

variable "temporal_address" {
  type = string
}

variable "temporal_namespace" {
  type = string
}

variable "task_queue" {
  type = string
}

variable "dev_task_queue" {
  type = string
}

variable "dev_branch_prefix" {
  type = string
}

variable "pr_idle_warning_seconds" {
  description = "Seconds without activity before the bot warns that it will close the pull request"
  type        = number

  validation {
    condition     = var.pr_idle_warning_seconds >= 1
    error_message = "pr_idle_warning_seconds must be at least 1."
  }
}

variable "pr_idle_close_seconds" {
  description = "Seconds without activity before the bot closes the pull request"
  type        = number

  validation {
    # The warning announces the close: it must come first.
    condition     = var.pr_idle_close_seconds > var.pr_idle_warning_seconds
    error_message = "pr_idle_close_seconds must be greater than pr_idle_warning_seconds."
  }
}

variable "deployment_name" {
  type = string
}

variable "bedrock_model_id" {
  description = "Bedrock global cross-region inference profile ID of the model (global.anthropic.claude-opus-5)"
  type        = string

  validation {
    # The worker's IAM policy follows the global inference profile's resource ARNs.
    condition     = startswith(var.bedrock_model_id, "global.")
    error_message = "bedrock_model_id must be a global cross-region inference profile ID (global.<model>)."
  }
}

variable "model_effort" {
  description = "How much effort Claude spends per answer (low, medium, high, ...), checked by Bedrock"
  type        = string
}

variable "max_parallel_agents" {
  type = number

  validation {
    # 0 would block every review round on Semaphore(0).
    condition     = var.max_parallel_agents >= 1
    error_message = "max_parallel_agents must be at least 1."
  }
}

variable "tracing" {
  description = "on to trace the worker and the router into CloudWatch (needs Transaction Search), off otherwise"
  type        = string

  validation {
    condition     = contains(["on", "off"], var.tracing)
    error_message = "tracing must be on or off."
  }
}

variable "build_id" {
  description = "Deployed worker build (image tag, endpoint name, Temporal Build ID); empty before the first deploy"
  type        = string
  default     = ""
  validation {
    condition     = var.build_id == "" || can(regex("^[a-zA-Z][a-zA-Z0-9_]{0,47}$", var.build_id))
    error_message = "build_id must be a valid AgentCore endpoint name (letters, digits, underscores)."
  }
}

variable "retained_endpoints" {
  description = "Endpoints of earlier builds still kept, name => runtime version (set by scripts/infra.sh)"
  type        = map(string)
  default     = {}
}

variable "domain_name" {
  description = "Cloudflare zone of the webhook's custom domain (e.g. example.com); empty to use the Function URL"
  type        = string
}

variable "subdomain" {
  description = "Subdomain of the webhook's custom domain (codereview for codereview.example.com)"
  type        = string
}

variable "cloudflare_zone_id" {
  description = "ID of the Cloudflare zone named by domain_name"
  type        = string
}
