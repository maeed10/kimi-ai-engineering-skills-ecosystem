# Multi-Model Router Configuration

## Configuration File

Place at `~/.kimi/config/multi-model-router.yaml`:

```yaml
router:
  default_provider: gemini
  fallback_provider: local  # NEVER fallback to paid without user consent

  providers:
    gemini:
      backend: gemini-cli
      model: gemini-2.5-flash-lite
      daily_limit_requests: 950
      cost_per_1k_tokens: 0.0
      billing_category: free_tier
      security_classification: non_security_only
      allowed_phases: [INGEST, PLAN, DELIVER, REMEMBER]

    claude:
      backend: anthropic-cli
      model: claude-sonnet-4
      daily_limit_requests: 500
      cost_per_1k_tokens: 3.00
      billing_category: paid
      security_classification: non_security_only
      allowed_phases: [INGEST, PLAN, DELIVER, REMEMBER]

    local:
      backend: ollama
      model: qwen2.5-coder:14b
      daily_limit_requests: unlimited
      cost_per_1k_tokens: 0.0
      billing_category: self_hosted
      security_classification: non_security_only
      allowed_phases: [INGEST, PLAN, DELIVER, REMEMBER]

  billing:
    monthly_budget_usd: 100.00
    daily_budget_usd: 3.33
    alert_threshold: 0.80
    hard_stop_threshold: 1.00
    currency: USD

  on_limit_reached:
    action: FALLBACK_TO_KIMI
    notify: true
    log_level: WARN

  fallback_on_limit_exceeded: true
  fallback_model: kimi-full
```

## Environment Setup

### Gemini CLI (Free Tier)

1. Install Gemini CLI:
   ```bash
   npm install -g @google/gemini-cli
   ```

2. Set your API key:
   ```bash
   # Get a free key from https://aistudio.google.com/app/apikey
   export GEMINI_API_KEY="your-key-here"
   ```

3. Verify:
   ```bash
   gemini -m gemini-2.5-flash-lite -p "Hello"
   ```

### Claude (Paid)

1. Install Anthropic CLI:
   ```bash
   npm install -g @anthropic-ai/cli
   ```

2. Set your API key:
   ```bash
   export ANTHROPIC_API_KEY="your-key-here"
   ```

### Local (Ollama)

1. Install Ollama: https://ollama.com
2. Pull a model:
   ```bash
   ollama pull qwen2.5-coder:14b
   ```

## User Preference Store

Stored at `~/.kimi/state/user-provider-preference.json`:

```json
{
  "preferred_provider": "gemini",
  "preferred_model": "gemini-2.5-flash-lite",
  "cost_ceiling_usd_per_day": 5.00,
  "auto_fallback_allowed": false,
  "last_updated": "2026-05-07T09:00:00Z"
}
```

## Billing-Linked Dynamic Limits

```
daily_limit_tokens = (daily_budget_usd / cost_per_1k_tokens) * 1000
```

When the billing threshold is reached, the system **HALTS** external routing and presents the user with three options:
1. Switch to a zero-cost provider (e.g., local Ollama, Gemini free tier if under its separate cap)
2. Increase the billing cap (requires explicit user action)
3. Continue with Kimi local execution

The system must NEVER silently route to a paid provider, upgrade the model tier, or charge the user without explicit per-decision consent.
