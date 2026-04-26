output "task_execution_role_arn" {
  value = aws_iam_role.task_execution.arn
}

output "api_task_role_arn" {
  value = aws_iam_role.api.arn
}

output "worker_task_role_arn" {
  value = aws_iam_role.worker.arn
}

output "redis_task_role_arn" {
  value = aws_iam_role.redis.arn
}
