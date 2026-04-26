data "aws_caller_identity" "current" {}

module "network" {
  source = "../../modules/network"

  project_name = var.project_name
  vpc_cidr     = var.vpc_cidr
  azs          = var.azs
}

module "dynamo" {
  source = "../../modules/dynamo"

  project_name = var.project_name
}

module "sqs" {
  source = "../../modules/sqs"

  project_name = var.project_name
}

module "sns" {
  source = "../../modules/sns"

  project_name = var.project_name
}

module "s3" {
  source = "../../modules/s3"

  project_name = var.project_name
  account_id   = data.aws_caller_identity.current.account_id
}

module "ecr" {
  source = "../../modules/ecr"

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
