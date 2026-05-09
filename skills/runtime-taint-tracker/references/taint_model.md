# Taint Model Reference

## Tag Schema (Formal)

```json
{
  "$schema": "TaintTag",
  "type": "object",
  "required": ["source", "trust_score", "taint_color", "provenance_chain", "first_seen"],
  "properties": {
    "source": {
      "type": "string",
      "enum": ["user", "web", "tool", "llm", "system"],
      "description": "Origin category of the data"
    },
    "trust_score": {
      "type": "number",
      "minimum": 0.0,
      "maximum": 1.0,
      "description": "Continuous trust score from 0.0 (untrusted) to 1.0 (fully trusted)"
    },
    "taint_color": {
      "type": "string",
      "enum": ["red", "yellow", "green"],
      "description": "Discrete classification derived from trust_score"
    },
    "provenance_chain": {
      "type": "array",
      "items": { "$ref": "#" },
      "description": "Ordered list of upstream taint tags"
    },
    "first_seen": {
      "type": "string",
      "format": "date-time",
      "description": "ISO 8601 timestamp when this tag was first applied"
    },
    "re_scanned": {
      "type": ["string", "null"],
      "format": "date-time",
      "description": "ISO 8601 timestamp of last periodic re-scan"
    },
    "source_detail": {
      "type": "string",
      "description": "Optional: URL, tool name, username, or other source identifier"
    }
  }
}
```

## Trust Score → Color Mapping

```
if trust_score >= 0.75:  color = green
if trust_score >= 0.35:  color = yellow
else:                     color = red
```

The policy engine may override color based on:
- Source type (e.g., `web` always starts yellow minimum)
- Known-bad source list (force red regardless of score)
- Known-good source whitelist (force green if score >= 0.6)
- Aggregation poisoning (force red if >= 50% tokens from red sources)

## Source Defaults

| Source | Default Score | Default Color | Override Conditions |
|--------|--------------|---------------|---------------------|
| system | 1.00 | green | Never overridden |
| user | 0.85 | green | Drop to 0.40/yellow if anonymous/unauthenticated |
| tool (internal) | 0.70 | green | Drop to 0.25/red if tool reports error or external |
| llm | 0.50 | yellow | Never starts green; synthesis decay applies |
| web | 0.30 | red | Raise to 0.60/green if whitelisted domain |

## Propagation Rules (Detailed)

### Rule P1: Direct Assignment
```
taint(B) = taint(A)
```
No transformation. `B` is a direct alias for `A`.

### Rule P2: Concatenation / Interpolation
```
source(B)     = most_restrictive_source(source(A1), source(A2), ...)
trust_score(B) = min(trust_score(A1), trust_score(A2), ...)
color(B)      = most_restrictive_color(color(A1), color(A2), ...)
provenance_chain(B) = provenance_chain(A1) ++ provenance_chain(A2) ++ [taint(A1), taint(A2)]
```
Most restrictive = red > yellow > green. Most restrictive source = system < user < tool < llm < web.

### Rule P3: Transformation
```
base_taint(B) = taint(A)
trust_score(B) = clamp(trust_score(A) * transformation_factor, 0.0, 1.0)
```

| Transformation | Factor | Notes |
|---------------|--------|-------|
| LLM reasoning | 0.95 | Synthetic decay: every reasoning step |
| String formatting | 1.00 | No semantic change |
| Case change | 1.00 | No semantic change |
| Substring/slice | 1.00 | No semantic change |
| Regex extract | 0.95 | Potential information loss |
| JSON parse/stringify | 0.98 | Structural transformation |
| Encoding change | 0.99 | Base64, URL encode, etc. |

### Rule P4: Aggregation
```
trust_score(B) = weighted_avg(trust_score(Ai), weight=token_count(Ai)) * 0.9
color(B) = color_from_score(trust_score(B))
```
The 0.9 aggregation penalty accounts for the risk of combining sources that individually appear safe.

### Rule P5: Sanitization
```
if rule_type == "exact_match_whitelist":
    trust_score(B) = min(1.0, trust_score(A) + 0.2)
    color(B) = color_from_score(trust_score(B))
elif rule_type == "pattern_blocklist":
    trust_score(B) = trust_score(A)   # unchanged; blocklist alone doesn't raise trust
    color(B) = max(color(A), yellow)  # cannot go below yellow with blocklist alone
elif rule_type == "schema_validation":
    trust_score(B) = min(0.75, trust_score(A) + 0.15)  # cap at green threshold
    color(B) = color_from_score(trust_score(B))
else:
    trust_score(B) = trust_score(A)   # unknown sanitizer = no change
```

**Hard constraint**: Red-tainted data can never become green through sanitization alone. Max post-sanitization color for red origin is yellow.

## Aggregation Poisoning Detection

Even if effective trust score is green, a side-effect argument is **poisoned** (treated as red) if:

```
red_token_count / total_token_count >= 0.5
```

This prevents an attacker from injecting a small amount of trusted data to mask a large amount of untrusted data.

## Re-Scan Adjustment Bounds

```
per_re_scan_delta_max = 0.15
cumulative_lifetime_delta_max = 0.30
```

Re-scan never removes taint. It only adjusts trust scores within bounded ranges. Re-scan log entries are appended to `provenance_chain`.

## Emergent Pattern Detection

The re-scanner looks for these patterns in accumulated context:

| Pattern | Detection Rule | Adjustment |
|---------|---------------|------------|
| Convergence | 3+ independent yellow sources agree on same fact | Each yellow source +0.10 |
| Divergence | Yellow source contradicted by 2+ green sources | Yellow source -0.15 |
| Novel combination | Source combination never seen in training data | Flag for review, -0.10 |
| Repetition | Same red source repeated >3 times | Red source -0.05 (escalation, not dilution) |