output "users_table_name" {
  value = aws_dynamodb_table.users.name
}

output "users_table_arn" {
  value = aws_dynamodb_table.users.arn
}

output "users_username_index_arn" {
  value = "${aws_dynamodb_table.users.arn}/index/username-index"
}

output "jobs_table_name" {
  value = aws_dynamodb_table.jobs.name
}

output "jobs_table_arn" {
  value = aws_dynamodb_table.jobs.arn
}

output "jobs_indexes_arn_pattern" {
  description = "ARN pattern matching every GSI on the jobs table"
  value       = "${aws_dynamodb_table.jobs.arn}/index/*"
}
