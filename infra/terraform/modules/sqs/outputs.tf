output "high_queue_url" {
  value = aws_sqs_queue.high.url
}

output "high_queue_arn" {
  value = aws_sqs_queue.high.arn
}

output "standard_queue_url" {
  value = aws_sqs_queue.standard.url
}

output "standard_queue_arn" {
  value = aws_sqs_queue.standard.arn
}

output "dlq_url" {
  value = aws_sqs_queue.dlq.url
}

output "dlq_arn" {
  value = aws_sqs_queue.dlq.arn
}

output "all_queue_arns" {
  value = [
    aws_sqs_queue.high.arn,
    aws_sqs_queue.standard.arn,
    aws_sqs_queue.dlq.arn,
  ]
}
