variable "role" {
  type        = string
  description = "Host role from contracts/runtime.yaml: platform, app or llm."
  validation {
    condition     = contains(["platform", "app", "llm"], var.role)
    error_message = "role must be platform, app or llm."
  }
}

variable "instance_type" {
  type        = string
  description = "nano to large only (Learner Lab). Graviton (t4g/m7g/m8g) by default; images are arm64."
  validation {
    condition     = can(regex("\\.(nano|micro|small|medium|large)$", var.instance_type))
    error_message = "Learner Lab allows instance sizes nano to large only."
  }
}

variable "subnet_id" {
  type = string
}

variable "security_group_ids" {
  type = list(string)
}

variable "root_volume_gb" {
  type    = number
  default = 30
  validation {
    condition     = var.root_volume_gb <= 100
    error_message = "Learner Lab caps EBS volumes at 100 GB."
  }
}

variable "elastic_ip" {
  type        = bool
  default     = true
  description = "Keep the same public IP across Learner Lab session restarts."
}

variable "compose_version" {
  type    = string
  default = "5.6.0"
}
