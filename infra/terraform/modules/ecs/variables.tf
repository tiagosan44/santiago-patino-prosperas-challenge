variable "project_name" {
  type = string
}

variable "aws_region" {
  type = string
}

variable "private_subnet_ids" {
  type = list(string)
}

variable "api_security_group_id" {
  type = string
}

variable "worker_security_group_id" {
  type = string
}

variable "redis_security_group_id" {
  type = string
}

variable "service_discovery_namespace_id" {
  type = string
}

variable "task_execution_role_arn" {
  type = string
}

variable "api_task_role_arn" {
  type = string
}

variable "worker_task_role_arn" {
  type = string
}

variable "redis_task_role_arn" {
  type = string
}

variable "api_image" {
  type        = string
  description = "Full ECR URI:tag for the api image"
}

variable "worker_image" {
  type        = string
  description = "Full ECR URI:tag for the worker image"
}

variable "api_log_group_name" {
  type = string
}

variable "worker_log_group_name" {
  type = string
}

variable "redis_log_group_name" {
  type = string
}

variable "api_target_group_arn" {
  type = string
}

variable "users_table_name" {
  type = string
}

variable "jobs_table_name" {
  type = string
}

variable "high_queue_url" {
  type = string
}

variable "standard_queue_url" {
  type = string
}

variable "dlq_url" {
  type = string
}

variable "reports_bucket_name" {
  type = string
}

variable "sns_topic_arn" {
  type = string
}

variable "jwt_secret" {
  type      = string
  sensitive = true
}

variable "git_sha" {
  type    = string
  default = "dev"
}

variable "api_desired_count" {
  type    = number
  default = 2
}

variable "worker_desired_count" {
  type    = number
  default = 2
}

variable "worker_concurrency" {
  type    = number
  default = 4
}

variable "api_cpu" {
  type    = number
  default = 256
}

variable "api_memory" {
  type    = number
  default = 512
}

variable "worker_cpu" {
  type    = number
  default = 256
}

variable "worker_memory" {
  type    = number
  default = 512
}

variable "redis_cpu" {
  type    = number
  default = 256
}

variable "redis_memory" {
  type    = number
  default = 512
}
