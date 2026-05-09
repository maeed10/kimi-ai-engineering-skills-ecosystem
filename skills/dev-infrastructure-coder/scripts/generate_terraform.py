#!/usr/bin/env python3
"""
generate_terraform.py

Generates opinionated Terraform module scaffolding from a JSON/YAML requirements file.
Supports AWS, Azure, and GCP for common modules: vpc, compute, database, storage,
loadbalancer, iam, and state backend.

Usage:
    python generate_terraform.py --requirements requirements.json --output ./modules
    python generate_terraform.py --requirements requirements.yaml --output ./modules --cloud aws

Requirements schema (JSON/YAML):
    {
        "cloud": "aws",          # aws | azure | gcp
        "region": "us-east-1",
        "environment": "dev",
        "name_prefix": "myapp",
        "tags": {"Project": "myapp", "CostCenter": "12345"},
        "modules": ["vpc", "compute", "database", "storage", "loadbalancer", "iam", "state"]
    }

Outputs:
    A directory tree per module under --output with:
        main.tf, variables.tf, outputs.tf, versions.tf, README.md
"""

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

try:
    import yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False


MODULE_TEMPLATES: dict[str, dict[str, Any]] = {
    "vpc": {
        "aws": {
            "main": '''
data "aws_availability_zones" "available" {
  state = "available"
}

resource "aws_vpc" "this" {
  cidr_block           = var.vpc_cidr
  enable_dns_hostnames = true
  enable_dns_support   = true

  tags = merge(var.tags, {
    Name = "${var.name_prefix}-vpc-${var.environment}"
  })
}

resource "aws_subnet" "public" {
  count                   = var.az_count
  vpc_id                  = aws_vpc.this.id
  cidr_block              = cidrsubnet(var.vpc_cidr, 8, count.index)
  availability_zone       = data.aws_availability_zones.available.names[count.index]
  map_public_ip_on_launch = true

  tags = merge(var.tags, {
    Name = "${var.name_prefix}-public-${count.index + 1}"
    Type = "Public"
  })
}

resource "aws_subnet" "private" {
  count             = var.az_count
  vpc_id            = aws_vpc.this.id
  cidr_block        = cidrsubnet(var.vpc_cidr, 8, count.index + var.az_count)
  availability_zone = data.aws_availability_zones.available.names[count.index]

  tags = merge(var.tags, {
    Name = "${var.name_prefix}-private-${count.index + 1}"
    Type = "Private"
  })
}

resource "aws_internet_gateway" "this" {
  vpc_id = aws_vpc.this.id

  tags = merge(var.tags, {
    Name = "${var.name_prefix}-igw"
  })
}

resource "aws_eip" "nat" {
  count  = var.az_count
  domain = "vpc"

  tags = merge(var.tags, {
    Name = "${var.name_prefix}-nat-${count.index + 1}"
  })
}

resource "aws_nat_gateway" "this" {
  count         = var.az_count
  allocation_id = aws_eip.nat[count.index].id
  subnet_id     = aws_subnet.public[count.index].id

  tags = merge(var.tags, {
    Name = "${var.name_prefix}-nat-${count.index + 1}"
  })

  depends_on = [aws_internet_gateway.this]
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.this.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.this.id
  }

  tags = merge(var.tags, {
    Name = "${var.name_prefix}-public"
  })
}

resource "aws_route_table_association" "public" {
  count          = var.az_count
  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public.id
}

resource "aws_route_table" "private" {
  count  = var.az_count
  vpc_id = aws_vpc.this.id

  route {
    cidr_block     = "0.0.0.0/0"
    nat_gateway_id = aws_nat_gateway.this[count.index].id
  }

  tags = merge(var.tags, {
    Name = "${var.name_prefix}-private-${count.index + 1}"
  })
}

resource "aws_route_table_association" "private" {
  count          = var.az_count
  subnet_id      = aws_subnet.private[count.index].id
  route_table_id = aws_route_table.private[count.index].id
}

resource "aws_flow_log" "this" {
  count                = var.enable_flow_logs ? 1 : 0
  vpc_id               = aws_vpc.this.id
  traffic_type         = "ALL"
  log_destination_type = "cloud-watch-logs"
  log_destination      = aws_cloudwatch_log_group.flow_logs[count.index].arn
  iam_role_arn         = aws_iam_role.flow_logs[count.index].arn
}

resource "aws_cloudwatch_log_group" "flow_logs" {
  count             = var.enable_flow_logs ? 1 : 0
  name              = "/aws/vpc/${var.name_prefix}-flowlogs"
  retention_in_days = 30
}

resource "aws_iam_role" "flow_logs" {
  count = var.enable_flow_logs ? 1 : 0
  name  = "${var.name_prefix}-vpc-flowlogs-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = {
        Service = "vpc-flow-logs.amazonaws.com"
      }
    }]
  })
}
''',
            "variables": '''
variable "vpc_cidr" {
  description = "CIDR block for the VPC"
  type        = string
  default     = "10.0.0.0/16"
}

variable "az_count" {
  description = "Number of AZs to use"
  type        = number
  default     = 3
}

variable "enable_flow_logs" {
  description = "Enable VPC flow logs"
  type        = bool
  default     = true
}
''',
            "outputs": '''
output "vpc_id" {
  description = "ID of the VPC"
  value       = aws_vpc.this.id
}

output "public_subnet_ids" {
  description = "List of public subnet IDs"
  value       = aws_subnet.public[*].id
}

output "private_subnet_ids" {
  description = "List of private subnet IDs"
  value       = aws_subnet.private[*].id
}

output "nat_gateway_ips" {
  description = "List of NAT gateway Elastic IPs"
  value       = aws_eip.nat[*].public_ip
}
''',
        },
        "azure": {
            "main": '''
data "azurerm_subscription" "current" {}

resource "azurerm_virtual_network" "this" {
  name                = "${var.name_prefix}-vnet-${var.environment}"
  address_space       = [var.vnet_cidr]
  location            = var.location
  resource_group_name = var.resource_group_name

  tags = var.tags
}

resource "azurerm_subnet" "public" {
  count                = var.az_count
  name                 = "${var.name_prefix}-public-${count.index + 1}"
  resource_group_name  = var.resource_group_name
  virtual_network_name = azurerm_virtual_network.this.name
  address_prefixes     = [cidrsubnet(var.vnet_cidr, 8, count.index)]
}

resource "azurerm_subnet" "private" {
  count                = var.az_count
  name                 = "${var.name_prefix}-private-${count.index + 1}"
  resource_group_name  = var.resource_group_name
  virtual_network_name = azurerm_virtual_network.this.name
  address_prefixes     = [cidrsubnet(var.vnet_cidr, 8, count.index + var.az_count)]
}

resource "azurerm_public_ip" "nat" {
  count               = var.az_count
  name                = "${var.name_prefix}-nat-pip-${count.index + 1}"
  location            = var.location
  resource_group_name = var.resource_group_name
  allocation_method   = "Static"
  sku                 = "Standard"

  tags = var.tags
}

resource "azurerm_nat_gateway" "this" {
  count               = var.az_count
  name                = "${var.name_prefix}-nat-${count.index + 1}"
  location            = var.location
  resource_group_name = var.resource_group_name
  sku_name            = "Standard"

  tags = var.tags
}

resource "azurerm_nat_gateway_public_ip_association" "this" {
  count                = var.az_count
  nat_gateway_id       = azurerm_nat_gateway.this[count.index].id
  public_ip_address_id = azurerm_public_ip.nat[count.index].id
}

resource "azurerm_subnet_nat_gateway_association" "private" {
  count          = var.az_count
  subnet_id      = azurerm_subnet.private[count.index].id
  nat_gateway_id = azurerm_nat_gateway.this[count.index].id
}

resource "azurerm_network_watcher_flow_log" "this" {
  count                     = var.enable_flow_logs ? 1 : 0
  name                      = "${var.name_prefix}-flowlogs"
  network_watcher_name      = var.network_watcher_name
  resource_group_name       = var.resource_group_name
  network_security_group_id = var.network_security_group_id
  storage_account_id        = var.flow_logs_storage_account_id
  enabled                   = true
  version                   = 2

  retention_policy {
    enabled = true
    days    = 30
  }

  traffic_analytics {
    enabled               = true
    workspace_id          = var.log_analytics_workspace_id
    workspace_region      = var.location
    workspace_resource_id = var.log_analytics_workspace_resource_id
    interval_in_minutes   = 10
  }
}
''',
            "variables": '''
variable "vnet_cidr" {
  description = "CIDR block for the VNet"
  type        = string
  default     = "10.0.0.0/16"
}

variable "resource_group_name" {
  description = "Name of the resource group"
  type        = string
}

variable "location" {
  description = "Azure region"
  type        = string
  default     = "East US"
}

variable "az_count" {
  description = "Number of AZs to use"
  type        = number
  default     = 3
}

variable "enable_flow_logs" {
  description = "Enable NSG flow logs"
  type        = bool
  default     = true
}

variable "network_watcher_name" {
  description = "Network Watcher name"
  type        = string
  default     = ""
}

variable "network_security_group_id" {
  description = "NSG ID for flow logging"
  type        = string
  default     = ""
}

variable "flow_logs_storage_account_id" {
  description = "Storage account ID for flow logs"
  type        = string
  default     = ""
}

variable "log_analytics_workspace_id" {
  description = "Log Analytics Workspace ID"
  type        = string
  default     = ""
}

variable "log_analytics_workspace_resource_id" {
  description = "Log Analytics Workspace resource ID"
  type        = string
  default     = ""
}
''',
            "outputs": '''
output "vnet_id" {
  description = "ID of the VNet"
  value       = azurerm_virtual_network.this.id
}

output "public_subnet_ids" {
  description = "List of public subnet IDs"
  value       = azurerm_subnet.public[*].id
}

output "private_subnet_ids" {
  description = "List of private subnet IDs"
  value       = azurerm_subnet.private[*].id
}
''',
        },
        "gcp": {
            "main": '''
resource "google_compute_network" "this" {
  name                    = "${var.name_prefix}-vpc-${var.environment}"
  auto_create_subnetworks = false
  routing_mode            = "GLOBAL"
}

resource "google_compute_subnetwork" "public" {
  count                    = var.az_count
  name                     = "${var.name_prefix}-public-${count.index + 1}"
  ip_cidr_range            = cidrsubnet(var.vpc_cidr, 8, count.index)
  region                   = var.region
  network                  = google_compute_network.this.id
  private_ip_google_access = true

  log_config {
    aggregation_interval = "INTERVAL_5_SEC"
    flow_sampling        = 0.5
    metadata             = "INCLUDE_ALL_METADATA"
  }
}

resource "google_compute_subnetwork" "private" {
  count                    = var.az_count
  name                     = "${var.name_prefix}-private-${count.index + 1}"
  ip_cidr_range            = cidrsubnet(var.vpc_cidr, 8, count.index + var.az_count)
  region                   = var.region
  network                  = google_compute_network.this.id
  private_ip_google_access = true

  log_config {
    aggregation_interval = "INTERVAL_5_SEC"
    flow_sampling        = 0.5
    metadata             = "INCLUDE_ALL_METADATA"
  }
}

resource "google_compute_router" "this" {
  name    = "${var.name_prefix}-router"
  region  = var.region
  network = google_compute_network.this.id
}

resource "google_compute_router_nat" "this" {
  name                               = "${var.name_prefix}-nat"
  router                             = google_compute_router.this.name
  region                             = var.region
  nat_ip_allocate_option             = "AUTO_ONLY"
  source_subnetwork_ip_ranges_to_nat = "LIST_OF_SUBNETWORKS"

  dynamic "subnetwork" {
    for_each = google_compute_subnetwork.private
    content {
      name                    = subnetwork.value.id
      source_ip_ranges_to_nat = ["ALL_IP_RANGES"]
    }
  }
}
''',
            "variables": '''
variable "vpc_cidr" {
  description = "CIDR block for the VPC"
  type        = string
  default     = "10.0.0.0/16"
}

variable "region" {
  description = "GCP region"
  type        = string
  default     = "us-central1"
}

variable "az_count" {
  description = "Number of zones to use"
  type        = number
  default     = 3
}
''',
            "outputs": '''
output "vpc_id" {
  description = "ID of the VPC"
  value       = google_compute_network.this.id
}

output "public_subnet_ids" {
  description = "List of public subnet IDs"
  value       = google_compute_subnetwork.public[*].id
}

output "private_subnet_ids" {
  description = "List of private subnet IDs"
  value       = google_compute_subnetwork.private[*].id
}
''',
        },
    },
    "compute": {
        "aws": {
            "main": '''
data "aws_ami" "amazon_linux" {
  most_recent = true
  owners      = ["amazon"]

  filter {
    name   = "name"
    values = ["amzn2-ami-hvm-*-x86_64-gp2"]
  }
}

resource "aws_launch_template" "this" {
  name_prefix   = "${var.name_prefix}-"
  image_id      = var.ami_id != "" ? var.ami_id : data.aws_ami.amazon_linux.id
  instance_type = var.instance_type
  key_name      = var.key_name

  vpc_security_group_ids = var.security_group_ids

  iam_instance_profile {
    name = var.instance_profile_name
  }

  metadata_options {
    http_endpoint               = "enabled"
    http_tokens                 = "required"
    http_put_response_hop_limit = 1
    instance_metadata_tags      = "enabled"
  }

  block_device_mappings {
    device_name = "/dev/xvda"
    ebs {
      volume_size           = var.root_volume_size
      volume_type           = "gp3"
      encrypted             = true
      kms_key_id            = var.kms_key_id
      delete_on_termination = true
    }
  }

  tag_specifications {
    resource_type = "instance"
    tags          = var.tags
  }

  user_data = base64encode(templatefile("${path.module}/templates/user_data.sh", {
    environment = var.environment
  }))

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_autoscaling_group" "this" {
  name                = "${var.name_prefix}-asg-${var.environment}"
  vpc_zone_identifier = var.subnet_ids
  target_group_arns   = var.target_group_arns
  health_check_type   = var.health_check_type

  min_size         = var.min_size
  max_size         = var.max_size
  desired_capacity = var.desired_capacity

  launch_template {
    id      = aws_launch_template.this.id
    version = "$Latest"
  }

  dynamic "tag" {
    for_each = var.tags
    content {
      key                 = tag.key
      value               = tag.value
      propagate_at_launch = true
    }
  }

  instance_refresh {
    strategy = "Rolling"
    preferences {
      min_healthy_percentage = 66
    }
  }
}
''',
            "variables": '''
variable "instance_type" {
  description = "EC2 instance type"
  type        = string
  default     = "t4g.micro"
}

variable "ami_id" {
  description = "AMI ID (leave empty for latest Amazon Linux 2)"
  type        = string
  default     = ""
}

variable "key_name" {
  description = "SSH key pair name"
  type        = string
  default     = ""
}

variable "security_group_ids" {
  description = "List of security group IDs"
  type        = list(string)
  default     = []
}

variable "instance_profile_name" {
  description = "IAM instance profile name"
  type        = string
  default     = ""
}

variable "subnet_ids" {
  description = "List of subnet IDs for the ASG"
  type        = list(string)
}

variable "target_group_arns" {
  description = "List of target group ARNs"
  type        = list(string)
  default     = []
}

variable "health_check_type" {
  description = "Health check type (EC2 or ELB)"
  type        = string
  default     = "ELB"
}

variable "min_size" {
  description = "Minimum ASG size"
  type        = number
  default     = 1
}

variable "max_size" {
  description = "Maximum ASG size"
  type        = number
  default     = 3
}

variable "desired_capacity" {
  description = "Desired ASG capacity"
  type        = number
  default     = 2
}

variable "root_volume_size" {
  description = "Root volume size in GiB"
  type        = number
  default     = 20
}

variable "kms_key_id" {
  description = "KMS key ID for EBS encryption"
  type        = string
  default     = ""
}
''',
            "outputs": '''
output "launch_template_id" {
  description = "ID of the launch template"
  value       = aws_launch_template.this.id
}

output "autoscaling_group_name" {
  description = "Name of the Auto Scaling Group"
  value       = aws_autoscaling_group.this.name
}

output "autoscaling_group_arn" {
  description = "ARN of the Auto Scaling Group"
  value       = aws_autoscaling_group.this.arn
}
''',
        },
        "azure": {
            "main": '''
resource "azurerm_linux_virtual_machine_scale_set" "this" {
  name                = "${var.name_prefix}-vmss-${var.environment}"
  resource_group_name = var.resource_group_name
  location            = var.location
  sku                 = var.sku
  instances           = var.desired_capacity
  admin_username      = var.admin_username

  admin_ssh_key {
    username   = var.admin_username
    public_key = file(var.ssh_public_key_path)
  }

  source_image_reference {
    publisher = "Canonical"
    offer     = "0001-com-ubuntu-server-jammy"
    sku       = "22_04-lts"
    version   = "latest"
  }

  os_disk {
    storage_account_type = "Premium_LRS"
    caching              = "ReadWrite"
    disk_size_gb         = var.os_disk_size_gb
  }

  network_interface {
    name    = "nic"
    primary = true

    ip_configuration {
      name                                   = "internal"
      primary                                = true
      subnet_id                              = var.subnet_id
      load_balancer_backend_address_pool_ids = var.backend_address_pool_ids
    }
  }

  identity {
    type = "SystemAssigned"
  }

  tags = var.tags

  lifecycle {
    ignore_changes = [instances]
  }
}

resource "azurerm_monitor_autoscale_setting" "this" {
  name                = "${var.name_prefix}-autoscale"
  resource_group_name = var.resource_group_name
  location            = var.location
  target_resource_id  = azurerm_linux_virtual_machine_scale_set.this.id

  profile {
    name = "default"

    capacity {
      default = var.desired_capacity
      minimum = var.min_size
      maximum = var.max_size
    }

    rule {
      metric_trigger {
        metric_name        = "Percentage CPU"
        metric_resource_id = azurerm_linux_virtual_machine_scale_set.this.id
        time_grain         = "PT1M"
        statistic          = "Average"
        time_window        = "PT5M"
        time_aggregation   = "Average"
        operator           = "GreaterThan"
        threshold          = 70
      }

      scale_action {
        direction = "Increase"
        type      = "ChangeCount"
        value     = "1"
        cooldown  = "PT5M"
      }
    }

    rule {
      metric_trigger {
        metric_name        = "Percentage CPU"
        metric_resource_id = azurerm_linux_virtual_machine_scale_set.this.id
        time_grain         = "PT1M"
        statistic          = "Average"
        time_window        = "PT5M"
        time_aggregation   = "Average"
        operator           = "LessThan"
        threshold          = 30
      }

      scale_action {
        direction = "Decrease"
        type      = "ChangeCount"
        value     = "1"
        cooldown  = "PT5M"
      }
    }
  }
}
''',
            "variables": '''
variable "sku" {
  description = "VM SKU"
  type        = string
  default     = "Standard_B2s"
}

variable "resource_group_name" {
  description = "Resource group name"
  type        = string
}

variable "location" {
  description = "Azure region"
  type        = string
  default     = "East US"
}

variable "subnet_id" {
  description = "Subnet ID for VMSS"
  type        = string
}

variable "backend_address_pool_ids" {
  description = "Load balancer backend pool IDs"
  type        = list(string)
  default     = []
}

variable "admin_username" {
  description = "Admin username"
  type        = string
  default     = "azureuser"
}

variable "ssh_public_key_path" {
  description = "Path to SSH public key"
  type        = string
  default     = "~/.ssh/id_rsa.pub"
}

variable "os_disk_size_gb" {
  description = "OS disk size in GiB"
  type        = number
  default     = 30
}

variable "min_size" {
  description = "Minimum instance count"
  type        = number
  default     = 1
}

variable "max_size" {
  description = "Maximum instance count"
  type        = number
  default     = 3
}

variable "desired_capacity" {
  description = "Desired instance count"
  type        = number
  default     = 2
}
''',
            "outputs": '''
output "vmss_id" {
  description = "ID of the VMSS"
  value       = azurerm_linux_virtual_machine_scale_set.this.id
}

output "vmss_name" {
  description = "Name of the VMSS"
  value       = azurerm_linux_virtual_machine_scale_set.this.name
}
''',
        },
        "gcp": {
            "main": '''
data "google_compute_image" "ubuntu" {
  family  = "ubuntu-2204-lts"
  project = "ubuntu-os-cloud"
}

resource "google_compute_instance_template" "this" {
  name_prefix  = "${var.name_prefix}-"
  machine_type = var.machine_type
  region       = var.region

  disk {
    source_image = var.source_image != "" ? var.source_image : data.google_compute_image.ubuntu.self_link
    auto_delete  = true
    boot         = true
    disk_size_gb = var.boot_disk_size
    disk_type    = "pd-balanced"
    kms_key_self_link = var.kms_key_self_link
  }

  network_interface {
    subnetwork = var.subnet_id
    # No external IP by default
  }

  metadata = {
    enable-oslogin = "TRUE"
    user-data      = templatefile("${path.module}/templates/user_data.sh", {
      environment = var.environment
    })
  }

  service_account {
    email  = var.service_account_email
    scopes = ["cloud-platform"]
  }

  labels = var.labels

  lifecycle {
    create_before_destroy = true
  }
}

resource "google_compute_region_instance_group_manager" "this" {
  name   = "${var.name_prefix}-mig-${var.environment}"
  region = var.region

  version {
    instance_template = google_compute_instance_template.this.id
    name              = "primary"
  }

  named_port {
    name = "http"
    port = 8080
  }

  auto_healing_policies {
    health_check      = var.health_check_id
    initial_delay_sec = 300
  }
}

resource "google_compute_region_autoscaler" "this" {
  name   = "${var.name_prefix}-autoscaler"
  region = var.region
  target = google_compute_region_instance_group_manager.this.id

  autoscaling_policy {
    min_replicas    = var.min_size
    max_replicas    = var.max_size
    cooldown_period = 60

    cpu_utilization {
      target = 0.6
    }
  }
}
''',
            "variables": '''
variable "machine_type" {
  description = "GCE machine type"
  type        = string
  default     = "e2-medium"
}

variable "region" {
  description = "GCP region"
  type        = string
  default     = "us-central1"
}

variable "subnet_id" {
  description = "Subnet ID for instances"
  type        = string
}

variable "source_image" {
  description = "Source image self_link (leave empty for Ubuntu 22.04)"
  type        = string
  default     = ""
}

variable "boot_disk_size" {
  description = "Boot disk size in GiB"
  type        = number
  default     = 20
}

variable "kms_key_self_link" {
  description = "CMEK key self_link for disk encryption"
  type        = string
  default     = ""
}

variable "service_account_email" {
  description = "Service account email"
  type        = string
  default     = ""
}

variable "health_check_id" {
  description = "Health check ID for auto-healing"
  type        = string
  default     = ""
}

variable "min_size" {
  description = "Minimum replicas"
  type        = number
  default     = 1
}

variable "max_size" {
  description = "Maximum replicas"
  type        = number
  default     = 3
}
''',
            "outputs": '''
output "instance_template_id" {
  description = "ID of the instance template"
  value       = google_compute_instance_template.this.id
}

output "mig_id" {
  description = "ID of the managed instance group"
  value       = google_compute_region_instance_group_manager.this.id
}
''',
        },
    },
    "database": {
        "aws": {
            "main": '''
resource "aws_db_subnet_group" "this" {
  name       = "${var.name_prefix}-db-subnet-group"
  subnet_ids = var.subnet_ids

  tags = var.tags
}

resource "aws_security_group" "rds" {
  name_prefix = "${var.name_prefix}-rds-"
  vpc_id      = var.vpc_id
  description = "Security group for RDS"

  ingress {
    description     = "Allow DB traffic from compute SG"
    from_port       = var.db_port
    to_port         = var.db_port
    protocol        = "tcp"
    security_groups = var.allowed_security_group_ids
  }

  egress {
    description = "Deny all outbound"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = []
  }

  tags = merge(var.tags, {
    Name = "${var.name_prefix}-rds"
  })
}

resource "aws_db_instance" "this" {
  identifier              = "${var.name_prefix}-${var.environment}"
  engine                  = var.engine
  engine_version          = var.engine_version
  instance_class          = var.instance_class
  allocated_storage       = var.allocated_storage
  max_allocated_storage   = var.max_allocated_storage
  storage_type            = "gp3"
  storage_encrypted       = true
  kms_key_id              = var.kms_key_id
  db_name                 = var.db_name
  username                = var.master_username
  password                = random_password.master.result
  port                    = var.db_port
  multi_az                = var.environment == "prod"
  publicly_accessible     = false
  deletion_protection       = var.environment == "prod"
  skip_final_snapshot     = var.environment != "prod"
  final_snapshot_identifier = var.environment == "prod" ? "${var.name_prefix}-final" : null

  vpc_security_group_ids = [aws_security_group.rds.id]
  db_subnet_group_name   = aws_db_subnet_group.this.name

  backup_retention_period = var.backup_retention_period
  backup_window           = var.backup_window
  maintenance_window      = var.maintenance_window

  enabled_cloudwatch_logs_exports = var.enabled_cloudwatch_logs_exports

  tags = var.tags
}

resource "random_password" "master" {
  length  = 24
  special = false
}

resource "aws_secretsmanager_secret" "db_password" {
  name                    = "${var.name_prefix}-db-password"
  description             = "RDS master password for ${var.name_prefix}"
  recovery_window_in_days = 7
  kms_key_id              = var.kms_key_id
}

resource "aws_secretsmanager_secret_version" "db_password" {
  secret_id     = aws_secretsmanager_secret.db_password.id
  secret_string = random_password.master.result
}
''',
            "variables": '''
variable "engine" {
  description = "Database engine"
  type        = string
  default     = "postgres"
}

variable "engine_version" {
  description = "Database engine version"
  type        = string
  default     = "15.4"
}

variable "instance_class" {
  description = "RDS instance class"
  type        = string
  default     = "db.t4g.micro"
}

variable "allocated_storage" {
  description = "Initial storage in GiB"
  type        = number
  default     = 20
}

variable "max_allocated_storage" {
  description = "Max autoscaling storage in GiB"
  type        = number
  default     = 100
}

variable "db_name" {
  description = "Name of the database"
  type        = string
  default     = "appdb"
}

variable "master_username" {
  description = "Master username"
  type        = string
  default     = "dbadmin"
}

variable "db_port" {
  description = "Database port"
  type        = number
  default     = 5432
}

variable "subnet_ids" {
  description = "List of subnet IDs for the DB subnet group"
  type        = list(string)
}

variable "vpc_id" {
  description = "VPC ID"
  type        = string
}

variable "allowed_security_group_ids" {
  description = "Security groups allowed to connect to the DB"
  type        = list(string)
  default     = []
}

variable "backup_retention_period" {
  description = "Backup retention in days"
  type        = number
  default     = 7
}

variable "backup_window" {
  description = "Preferred backup window"
  type        = string
  default     = "03:00-04:00"
}

variable "maintenance_window" {
  description = "Preferred maintenance window"
  type        = string
  default     = "Mon:04:00-Mon:05:00"
}

variable "enabled_cloudwatch_logs_exports" {
  description = "List of logs to export to CloudWatch"
  type        = list(string)
  default     = ["postgresql"]
}

variable "kms_key_id" {
  description = "KMS key ID for encryption"
  type        = string
  default     = ""
}
''',
            "outputs": '''
output "db_instance_endpoint" {
  description = "RDS instance endpoint"
  value       = aws_db_instance.this.endpoint
}

output "db_instance_id" {
  description = "RDS instance ID"
  value       = aws_db_instance.this.id
}

output "db_secret_arn" {
  description = "Secrets Manager ARN for the master password"
  value       = aws_secretsmanager_secret.db_password.arn
}
''',
        },
        "azure": {
            "main": '''
resource "azurerm_postgresql_flexible_server" "this" {
  name                   = "${var.name_prefix}-psql-${var.environment}"
  resource_group_name    = var.resource_group_name
  location               = var.location
  version                = var.server_version
  sku_name               = var.sku_name
  storage_mb             = var.storage_mb
  backup_retention_days  = var.backup_retention_days
  geo_redundant_backup_enabled = var.environment == "prod"

  administrator_login          = var.administrator_login
  administrator_password       = random_password.admin.result

  delegated_subnet_id = var.delegated_subnet_id
  private_dns_zone_id = var.private_dns_zone_id

  public_network_access_enabled = false

  tags = var.tags
}

resource "random_password" "admin" {
  length  = 24
  special = true
}

resource "azurerm_key_vault_secret" "db_password" {
  name         = "${var.name_prefix}-db-password"
  value        = random_password.admin.result
  key_vault_id = var.key_vault_id
}
''',
            "variables": '''
variable "server_version" {
  description = "PostgreSQL server version"
  type        = string
  default     = "15"
}

variable "sku_name" {
  description = "SKU name (e.g., B_Standard_B1ms, GP_Standard_D2s_v3)"
  type        = string
  default     = "B_Standard_B1ms"
}

variable "storage_mb" {
  description = "Storage in MB"
  type        = number
  default     = 32768
}

variable "backup_retention_days" {
  description = "Backup retention days"
  type        = number
  default     = 7
}

variable "resource_group_name" {
  description = "Resource group name"
  type        = string
}

variable "location" {
  description = "Azure region"
  type        = string
  default     = "East US"
}

variable "administrator_login" {
  description = "Admin username"
  type        = string
  default     = "psqladmin"
}

variable "delegated_subnet_id" {
  description = "Delegated subnet ID for private endpoint"
  type        = string
}

variable "private_dns_zone_id" {
  description = "Private DNS zone ID"
  type        = string
  default     = ""
}

variable "key_vault_id" {
  description = "Key Vault ID to store the password"
  type        = string
}
''',
            "outputs": '''
output "server_fqdn" {
  description = "PostgreSQL server FQDN"
  value       = azurerm_postgresql_flexible_server.this.fqdn
}

output "server_id" {
  description = "PostgreSQL server ID"
  value       = azurerm_postgresql_flexible_server.this.id
}
''',
        },
        "gcp": {
            "main": '''
resource "google_sql_database_instance" "this" {
  name             = "${var.name_prefix}-psql-${var.environment}"
  database_version = var.database_version
  region           = var.region

  settings {
    tier              = var.tier
    availability_type = var.environment == "prod" ? "REGIONAL" : "ZONAL"
    disk_size         = var.disk_size
    disk_type         = "PD_SSD"
    disk_autoresize   = true

    ip_configuration {
      ipv4_enabled    = false
      private_network = var.vpc_id
    }

    backup_configuration {
      enabled                        = true
      start_time                     = "03:00"
      point_in_time_recovery_enabled = var.environment == "prod"
    }

    maintenance_window {
      day          = 1
      hour         = 4
      update_track = "stable"
    }

    insights_config {
      query_insights_enabled  = true
      query_string_length     = 1024
      record_application_tags = true
      record_client_address   = true
    }
  }

  deletion_protection = var.environment == "prod"

  depends_on = [google_service_networking_connection.private_vpc_connection]
}

resource "google_sql_database" "this" {
  name     = var.db_name
  instance = google_sql_database_instance.this.name
}

resource "google_sql_user" "this" {
  name     = var.db_user
  instance = google_sql_database_instance.this.name
  password = random_password.admin.result
}

resource "random_password" "admin" {
  length  = 24
  special = false
}

resource "google_secret_manager_secret" "db_password" {
  secret_id = "${var.name_prefix}-db-password"
  replication {
    auto {}
  }
}

resource "google_secret_manager_secret_version" "db_password" {
  secret     = google_secret_manager_secret.db_password.id
  secret_data = random_password.admin.result
}
''',
            "variables": '''
variable "database_version" {
  description = "Cloud SQL database version"
  type        = string
  default     = "POSTGRES_15"
}

variable "tier" {
  description = "Machine tier (e.g., db-f1-micro, db-custom-2-4096)"
  type        = string
  default     = "db-f1-micro"
}

variable "disk_size" {
  description = "Initial disk size in GiB"
  type        = number
  default     = 20
}

variable "region" {
  description = "GCP region"
  type        = string
  default     = "us-central1"
}

variable "vpc_id" {
  description = "VPC network ID (self_link)"
  type        = string
}

variable "db_name" {
  description = "Name of the default database"
  type        = string
  default     = "appdb"
}

variable "db_user" {
  description = "Default database user"
  type        = string
  default     = "dbadmin"
}

variable "service_networking_connection" {
  description = "Service networking connection for private IP"
  type        = bool
  default     = true
}
''',
            "outputs": '''
output "db_instance_connection_name" {
  description = "Cloud SQL connection name"
  value       = google_sql_database_instance.this.connection_name
}

output "db_instance_private_ip" {
  description = "Private IP of the Cloud SQL instance"
  value       = google_sql_database_instance.this.private_ip_address
}

output "db_secret_id" {
  description = "Secret Manager secret ID for the password"
  value       = google_secret_manager_secret.db_password.id
}
''',
        },
    },
    "storage": {
        "aws": {
            "main": '''
resource "aws_s3_bucket" "this" {
  bucket = "${var.name_prefix}-data-${var.environment}-${random_id.bucket.hex}"

  tags = var.tags
}

resource "random_id" "bucket" {
  byte_length = 4
}

resource "aws_s3_bucket_ownership_controls" "this" {
  bucket = aws_s3_bucket.this.id
  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_public_access_block" "this" {
  bucket = aws_s3_bucket.this.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_versioning" "this" {
  bucket = aws_s3_bucket.this.id
  versioning_configuration {
    status = var.enable_versioning ? "Enabled" : "Disabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "this" {
  bucket = aws_s3_bucket.this.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = var.kms_key_id != "" ? "aws:kms" : "AES256"
      kms_master_key_id = var.kms_key_id != "" ? var.kms_key_id : null
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "this" {
  bucket = aws_s3_bucket.this.id

  rule {
    id     = "transition-to-ia"
    status = "Enabled"

    transition {
      days          = var.transition_ia_days
      storage_class = "STANDARD_IA"
    }

    transition {
      days          = var.transition_glacier_days
      storage_class = "GLACIER"
    }
  }
}

resource "aws_s3_bucket_logging" "this" {
  count  = var.log_bucket_name != "" ? 1 : 0
  bucket = aws_s3_bucket.this.id

  target_bucket = var.log_bucket_name
  target_prefix = "logs/${var.name_prefix}-data/"
}
''',
            "variables": '''
variable "enable_versioning" {
  description = "Enable bucket versioning"
  type        = bool
  default     = true
}

variable "kms_key_id" {
  description = "KMS key ID for SSE"
  type        = string
  default     = ""
}

variable "transition_ia_days" {
  description = "Days before transitioning to STANDARD_IA"
  type        = number
  default     = 30
}

variable "transition_glacier_days" {
  description = "Days before transitioning to GLACIER"
  type        = number
  default     = 90
}

variable "log_bucket_name" {
  description = "Target bucket for access logs"
  type        = string
  default     = ""
}
''',
            "outputs": '''
output "bucket_id" {
  description = "S3 bucket ID"
  value       = aws_s3_bucket.this.id
}

output "bucket_arn" {
  description = "S3 bucket ARN"
  value       = aws_s3_bucket.this.arn
}
''',
        },
        "azure": {
            "main": '''
resource "azurerm_storage_account" "this" {
  name                     = "${var.name_prefix}data${random_id.storage.hex}"
  resource_group_name      = var.resource_group_name
  location                 = var.location
  account_tier             = "Standard"
  account_replication_type = var.environment == "prod" ? "GRS" : "LRS"
  min_tls_version          = "TLS1_2"
  allow_nested_items_to_be_public = false

  blob_properties {
    versioning_enabled = var.enable_versioning
    delete_retention_policy {
      days = 7
    }
    container_delete_retention_policy {
      days = 7
    }
  }

  network_rules {
    default_action             = "Deny"
    bypass                     = ["AzureServices"]
    virtual_network_subnet_ids = var.allowed_subnet_ids
  }

  identity {
    type = "SystemAssigned"
  }

  tags = var.tags
}

resource "random_id" "storage" {
  byte_length = 4
}

resource "azurerm_storage_container" "this" {
  name                  = "data"
  storage_account_name  = azurerm_storage_account.this.name
  container_access_type = "private"
}
''',
            "variables": '''
variable "resource_group_name" {
  description = "Resource group name"
  type        = string
}

variable "location" {
  description = "Azure region"
  type        = string
  default     = "East US"
}

variable "enable_versioning" {
  description = "Enable blob versioning"
  type        = bool
  default     = true
}

variable "allowed_subnet_ids" {
  description = "Allowed subnet IDs for network rules"
  type        = list(string)
  default     = []
}
''',
            "outputs": '''
output "storage_account_id" {
  description = "Storage account ID"
  value       = azurerm_storage_account.this.id
}

output "storage_account_name" {
  description = "Storage account name"
  value       = azurerm_storage_account.this.name
}

output "primary_blob_endpoint" {
  description = "Primary blob endpoint"
  value       = azurerm_storage_account.this.primary_blob_endpoint
}
''',
        },
        "gcp": {
            "main": '''
resource "random_id" "bucket" {
  byte_length = 4
}

resource "google_storage_bucket" "this" {
  name          = "${var.name_prefix}-data-${var.environment}-${random_id.bucket.hex}"
  location      = var.bucket_location
  storage_class = "STANDARD"
  force_destroy = var.environment != "prod"

  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"

  versioning {
    enabled = var.enable_versioning
  }

  encryption {
    default_kms_key_name = var.kms_key_name
  }

  lifecycle_rule {
    action {
      type = "SetStorageClass"
      storage_class = "NEARLINE"
    }
    condition {
      age = var.nearline_age_days
    }
  }

  lifecycle_rule {
    action {
      type = "SetStorageClass"
      storage_class = "COLDLINE"
    }
    condition {
      age = var.coldline_age_days
    }
  }

  logging {
    log_bucket        = var.log_bucket_name
    log_object_prefix = var.name_prefix
  }
}
''',
            "variables": '''
variable "bucket_location" {
  description = "GCS bucket location (e.g., US, EU, ASIA)"
  type        = string
  default     = "US"
}

variable "enable_versioning" {
  description = "Enable object versioning"
  type        = bool
  default     = true
}

variable "kms_key_name" {
  description = "CMEK key name for bucket encryption"
  type        = string
  default     = ""
}

variable "nearline_age_days" {
  description = "Days before transitioning to Nearline"
  type        = number
  default     = 30
}

variable "coldline_age_days" {
  description = "Days before transitioning to Coldline"
  type        = number
  default     = 90
}

variable "log_bucket_name" {
  description = "Access log target bucket"
  type        = string
  default     = ""
}
''',
            "outputs": '''
output "bucket_id" {
  description = "GCS bucket ID"
  value       = google_storage_bucket.this.id
}

output "bucket_self_link" {
  description = "GCS bucket self_link"
  value       = google_storage_bucket.this.self_link
}
''',
        },
    },
    "loadbalancer": {
        "aws": {
            "main": '''
resource "aws_lb" "this" {
  name               = "${var.name_prefix}-alb"
  internal           = var.internal
  load_balancer_type = "application"
  security_groups    = var.security_group_ids
  subnets            = var.subnet_ids

  enable_deletion_protection = var.environment == "prod"
  drop_invalid_header_fields = true

  access_logs {
    bucket  = var.access_logs_bucket
    enabled = var.access_logs_bucket != ""
  }

  tags = var.tags
}

resource "aws_lb_target_group" "this" {
  name     = "${var.name_prefix}-tg"
  port     = var.target_port
  protocol = var.target_protocol
  vpc_id   = var.vpc_id
  target_type = "ip"

  health_check {
    enabled             = true
    healthy_threshold   = 2
    interval            = 30
    matcher             = "200"
    path                = var.health_check_path
    port                = "traffic-port"
    protocol            = var.target_protocol
    timeout             = 5
    unhealthy_threshold = 2
  }

  tags = var.tags
}

resource "aws_lb_listener" "https" {
  count             = var.certificate_arn != "" ? 1 : 0
  load_balancer_arn = aws_lb.this.arn
  port              = "443"
  protocol          = "HTTPS"
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"
  certificate_arn   = var.certificate_arn

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.this.arn
  }
}

resource "aws_lb_listener" "http_redirect" {
  load_balancer_arn = aws_lb.this.arn
  port              = "80"
  protocol          = "HTTP"

  default_action {
    type = "redirect"

    redirect {
      port        = "443"
      protocol    = "HTTPS"
      status_code = "HTTP_301"
    }
  }
}
''',
            "variables": '''
variable "internal" {
  description = "Create an internal LB"
  type        = bool
  default     = false
}

variable "security_group_ids" {
  description = "Security group IDs for the LB"
  type        = list(string)
}

variable "subnet_ids" {
  description = "Subnet IDs for the LB"
  type        = list(string)
}

variable "vpc_id" {
  description = "VPC ID"
  type        = string
}

variable "target_port" {
  description = "Target group port"
  type        = number
  default     = 8080
}

variable "target_protocol" {
  description = "Target group protocol"
  type        = string
  default     = "HTTP"
}

variable "health_check_path" {
  description = "Health check path"
  type        = string
  default     = "/healthz"
}

variable "certificate_arn" {
  description = "ACM certificate ARN"
  type        = string
  default     = ""
}

variable "access_logs_bucket" {
  description = "S3 bucket for access logs"
  type        = string
  default     = ""
}
''',
            "outputs": '''
output "lb_dns_name" {
  description = "DNS name of the load balancer"
  value       = aws_lb.this.dns_name
}

output "lb_arn" {
  description = "ARN of the load balancer"
  value       = aws_lb.this.arn
}

output "target_group_arn" {
  description = "Target group ARN"
  value       = aws_lb_target_group.this.arn
}
''',
        },
        "azure": {
            "main": '''
resource "azurerm_public_ip" "this" {
  count               = var.internal ? 0 : 1
  name                = "${var.name_prefix}-pip"
  resource_group_name = var.resource_group_name
  location            = var.location
  allocation_method   = "Static"
  sku                 = "Standard"

  tags = var.tags
}

resource "azurerm_application_gateway" "this" {
  name                = "${var.name_prefix}-agw"
  resource_group_name = var.resource_group_name
  location            = var.location

  sku {
    name     = var.sku_name
    tier     = var.sku_tier
    capacity = var.capacity
  }

  gateway_ip_configuration {
    name      = "gateway-ip"
    subnet_id = var.subnet_id
  }

  frontend_port {
    name = "https-port"
    port = 443
  }

  frontend_port {
    name = "http-port"
    port = 80
  }

  frontend_ip_configuration {
    name                 = "frontend-ip"
    public_ip_address_id = var.internal ? null : azurerm_public_ip.this[0].id
  }

  backend_address_pool {
    name = "backend-pool"
  }

  backend_http_settings {
    name                  = "backend-settings"
    cookie_based_affinity = "Disabled"
    port                  = var.backend_port
    protocol              = "Http"
    request_timeout       = 60
    probe_name            = "health-probe"
  }

  http_listener {
    name                           = "https-listener"
    frontend_ip_configuration_name = "frontend-ip"
    frontend_port_name             = "https-port"
    protocol                       = "Https"
    ssl_certificate_name           = "cert"
  }

  http_listener {
    name                           = "http-listener"
    frontend_ip_configuration_name = "frontend-ip"
    frontend_port_name             = "http-port"
    protocol                       = "Http"
  }

  request_routing_rule {
    name                       = "https-rule"
    rule_type                  = "Basic"
    http_listener_name         = "https-listener"
    backend_address_pool_name  = "backend-pool"
    backend_http_settings_name = "backend-settings"
    priority                   = 100
  }

  request_routing_rule {
    name                       = "http-redirect-rule"
    rule_type                  = "Basic"
    http_listener_name         = "http-listener"
    redirect_configuration_name = "redirect-to-https"
    priority                   = 200
  }

  redirect_configuration {
    name                 = "redirect-to-https"
    redirect_type        = "Permanent"
    target_listener_name = "https-listener"
    include_path         = true
    include_query_string = true
  }

  probe {
    name                = "health-probe"
    protocol            = "Http"
    path                = var.health_check_path
    interval            = 30
    timeout             = 30
    unhealthy_threshold = 3
  }

  ssl_certificate {
    name     = "cert"
    data     = var.ssl_certificate_data
    password = var.ssl_certificate_password
  }

  tags = var.tags
}
''',
            "variables": '''
variable "sku_name" {
  description = "SKU name"
  type        = string
  default     = "Standard_v2"
}

variable "sku_tier" {
  description = "SKU tier"
  type        = string
  default     = "Standard_v2"
}

variable "capacity" {
  description = "Instance count"
  type        = number
  default     = 2
}

variable "resource_group_name" {
  description = "Resource group name"
  type        = string
}

variable "location" {
  description = "Azure region"
  type        = string
  default     = "East US"
}

variable "subnet_id" {
  description = "Subnet ID for the gateway"
  type        = string
}

variable "backend_port" {
  description = "Backend port"
  type        = number
  default     = 8080
}

variable "health_check_path" {
  description = "Health probe path"
  type        = string
  default     = "/healthz"
}

variable "ssl_certificate_data" {
  description = "Base64-encoded PFX certificate data"
  type        = string
  default     = ""
}

variable "ssl_certificate_password" {
  description = "PFX certificate password"
  type        = string
  default     = ""
}
''',
            "outputs": '''
output "gateway_id" {
  description = "Application Gateway ID"
  value       = azurerm_application_gateway.this.id
}

output "gateway_name" {
  description = "Application Gateway name"
  value       = azurerm_application_gateway.this.name
}
''',
        },
        "gcp": {
            "main": '''
resource "google_compute_global_address" "this" {
  count = var.internal ? 0 : 1
  name  = "${var.name_prefix}-ip"
}

resource "google_compute_managed_ssl_certificate" "this" {
  count = var.managed_ssl ? 1 : 0
  name  = "${var.name_prefix}-ssl"

  managed {
    domains = var.domains
  }
}

resource "google_compute_backend_service" "this" {
  name        = "${var.name_prefix}-backend"
  port_name   = "http"
  protocol    = "HTTP"
  timeout_sec = 60

  health_checks = [google_compute_health_check.this.id]

  backend {
    group = var.instance_group
  }

  log_config {
    enable = true
    sample_rate = 1.0
  }

  iap {
    oauth2_client_id     = var.iap_oauth2_client_id
    oauth2_client_secret = var.iap_oauth2_client_secret
  }
}

resource "google_compute_health_check" "this" {
  name = "${var.name_prefix}-hc"

  http_health_check {
    port         = var.backend_port
    request_path = var.health_check_path
  }
}

resource "google_compute_url_map" "this" {
  name            = "${var.name_prefix}-urlmap"
  default_service = google_compute_backend_service.this.id
}

resource "google_compute_target_https_proxy" "this" {
  count = var.internal ? 0 : 1
  name    = "${var.name_prefix}-https-proxy"
  url_map = google_compute_url_map.this.id

  ssl_certificates = var.managed_ssl ? [google_compute_managed_ssl_certificate.this[0].id] : var.ssl_certificate_ids
  ssl_policy       = var.ssl_policy_id
}

resource "google_compute_global_forwarding_rule" "https" {
  count = var.internal ? 0 : 1
  name       = "${var.name_prefix}-https-forwarding-rule"
  target     = google_compute_target_https_proxy.this[0].id
  port_range = "443"
  ip_address = google_compute_global_address.this[0].address
}

resource "google_compute_url_map" "http_redirect" {
  count = var.internal ? 0 : 1
  name = "${var.name_prefix}-http-redirect"

  default_url_redirect {
    https_redirect         = true
    redirect_response_code = "MOVED_PERMANENTLY_DEFAULT"
    strip_query            = false
  }
}

resource "google_compute_target_http_proxy" "http_redirect" {
  count = var.internal ? 0 : 1
  name    = "${var.name_prefix}-http-proxy"
  url_map = google_compute_url_map.http_redirect[0].id
}

resource "google_compute_global_forwarding_rule" "http" {
  count = var.internal ? 0 : 1
  name       = "${var.name_prefix}-http-forwarding-rule"
  target     = google_compute_target_http_proxy.http_redirect[0].id
  port_range = "80"
  ip_address = google_compute_global_address.this[0].address
}
''',
            "variables": '''
variable "internal" {
  description = "Create an internal LB"
  type        = bool
  default     = false
}

variable "managed_ssl" {
  description = "Use Google-managed SSL certificates"
  type        = bool
  default     = true
}

variable "domains" {
  description = "Domains for managed SSL"
  type        = list(string)
  default     = []
}

variable "instance_group" {
  description = "Backend instance group"
  type        = string
}

variable "backend_port" {
  description = "Backend port"
  type        = number
  default     = 8080
}

variable "health_check_path" {
  description = "Health check path"
  type        = string
  default     = "/healthz"
}

variable "ssl_certificate_ids" {
  description = "SSL certificate IDs (if not managed)"
  type        = list(string)
  default     = []
}

variable "ssl_policy_id" {
  description = "SSL policy ID"
  type        = string
  default     = ""
}

variable "iap_oauth2_client_id" {
  description = "IAP OAuth2 client ID"
  type        = string
  default     = ""
}

variable "iap_oauth2_client_secret" {
  description = "IAP OAuth2 client secret"
  type        = string
  default     = ""
}
''',
            "outputs": '''
output "lb_ip_address" {
  description = "Global load balancer IP address"
  value       = var.internal ? null : google_compute_global_address.this[0].address
}

output "backend_service_id" {
  description = "Backend service ID"
  value       = google_compute_backend_service.this.id
}
''',
        },
    },
    "iam": {
        "aws": {
            "main": '''
resource "aws_iam_role" "this" {
  name = "${var.name_prefix}-role-${var.environment}"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = {
        Service = var.assume_role_service
      }
      Condition = {
        StringEquals = {
          "aws:SourceAccount" = data.aws_caller_identity.current.account_id
        }
      }
    }]
  })

  tags = var.tags
}

data "aws_caller_identity" "current" {}

resource "aws_iam_role_policy" "this" {
  name = "${var.name_prefix}-policy"
  role = aws_iam_role.this.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = var.policy_statements
  })
}

resource "aws_iam_instance_profile" "this" {
  count = var.create_instance_profile ? 1 : 0
  name  = "${var.name_prefix}-profile"
  role  = aws_iam_role.this.name
}
''',
            "variables": '''
variable "assume_role_service" {
  description = "AWS service allowed to assume the role"
  type        = string
  default     = "ec2.amazonaws.com"
}

variable "policy_statements" {
  description = "List of IAM policy statements"
  type        = list(any)
  default     = []
}

variable "create_instance_profile" {
  description = "Create an instance profile for the role"
  type        = bool
  default     = false
}
''',
            "outputs": '''
output "role_arn" {
  description = "ARN of the IAM role"
  value       = aws_iam_role.this.arn
}

output "role_name" {
  description = "Name of the IAM role"
  value       = aws_iam_role.this.name
}

output "instance_profile_name" {
  description = "Instance profile name"
  value       = var.create_instance_profile ? aws_iam_instance_profile.this[0].name : null
}
''',
        },
        "azure": {
            "main": '''
resource "azurerm_user_assigned_identity" "this" {
  name                = "${var.name_prefix}-identity"
  resource_group_name = var.resource_group_name
  location            = var.location

  tags = var.tags
}

resource "azurerm_role_assignment" "this" {
  for_each = { for idx, role in var.role_assignments : idx => role }

  scope                = each.value.scope
  role_definition_name = each.value.role_name
  principal_id         = azurerm_user_assigned_identity.this.principal_id
}
''',
            "variables": '''
variable "resource_group_name" {
  description = "Resource group name"
  type        = string
}

variable "location" {
  description = "Azure region"
  type        = string
  default     = "East US"
}

variable "role_assignments" {
  description = "List of role assignments {scope, role_name}"
  type        = list(object({
    scope     = string
    role_name = string
  }))
  default = []
}
''',
            "outputs": '''
output "identity_id" {
  description = "User assigned identity ID"
  value       = azurerm_user_assigned_identity.this.id
}

output "principal_id" {
  description = "Principal ID of the identity"
  value       = azurerm_user_assigned_identity.this.principal_id
}

output "client_id" {
  description = "Client ID of the identity"
  value       = azurerm_user_assigned_identity.this.client_id
}
''',
        },
        "gcp": {
            "main": '''
resource "google_service_account" "this" {
  account_id   = "${var.name_prefix}-sa"
  display_name = "${var.name_prefix} Service Account"
  description  = "Managed by Terraform"
}

resource "google_project_iam_member" "this" {
  for_each = toset(var.roles)

  project = var.project_id
  role    = each.value
  member  = "serviceAccount:${google_service_account.this.email}"
}

resource "google_service_account_iam_member" "token_creator" {
  count = var.allow_impersonation ? 1 : 0

  service_account_id = google_service_account.this.name
  role               = "roles/iam.serviceAccountTokenCreator"
  member             = var.impersonation_member
}
''',
            "variables": '''
variable "project_id" {
  description = "GCP project ID"
  type        = string
}

variable "roles" {
  description = "List of IAM roles to assign"
  type        = list(string)
  default     = []
}

variable "allow_impersonation" {
  description = "Allow a member to impersonate this service account"
  type        = bool
  default     = false
}

variable "impersonation_member" {
  description = "Member allowed to impersonate (e.g., user:foo@bar.com)"
  type        = string
  default     = ""
}
''',
            "outputs": '''
output "service_account_email" {
  description = "Service account email"
  value       = google_service_account.this.email
}

output "service_account_id" {
  description = "Service account ID"
  value       = google_service_account.this.id
}
''',
        },
    },
    "state": {
        "aws": {
            "main": '''
resource "aws_s3_bucket" "state" {
  bucket = "${var.name_prefix}-tfstate-${data.aws_caller_identity.current.account_id}-${random_id.state.hex}"

  tags = var.tags
}

resource "random_id" "state" {
  byte_length = 4
}

data "aws_caller_identity" "current" {}

resource "aws_s3_bucket_versioning" "state" {
  bucket = aws_s3_bucket.state.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "state" {
  bucket = aws_s3_bucket.state.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = var.kms_key_id != "" ? "aws:kms" : "AES256"
      kms_master_key_id = var.kms_key_id != "" ? var.kms_key_id : null
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_public_access_block" "state" {
  bucket = aws_s3_bucket.state.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_dynamodb_table" "lock" {
  name         = "${var.name_prefix}-tflock"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "LockID"

  attribute {
    name = "LockID"
    type = "S"
  }

  point_in_time_recovery {
    enabled = true
  }

  server_side_encryption {
    enabled     = true
    kms_key_arn = var.kms_key_id
  }

  tags = var.tags
}
''',
            "variables": '''
variable "kms_key_id" {
  description = "KMS key ID for encryption"
  type        = string
  default     = ""
}
''',
            "outputs": '''
output "bucket_name" {
  description = "S3 bucket name for remote state"
  value       = aws_s3_bucket.state.id
}

output "dynamodb_table_name" {
  description = "DynamoDB table name for state locking"
  value       = aws_dynamodb_table.lock.name
}

output "backend_config" {
  description = "Backend configuration snippet"
  value       = <<-EOT
    backend "s3" {
      bucket         = "${aws_s3_bucket.state.id}"
      key            = "terraform.tfstate"
      region         = "${var.region}"
      dynamodb_table = "${aws_dynamodb_table.lock.name}"
      encrypt        = true
    }
  EOT
}
''',
        },
        "azure": {
            "main": '''
resource "azurerm_storage_account" "state" {
  name                     = "${var.name_prefix}tfstate${random_id.state.hex}"
  resource_group_name      = var.resource_group_name
  location                 = var.location
  account_tier             = "Standard"
  account_replication_type = "GRS"
  min_tls_version          = "TLS1_2"

  blob_properties {
    versioning_enabled = true
  }

  network_rules {
    default_action = "Deny"
    bypass         = ["AzureServices"]
  }

  identity {
    type = "SystemAssigned"
  }

  tags = var.tags
}

resource "random_id" "state" {
  byte_length = 4
}

resource "azurerm_storage_container" "state" {
  name                  = "tfstate"
  storage_account_name  = azurerm_storage_account.state.name
  container_access_type = "private"
}
''',
            "variables": '''
variable "resource_group_name" {
  description = "Resource group name"
  type        = string
}

variable "location" {
  description = "Azure region"
  type        = string
  default     = "East US"
}
''',
            "outputs": '''
output "storage_account_name" {
  description = "Storage account name for remote state"
  value       = azurerm_storage_account.state.name
}

output "container_name" {
  description = "Blob container name"
  value       = azurerm_storage_container.state.name
}

output "backend_config" {
  description = "Backend configuration snippet"
  value       = <<-EOT
    backend "azurerm" {
      resource_group_name  = "${var.resource_group_name}"
      storage_account_name = "${azurerm_storage_account.state.name}"
      container_name       = "${azurerm_storage_container.state.name}"
      key                  = "terraform.tfstate"
    }
  EOT
}
''',
        },
        "gcp": {
            "main": '''
resource "google_storage_bucket" "state" {
  name          = "${var.name_prefix}-tfstate-${var.project_id}-${random_id.state.hex}"
  location      = var.location
  force_destroy = false

  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"

  versioning {
    enabled = true
  }

  encryption {
    default_kms_key_name = var.kms_key_name
  }

  logging {
    log_bucket        = var.log_bucket_name
    log_object_prefix = "tfstate"
  }
}

resource "random_id" "state" {
  byte_length = 4
}
''',
            "variables": '''
variable "project_id" {
  description = "GCP project ID"
  type        = string
}

variable "location" {
  description = "GCS bucket location"
  type        = string
  default     = "US"
}

variable "kms_key_name" {
  description = "CMEK key name for bucket encryption"
  type        = string
  default     = ""
}

variable "log_bucket_name" {
  description = "Access log target bucket"
  type        = string
  default     = ""
}
''',
            "outputs": '''
output "bucket_name" {
  description = "GCS bucket name for remote state"
  value       = google_storage_bucket.state.name
}

output "backend_config" {
  description = "Backend configuration snippet"
  value       = <<-EOT
    backend "gcs" {
      bucket = "${google_storage_bucket.state.name}"
      prefix = "terraform/state"
    }
  EOT
}
''',
        },
    },
}


def load_requirements(path: str) -> dict[str, Any]:
    """Load requirements from JSON or YAML."""
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    if p.suffix in (".yaml", ".yml"):
        if not HAS_YAML:
            print("ERROR: PyYAML is required for YAML files. Install it with: pip install pyyaml")
            sys.exit(1)
        return yaml.safe_load(text)
    return json.loads(text)


def generate_common_variables(req: dict) -> str:
    """Generate common variables present in every module."""
    lines = [
        'variable "name_prefix" {',
        '  description = "Prefix for resource names"',
        '  type        = string',
        f'  default     = "{req.get("name_prefix", "app")}"',
        '}',
        '',
        'variable "environment" {',
        '  description = "Environment name"',
        '  type        = string',
        f'  default     = "{req.get("environment", "dev")}"',
        '}',
        '',
    ]
    cloud = req.get("cloud", "aws")
    if cloud == "aws":
        lines += [
            'variable "region" {',
            '  description = "AWS region"',
            '  type        = string',
            f'  default     = "{req.get("region", "us-east-1")}"',
            '}',
            '',
            'variable "tags" {',
            '  description = "Tags to apply to all resources"',
            '  type        = map(string)',
            f'  default     = {json.dumps(req.get("tags", {}), indent=2).replace("\"", "\\\"")}',
            '}',
            '',
        ]
    elif cloud == "azure":
        lines += [
            'variable "location" {',
            '  description = "Azure region"',
            '  type        = string',
            f'  default     = "{req.get("region", "East US")}"',
            '}',
            '',
            'variable "tags" {',
            '  description = "Tags to apply to all resources"',
            '  type        = map(string)',
            f'  default     = {json.dumps(req.get("tags", {}), indent=2).replace("\"", "\\\"")}',
            '}',
            '',
        ]
    elif cloud == "gcp":
        lines += [
            'variable "region" {',
            '  description = "GCP region"',
            '  type        = string',
            f'  default     = "{req.get("region", "us-central1")}"',
            '}',
            '',
            'variable "labels" {',
            '  description = "Labels to apply to all resources"',
            '  type        = map(string)',
            f'  default     = {json.dumps(req.get("tags", {}), indent=2).replace("\"", "\\\"")}',
            '}',
            '',
        ]
    return "\n".join(lines)


def generate_versions(cloud: str) -> str:
    """Generate versions.tf for the given cloud."""
    lines = [
        'terraform {',
        '  required_version = ">= 1.5.0"',
        '',
        '  required_providers {',
    ]
    if cloud == "aws":
        lines += [
            '    aws = {',
            '      source  = "hashicorp/aws"',
            '      version = "~> 5.0"',
            '    }',
            '    random = {',
            '      source  = "hashicorp/random"',
            '      version = "~> 3.6"',
            '    }',
        ]
    elif cloud == "azure":
        lines += [
            '    azurerm = {',
            '      source  = "hashicorp/azurerm"',
            '      version = "~> 3.0"',
            '    }',
            '    random = {',
            '      source  = "hashicorp/random"',
            '      version = "~> 3.6"',
            '    }',
        ]
    elif cloud == "gcp":
        lines += [
            '    google = {',
            '      source  = "hashicorp/google"',
            '      version = "~> 5.0"',
            '    }',
            '    random = {',
            '      source  = "hashicorp/random"',
            '      version = "~> 3.6"',
            '    }',
        ]
    lines += [
        '  }',
        '}',
        '',
    ]
    if cloud == "aws":
        lines += ['provider "aws" {', '  region = var.region', '}', '']
    elif cloud == "azure":
        lines += ['provider "azurerm" {', '  features {}', '}', '']
    elif cloud == "gcp":
        lines += ['provider "google" {', '  region = var.region', '}', '']
    return "\n".join(lines)


def generate_readme(module_name: str, cloud: str) -> str:
    return f"""# {module_name} Module ({cloud.upper()})

Generated by dev-infrastructure-coder.

## Usage

```hcl
module "{module_name}" {{
  source = "./modules/{module_name}"

  name_prefix = "myapp"
  environment = "dev"
}}
```

## Requirements

| Name | Version |
|------|---------|
| terraform | >= 1.5.0 |
| {cloud} provider | ~> 5.0 (or ~> 3.0 for Azure) |

## Inputs

See `variables.tf` for all inputs.

## Outputs

See `outputs.tf` for all outputs.

## Security Notes

- Encryption is enabled by default where supported.
- Public access is blocked by default.
- Secrets are generated and stored in the platform secret manager.
"""


def write_module(base_dir: Path, module_name: str, cloud: str, req: dict) -> None:
    """Write a single module's files to disk."""
    mod_dir = base_dir / module_name
    mod_dir.mkdir(parents=True, exist_ok=True)

    tmpl = MODULE_TEMPLATES.get(module_name, {}).get(cloud)
    if not tmpl:
        print(f"WARNING: No template for module '{module_name}' on cloud '{cloud}'")
        return

    # versions.tf
    (mod_dir / "versions.tf").write_text(generate_versions(cloud), encoding="utf-8")

    # main.tf
    (mod_dir / "main.tf").write_text(tmpl["main"].strip() + "\n", encoding="utf-8")

    # variables.tf (common + module-specific)
    common_vars = generate_common_variables(req)
    module_vars = tmpl.get("variables", "").strip()
    (mod_dir / "variables.tf").write_text(common_vars + "\n" + module_vars + "\n", encoding="utf-8")

    # outputs.tf
    (mod_dir / "outputs.tf").write_text(tmpl.get("outputs", "").strip() + "\n", encoding="utf-8")

    # README.md
    (mod_dir / "README.md").write_text(generate_readme(module_name, cloud), encoding="utf-8")

    print(f"  -> {mod_dir}")


def generate_requirements_template(output_path: str) -> None:
    """Emit a sample requirements JSON file."""
    sample = {
        "cloud": "aws",
        "region": "us-east-1",
        "environment": "dev",
        "name_prefix": "myapp",
        "tags": {"Project": "myapp", "CostCenter": "12345", "ManagedBy": "terraform"},
        "modules": ["vpc", "compute", "database", "storage", "loadbalancer", "iam", "state"],
    }
    Path(output_path).write_text(json.dumps(sample, indent=2) + "\n", encoding="utf-8")
    print(f"Sample requirements written to {output_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate Terraform module scaffolding")
    parser.add_argument("--requirements", "-r", help="Path to requirements JSON/YAML")
    parser.add_argument("--output", "-o", default="./modules", help="Output directory")
    parser.add_argument("--cloud", "-c", choices=["aws", "azure", "gcp"], help="Override cloud provider")
    parser.add_argument("--generate-template", action="store_true", help="Write a sample requirements.json and exit")
    args = parser.parse_args()

    if args.generate_template:
        generate_requirements_template("requirements.json")
        return

    if not args.requirements:
        parser.error("--requirements is required (or use --generate-template)")

    req = load_requirements(args.requirements)
    cloud = args.cloud or req.get("cloud", "aws")
    req["cloud"] = cloud

    base_dir = Path(args.output)
    base_dir.mkdir(parents=True, exist_ok=True)

    modules = req.get("modules", [])
    print(f"Generating {len(modules)} module(s) for {cloud} in {base_dir.resolve()}")
    for mod in modules:
        write_module(base_dir, mod, cloud, req)

    # Write a root versions.tf if it does not exist
    root_versions = base_dir / "../versions.tf"
    if not root_versions.exists():
        root_versions.write_text(generate_versions(cloud), encoding="utf-8")
        print(f"  -> {root_versions}")

    print("Done.")


if __name__ == "__main__":
    main()
