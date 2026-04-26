# Kept as forward-compatibility hook even though the current
# implementation publishes job-update events directly to Redis.
# Cost: $0 idle.

resource "aws_sns_topic" "job_updates" {
  name              = "${var.project_name}-job-updates"
  kms_master_key_id = "alias/aws/sns"

  tags = {
    Name = "${var.project_name}-job-updates"
  }
}
