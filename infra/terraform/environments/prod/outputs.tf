output "vpc_id" {
  value = module.network.vpc_id
}

output "public_subnet_ids" {
  value = module.network.public_subnet_ids
}

output "private_subnet_ids" {
  value = module.network.private_subnet_ids
}

output "alb_security_group_id" {
  value = module.network.alb_security_group_id
}

output "api_security_group_id" {
  value = module.network.api_security_group_id
}

output "worker_security_group_id" {
  value = module.network.worker_security_group_id
}

output "redis_security_group_id" {
  value = module.network.redis_security_group_id
}

output "service_discovery_namespace_id" {
  value = module.network.service_discovery_namespace_id
}

# ---- New outputs from Tasks 8.3 + 8.4 ----

output "users_table_name" {
  value = module.dynamo.users_table_name
}

output "jobs_table_name" {
  value = module.dynamo.jobs_table_name
}

output "high_queue_url" {
  value = module.sqs.high_queue_url
}

output "standard_queue_url" {
  value = module.sqs.standard_queue_url
}

output "dlq_url" {
  value = module.sqs.dlq_url
}

output "reports_bucket_name" {
  value = module.s3.reports_bucket_name
}

output "frontend_bucket_name" {
  value = module.s3.frontend_bucket_name
}

output "sns_topic_arn" {
  value = module.sns.topic_arn
}

output "api_repository_url" {
  value = module.ecr.api_repository_url
}

output "worker_repository_url" {
  value = module.ecr.worker_repository_url
}

output "api_task_role_arn" {
  value = module.iam.api_task_role_arn
}

output "worker_task_role_arn" {
  value = module.iam.worker_task_role_arn
}

output "task_execution_role_arn" {
  value = module.iam.task_execution_role_arn
}

output "api_log_group_name" {
  value = module.observability.api_log_group_name
}

output "worker_log_group_name" {
  value = module.observability.worker_log_group_name
}

output "alarm_topic_arn" {
  value = module.observability.alarm_topic_arn
}

output "alb_dns_name" {
  description = "Public DNS of the API ALB. Send API requests here."
  value       = module.alb.alb_dns_name
}

output "frontend_url" {
  description = "Public HTTPS URL of the frontend (CloudFront)."
  value       = "https://${module.cloudfront.distribution_domain_name}"
}

output "cloudfront_distribution_id" {
  value = module.cloudfront.distribution_id
}

output "ecs_cluster_name" {
  value = module.ecs.cluster_name
}

output "api_service_name" {
  value = module.ecs.api_service_name
}

output "worker_service_name" {
  value = module.ecs.worker_service_name
}
