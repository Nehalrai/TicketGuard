resource "aws_dynamodb_table" "seats" {
  name         = "${var.project_name}-seats"
  billing_mode = "PAY_PER_REQUEST" # spiky, unpredictable traffic — on-demand avoids both throttling and over-provisioning cost
  hash_key     = "seat_id"

  attribute {
    name = "seat_id"
    type = "S"
  }

  point_in_time_recovery {
    enabled = true
  }
}

resource "aws_dynamodb_table" "idempotency_keys" {
  name         = "${var.project_name}-idempotency-keys"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "idempotency_key"

  attribute {
    name = "idempotency_key"
    type = "S"
  }

  ttl {
    attribute_name = "expires_at"
    enabled        = true
  }
}

resource "aws_sqs_queue" "booking_events_dlq" {
  name = "${var.project_name}-booking-events-dlq"
}

resource "aws_sqs_queue" "booking_events" {
  name                       = "${var.project_name}-booking-events"
  visibility_timeout_seconds = 30
  message_retention_seconds  = 86400

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.booking_events_dlq.arn
    maxReceiveCount      = 5
  })
}

resource "aws_secretsmanager_secret" "app_secrets" {
  name = "${var.project_name}/app-secrets"
}