variable "project_name" {
  type = string
}

variable "users_table_arn" {
  type = string
}

variable "users_username_index_arn" {
  type = string
}

variable "jobs_table_arn" {
  type = string
}

variable "jobs_indexes_arn_pattern" {
  type = string
}

variable "high_queue_arn" {
  type = string
}

variable "standard_queue_arn" {
  type = string
}

variable "dlq_arn" {
  type = string
}

variable "reports_bucket_arn" {
  type = string
}

variable "reports_bucket_objects_arn" {
  type = string
}

variable "sns_topic_arn" {
  type = string
}
