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
  type    = string
  default = "review"
}

variable "dev_task_queue" {
  type    = string
  default = "review-dev"
}

variable "dev_branch_prefix" {
  type    = string
  default = "dev/"
}

variable "deployment_name" {
  type    = string
  default = "agentcore-review-demo-worker"
}

variable "anthropic_model" {
  type    = string
  default = "claude-opus-5"
}

variable "anthropic_effort" {
  type    = string
  default = "high"
}

variable "max_parallel_agents" {
  type    = number
  default = 3
}

variable "idle_timeout" {
  description = "AgentCore session idle timeout, in seconds"
  type        = number
  default     = 120
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
  description = "Endpoints of earlier builds still kept, name => runtime version (set by agentcore_review_tools.infra)"
  type        = map(string)
  default     = {}
}
