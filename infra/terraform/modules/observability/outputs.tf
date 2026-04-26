output "api_log_group_name" {
  value = aws_cloudwatch_log_group.api.name
}

output "worker_log_group_name" {
  value = aws_cloudwatch_log_group.worker.name
}

output "redis_log_group_name" {
  value = aws_cloudwatch_log_group.redis.name
}

output "alarm_topic_arn" {
  value = aws_sns_topic.alarms.arn
}
