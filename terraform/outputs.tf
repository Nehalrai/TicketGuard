output "eks_cluster_name" {
  value = module.eks.cluster_name
}

output "eks_cluster_endpoint" {
  value = module.eks.cluster_endpoint
}

output "ecr_repositories" {
  value = {
    inventory    = aws_ecr_repository.inventory.repository_url
    booking      = aws_ecr_repository.booking.repository_url
    notification = aws_ecr_repository.notification.repository_url
  }
}

output "sqs_booking_events_url" {
  value = aws_sqs_queue.booking_events.url
}

output "github_actions_role_arn" {
  value = aws_iam_role.github_actions_deploy.arn
}