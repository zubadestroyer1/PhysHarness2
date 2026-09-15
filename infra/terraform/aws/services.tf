locals {
  task_kinds = toset(["api", "worker", "migration"])
  shared_environment = [
    { name = "PHYSHARNESS_MODE", value = "production" },
    { name = "PHYSHARNESS_AUTO_CREATE_SCHEMA", value = "false" },
    { name = "PHYSHARNESS_ARTIFACT_BUCKET", value = aws_s3_bucket.artifacts.id },
    { name = "PHYSHARNESS_TEMPORAL_ADDRESS", value = var.temporal_address },
    { name = "PHYSHARNESS_TEMPORAL_NAMESPACE", value = var.temporal_namespace },
    { name = "PHYSHARNESS_TEMPORAL_TLS", value = "true" },
    { name = "PHYSHARNESS_CORS_ORIGINS", value = jsonencode(var.cors_origins) },
    { name = "AWS_REGION", value = var.aws_region },
    { name = "AWS_DEFAULT_REGION", value = var.aws_region },
    { name = "PGSSLROOTCERT", value = "/app/rds-ca.pem" },
    { name = "PGSSLMODE", value = "verify-full" },
  ]
  secrets = {
    api = {
      PHYSHARNESS_DATABASE_URL = var.database_url_secret_arn
      PHYSHARNESS_AUTH_TOKENS  = var.auth_tokens_secret_arn
    }
    worker = merge({
      PHYSHARNESS_DATABASE_URL     = var.database_url_secret_arn
      PHYSHARNESS_AUTH_TOKENS      = var.auth_tokens_secret_arn
      PHYSHARNESS_TEMPORAL_API_KEY = var.temporal_api_key_secret_arn
      OPENAI_API_KEY               = var.openai_api_key_secret_arn
    }, var.e2b_api_key_secret_arn == null ? {} : { E2B_API_KEY = var.e2b_api_key_secret_arn })
    migration = { PHYSHARNESS_DATABASE_URL = var.migration_database_url_secret_arn }
  }
  commands = {
    api       = ["python", "-m", "uvicorn", "physharness.api:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
    worker    = ["python", "-m", "physharness.worker"]
    migration = ["python", "-m", "alembic", "upgrade", "head"]
  }
}
resource "aws_ecs_cluster" "main" {
  name = var.name
  setting {
    name  = "containerInsights"
    value = "enabled"
  }
}
resource "aws_cloudwatch_log_group" "tasks" {
  for_each          = local.task_kinds
  name              = "/ecs/${var.name}/${each.key}"
  retention_in_days = 30
}
resource "aws_iam_role" "execution" {
  for_each    = local.task_kinds
  name_prefix = "${var.name}-${each.key}-exec-"
  assume_role_policy = jsonencode({
    Version = "2012-10-17", Statement = [{
      Effect = "Allow", Action = "sts:AssumeRole", Principal = { Service = "ecs-tasks.amazonaws.com" }
    }]
  })
}
resource "aws_iam_role_policy_attachment" "execution" {
  for_each   = local.task_kinds
  role       = aws_iam_role.execution[each.key].name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}
resource "aws_iam_role_policy" "secrets" {
  for_each = local.task_kinds
  role     = aws_iam_role.execution[each.key].id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = concat([
      { Effect = "Allow", Action = ["secretsmanager:GetSecretValue"], Resource = values(local.secrets[each.key]) }
      ], length(var.secret_kms_key_arns) == 0 ? [] : [
      { Effect = "Allow", Action = ["kms:Decrypt"], Resource = var.secret_kms_key_arns }
    ])
  })
}
resource "aws_iam_role" "task" {
  for_each    = local.task_kinds
  name_prefix = "${var.name}-${each.key}-task-"
  assume_role_policy = jsonencode({
    Version = "2012-10-17", Statement = [{
      Effect = "Allow", Action = "sts:AssumeRole", Principal = { Service = "ecs-tasks.amazonaws.com" }
    }]
  })
}
resource "aws_iam_role_policy" "artifacts" {
  for_each = toset(["api", "worker"])
  role     = aws_iam_role.task[each.key].id
  policy = jsonencode({
    Version = "2012-10-17", Statement = [
      { Effect = "Allow", Action = ["s3:GetObject", "s3:GetObjectVersion", "s3:PutObject"], Resource = "${aws_s3_bucket.artifacts.arn}/*" },
      { Effect = "Allow", Action = ["s3:ListBucket"], Resource = aws_s3_bucket.artifacts.arn },
      { Effect = "Allow", Action = ["kms:Decrypt", "kms:GenerateDataKey"], Resource = aws_kms_key.artifacts.arn }
    ]
  })
}
resource "aws_ecs_task_definition" "app" {
  for_each                 = local.task_kinds
  family                   = "${var.name}-${each.key}"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.task_cpu
  memory                   = var.task_memory_mib
  execution_role_arn       = aws_iam_role.execution[each.key].arn
  task_role_arn            = aws_iam_role.task[each.key].arn
  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "X86_64"
  }
  volume { name = "scratch" }
  container_definitions = jsonencode([{
    name                   = "app", image = var.app_image, essential = true, user = "10001:10001",
    readonlyRootFilesystem = true, command = local.commands[each.key], stopTimeout = 120,
    mountPoints            = [{ sourceVolume = "scratch", containerPath = "/app/.state", readOnly = false }],
    environment = concat(local.shared_environment, each.key == "worker" ? concat([
      { name = "PHYSHARNESS_MODEL_PRICES", value = jsonencode(var.model_prices) }
      ], var.e2b_template_id == null ? [] : [{ name = "PHYSHARNESS_E2B_TEMPLATE_ID", value = var.e2b_template_id }],
    var.worker_workspace == null ? [] : [{ name = "PHYSHARNESS_WORKER_WORKSPACE", value = jsonencode(var.worker_workspace) }]) : []),
    secrets         = [for name, arn in local.secrets[each.key] : { name = name, valueFrom = arn }],
    portMappings    = each.key == "api" ? [{ containerPort = 8000, hostPort = 8000, protocol = "tcp" }] : [],
    linuxParameters = { initProcessEnabled = true },
    logConfiguration = {
      logDriver = "awslogs",
      options = { "awslogs-group" = aws_cloudwatch_log_group.tasks[each.key].name,
      "awslogs-region" = var.aws_region, "awslogs-stream-prefix" = "task" }
    }
  }])
}
resource "aws_lb" "api" {
  name                       = var.name
  internal                   = true
  load_balancer_type         = "application"
  subnets                    = aws_subnet.app[*].id
  security_groups            = [aws_security_group.alb.id]
  drop_invalid_header_fields = true
  enable_deletion_protection = true
}
resource "aws_lb_target_group" "api" {
  name        = var.name
  port        = 8000
  protocol    = "HTTP"
  target_type = "ip"
  vpc_id      = aws_vpc.main.id
  health_check {
    path                = "/healthz"
    matcher             = "200"
    healthy_threshold   = 2
    unhealthy_threshold = 3
  }
}
resource "aws_lb_listener" "api" {
  load_balancer_arn = aws_lb.api.arn
  port              = 443
  protocol          = "HTTPS"
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"
  certificate_arn   = var.certificate_arn
  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.api.arn
  }
}
resource "aws_ecs_service" "api" {
  name             = "api"
  cluster          = aws_ecs_cluster.main.id
  task_definition  = aws_ecs_task_definition.app["api"].arn
  desired_count    = var.api_desired_count
  launch_type      = "FARGATE"
  platform_version = "1.4.0"
  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }
  network_configuration {
    subnets          = aws_subnet.app[*].id
    security_groups  = [aws_security_group.tasks.id]
    assign_public_ip = false
  }
  load_balancer {
    target_group_arn = aws_lb_target_group.api.arn
    container_name   = "app"
    container_port   = 8000
  }
  depends_on = [aws_lb_listener.api]
}
resource "aws_ecs_service" "worker" {
  name             = "worker"
  cluster          = aws_ecs_cluster.main.id
  task_definition  = aws_ecs_task_definition.app["worker"].arn
  desired_count    = var.worker_desired_count
  launch_type      = "FARGATE"
  platform_version = "1.4.0"
  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }
  network_configuration {
    subnets          = aws_subnet.app[*].id
    security_groups  = [aws_security_group.tasks.id]
    assign_public_ip = false
  }
}
