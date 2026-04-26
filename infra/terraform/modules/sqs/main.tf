resource "aws_sqs_queue" "dlq" {
  name                      = "${var.project_name}-jobs-dlq"
  message_retention_seconds = 1209600 # 14 days, max
  sqs_managed_sse_enabled   = true

  tags = {
    Name = "${var.project_name}-jobs-dlq"
  }
}

resource "aws_sqs_queue" "high" {
  name                       = "${var.project_name}-jobs-high"
  visibility_timeout_seconds = var.visibility_timeout_seconds
  message_retention_seconds  = 345600 # 4 days
  sqs_managed_sse_enabled    = true

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.dlq.arn
    maxReceiveCount     = var.max_receive_count
  })

  tags = {
    Name = "${var.project_name}-jobs-high"
  }
}

resource "aws_sqs_queue" "standard" {
  name                       = "${var.project_name}-jobs-standard"
  visibility_timeout_seconds = var.visibility_timeout_seconds
  message_retention_seconds  = 345600
  sqs_managed_sse_enabled    = true

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.dlq.arn
    maxReceiveCount     = var.max_receive_count
  })

  tags = {
    Name = "${var.project_name}-jobs-standard"
  }
}

# Allow the DLQ to be the redrive target for the two main queues.
resource "aws_sqs_queue_redrive_allow_policy" "dlq" {
  queue_url = aws_sqs_queue.dlq.id

  redrive_allow_policy = jsonencode({
    redrivePermission = "byQueue"
    sourceQueueArns   = [aws_sqs_queue.high.arn, aws_sqs_queue.standard.arn]
  })
}
