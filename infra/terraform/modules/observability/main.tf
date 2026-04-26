# ---- CloudWatch log groups (one per service) ----

resource "aws_cloudwatch_log_group" "api" {
  name              = "/ecs/${var.project_name}/api"
  retention_in_days = var.log_retention_days

  tags = { Service = "api" }
}

resource "aws_cloudwatch_log_group" "worker" {
  name              = "/ecs/${var.project_name}/worker"
  retention_in_days = var.log_retention_days

  tags = { Service = "worker" }
}

resource "aws_cloudwatch_log_group" "redis" {
  name              = "/ecs/${var.project_name}/redis"
  retention_in_days = var.log_retention_days

  tags = { Service = "redis" }
}

# ---- Alarm SNS topic + email subscription ----

resource "aws_sns_topic" "alarms" {
  name = "${var.project_name}-alarms"

  tags = { Name = "${var.project_name}-alarms" }
}

resource "aws_sns_topic_subscription" "alarm_email" {
  topic_arn = aws_sns_topic.alarms.arn
  protocol  = "email"
  endpoint  = var.alarm_email
}

# ---- Alarms ----

resource "aws_cloudwatch_metric_alarm" "dlq_not_empty" {
  alarm_name          = "${var.project_name}-dlq-not-empty"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "ApproximateNumberOfMessagesVisible"
  namespace           = "AWS/SQS"
  period              = 300
  statistic           = "Maximum"
  threshold           = 0
  alarm_description   = "Messages reached the DLQ — investigate poison pill or processing bug"

  dimensions = {
    QueueName = var.dlq_name
  }

  alarm_actions = [aws_sns_topic.alarms.arn]
  ok_actions    = [aws_sns_topic.alarms.arn]
}

resource "aws_cloudwatch_metric_alarm" "jobs_failed_high" {
  alarm_name          = "${var.project_name}-jobs-failed-high"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "jobs.failed"
  namespace           = "Prosperas"
  period              = 300
  statistic           = "Sum"
  threshold           = 5
  alarm_description   = "More than 5 jobs failed in 10 minutes"
  treat_missing_data  = "notBreaching"

  alarm_actions = [aws_sns_topic.alarms.arn]
}
