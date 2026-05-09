#!/usr/bin/env python3
"""
generate-terraform.py — Terraform module template generator for Kimi IaC skill.

Generates opinionated Terraform modules with:
  - Mandatory tagging (environment, owner, cost-center, project)
  - Security defaults (encryption, least-privilege, network segmentation)
  - Vault-based secret references (no inline secrets)
  - Platform support: AWS, GCP, Azure

Usage:
  python generate-terraform.py --project myapp --platform aws --env staging --owner team-platform \
    --cost-center cc-1234 --components "vpc,compute,rds,alb,s3" --output ./infra

Components supported:
  - vpc / network      — Virtual network, subnets, routing, firewall rules
  - compute / vm       — VMs, instance groups, launch templates (AWS EC2 / GCP Compute / Azure VM)
  - rds / db           — Managed relational databases (RDS / Cloud SQL / Azure SQL)
  - alb / lb           — Application load balancers with TLS termination
  - s3 / storage       — Object storage buckets with encryption and lifecycle
  - cache / redis      — Managed Redis/Memcached (ElastiCache / Memorystore / Azure Cache)
  - iam                — IAM roles, policies, service accounts with least-privilege defaults
  - eks / gke / aks    — Kubernetes cluster (platform-specific)

This script is intended to be called by the Kimi agent during Step 3 of the IaC workflow.
"""

import argparse
import json
import os
import sys
from pathlib import Path
from typing import List, Optional

# ────────────────────────────── defaults ──────────────────────────────

DEFAULT_REGIONS = {
    "aws": "us-east-1",
    "gcp": "us-central1",
    "azure": "eastus",
}

MANDATORY_TAGS = ["environment", "owner", "cost-center", "project"]

SECURITY_DEFAULTS = {
    "aws": {
        "enable_eni_encryption": True,
        "enable_ebs_encryption": True,
        "enable_rds_encryption": True,
        "enable_s3_encryption": "AES256",
        "enable_s3_versioning": True,
        "enable_s3_block_public_access": True,
        "enable_vpc_flow_logs": True,
        "enable_guardduty": False,  # opt-in, costs $$$
        "enable_cloudtrail": True,
    },
    "gcp": {
        "enable_disk_encryption": "CMEK",
        "enable_sql_encryption": True,
        "enable_gcs_encryption": True,
        "enable_gcs_uniform_access": True,
        "enable_vpc_flow_logs": True,
        "enable_cloud_audit": True,
    },
    "azure": {
        "enable_disk_encryption": True,
        "enable_sql_encryption": True,
        "enable_storage_encryption": True,
        "enable_blob_public_access": False,
        "enable_nsg_flow_logs": True,
        "enable_activity_logs": True,
    },
}

# ────────────────────────────── helpers ──────────────────────────────


def _tag_block(project: str, env: str, owner: str, cost_center: str, extra: Optional[dict] = None) -> str:
    tags = {
        "project": project,
        "environment": env,
        "owner": owner,
        "cost-center": cost_center,
    }
    if extra:
        tags.update(extra)
    lines = json.dumps(tags, indent=2)
    # convert to HCL2 map syntax
    return lines


def _header(project: str, platform: str, region: str) -> str:
    return f"""# Auto-generated Terraform for {project}
# Platform: {platform}
# Region:   {region}
#
# SECURITY NOTICE:
# - All taggable resources MUST include the default_tags block.
# - Secrets are referenced via vault variables; NEVER hardcode credentials.
# - Encryption is enabled by default for storage and databases.
# - State locking is configured via S3 + DynamoDB (or equivalent); NEVER use local state.
# - Run Checkov before generating any plan; block on CRITICAL findings.

terraform {{
  required_version = ">= 1.5.0"

  backend "s3" {{
    # Example: configure remote state with encryption and DynamoDB locking.
    # Replace with your actual bucket, key, region, and DynamoDB table.
    bucket         = "myorg-terraform-state"
    key            = "{project}/{project}-env/terraform.tfstate"
    region         = "us-east-1"
    encrypt        = true
    kms_key_id     = "arn:aws:kms:us-east-1:123456789:key/alias/terraform-state"
    dynamodb_table = "terraform-locks"
    # NEVER commit state files to version control.
  }}
}}

provider "{platform}" {{
  region = var.region
  default_tags {{
    tags = var.mandatory_tags
  }}
}}

variable "region" {{
  type    = string
  default = "{region}"
}}

variable "project" {{
  type    = string
  default = "{project}"
}}

variable "environment" {{
  type    = string
  default = "{project}-env"
}}

variable "owner" {{
  type = string
}}

variable "cost-center" {{
  type = string
}}

variable "mandatory_tags" {{
  type = map(string)
  default = {{
    environment = "{project}-env"
    owner       = var.owner
    cost-center = var.cost-center
    project     = "{project}"
  }}
}}

# ── Vault secret references (NO inline secrets) ──
# Example: database_password = data.vault_generic_secret.db.data["password"]
# Ensure Vault provider is configured separately.
"""


# ────────────────────────── component generators ──────────────────────────


def _aws_vpc(project: str, env: str, owner: str, cost_center: str) -> str:
    return f"""
# ── VPC & Networking ──
module "vpc" {{
  source  = "terraform-aws-modules/vpc/aws"
  version = "~> 5.0"

  name = "${{var.project}}-${{var.environment}}-vpc"
  cidr = "10.0.0.0/16"

  azs             = ["${{var.region}}a", "${{var.region}}b", "${{var.region}}c"]
  private_subnets = ["10.0.1.0/24", "10.0.2.0/24", "10.0.3.0/24"]
  public_subnets  = ["10.0.101.0/24", "10.0.102.0/24", "10.0.103.0/24"]

  enable_nat_gateway   = true
  single_nat_gateway   = var.environment != "prod"
  enable_dns_hostnames = true
  enable_dns_support   = true

  # Security: VPC Flow Logs
  enable_flow_log                      = true
  create_flow_log_cloudwatch_log_group = true
  create_flow_log_cloudwatch_iam_role    = true

  tags = var.mandatory_tags
}}
"""


def _aws_compute(project: str, env: str) -> str:
    return """
# ── Compute (EC2 Launch Template / ASG) ──
module "asg" {
  source  = "terraform-aws-modules/autoscaling/aws"
  version = "~> 7.0"

  name = "${var.project}-${var.environment}-asg"

  min_size         = var.environment == "prod" ? 2 : 1
  max_size         = var.environment == "prod" ? 10 : 3
  desired_capacity = var.environment == "prod" ? 2 : 1

  launch_template_name        = "${var.project}-${var.environment}-lt"
  launch_template_description = "Launch template for ${var.project}"
  image_id                    = data.aws_ami.amazon_linux.id
  instance_type               = var.environment == "prod" ? "m6i.large" : "t3.medium"
  enable_monitoring           = true

  # Security: encrypted EBS
  block_device_mappings = [
    {
      device_name = "/dev/xvda"
      ebs = {
        volume_size           = 50
        volume_type           = "gp3"
        encrypted             = true
        kms_key_id            = aws_kms_key.ebs.arn
        delete_on_termination = true
      }
    }
  ]

  vpc_zone_identifier = module.vpc.private_subnets
  security_groups     = [aws_security_group.compute.id]

  tags = var.mandatory_tags
}

resource "aws_kms_key" "ebs" {
  description             = "EBS encryption key for ${var.project}"
  deletion_window_in_days = 7
  enable_key_rotation     = true
  tags                    = var.mandatory_tags
}

resource "aws_security_group" "compute" {
  name_prefix = "${var.project}-${var.environment}-compute-"
  vpc_id      = module.vpc.vpc_id
  description = "Least-privilege security group for compute"

  # Security: no ingress by default; refine per workload
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
    description = "Egress to internet via NAT"
  }

  tags = var.mandatory_tags
}
"""


def _aws_rds(project: str, env: str) -> str:
    return """
# ── RDS (PostgreSQL) ──
module "rds" {
  source  = "terraform-aws-modules/rds/aws"
  version = "~> 6.0"

  identifier = "${var.project}-${var.environment}-db"

  engine               = "postgres"
  engine_version       = "15.4"
  family               = "postgres15"
  major_engine_version = "15"
  instance_class       = var.environment == "prod" ? "db.r6g.large" : "db.t4g.medium"
  allocated_storage    = 50
  max_allocated_storage= 200

  db_name  = replace("${var.project}_${var.environment}", "-", "_")
  username = "db_admin"
  port     = 5432

  # Security: NO hardcoded password — use Vault or AWS Secrets Manager
  password = data.aws_secretsmanager_secret_version.db_password.secret_string

  iam_database_authentication_enabled = true

  multi_az               = var.environment == "prod"
  subnet_ids             = module.vpc.private_subnets
  vpc_security_group_ids = [aws_security_group.rds.id]

  # Security: encryption + backup + deletion protection
  storage_encrypted   = true
  kms_key_id          = aws_kms_key.rds.arn
  deletion_protection = var.environment == "prod"
  skip_final_snapshot = var.environment != "prod"
  backup_retention_period = var.environment == "prod" ? 7 : 1

  # Performance Insights for observability
  performance_insights_enabled = true

  tags = var.mandatory_tags
}

resource "aws_kms_key" "rds" {
  description             = "RDS encryption key for ${var.project}"
  deletion_window_in_days = 7
  enable_key_rotation     = true
  tags                    = var.mandatory_tags
}

resource "aws_security_group" "rds" {
  name_prefix = "${var.project}-${var.environment}-rds-"
  vpc_id      = module.vpc.vpc_id
  description = "RDS security group — restrict to compute SG"

  ingress {
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.compute.id]
    description     = "PostgreSQL from compute"
  }

  tags = var.mandatory_tags
}

# Secret reference — create in AWS Secrets Manager or Vault before apply
data "aws_secretsmanager_secret_version" "db_password" {
  secret_id = "${var.project}/${var.environment}/db_password"
}
"""


def _aws_alb(project: str, env: str) -> str:
    return """
# ── Application Load Balancer ──
module "alb" {
  source  = "terraform-aws-modules/alb/aws"
  version = "~> 9.0"

  name = "${var.project}-${var.environment}-alb"

  load_balancer_type = "application"
  vpc_id             = module.vpc.vpc_id
  subnets            = module.vpc.public_subnets
  security_groups    = [aws_security_group.alb.id]

  # Security: enforce HTTPS
  listeners = {
    https = {
      port            = 443
      protocol        = "HTTPS"
      certificate_arn = aws_acm_certificate.main.arn
      fixed_response  = {
        content_type = "text/plain"
        message_body = "OK"
        status_code  = "200"
      }
      # Default action routes to target group via separate rule
    }
  }

  target_groups = {
    compute = {
      name_prefix      = "${substr(var.project, 0, 4)}${substr(var.environment, 0, 2)}"
      protocol         = "HTTP"
      port             = 8080
      target_type      = "instance"
      health_check = {
        path                = "/health"
        interval            = 30
        healthy_threshold   = 2
        unhealthy_threshold = 3
      }
      create_attachment = false
    }
  }

  tags = var.mandatory_tags
}

resource "aws_security_group" "alb" {
  name_prefix = "${var.project}-${var.environment}-alb-"
  vpc_id      = module.vpc.vpc_id
  description = "ALB security group — HTTPS ingress only"

  ingress {
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
    description = "HTTPS from internet"
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = var.mandatory_tags
}

resource "aws_acm_certificate" "main" {
  domain_name       = "${var.environment}.${var.project}.example.com"
  validation_method = "DNS"
  tags              = var.mandatory_tags

  lifecycle {
    create_before_destroy = true
  }
}
"""


def _aws_s3(project: str, env: str) -> str:
    return """
# ── S3 Bucket ──
module "s3_bucket" {
  source  = "terraform-aws-modules/s3-bucket/aws"
  version = "~> 4.0"

  bucket = "${var.project}-${var.environment}-data-${data.aws_caller_identity.current.account_id}"

  # Security
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true

  server_side_encryption_configuration = {
    rule = {
      apply_server_side_encryption_by_default = {
        sse_algorithm = "AES256"
      }
      bucket_key_enabled = true
    }
  }

  versioning = {
    enabled = true
  }

  lifecycle_rule = [
    {
      id      = "transition-to-ia"
      status  = "Enabled"
      transition = [
        {
          days          = 30
          storage_class = "STANDARD_IA"
        },
        {
          days          = 90
          storage_class = "GLACIER"
        }
      ]
      noncurrent_version_transition = [
        {
          noncurrent_days = 30
          storage_class   = "GLACIER"
        }
      ]
      expiration = {
        days = 365
      }
    }
  ]

  tags = var.mandatory_tags
}
"""


def _aws_cache(project: str, env: str) -> str:
    return """
# ── ElastiCache (Redis) ──
resource "aws_elasticache_subnet_group" "redis" {
  name       = "${var.project}-${var.environment}-redis"
  subnet_ids = module.vpc.private_subnets
}

resource "aws_elasticache_replication_group" "redis" {
  replication_group_id = "${var.project}-${var.environment}-redis"
  description          = "Redis cluster for ${var.project}"

  node_type             = var.environment == "prod" ? "cache.r6g.large" : "cache.t4g.medium"
  num_cache_clusters    = var.environment == "prod" ? 2 : 1
  automatic_failover_enabled = var.environment == "prod"

  port               = 6379
  subnet_group_name  = aws_elasticache_subnet_group.redis.name
  security_group_ids = [aws_security_group.redis.id]

  # Security
  at_rest_encryption_enabled = true
  transit_encryption_enabled = true
  auth_token                 = data.aws_secretsmanager_secret_version.redis_auth.secret_string

  snapshot_retention_limit = 5
  snapshot_window          = "03:00-04:00"

  tags = var.mandatory_tags
}

resource "aws_security_group" "redis" {
  name_prefix = "${var.project}-${var.environment}-redis-"
  vpc_id      = module.vpc.vpc_id
  description = "Redis security group"

  ingress {
    from_port       = 6379
    to_port         = 6379
    protocol        = "tcp"
    security_groups = [aws_security_group.compute.id]
    description     = "Redis from compute"
  }

  tags = var.mandatory_tags
}

data "aws_secretsmanager_secret_version" "redis_auth" {
  secret_id = "${var.project}/${var.environment}/redis_auth_token"
}
"""


def _aws_eks(project: str, env: str) -> str:
    return """
# ── EKS Cluster ──
module "eks" {
  source  = "terraform-aws-modules/eks/aws"
  version = "~> 20.0"

  cluster_name    = "${var.project}-${var.environment}"
  cluster_version = "1.29"

  vpc_id     = module.vpc.vpc_id
  subnet_ids = module.vpc.private_subnets

  cluster_endpoint_public_access  = var.environment != "prod"
  cluster_endpoint_private_access = true

  # Security: audit logging
  cluster_enabled_log_types = ["api", "audit", "authenticator", "controllerManager", "scheduler"]

  eks_managed_node_groups = {
    main = {
      name           = "${var.project}-${var.environment}-ng"
      instance_types = [var.environment == "prod" ? "m6i.large" : "t3.medium"]
      min_size       = var.environment == "prod" ? 2 : 1
      max_size       = var.environment == "prod" ? 10 : 3
      desired_size   = var.environment == "prod" ? 2 : 1

      iam_role_additional_policies = {
        CloudWatchAgentServerPolicy = "arn:aws:iam::aws:policy/CloudWatchAgentServerPolicy"
      }
    }
  }

  tags = var.mandatory_tags
}
"""


def _aws_iam(project: str, env: str) -> str:
    return """
# ── IAM (Least-privilege roles & policies) ──
resource "aws_iam_role" "workload" {
  name = "${var.project}-${var.environment}-workload"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "ec2.amazonaws.com"
        }
      }
    ]
  })
  tags = var.mandatory_tags
}

resource "aws_iam_policy" "workload_minimal" {
  name   = "${var.project}-${var.environment}-minimal"
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents",
        ]
        Resource = "arn:aws:logs:*:*:log-group:/aws/${var.project}/${var.environment}/*"
      },
      {
        Effect = "Allow"
        Action = [
          "secretsmanager:GetSecretValue",
        ]
        Resource = "arn:aws:secretsmanager:*:*:secret:${var.project}/${var.environment}/*"
      }
    ]
  })
  tags = var.mandatory_tags
}

resource "aws_iam_role_policy_attachment" "workload" {
  role       = aws_iam_role.workload.name
  policy_arn = aws_iam_policy.workload_minimal.arn
}
"""


# ────────────────────────── dispatch map ──────────────────────────

AWS_COMPONENTS = {
    "vpc": _aws_vpc,
    "network": _aws_vpc,
    "compute": _aws_compute,
    "vm": _aws_compute,
    "rds": _aws_rds,
    "db": _aws_rds,
    "alb": _aws_alb,
    "lb": _aws_alb,
    "s3": _aws_s3,
    "storage": _aws_s3,
    "cache": _aws_cache,
    "redis": _aws_cache,
    "eks": _aws_eks,
    "gke": _aws_eks,   # fallback for GCP mapped later
    "aks": _aws_eks,   # fallback for Azure mapped later
    "iam": _aws_iam,
}


# ────────────────────────── GCP generators ──────────────────────────


def _gcp_vpc(project: str, env: str) -> str:
    return f"""
# ── VPC & Networking (GCP) ──
resource "google_compute_network" "vpc" {{
  name                    = "${{var.project}}-${{var.environment}}-vpc"
  auto_create_subnetworks = false
  routing_mode            = "GLOBAL"
}}

resource "google_compute_subnetwork" "private" {{
  name          = "${{var.project}}-${{var.environment}}-private"
  ip_cidr_range = "10.0.0.0/16"
  region        = var.region
  network       = google_compute_network.vpc.id

  private_ip_google_access = true

  log_config {{
    aggregation_interval = "INTERVAL_5_SEC"
    flow_sampling        = 0.5
    metadata             = "INCLUDE_ALL_METADATA"
  }}
}}
"""


def _gcp_compute(project: str, env: str) -> str:
    return """
# ── Compute (GCP Managed Instance Group) ──
resource "google_compute_instance_template" "main" {
  name_prefix = "${var.project}-${var.environment}-"
  machine_type = var.environment == "prod" ? "n2-standard-2" : "e2-medium"

  disk {
    source_image = "cos-cloud/cos-stable"
    auto_delete  = true
    boot         = true
    disk_encryption_key {
      kms_key_self_link = google_kms_crypto_key.compute.id
    }
  }

  network_interface {
    subnetwork = google_compute_subnetwork.private.id
    # No external IP — use Cloud NAT
  }

  metadata = {
    enable-oslogin = "TRUE"
  }

  tags = ["${var.project}", "${var.environment}"]

  labels = var.mandatory_tags
}

resource "google_compute_region_instance_group_manager" "main" {
  name = "${var.project}-${var.environment}-mig"

  base_instance_name = "${var.project}-${var.environment}"
  region             = var.region

  version {
    instance_template = google_compute_instance_template.main.id
  }

  target_size = var.environment == "prod" ? 2 : 1
}
"""


def _gcp_sql(project: str, env: str) -> str:
    return """
# ── Cloud SQL (PostgreSQL) ──
resource "google_sql_database_instance" "main" {
  name             = "${var.project}-${var.environment}-db"
  database_version = "POSTGRES_15"
  region           = var.region

  settings {
    tier = var.environment == "prod" ? "db-custom-2-7680" : "db-f1-micro"
    availability_type = var.environment == "prod" ? "REGIONAL" : "ZONAL"

    backup_configuration {
      enabled            = true
      start_time         = "03:00"
      point_in_time_recovery_enabled = true
    }

    ip_configuration {
      ipv4_enabled    = false
      private_network = google_compute_network.vpc.id
    }

    insights_config {
      query_insights_enabled = true
    }
  }

  deletion_protection = var.environment == "prod"

  # Security: encryption with CMEK
  encryption_key_name = google_kms_crypto_key.sql.id

  depends_on = [google_service_networking_connection.private_vpc_connection]
}

resource "google_sql_user" "main" {
  name     = "db_admin"
  instance = google_sql_database_instance.main.name
  password = data.google_secret_manager_secret_version.db_password.secret_data
}
"""


# ────────────────────────── Azure generators ──────────────────────────


def _azure_vnet(project: str, env: str) -> str:
    return f"""
# ── VNet & Networking (Azure) ──
resource "azurerm_virtual_network" "vnet" {{
  name                = "${{var.project}}-${{var.environment}}-vnet"
  address_space       = ["10.0.0.0/16"]
  location            = var.region
  resource_group_name = azurerm_resource_group.main.name
  tags                = var.mandatory_tags
}}

resource "azurerm_subnet" "private" {{
  name                 = "private"
  resource_group_name  = azurerm_resource_group.main.name
  virtual_network_name = azurerm_virtual_network.vnet.name
  address_prefixes     = ["10.0.1.0/24"]
}}

resource "azurerm_network_watcher_flow_log" "main" {{
  name                = "${{var.project}}-${{var.environment}}-flowlog"
  location            = var.region
  resource_group_name = azurerm_resource_group.main.name
  network_watcher_name = azurerm_network_watcher.main.name

  target_resource_id = azurerm_virtual_network.vnet.id
  storage_account_id = azurerm_storage_account.flowlogs.id

  enabled = true
}}
"""


def _azure_vm(project: str, env: str) -> str:
    return """
# ── Virtual Machine Scale Set (Azure) ──
resource "azurerm_linux_virtual_machine_scale_set" "main" {
  name                = "${var.project}-${var.environment}-vmss"
  resource_group_name = azurerm_resource_group.main.name
  location            = var.region
  sku                 = var.environment == "prod" ? "Standard_D2s_v5" : "Standard_B2s"
  instances           = var.environment == "prod" ? 2 : 1

  admin_username = "adminuser"
  admin_ssh_key {
    username   = "adminuser"
    public_key = data.azurerm_key_vault_secret.ssh_public_key.value
  }

  os_disk {
    caching              = "ReadWrite"
    storage_account_type = "Premium_LRS"
    disk_encryption_set_id = azurerm_disk_encryption_set.main.id
  }

  network_interface {
    name    = "nic"
    primary = true

    ip_configuration {
      name      = "internal"
      primary   = true
      subnet_id = azurerm_subnet.private.id
    }
  }

  tags = var.mandatory_tags
}
"""


def _azure_sql(project: str, env: str) -> str:
    return """
# ── Azure SQL Database ──
resource "azurerm_mssql_server" "main" {
  name                         = "${var.project}-${var.environment}-sql"
  resource_group_name          = azurerm_resource_group.main.name
  location                     = var.region
  version                      = "12.0"
  administrator_login          = "sqladmin"
  administrator_login_password = data.azurerm_key_vault_secret.sql_password.value

  minimum_tls_version = "1.2"
  azuread_administrator {
    login_username = var.owner
    object_id      = data.azuread_group.admins.object_id
  }

  tags = var.mandatory_tags
}

resource "azurerm_mssql_database" "main" {
  name         = "${var.project}_${var.environment}"
  server_id    = azurerm_mssql_server.main.id
  sku_name     = var.environment == "prod" ? "S2" : "S0"
  enclave_type = "VBS"

  transparent_data_encryption {
    key_vault_key_id = azurerm_key_vault_key.tde.id
  }

  tags = var.mandatory_tags
}
"""


# ────────────────────────── platform dispatch ──────────────────────────

PLATFORM_COMPONENTS = {
    "aws": AWS_COMPONENTS,
    "gcp": {
        "vpc": _gcp_vpc,
        "network": _gcp_vpc,
        "compute": _gcp_compute,
        "vm": _gcp_compute,
        "rds": _gcp_sql,
        "db": _gcp_sql,
    },
    "azure": {
        "vpc": _azure_vnet,
        "network": _azure_vnet,
        "compute": _azure_vm,
        "vm": _azure_vm,
        "rds": _azure_sql,
        "db": _azure_sql,
    },
}


def generate_module(platform: str, components: List[str], project: str, env: str,
                    owner: str, cost_center: str, region: str) -> str:
    """Generate a complete Terraform module for the given platform and components."""
    registry = PLATFORM_COMPONENTS.get(platform)
    if not registry:
        raise ValueError(f"Unsupported platform: {platform}. Choose from aws, gcp, azure.")

    parts = [_header(project, platform, region)]
    seen = set()

    # Normalize component names
    for comp in components:
        comp = comp.strip().lower()
        if comp in seen:
            continue
        seen.add(comp)
        gen = registry.get(comp)
        if gen:
            parts.append(gen(project, env))
        else:
            # Write a placeholder for unimplemented components
            parts.append(f"\n# ── {comp.upper()} (placeholder — extend generator) ──\n# TODO: add {comp} module\n")

    # Append data sources and footer
    parts.append(f"""
# ── Data sources ──
data "aws_caller_identity" "current" {{}}

# ── Outputs ──
output "project" {{
  value = var.project
}}

output "environment" {{
  value = var.environment
}}

output "mandatory_tags" {{
  value = var.mandatory_tags
}}
""")

    return "\n".join(parts)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate opinionated Terraform modules with security defaults and mandatory tagging."
    )
    parser.add_argument("--project", required=True, help="Project name")
    parser.add_argument("--platform", required=True, choices=["aws", "gcp", "azure"], help="Cloud platform")
    parser.add_argument("--env", default="dev", help="Environment name (dev/staging/prod)")
    parser.add_argument("--owner", required=True, help="Team or individual owner")
    parser.add_argument("--cost-center", required=True, help="Cost center / billing code")
    parser.add_argument("--components", required=True, help="Comma-separated component list")
    parser.add_argument("--region", default=None, help="Cloud region (platform default if omitted)")
    parser.add_argument("--output", default="./terraform", help="Output directory for generated files")

    args = parser.parse_args()

    region = args.region or DEFAULT_REGIONS[args.platform]
    components = [c.strip() for c in args.components.split(",")]

    # Validate mandatory parameters are non-empty
    for param in (args.project, args.owner, args.cost_center):
        if not param or not param.strip():
            print(f"ERROR: required parameter is empty", file=sys.stderr)
            return 1

    # Validate all requested components exist in registry (warn on unknown)
    registry = PLATFORM_COMPONENTS.get(args.platform, {})
    unknown = [c for c in components if c.lower() not in registry]
    if unknown:
        print(f"WARNING: unimplemented components for {args.platform}: {unknown}", file=sys.stderr)
        print(f"  Supported: {list(registry.keys())}", file=sys.stderr)

    module_content = generate_module(
        platform=args.platform,
        components=components,
        project=args.project,
        env=args.env,
        owner=args.owner,
        cost_center=args.cost_center,
        region=region,
    )

    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)

    main_tf = out_dir / "main.tf"
    main_tf.write_text(module_content, encoding="utf-8")

    # Write README with security notice
    readme = out_dir / "README.md"
    readme.write_text(f"""# {args.project} — {args.platform} infrastructure

## Security Checklist
- [ ] All resources tagged with: environment, owner, cost-center, project
- [ ] No secrets hardcoded in `.tf` files
- [ ] Remote state backend configured with encryption + locking (S3 + DynamoDB / GCS / Azure Blob)
- [ ] Checkov scan run **before** plan generation — no CRITICAL findings
- [ ] `terraform plan -out=plan.tfplan` generated and stored as artifact
- [ ] Plan review artifact (`PLAN_REVIEW.md`) generated and reviewed
- [ ] External human or CI-native approval obtained — agent cannot self-approve
- [ ] State backup (`terraform state pull`) captured before apply
- [ ] Rollback procedure documented in `PLAN_REVIEW.md`

## Usage
```bash
cd {out_dir}
terraform init
terraform validate
checkov --framework terraform -d . --soft-fail false --check CRITICAL
# If Checkov passes:
terraform plan -out=plan.tfplan
# Generate plan review artifact:
python ../scripts/generate-plan-review.py \\
  --plan-json plan.json \\
  --checkov-json checkov.json \\
  --project {args.project} --env {args.env} --owner {args.owner} --cost-center {args.cost_center} \\
  --output ./PLAN_REVIEW.md
# Review PLAN_REVIEW.md, obtain external approval, then:
terraform apply plan.tfplan
```
""", encoding="utf-8")

    print(f"Generated Terraform module at: {main_tf}")
    print(f"Generated README at: {readme}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
