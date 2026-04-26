data "aws_iam_policy_document" "ecs_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

# ----- Task execution role (pull from ECR, write CloudWatch logs) -----

resource "aws_iam_role" "task_execution" {
  name               = "${var.project_name}-task-execution"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json
}

resource "aws_iam_role_policy_attachment" "task_execution_managed" {
  role       = aws_iam_role.task_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

# ----- API task role -----

data "aws_iam_policy_document" "api_task" {
  statement {
    sid    = "DynamoUsersAndJobs"
    effect = "Allow"
    actions = [
      "dynamodb:GetItem",
      "dynamodb:PutItem",
      "dynamodb:UpdateItem",
      "dynamodb:Query",
      "dynamodb:DescribeTable",
    ]
    resources = [
      var.users_table_arn,
      var.users_username_index_arn,
      var.jobs_table_arn,
      var.jobs_indexes_arn_pattern,
    ]
  }

  statement {
    sid       = "SqsSendOnly"
    effect    = "Allow"
    actions   = ["sqs:SendMessage", "sqs:GetQueueAttributes", "sqs:GetQueueUrl"]
    resources = [var.high_queue_arn, var.standard_queue_arn, var.dlq_arn]
  }

  statement {
    sid       = "S3GetReports"
    effect    = "Allow"
    actions   = ["s3:GetObject"]
    resources = [var.reports_bucket_objects_arn]
  }

  statement {
    sid       = "S3HeadBucket"
    effect    = "Allow"
    actions   = ["s3:ListBucket"]
    resources = [var.reports_bucket_arn]
  }

  statement {
    sid       = "SnsSubscribe"
    effect    = "Allow"
    actions   = ["sns:Subscribe", "sns:Unsubscribe"]
    resources = [var.sns_topic_arn]
  }

  statement {
    sid       = "CloudWatchMetrics"
    effect    = "Allow"
    actions   = ["cloudwatch:PutMetricData"]
    resources = ["*"] # PutMetricData requires "*"; restricted by namespace via condition
    condition {
      test     = "StringEquals"
      variable = "cloudwatch:namespace"
      values   = ["Prosperas"]
    }
  }
}

resource "aws_iam_role" "api" {
  name               = "${var.project_name}-api-task"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json
}

resource "aws_iam_role_policy" "api" {
  name   = "${var.project_name}-api-policy"
  role   = aws_iam_role.api.id
  policy = data.aws_iam_policy_document.api_task.json
}

# ----- Worker task role -----

data "aws_iam_policy_document" "worker_task" {
  statement {
    sid    = "SqsConsume"
    effect = "Allow"
    actions = [
      "sqs:ReceiveMessage",
      "sqs:DeleteMessage",
      "sqs:ChangeMessageVisibility",
      "sqs:GetQueueAttributes",
      "sqs:GetQueueUrl",
    ]
    resources = [var.high_queue_arn, var.standard_queue_arn, var.dlq_arn]
  }

  statement {
    sid    = "DynamoJobs"
    effect = "Allow"
    actions = [
      "dynamodb:GetItem",
      "dynamodb:UpdateItem",
      "dynamodb:Query",
      "dynamodb:DescribeTable",
    ]
    resources = [var.jobs_table_arn, var.jobs_indexes_arn_pattern]
  }

  statement {
    sid       = "S3PutReports"
    effect    = "Allow"
    actions   = ["s3:PutObject"]
    resources = [var.reports_bucket_objects_arn]
  }

  statement {
    sid       = "SnsPublish"
    effect    = "Allow"
    actions   = ["sns:Publish"]
    resources = [var.sns_topic_arn]
  }

  statement {
    sid       = "CloudWatchMetrics"
    effect    = "Allow"
    actions   = ["cloudwatch:PutMetricData"]
    resources = ["*"]
    condition {
      test     = "StringEquals"
      variable = "cloudwatch:namespace"
      values   = ["Prosperas"]
    }
  }
}

resource "aws_iam_role" "worker" {
  name               = "${var.project_name}-worker-task"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json
}

resource "aws_iam_role_policy" "worker" {
  name   = "${var.project_name}-worker-policy"
  role   = aws_iam_role.worker.id
  policy = data.aws_iam_policy_document.worker_task.json
}

# ----- Redis task role (no permissions; redis just runs in a container) -----

resource "aws_iam_role" "redis" {
  name               = "${var.project_name}-redis-task"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json
}
