variable "project_name" {
  type = string
}

variable "frontend_bucket_id" {
  type = string
}

variable "frontend_bucket_arn" {
  type = string
}

variable "frontend_bucket_regional_domain_name" {
  type = string
}

variable "alb_dns_name" {
  description = "DNS of the API ALB. Used as second CloudFront origin so /auth, /jobs, /events, /health are reachable over HTTPS without Mixed Content."
  type        = string
}
