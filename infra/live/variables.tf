variable "ingress_cidrs" {
  type        = list(string)
  description = "Who may reach the app (Traefik, port 80). Decision point: how wide is this?"
  validation {
    condition     = alltrue([for c in var.ingress_cidrs : can(cidrhost(c, 0))])
    error_message = "Each entry must be a CIDR, e.g. 203.0.113.10/32."
  }
}

variable "availability_zone" {
  type        = string
  default     = "us-east-1a"
  description = "AZ for the three hosts (us-east-1e lacks Graviton types)."
}

variable "platform_instance_type" {
  type    = string
  default = "t4g.large"
}

variable "app_instance_type" {
  type    = string
  default = "t4g.large"
}

variable "llm_instance_type" {
  type        = string
  default     = "m8g.large"
  description = "Not t-class: CPU credits would throttle sustained inference. m8g.large won the LLM bench (Graviton4: 3.3x m5.large generation)."
}

variable "rds_instance_class" {
  type    = string
  default = "db.t4g.medium"
}

variable "github_repo" {
  type        = string
  default     = null
  description = "Your lab repo as owner/name. The notebook (S2) clones it; the repo is public."
}
