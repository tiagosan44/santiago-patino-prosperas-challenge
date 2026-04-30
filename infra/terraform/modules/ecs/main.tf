# ---- Cluster ----

resource "aws_ecs_cluster" "this" {
  name = "${var.project_name}-cluster"

  setting {
    name  = "containerInsights"
    value = "enabled"
  }

  tags = {
    Name = "${var.project_name}-cluster"
  }
}

resource "aws_ecs_cluster_capacity_providers" "this" {
  cluster_name = aws_ecs_cluster.this.name

  capacity_providers = ["FARGATE", "FARGATE_SPOT"]
}

# ---- Service Discovery ----

resource "aws_service_discovery_service" "redis" {
  name = "redis"

  dns_config {
    namespace_id = var.service_discovery_namespace_id

    dns_records {
      ttl  = 10
      type = "A"
    }

    routing_policy = "MULTIVALUE"
  }

  health_check_custom_config {
    failure_threshold = 1
  }
}

# ---- Common environment for api + worker ----

locals {
  shared_env = [
    { name = "AWS_REGION", value = var.aws_region },
    { name = "DYNAMODB_USERS_TABLE", value = var.users_table_name },
    { name = "DYNAMODB_JOBS_TABLE", value = var.jobs_table_name },
    { name = "SQS_HIGH_QUEUE_URL", value = var.high_queue_url },
    { name = "SQS_STANDARD_QUEUE_URL", value = var.standard_queue_url },
    { name = "SQS_DLQ_URL", value = var.dlq_url },
    { name = "S3_REPORTS_BUCKET", value = var.reports_bucket_name },
    { name = "SNS_TOPIC_ARN", value = var.sns_topic_arn },
    { name = "REDIS_URL", value = "redis://redis.prosperas.local:6379/0" },
    { name = "JWT_SECRET", value = var.jwt_secret },
    { name = "JWT_EXPIRY_MINUTES", value = "60" },
    { name = "LOG_LEVEL", value = "INFO" },
    { name = "GIT_SHA", value = var.git_sha },
  ]
}

# ---- API task definition ----

resource "aws_ecs_task_definition" "api" {
  family                   = "${var.project_name}-api"
  cpu                      = var.api_cpu
  memory                   = var.api_memory
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  execution_role_arn       = var.task_execution_role_arn
  task_role_arn            = var.api_task_role_arn

  container_definitions = jsonencode([
    {
      name      = "api"
      image     = var.api_image
      essential = true
      portMappings = [{
        containerPort = 8000
        protocol      = "tcp"
      }]
      environment = local.shared_env
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-group         = var.api_log_group_name
          awslogs-region        = var.aws_region
          awslogs-stream-prefix = "ecs"
        }
      }
      # Use Python (already present in the image) instead of curl
      # (which is not in python:3.12-slim) — every check on the previous
      # config exited "curl: not found", so ECS killed each container
      # 90s after start and the rolling deploy never converged.
      healthCheck = {
        command     = ["CMD", "python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/health').status==200 else 1)"]
        interval    = 30
        timeout     = 5
        retries     = 3
        startPeriod = 30
      }
    }
  ])
}

# ---- Worker task definition ----

resource "aws_ecs_task_definition" "worker" {
  family                   = "${var.project_name}-worker"
  cpu                      = var.worker_cpu
  memory                   = var.worker_memory
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  execution_role_arn       = var.task_execution_role_arn
  task_role_arn            = var.worker_task_role_arn

  container_definitions = jsonencode([
    {
      name      = "worker"
      image     = var.worker_image
      essential = true
      command   = ["python", "-m", "worker.main"]
      environment = concat(local.shared_env, [
        { name = "WORKER_CONCURRENCY", value = tostring(var.worker_concurrency) },
      ])
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-group         = var.worker_log_group_name
          awslogs-region        = var.aws_region
          awslogs-stream-prefix = "ecs"
        }
      }
    }
  ])
}

# ---- Redis task definition (Fargate Spot, ephemeral) ----

resource "aws_ecs_task_definition" "redis" {
  family                   = "${var.project_name}-redis"
  cpu                      = var.redis_cpu
  memory                   = var.redis_memory
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  execution_role_arn       = var.task_execution_role_arn
  task_role_arn            = var.redis_task_role_arn

  container_definitions = jsonencode([
    {
      name      = "redis"
      image     = "redis:7-alpine"
      essential = true
      portMappings = [{
        containerPort = 6379
        protocol      = "tcp"
      }]
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-group         = var.redis_log_group_name
          awslogs-region        = var.aws_region
          awslogs-stream-prefix = "ecs"
        }
      }
    }
  ])
}

# ---- API service ----

resource "aws_ecs_service" "api" {
  name            = "${var.project_name}-api"
  cluster         = aws_ecs_cluster.this.id
  task_definition = aws_ecs_task_definition.api.arn
  desired_count   = var.api_desired_count
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = var.private_subnet_ids
    security_groups  = [var.api_security_group_id]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = var.api_target_group_arn
    container_name   = "api"
    container_port   = 8000
  }

  deployment_minimum_healthy_percent = 50
  deployment_maximum_percent         = 200

  lifecycle {
    ignore_changes = [task_definition] # CI updates this with --force-new-deployment
  }
}

# ---- Worker service ----

resource "aws_ecs_service" "worker" {
  name            = "${var.project_name}-worker"
  cluster         = aws_ecs_cluster.this.id
  task_definition = aws_ecs_task_definition.worker.arn
  desired_count   = var.worker_desired_count
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = var.private_subnet_ids
    security_groups  = [var.worker_security_group_id]
    assign_public_ip = false
  }

  deployment_minimum_healthy_percent = 50
  deployment_maximum_percent         = 200

  lifecycle {
    ignore_changes = [task_definition]
  }
}

# ---- Redis service (Fargate Spot, single replica) ----

resource "aws_ecs_service" "redis" {
  name            = "${var.project_name}-redis"
  cluster         = aws_ecs_cluster.this.id
  task_definition = aws_ecs_task_definition.redis.arn
  desired_count   = 1

  capacity_provider_strategy {
    capacity_provider = "FARGATE_SPOT"
    weight            = 1
  }

  network_configuration {
    subnets          = var.private_subnet_ids
    security_groups  = [var.redis_security_group_id]
    assign_public_ip = false
  }

  service_registries {
    registry_arn = aws_service_discovery_service.redis.arn
  }

  lifecycle {
    ignore_changes = [task_definition]
  }
}

# ---- Auto-scaling for the API (CPU based) ----

resource "aws_appautoscaling_target" "api" {
  max_capacity       = 6
  min_capacity       = var.api_desired_count
  resource_id        = "service/${aws_ecs_cluster.this.name}/${aws_ecs_service.api.name}"
  scalable_dimension = "ecs:service:DesiredCount"
  service_namespace  = "ecs"
}

resource "aws_appautoscaling_policy" "api_cpu" {
  name               = "${var.project_name}-api-cpu-target"
  policy_type        = "TargetTrackingScaling"
  resource_id        = aws_appautoscaling_target.api.resource_id
  scalable_dimension = aws_appautoscaling_target.api.scalable_dimension
  service_namespace  = aws_appautoscaling_target.api.service_namespace

  target_tracking_scaling_policy_configuration {
    predefined_metric_specification {
      predefined_metric_type = "ECSServiceAverageCPUUtilization"
    }
    target_value       = 70
    scale_in_cooldown  = 60
    scale_out_cooldown = 60
  }
}

# ---- Auto-scaling for the worker (SQS lag based) ----

resource "aws_appautoscaling_target" "worker" {
  max_capacity       = 6
  min_capacity       = var.worker_desired_count
  resource_id        = "service/${aws_ecs_cluster.this.name}/${aws_ecs_service.worker.name}"
  scalable_dimension = "ecs:service:DesiredCount"
  service_namespace  = "ecs"
}

resource "aws_appautoscaling_policy" "worker_lag" {
  name               = "${var.project_name}-worker-lag-target"
  policy_type        = "TargetTrackingScaling"
  resource_id        = aws_appautoscaling_target.worker.resource_id
  scalable_dimension = aws_appautoscaling_target.worker.scalable_dimension
  service_namespace  = aws_appautoscaling_target.worker.service_namespace

  target_tracking_scaling_policy_configuration {
    customized_metric_specification {
      metric_name = "ApproximateNumberOfMessagesVisible"
      namespace   = "AWS/SQS"
      statistic   = "Average"

      dimensions {
        name  = "QueueName"
        value = "${var.project_name}-jobs-standard"
      }
    }
    target_value       = 10
    scale_in_cooldown  = 120
    scale_out_cooldown = 60
  }
}
