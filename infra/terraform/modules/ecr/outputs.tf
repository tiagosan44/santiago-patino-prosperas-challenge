output "api_repository_url" {
  value = aws_ecr_repository.this["api"].repository_url
}

output "worker_repository_url" {
  value = aws_ecr_repository.this["worker"].repository_url
}

output "api_repository_arn" {
  value = aws_ecr_repository.this["api"].arn
}

output "worker_repository_arn" {
  value = aws_ecr_repository.this["worker"].arn
}
