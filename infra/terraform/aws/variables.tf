variable "aws_region" {
  type = string
}
variable "name" {
  type    = string
  default = "physharness"
  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{2,23}$", var.name))
    error_message = "Use a 3-24 character lowercase deployment name."
  }
}
variable "availability_zones" {
  type = list(string)
  validation {
    condition     = length(distinct(var.availability_zones)) == 2
    error_message = "Supply exactly two distinct availability zones in the configured region."
  }
}
variable "vpc_cidr" {
  type    = string
  default = "10.42.0.0/16"
}
variable "app_image" {
  description = "Published application image pinned by SHA-256 digest; no tag-only images."
  type        = string
  validation {
    condition     = can(regex("^[^[:space:]]+@sha256:[0-9a-f]{64}$", var.app_image))
    error_message = "app_image must include an immutable sha256 digest."
  }
}
variable "certificate_arn" {
  description = "Existing regional ACM TLS certificate for the private API hostname."
  type        = string
}
variable "allowed_client_cidrs" {
  description = "Private client/VPN ranges allowed to reach the internal TLS load balancer."
  type        = list(string)
  validation {
    condition     = length(var.allowed_client_cidrs) > 0 && !contains(var.allowed_client_cidrs, "0.0.0.0/0")
    error_message = "Explicit private client ranges are required; unrestricted ingress is prohibited."
  }
}
variable "postgres_engine_version" {
  description = "Exact RDS PostgreSQL minor release, reviewed and supported in the selected region."
  type        = string
  validation {
    condition     = can(regex("^16\\.[0-9]+$", var.postgres_engine_version))
    error_message = "Supply an explicit PostgreSQL 16 minor version."
  }
}
variable "database_instance_class" {
  type    = string
  default = "db.t4g.medium"
}
variable "database_allocated_storage_gib" {
  type    = number
  default = 100
}
variable "artifact_bucket_name" {
  description = "Globally unique S3 bucket name."
  type        = string
}
variable "database_url_secret_arn" {
  description = "Existing Secrets Manager secret containing the application-role PostgreSQL URL with TLS."
  type        = string
}
variable "migration_database_url_secret_arn" {
  description = "Existing separate secret containing a schema-owner PostgreSQL URL for one-shot migrations."
  type        = string
}
variable "auth_tokens_secret_arn" {
  description = "Existing secret: JSON token-to-Principal mapping consumed by PHYSHARNESS_AUTH_TOKENS."
  type        = string
}
variable "openai_api_key_secret_arn" {
  description = "Existing OpenAI API credential secret; injected only into worker tasks."
  type        = string
}
variable "e2b_api_key_secret_arn" {
  type    = string
  default = null
}
variable "e2b_template_id" {
  description = "Exact separately qualified template ID; null leaves E2B tools unavailable."
  type        = string
  default     = null
}
variable "temporal_address" {
  description = "Existing managed Temporal endpoint including port (normally 7233)."
  type        = string
}
variable "temporal_namespace" {
  type = string
}
variable "temporal_api_key_secret_arn" {
  description = "Existing Temporal Cloud API-key secret, injected only into the worker."
  type        = string
}
variable "model_prices" {
  description = "Explicit exact-model price table. Models are chosen in experiments, never substituted."
  type = map(object({
    input_usd_per_million  = string
    output_usd_per_million = string
    source                 = string
  }))
  validation {
    condition     = length(var.model_prices) > 0
    error_message = "Provide a reviewed nonempty price table for the exact models permitted to run."
  }
}
variable "cors_origins" {
  type = list(string)
}
variable "secret_kms_key_arns" {
  description = "Customer-managed KMS keys used by supplied secrets, if any."
  type        = list(string)
  default     = []
}
variable "api_desired_count" {
  description = "Starts at zero until DB roles, secrets and migrations are provisioned."
  type        = number
  default     = 0
}
variable "worker_desired_count" {
  description = "Explicit worker count; zero prevents accidental model allocations at bootstrap."
  type        = number
  default     = 0
}
variable "task_cpu" {
  type    = number
  default = 1024
}
variable "task_memory_mib" {
  type    = number
  default = 2048
}

variable "worker_workspace" {
  description = "Optional operator-qualified VM policy; credentials are supplied by separate secret ARN."
  type = object({
    template_id                 = string
    environment_digest          = string
    qualification_report_sha256 = string
    timeout_seconds             = number
    cost_bound_usd              = string
    cost_source                 = string
  })
  default = null
  validation {
    condition = var.worker_workspace == null ? true : (
      can(regex("^[a-f0-9]{64}$", var.worker_workspace.environment_digest)) &&
      can(regex("^[a-f0-9]{64}$", var.worker_workspace.qualification_report_sha256)) &&
      var.worker_workspace.timeout_seconds >= 1 && var.worker_workspace.timeout_seconds <= 86400 &&
      can(tonumber(var.worker_workspace.cost_bound_usd)) &&
      try(tonumber(var.worker_workspace.cost_bound_usd) > 0, false)
    )
    error_message = "Supply complete qualification/environment SHA-256 pins, positive cost bound and VM timeout 1-86400s."
  }
}
