# Cloud Patterns Reference

Opinionated patterns for AWS, Azure, and GCP across compute, storage, networking, and databases. Use as a baseline when generating Terraform, CloudFormation, Pulumi, or Ansible artifacts.

---

## Compute

### AWS EC2 / Auto Scaling
- **Pattern**: Launch Template → Auto Scaling Group → Application Load Balancer
- **Instance family**: `t4g` (ARM, cost-opt) for dev; `m6i` / `c6i` for general prod; `r6i` for memory-heavy.
- **AMI strategy**: Use SSM Parameter `/aws/service/ami-amazon-linux-latest/amzn2-ami-hvm-x86_64-gp2` or golden AMI pipeline.
- **User data**: Cloud-init script stored in `templates/user_data.sh`; avoid secrets in user data.
- **Metadata options**: IMDSv2 required (`http_tokens = "required"`).
- **EBS**: GP3 by default; encrypt with KMS; enable snapshots via AWS Backup.
- **Spot**: Use `mixed_instances_policy` with up to 70% spot for stateless workloads.

### Azure VMs / VMSS
- **Pattern**: VMSS + Azure Load Balancer / Application Gateway
- **Instance family**: `B-series` for dev; `Dsv5` for general prod; `Esv5` for memory-heavy.
- **Image**: Ubuntu Server 22.04 LTS or Azure Compute Gallery custom images.
- **Disk**: Managed Disk Premium SSD v2 or Standard SSD; encrypt with Disk Encryption Set + CMK.
- **Spot**: Use `priority = "Spot"` with `eviction_policy = "Deallocate"` for fault-tolerant workloads.
- **Identity**: System-assigned managed identity for Azure resource access.

### GCP Compute Engine / MIG
- **Pattern**: Instance Template → Managed Instance Group → Global Load Balancer
- **Machine family**: `e2` for cost-opt; `n2` for balanced; `n2d` for AMD cost-opt; `c2` for compute-heavy.
- **Image**: COS (Container-Optimized OS) for containers; Ubuntu LTS for general.
- **Disk**: Balanced persistent disk by default; encrypt with CMEK.
- **Spot**: Use `provisioning_model = "SPOT"` with `instance_termination_action = "STOP"`.
- **Metadata**: Block project-wide SSH keys; use OS Login.

### Serverless Compute
| Platform | Service | Trigger | Pattern |
|----------|---------|---------|---------|
| AWS | Lambda | API Gateway / EventBridge | Function URL or ALB target for HTTP |
| Azure | Functions | HTTP / Service Bus / Event Grid | Premium plan for VNet integration |
| GCP | Cloud Functions / Cloud Run | HTTP / Pub/Sub | Cloud Run for containerized workloads |

---

## Storage

### Object Storage
| Concern | AWS S3 | Azure Blob | GCP GCS |
|---------|--------|-----------|---------|
| Encryption at rest | SSE-S3 / SSE-KMS | Microsoft-managed / CMK | Google-managed / CMEK |
| Versioning | Enabled by default in module | Enabled via blob versioning | Enabled via object versioning |
| Lifecycle | Transition to IA/Glacier after 30/90 days | Cool/Archive tiers | Nearline / Coldline / Archive |
| Public access | Block all public access | Disable public blob access | Uniform bucket-level access |
| Logging | Server access logs + CloudTrail | Storage Analytics logs | Cloud Audit Logs |
| Replication | Cross-Region Replication | Object replication | Dual-region or multi-region |

### Block Storage
| Concern | AWS EBS | Azure Disk | GCP PD |
|---------|---------|-----------|--------|
| Default type | gp3 | Premium SSD v2 / Standard SSD | Balanced PD |
| Encryption | KMS CMK | Disk Encryption Set + CMK | CMEK |
| Snapshot | AWS Backup / DLM | Azure Backup | Persistent Disk Snapshots |
| IOPS scaling | Independent from size | Independent from size | Independent from size |

### File Storage
| Platform | Service | Pattern |
|----------|---------|---------|
| AWS | EFS | General Purpose, encrypted, lifecycle to Infrequent Access |
| Azure | Files (SMB/NFS) | Premium tier for low-latency, private endpoint |
| GCP | Filestore | Enterprise tier for HA, encrypted |

---

## Networking

### VPC / VNet / VPC Network
| Concern | AWS VPC | Azure VNet | GCP VPC |
|---------|---------|-----------|---------|
| CIDR block | RFC1918, /16 preferred | RFC1918, /16 preferred | RFC1918, /16 preferred |
| Subnets | Public + Private across 3 AZs | Public + Private across 3 AZs | Public + Private across 3 regions |
| NAT | NAT Gateway per AZ (HA) | NAT Gateway (zone-redundant) | Cloud NAT (regional) |
| DNS | Route53 private zones | Azure Private DNS | Cloud DNS private zones |
| Peering | VPC Peering / Transit Gateway | VNet Peering / Virtual WAN | VPC Peering / Network Connectivity Center |
| Flow logs | VPC Flow Logs → S3/CloudWatch | NSG Flow Logs → Storage Account | VPC Flow Logs → Cloud Logging |

### Load Balancing
| Concern | AWS ALB/NLB | Azure ALB / AGW | GCP GLB |
|---------|-------------|-----------------|---------|
| Layer 7 | Application Load Balancer | Application Gateway | External HTTP(S) Load Balancer |
| Layer 4 | Network Load Balancer | Azure Load Balancer (Standard) | External TCP/UDP Network Load Balancer |
| TLS | ACM certificates | App Gateway / Key Vault certificates | Google-managed / self-managed SSL |
| Health checks | HTTP/HTTPS paths | HTTP/HTTPS probes | HTTP/HTTPS health checks |
| WAF | AWS WAF v2 | WAF on Application Gateway | Cloud Armor |

### Private Connectivity
- **AWS**: VPC Endpoints (Gateway + Interface) for S3, DynamoDB, ECR, etc.
- **Azure**: Private Link + Private Endpoints for Storage, SQL, ACR, etc.
- **GCP**: Private Service Connect + VPC Service Controls for APIs and services.

---

## Databases

### Relational
| Concern | AWS RDS | Azure SQL / PostgreSQL | GCP Cloud SQL / AlloyDB |
|---------|---------|----------------------|------------------------|
| Engine | PostgreSQL 15+ / MySQL 8.0 | PostgreSQL / SQL Server | PostgreSQL / MySQL / AlloyDB |
| Instance class | db.t4g (dev) / db.m6i (prod) | B-series (dev) / GP (prod) | db-f1-micro (dev) / db-n1-standard (prod) |
| Storage | gp3 / io1; encrypted | Managed Disk; encrypted | SSD; encrypted |
| Multi-AZ | `multi_az = true` | Zone-redundant HA | High Availability (regional) |
| Backup | 7-35 days automated | 7-35 days automated | 7-365 days automated |
| Public access | `publicly_accessible = false` | Private endpoint only | Private IP only |
| Secrets | Secrets Manager | Key Vault | Secret Manager |

### NoSQL / Document
| Platform | Service | Pattern |
|----------|---------|---------|
| AWS | DynamoDB | On-demand for unknown traffic; provisioned with auto-scaling for known traffic; DAX for cache |
| Azure | Cosmos DB | Serverless for dev; provisioned throughput for prod; single-region write, multi-region read |
| GCP | Firestore / Bigtable | Firestore for document; Bigtable for wide-column, high-throughput |

### Caching
| Platform | Service | Pattern |
|----------|---------|---------|
| AWS | ElastiCache (Redis/Valkey/Memcached) | Cluster mode on for Redis; encryption in transit and at rest |
| Azure | Azure Cache for Redis | Enterprise tier for clustering; private link |
| GCP | Memorystore (Redis/Memcached) | HA tier with read replicas; auth enabled |

### Search / Analytics
| Platform | Service | Pattern |
|----------|---------|---------|
| AWS | OpenSearch | Encryption at rest, fine-grained access control, VPC endpoint |
| Azure | Cognitive Search | Private endpoints, managed identity |
| GCP | Vertex AI Search / BigQuery | VPC Service Controls, column-level security |

---

## Messaging & Integration

| Concern | AWS | Azure | GCP |
|---------|-----|-------|-----|
| Queue | SQS (standard + FIFO) | Service Bus Queue / Storage Queue | Pub/Sub pull/push subscriptions |
| Pub/Sub | SNS / EventBridge | Event Grid / Service Bus Topic | Pub/Sub |
| Streaming | Kinesis Data Streams | Event Hubs | Dataflow / Pub/Sub |
| API Management | API Gateway | API Management | Apigee / API Gateway |
| Service Mesh | App Mesh / Istio on EKS | Open Service Mesh / Istio on AKS | Anthos Service Mesh / Istio on GKE |

---

## Observability Baseline

| Concern | AWS | Azure | GCP |
|---------|-----|-------|-----|
| Metrics | CloudWatch | Azure Monitor Metrics | Cloud Monitoring |
| Logs | CloudWatch Logs | Log Analytics | Cloud Logging |
| Tracing | X-Ray | Application Insights | Cloud Trace |
| Alarms | CloudWatch Alarms | Alert Rules | Alerting Policies |
| Dashboards | CloudWatch Dashboards | Azure Dashboards / Grafana | Cloud Monitoring Dashboards |
| Synthetic | CloudWatch Synthetics | Application Insights Availability Tests | Cloud Monitoring Uptime Checks |

---

## Backup & DR

| Concern | AWS | Azure | GCP |
|---------|-----|-------|-----|
| Backup service | AWS Backup | Azure Backup | Backup for GKE / Cloud SQL native |
| Cross-region copy | Copy to DR region | Geo-redundant storage / GRS | Dual-region buckets / cross-region SQL replica |
| RPO/RTO targets | Document per workload | Document per workload | Document per workload |
| Immutable backup | Vault lock (compliance mode) | Immutable blob container | Bucket retention policy / locked |

---

## Tagging / Labeling Strategy

Every resource should have:
- `Environment`: dev, staging, prod
- `Project` / `CostCenter`: owning team or budget code
- `ManagedBy`: terraform / cloudformation / pulumi / ansible
- `DataClassification`: public, internal, confidential, restricted
- `AutoShutdown`: true / false (for dev cost control)
- `BackupPolicy`: default / critical / none

This enables cost allocation, access filtering, and automated lifecycle policies.
