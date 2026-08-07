terraform {
  required_version = ">= 1.6.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    kubernetes = {
      source  = "hashicorp/kubernetes"
      version = "~> 2.27"
    }
  }

  # Remote state — created once, out of band, before first `terraform init`.
  # backend "s3" {
  #   bucket         = "ticketguard-tfstate"
  #   key            = "ticketguard/terraform.tfstate"
  #   region         = "ap-south-1"
  #   dynamodb_table = "ticketguard-tf-lock"
  #   encrypt        = true
  # }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project   = "ticketguard"
      ManagedBy = "terraform"
    }
  }
}