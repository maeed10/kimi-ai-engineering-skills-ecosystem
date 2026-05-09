# Production-Ready Prompt Library — Detailed Reference

## Overview

These ten prompts represent production-ready templates derived from the operational guidelines, tone specifications, and best practices documented throughout this instruction set. Each prompt targets a specific engineering scenario and incorporates principles of clarity, structure, and precision. These prompts serve as exemplars for how the agent should be directed across diverse technical contexts.

Each prompt follows a consistent structure: scenario context that establishes the problem domain, explicit requirements that define success criteria, constraints that bound the solution space, and output specifications that describe deliverable format. This structure reflects the prompt engineering best practices from Google Cloud Vertex AI documentation and Anthropic's research on effective context engineering.

## Prompt 1: System Architecture Design

**Full Text:**
Design a distributed microservices architecture for a high-throughput e-commerce platform handling 100,000 orders per minute at peak. The system must support real-time inventory management, payment processing with PCI DSS compliance, and multi-region deployment. Include service boundaries, communication patterns, data consistency strategy, failover mechanisms, and observability stack. Justify each architectural decision with trade-off analysis. Consider CAP theorem implications, latency budgets per service tier, and cost optimization strategies for steady-state versus peak loads.

**Use Case:** Architecture reviews, platform modernization, scalability planning.
**Adaptation:** Modify throughput requirements, compliance frameworks, and deployment constraints to match your domain.

## Prompt 2: Production Code Review

**Full Text:**
Perform a comprehensive code review of the following Python FastAPI service. Evaluate: error handling completeness, input validation coverage, security posture, async pattern correctness, database connection management, logging adequacy, testability, and adherence to PEP 8. Identify specific vulnerabilities or bugs with line references. Provide corrected code for critical issues and architectural recommendations for structural problems. Include severity classification (critical, high, medium, low) with justification for each finding.

**Use Case:** Pre-merge reviews, security audits, technical debt assessment.
**Adaptation:** Change the target language and framework while maintaining the evaluation dimensions relevant to that stack.

## Prompt 3: Database Schema Optimization

**Full Text:**
Analyze and optimize the following PostgreSQL schema for a SaaS analytics platform with 50TB of time-series data and 500 concurrent query users. Identify: missing indexes, normalization issues, partitioning opportunities, query anti-patterns, and locking risks. Propose schema changes with migration scripts, estimate performance impact, and recommend monitoring queries. Consider both read-heavy analytical workloads and write-heavy ingestion pipelines. Address hot spot identification and connection pool sizing recommendations.

**Use Case:** Database optimization, schema migrations, capacity planning.
**Adaptation:** Specify your database engine, data volume, and query patterns. Time-series workloads have different optimization profiles than transactional or document-oriented workloads.

## Prompt 4: CI/CD Pipeline Construction

**Full Text:**
Design a complete CI/CD pipeline for a containerized Go microservice deployed to Amazon EKS. The pipeline must include: automated unit and integration testing, security scanning (SAST, DAST, dependency vulnerabilities), image signing, blue-green deployment strategy, automated rollback triggers, and compliance audit logging. Provide GitHub Actions or GitLab CI YAML configurations with explanatory comments for each stage. Include environment promotion strategy and secrets management integration.

**Use Case:** DevOps automation, compliance enablement, deployment standardization.
**Adaptation:** Change the target platform (GCP, Azure, on-premises) and container orchestrator while preserving the security and verification stages.

## Prompt 5: Security Incident Response

**Full Text:**
You are responding to a suspected data exfiltration incident. The following logs show anomalous database access patterns over the past 72 hours. Analyze: access source identification, privilege escalation indicators, data volume transferred, lateral movement evidence, and persistence mechanisms. Recommend immediate containment steps, forensic preservation actions, and long-term remediation. Maintain chain of custody considerations in your recommendations. Include timeline reconstruction and impact scope quantification.

**Use Case:** Incident response, forensic analysis, security operations.
**Adaptation:** Specify log formats, SIEM tools in use, and regulatory reporting requirements relevant to your jurisdiction and industry.

## Prompt 6: API Design & Documentation

**Full Text:**
Design a RESTful API specification for a banking transaction service that supports domestic transfers, international wire transfers, scheduled payments, and recurring transfers. Include OpenAPI 3.0 specification with: authentication scheme, rate limiting, idempotency patterns, error response taxonomy, pagination for transaction history, and webhook event definitions. Ensure all endpoints address OWASP API Security Top 10 concerns. Provide request/response examples for each endpoint.

**Use Case:** API design, service definition, contract-first development.
**Adaptation:** Change the domain and regulatory requirements. Financial services require different controls than healthcare, logistics, or social platforms.

## Prompt 7: Performance Bottleneck Analysis

**Full Text:**
The following application metrics show degraded performance under load: p95 latency increased from 120ms to 4.2s, CPU utilization at 35%, memory stable at 60%, database connection pool at 95% saturation, and disk I/O wait at 78%. Analyze the bottleneck hierarchy, identify the root cause with supporting evidence, and propose targeted optimizations. Include before/after estimates and verification approaches for each proposed change. Rank optimizations by expected impact and implementation difficulty.

**Use Case:** Production troubleshooting, capacity planning, performance engineering.
**Adaptation:** Provide your specific metrics and SLA targets. Different applications have different critical paths that require domain-specific analysis.

## Prompt 8: Infrastructure as Code Refactoring

**Full Text:**
Refactor the following Terraform configuration for a multi-environment AWS infrastructure setup. The current configuration has significant duplication across dev, staging, and production environments. Apply DRY principles, introduce modular components, implement remote state management with locking, add input validation, and include cost estimation tags. Ensure the refactored code maintains existing functionality while improving maintainability and reducing blast radius for changes. Include migration strategy from current state without downtime.

**Use Case:** Infrastructure modernization, IaC standardization, multi-environment management.
**Adaptation:** Change the cloud provider and infrastructure types while preserving the modularization and validation principles.

## Prompt 9: Data Pipeline Engineering

**Full Text:**
Design a real-time event streaming pipeline processing 2 million events per second from IoT sensors. Data must be ingested, validated against schemas, enriched with reference data, aggregated into 1-minute windows, and written to both a data warehouse and real-time serving layer. Include: Kafka topic partitioning strategy, schema registry configuration, stream processing topology (Flink or Kafka Streams), exactly-once semantics, backpressure handling, and schema evolution approach. Address data quality and late-arriving event strategies. Provide cost estimates for infrastructure at scale.

**Use Case:** Data platform design, IoT architectures, real-time analytics.
**Adaptation:** Modify event volumes, latency requirements, and sink systems. Financial tick data, telemetry, and user behavior streams have different processing characteristics.

## Prompt 10: Technical Debt Assessment

**Full Text:**
Conduct a technical debt assessment of the following legacy monolithic application. Categorize debt items by: architectural (coupling, scaling limits), code-level (complexity, duplication, outdated patterns), operational (deployment friction, monitoring gaps), and security (vulnerability exposure, dependency aging). For each category, provide severity scoring, estimated remediation effort, risk quantification, and phased remediation roadmap that balances stability with modernization velocity. Include business case justification for remediation investment.

**Use Case:** Modernization planning, resource allocation, risk management.
**Adaptation:** Specify the technology stack, business criticality of the application, and team capacity constraints. Debt assessment must be actionable, not merely descriptive.

## Prompt Engineering Principles Summary

These ten prompts illustrate core prompt engineering principles synthesized from Google Cloud Vertex AI documentation, Anthropic's prompting research, OpenAI's agent guidelines, and production system design practices. The key principles demonstrated include:

- Clear role anchoring at the start of each prompt
- Explicit task definition with success criteria
- Constraint specification that bounds the solution space
- Structured output requirements
- Reasoning transparency through justification requirements

### Effective Prompt Hierarchy

Effective prompts for engineering agents follow a hierarchy:
1. Identity establishment
2. Safety constraints
3. Task specification with context
4. Output format definition
5. Quality verification instructions

This hierarchy exploits the primacy and recency effects documented in language model attention research. Instructions at the beginning and end of prompts receive stronger adherence than instructions buried in the middle.

### Specificity Guidelines

When crafting prompts for this agent, remember that specificity should increase with task complexity:
- Simple tasks require minimal instruction.
- Complex tasks benefit from structured sections with clear headers.
- Always include examples for format-sensitive outputs.
- Use absolute language (NEVER, ALWAYS, MUST) for hard constraints.
- Use recommendatory language for best practices.
- This distinction helps the agent calibrate its autonomy appropriately.

### Iterative Refinement

Treat prompts as evolving artifacts. Initial prompts rarely achieve optimal results. Iterate based on observed outputs:
- Identify where the agent deviates from expectations.
- Add clarifying constraints.
- Provide corrective examples.
- Refine output specifications.

Prompt engineering is iterative refinement, not one-shot perfection. The prompts in this library represent vetted starting points that should be adapted based on your specific context and validated through use.

### Versioning & Testing

Document all prompt versions and their observed performance. Maintain a changelog that records what was modified, why the change was made, and how output quality shifted. This empirical approach transforms prompt engineering from art into measurable practice. The most effective engineering organizations treat prompts as versioned artifacts with regression testing, just like code.

### Adaptation Framework

Each prompt template can be extended with domain-specific context, regulatory constraints, or organizational standards. The base structure remains constant while the specific parameters adapt to environment. This modular approach to prompt design enables reuse across projects while maintaining contextual relevance.
