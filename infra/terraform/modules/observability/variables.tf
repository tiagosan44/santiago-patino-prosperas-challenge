variable "project_name" {
  type = string
}

variable "alarm_email" {
  description = "Email to subscribe to alarm notifications"
  type        = string
  default     = "tiago.san44@gmail.com"
}

variable "dlq_name" {
  type = string
}

variable "log_retention_days" {
  type    = number
  default = 7
}
