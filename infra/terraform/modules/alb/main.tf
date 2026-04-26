# Public Application Load Balancer.
#
# Runs HTTP-only because we don't have a domain + ACM certificate for
# this demo. In production we'd add an HTTPS listener with an ACM cert
# attached to a domain and redirect HTTP -> HTTPS. The CloudFront
# distribution in front of the frontend already serves HTTPS via the
# default *.cloudfront.net cert; this ALB is for API traffic only.

resource "aws_lb" "this" {
  name               = "${var.project_name}-alb"
  load_balancer_type = "application"
  internal           = false
  security_groups    = [var.alb_security_group_id]
  subnets            = var.public_subnet_ids

  idle_timeout = 120 # SSE keepalives every 15s; default 60s would be fine, 120s is generous

  tags = {
    Name = "${var.project_name}-alb"
  }
}

resource "aws_lb_target_group" "api" {
  name        = "${var.project_name}-api-tg"
  vpc_id      = var.vpc_id
  port        = 8000
  protocol    = "HTTP"
  target_type = "ip" # Required for Fargate

  health_check {
    path                = "/health"
    matcher             = "200"
    interval            = 30
    timeout             = 5
    healthy_threshold   = 2
    unhealthy_threshold = 3
  }

  deregistration_delay = 30 # Drain in-flight requests; SSE clients will reconnect

  tags = {
    Name = "${var.project_name}-api-tg"
  }
}

resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.this.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.api.arn
  }
}
