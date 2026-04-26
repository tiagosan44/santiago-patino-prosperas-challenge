module "network" {
  source = "../../modules/network"

  project_name = var.project_name
  vpc_cidr     = var.vpc_cidr
  azs          = var.azs
}

# Other modules (dynamo, sqs, sns, s3, ecr, iam, alb, ecs, cloudfront,
# observability) will be wired in later tasks. This file is the
# composition root; each module declares its own resources.
