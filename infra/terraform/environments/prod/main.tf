data "aws_caller_identity" "current" {}

module "network" {
  source = "../../modules/network"

  project_name = var.project_name
  vpc_cidr     = var.vpc_cidr
  azs          = var.azs
}

module "dynamo" {
  source       = "../../modules/dynamo"
  project_name = var.project_name
}

module "sqs" {
  source       = "../../modules/sqs"
  project_name = var.project_name
}

module "sns" {
  source       = "../../modules/sns"
  project_name = var.project_name
}

module "s3" {
  source = "../../modules/s3"

  project_name = var.project_name
  account_id   = data.aws_caller_identity.current.account_id
}

module "ecr" {
  source       = "../../modules/ecr"
  project_name = var.project_name
}

module "iam" {
  source = "../../modules/iam"

  project_name               = var.project_name
  users_table_arn            = module.dynamo.users_table_arn
  users_username_index_arn   = module.dynamo.users_username_index_arn
  jobs_table_arn             = module.dynamo.jobs_table_arn
  jobs_indexes_arn_pattern   = module.dynamo.jobs_indexes_arn_pattern
  high_queue_arn             = module.sqs.high_queue_arn
  standard_queue_arn         = module.sqs.standard_queue_arn
  dlq_arn                    = module.sqs.dlq_arn
  reports_bucket_arn         = module.s3.reports_bucket_arn
  reports_bucket_objects_arn = module.s3.reports_bucket_objects_arn
  sns_topic_arn              = module.sns.topic_arn
}

module "observability" {
  source = "../../modules/observability"

  project_name = var.project_name
  dlq_name     = "${var.project_name}-jobs-dlq"
}

module "alb" {
  source = "../../modules/alb"

  project_name          = var.project_name
  vpc_id                = module.network.vpc_id
  public_subnet_ids     = module.network.public_subnet_ids
  alb_security_group_id = module.network.alb_security_group_id
}

module "ecs" {
  source = "../../modules/ecs"

  project_name = var.project_name
  aws_region   = var.aws_region

  private_subnet_ids             = module.network.private_subnet_ids
  api_security_group_id          = module.network.api_security_group_id
  worker_security_group_id       = module.network.worker_security_group_id
  redis_security_group_id        = module.network.redis_security_group_id
  service_discovery_namespace_id = module.network.service_discovery_namespace_id

  task_execution_role_arn = module.iam.task_execution_role_arn
  api_task_role_arn       = module.iam.api_task_role_arn
  worker_task_role_arn    = module.iam.worker_task_role_arn
  redis_task_role_arn     = module.iam.redis_task_role_arn

  api_image    = "${module.ecr.api_repository_url}:${var.image_tag}"
  worker_image = "${module.ecr.worker_repository_url}:${var.image_tag}"

  api_log_group_name    = module.observability.api_log_group_name
  worker_log_group_name = module.observability.worker_log_group_name
  redis_log_group_name  = module.observability.redis_log_group_name

  api_target_group_arn = module.alb.api_target_group_arn

  users_table_name    = module.dynamo.users_table_name
  jobs_table_name     = module.dynamo.jobs_table_name
  high_queue_url      = module.sqs.high_queue_url
  standard_queue_url  = module.sqs.standard_queue_url
  dlq_url             = module.sqs.dlq_url
  reports_bucket_name = module.s3.reports_bucket_name
  sns_topic_arn       = module.sns.topic_arn

  jwt_secret = var.jwt_secret
  git_sha    = var.image_tag
}

module "cloudfront" {
  source = "../../modules/cloudfront"

  project_name                         = var.project_name
  frontend_bucket_id                   = module.s3.frontend_bucket_name
  frontend_bucket_arn                  = module.s3.frontend_bucket_arn
  frontend_bucket_regional_domain_name = module.s3.frontend_bucket_regional_domain_name
  alb_dns_name                         = module.alb.alb_dns_name
}
