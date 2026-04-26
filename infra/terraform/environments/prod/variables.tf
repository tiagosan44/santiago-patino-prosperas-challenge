variable "aws_region" {
  description = "AWS region for all resources"
  type        = string
  default     = "us-east-1"
}

variable "project_name" {
  description = "Short project identifier used in resource names"
  type        = string
  default     = "prosperas"
}

variable "vpc_cidr" {
  description = "Primary CIDR block for the VPC"
  type        = string
  default     = "10.0.0.0/16"
}

variable "azs" {
  description = "Availability zones used for public/private subnets"
  type        = list(string)
  default     = ["us-east-1a", "us-east-1b"]
}

variable "jwt_secret" {
  description = "JWT signing secret. Pass via TF_VAR_jwt_secret env var; do NOT hardcode."
  type        = string
  sensitive   = true
}

variable "image_tag" {
  description = "Docker image tag to deploy (typically the git SHA from CI). Use 'latest' for the first apply, then CI will override per push."
  type        = string
  default     = "latest"
}
