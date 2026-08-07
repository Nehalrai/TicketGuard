resource "aws_ecr_repository" "inventory" {
  name                 = "${var.project_name}/inventory-service"
  image_tag_mutability = "IMMUTABLE"

  image_scanning_configuration {
    scan_on_push = true # feeds the Trivy/ECR scan gate in CI
  }
}

resource "aws_ecr_repository" "booking" {
  name                 = "${var.project_name}/booking-service"
  image_tag_mutability = "IMMUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }
}

resource "aws_ecr_repository" "notification" {
  name                 = "${var.project_name}/notification-service"
  image_tag_mutability = "IMMUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }
}