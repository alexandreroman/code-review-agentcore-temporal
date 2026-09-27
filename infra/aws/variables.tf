variable "region" {
  type    = string
  default = "ca-central-1"
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

variable "deployment_name" {
  type = string
}

variable "anthropic_model" {
  type = string
}

variable "anthropic_effort" {
  type = string
}

variable "max_parallel_agents" {
  type = number

  validation {
    # 0 would block every review round on Semaphore(0).
    condition     = var.max_parallel_agents >= 1
    error_message = "max_parallel_agents must be at least 1."
  }
}

variable "idle_timeout" {
  description = "AgentCore session idle timeout, in seconds"
  type        = number
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
