# Provider Comparison Matrix

| Provider | Model | Cost / 1k tokens | Daily Limit | Latency | Quality | Best For |
|----------|-------|-----------------|-------------|---------|---------|----------|
| **Gemini** | gemini-2.5-flash-lite | $0.00 (free tier) | 950 req/day | Low | Good | INGEST, PLAN, DELIVER, REMEMBER — all low-cost tasks |
| **Claude** | claude-sonnet-4 | $3.00 | 500 req/day | Medium | Excellent | Complex reasoning when user explicitly consents to cost |
| **Local** | qwen2.5-coder:14b | $0.00 (self-hosted) | Unlimited | High (GPU) | Good | Air-gapped environments, zero egress |

## Cost Tier Mapping

| Task Complexity | Recommended Provider | Rationale |
|-----------------|---------------------|-----------|
| Simple parsing/summarization | Gemini (free) | Zero cost, sufficient quality |
| Multi-step reasoning | Claude (paid) | Better reasoning, requires user consent |
| Sensitive/internal data | Local (Ollama) | No data leaves the network |

## Security Classification

All three providers are classified as `non_security_only`. No provider in this router handles:
- Security-critical tasks
- Secret/credential processing
- Sandbox configuration
- Policy decisions

Such tasks are always routed to Kimi local execution.
