terraform {
  required_version = ">= 1.6"

  backend "s3" {
    bucket         = "prosperas-tfstate-000758060526"
    key            = "prod/terraform.tfstate"
    region         = "us-east-1"
    dynamodb_table = "prosperas-tflock"
    encrypt        = true
  }

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.70"
    }
  }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project     = "prosperas-challenge"
      ManagedBy   = "terraform"
      Environment = "prod"
    }
  }
}
