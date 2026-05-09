# Architecture Criteria Registry Schema

This document defines the JSON/YAML schema for the human-curated `architecture-criteria-registry`. The registry prevents LLM bias by requiring human-curated constraints, weights, and team/org context before any architecture decision proceeds to ASSESS.

## Purpose

- **Single source of truth** for org-specific architectural constraints
- **Human-curated weights** for trade-off scoring that the LLM must reference, not synthesize
- **Team and operational context** that the LLM cannot reliably infer from code alone

## Schema (JSON)

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "ArchitectureCriteriaRegistry",
  "type": "object",
  "required": ["version", "org_context", "criteria_catalog", "pattern_registry", "infrastructure_constraints"],
  "properties": {
    "version": {
      "type": "string",
      "description": "Registry version. SemVer recommended.",
      "example": "1.2.0"
    },
    "last_updated": {
      "type": "string",
      "format": "date-time",
      "description": "Timestamp of last human curation event."
    },
    "curator": {
      "type": "string",
      "description": "Identity of the human or team that last updated the registry."
    },
    "org_context": {
      "type": "object",
      "required": ["team_size_range", "primary_deployment_model", "compliance_requirements"],
      "properties": {
        "team_size_range": {
          "type": "object",
          "required": ["min", "max", "effective_date"],
          "properties": {
            "min": { "type": "integer", "minimum": 1 },
            "max": { "type": "integer", "minimum": 1 },
            "effective_date": { "type": "string", "format": "date" },
            "note": { "type": "string" }
          }
        },
        "primary_deployment_model": {
          "type": "string",
          "enum": ["monolith", "modular_monolith", "microservices", "serverless", "hybrid", "edge", "other"],
          "description": "Current org-wide default. New models require explicit override."
        },
        "compliance_requirements": {
          "type": "array",
          "items": { "type": "string" },
          "description": "Regulatory or audit constraints (e.g., SOC2, GDPR, HIPAA)."
        },
        "budget_ceiling_ops_monthly_usd": {
          "type": "number",
          "description": "Soft operational budget ceiling per month in USD. Used as a criteria weight anchor."
        }
      }
    },
    "criteria_catalog": {
      "type": "array",
      "description": "Human-curated criteria with org-specific weights and sources.",
      "items": {
        "type": "object",
        "required": ["id", "name", "weight", "source", "applicable_to"],
        "properties": {
          "id": { "type": "string", "pattern": "^[a-z0-9_]+$" },
          "name": { "type": "string" },
          "description": { "type": "string" },
          "weight": {
            "type": "number",
            "minimum": 0,
            "maximum": 1,
            "description": "Relative weight in trade-off scoring. Sum need not be 1.0; normalizer should handle."
          },
          "source": {
            "type": "string",
            "description": "Human source of this weight: 'team_vote_2024_Q1', 'cto_directive_42', 'post_mortem_2023_11', 'historical_decision_adr_007', etc. NEVER 'llm_default' or 'industry_standard'."
          },
          "applicable_to": {
            "type": "array",
            "items": { "type": "string", "enum": ["pattern", "deployment", "data_store", "message_bus", "observability", "security"] },
            "description": "Which decision types this criteria applies to."
          },
          "override_policy": {
            "type": "string",
            "enum": ["fixed", "requires_arch_board", "requires_cto", "team_lead_can_adjust"],
            "description": "Governance rule for changing this weight."
          }
        }
      }
    },
    "pattern_registry": {
      "type": "array",
      "description": "Human-curated list of approved, deprecated, or prohibited patterns.",
      "items": {
        "type": "object",
        "required": ["pattern_name", "status"],
        "properties": {
          "pattern_name": { "type": "string" },
          "status": {
            "type": "string",
            "enum": ["approved", "prohibited", "deprecated", "requires_exemption", "experimental" ]
          },
          "min_team_size": { "type": "integer", "description": "Minimum team size for this pattern to be considered." },
          "max_team_size": { "type": "integer", "description": "Maximum team size for this pattern to be viable." },
          "required_expertise": {
            "type": "array",
            "items": { "type": "string" },
            "description": "Required team capabilities (e.g., 'k8s_admin', 'event_sourcing_experience')."
          },
          "rationale": { "type": "string", "description": "Human-written rationale for the status." },
          "adr_reference": { "type": "string", "description": "Link or ID to the ADR that recorded this decision." }
        }
      }
    },
    "infrastructure_constraints": {
      "type": "object",
      "description": "Hard and soft limits on infrastructure additions.",
      "properties": {
        "max_data_stores_per_service": { "type": "integer", "minimum": 1 },
        "max_message_buses_global": { "type": "integer", "minimum": 1 },
        "new_store_requires_approval_above_n_usd_monthly": { "type": "number" },
        "preferred_providers": {
          "type": "array",
          "items": { "type": "string" },
          "description": "Preferred cloud providers or vendors. Deviations require justification."
        },
        "prohibited_technologies": {
          "type": "array",
          "items": { "type": "string" },
          "description": "Explicitly prohibited technologies. Proposals using these hit mandatory HITL."
        }
      }
    }
  }
}
```

## Example Registry (YAML)

```yaml
version: "1.0.0"
last_updated: "2024-06-15T09:00:00Z"
curator: "platform-team@example.com"

org_context:
  team_size_range:
    min: 4
    max: 12
    effective_date: "2024-01-01"
    note: "Platform squad effective size. Contracted 2 engineers in Q1."
  primary_deployment_model: modular_monolith
  compliance_requirements:
    - SOC2 Type II
    - GDPR
  budget_ceiling_ops_monthly_usd: 3500.00

criteria_catalog:
  - id: operational_cost
    name: Operational Cost
    description: Monthly infrastructure and licensing cost in USD.
    weight: 0.25
    source: "cto_directive_infra_budget_2024"
    applicable_to: ["deployment", "data_store", "message_bus", "observability"]
    override_policy: requires_cto

  - id: team_expertise
    name: Team Expertise Coverage
    description: Fraction of team with production experience in the proposed technology.
    weight: 0.30
    source: "post_mortem_kafka_outage_2023_11"
    applicable_to: ["pattern", "deployment", "data_store", "message_bus"]
    override_policy: requires_arch_board

  - id: maintainability
    name: Long-term Maintainability
    description: Estimated burden over 2 years: onboarding time, debug complexity, bus factor.
    weight: 0.25
    source: "team_vote_2024_q1"
    applicable_to: ["pattern", "deployment", "data_store"]
    override_policy: team_lead_can_adjust

  - id: latency_p99
    name: P99 Latency
    description: End-to-end P99 latency requirement in milliseconds.
    weight: 0.15
    source: "slo_document_2024"
    applicable_to: ["pattern", "data_store", "message_bus"]
    override_policy: requires_arch_board

  - id: vendor_lockin_risk
    name: Vendor Lock-in Risk
    description: Cost and complexity of migration away from the proposed technology.
    weight: 0.05
    source: "historical_decision_adr_014"
    applicable_to: ["deployment", "data_store", "message_bus", "observability"]
    override_policy: requires_arch_board

pattern_registry:
  - pattern_name: microservices
    status: requires_exemption
    min_team_size: 8
    required_expertise: ["k8s_admin", "distributed_tracing", "circuit_breaker_ops"]
    rationale: "Team is below minimum size and lacks distributed tracing expertise. Exemption only with arch board sign-off."
    adr_reference: "ADR-018"

  - pattern_name: modular_monolith
    status: approved
    min_team_size: 3
    max_team_size: 15
    required_expertise: []
    rationale: "Current default. Proven fit for team size and expertise."
    adr_reference: "ADR-001"

  - pattern_name: event_sourcing
    status: experimental
    min_team_size: 10
    required_expertise: ["event_sourcing_experience", "event_schema_governance"]
    rationale: "High complexity. Approved only for greenfield experiments with dedicated SRE."
    adr_reference: "ADR-021"

  - pattern_name: serverless
    status: approved
    min_team_size: 2
    max_team_size: 20
    required_expertise: ["aws_lambda"]
    rationale: "Low operational overhead for event-driven workloads."
    adr_reference: "ADR-009"

infrastructure_constraints:
  max_data_stores_per_service: 2
  max_message_buses_global: 2
  new_store_requires_approval_above_n_usd_monthly: 500.00
  preferred_providers:
    - AWS
    - GCP
  prohibited_technologies:
    - Cassandra
    - Hadoop
    - ZooKeeper
```

## Validation Rules for Gate 3

1. **Weight Source Check**: Every criteria used in the current trade-off must have a `source` field in the registry. If the source is missing or marked `llm_default`, the criteria does not count toward the 50% external-weight threshold.
2. **Pattern Status Check**: The primary recommended pattern must have a `status` of `approved` or `experimental`. `prohibited` blocks immediately. `deprecated` requires explicit migration rationale. `requires_exemption` requires an exemption record in the gate output.
3. **Team-Size Check**: The current `org_context.team_size_range` must overlap with the pattern's `[min_team_size, max_team_size]` (if defined). No overlap = flag `TEAM_SIZE_MISMATCH`.
4. **Constraint Check**: The proposal must not exceed `max_data_stores_per_service`, `max_message_buses_global`, or use `prohibited_technologies`. Breaches are automatic HITL triggers.

## Registry Maintenance Policy

- **Update cadence**: At least quarterly human review. Record `last_updated` and `curator` on every change.
- **Override governance**: Weights with `override_policy: fixed` can only be changed by registry version bump with arch board approval.
- **New entries**: Adding a new pattern to `pattern_registry` requires at least one human author and one reviewer documented in commit/change metadata.
