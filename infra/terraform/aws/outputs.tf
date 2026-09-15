output "cluster_arn" { value = aws_ecs_cluster.main.arn }
output "api_hostname" { value = aws_lb.api.dns_name }
output "database_address" { value = aws_db_instance.main.address }
output "database_admin_secret_arn" {
  description = "Administrative bootstrap only; never inject this secret into API/model workers."
  value       = aws_db_instance.main.master_user_secret[0].secret_arn
}
output "artifact_bucket" { value = aws_s3_bucket.artifacts.id }
output "migration_task_definition" { value = aws_ecs_task_definition.app["migration"].arn }
output "private_subnet_ids" { value = aws_subnet.app[*].id }
output "task_security_group_id" { value = aws_security_group.tasks.id }
output "qualification" { value = "UNQUALIFIED: validate live failover, backups, IAM, provider access and load before production" }
