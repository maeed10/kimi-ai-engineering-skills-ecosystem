# Example Mapping Reference

## Purpose

Convert ambiguous requirement statements into concrete, testable Given/When/Then (G/W/T) scenarios. User validates each scenario; unvalidated scenarios block PLAN.

## When to Apply

- Task node ambiguity score > 0.2
- Requirements contain hedge words or unquantified adjectives
- User story has no existing acceptance criteria
- Cross-functional requirements (auth, billing, notifications) where behavior varies by role/state

## G/W/T Template

```gherkin
Scenario: <descriptive name>
  Given <precondition: system state or user context>
  And <additional precondition if needed>
  When <action: user or system behavior>
  Then <outcome: observable, verifiable result>
  And <additional outcome if needed>
```

## Generation Rules

1. **One concept per scenario** — do not combine happy path + edge case
2. **No ambiguous terms in Then** — every outcome must be measurable
3. **Given must be setup, not action** — state, not behavior
4. **When is singular** — one action triggers the scenario
5. **Data values are concrete** — use realistic numbers, IDs, strings, not placeholders

## Three-Scenario Minimum Per Story

### 1. Happy Path
Standard success. The 80% case.

```gherkin
Scenario: Successful payment with valid card
  Given a user with id "U-4421" has a Visa card ending in 4242 on file
  And the card has not expired
  When the user purchases a "Pro Plan" subscription for $29.00
  Then the payment succeeds with status "confirmed"
  And the user's subscription tier updates to "pro"
  And an invoice email is queued to the user's registered address
```

### 2. Edge Case
Boundary condition. Tests limits.

```gherkin
Scenario: Payment with expired card
  Given a user with id "U-4421" has a Visa card that expired last month
  When the user attempts to purchase a "Pro Plan" subscription for $29.00
  Then the payment fails with error code "CARD_EXPIRED"
  And the user is prompted to update their payment method
  And no subscription tier change occurs
```

### 3. Failure Path
Error handling. Tests resilience.

```gherkin
Scenario: Payment gateway timeout
  Given a user with id "U-4421" has a valid Mastercard on file
  And the payment gateway is experiencing latency > 30s
  When the user purchases a "Pro Plan" subscription for $29.00
  Then the system retries the payment up to 3 times with exponential backoff
  And after final failure, the payment is marked "PENDING_GATEWAY"
  And the user sees "Payment is processing, check back in 5 minutes"
  And a reconciliation job is queued
```

## Data Realism Standards

| Field Type | Example | Anti-Pattern |
|------------|---------|--------------|
| User ID | `U-4421` | `user1` |
| Email | `sarah.chen@example.com` | `test@test.com` |
| Currency amount | `$29.00` | `$X` |
| Date | `2024-03-15` | `some date` |
| Status code | `CARD_EXPIRED` | `error` |
| Timeout | `30s` | `a long time` |

## Validation Workflow

```
GENERATE 3 scenarios per user story
PRESENT to user with:
  - The original requirement statement
  - Each scenario with highlighting on changed/uncertain parts
  - A binary choice per scenario: [Correct] [Needs Change] [Wrong]

IF user selects [Correct]:
  Mark scenario VALIDATED, append to EXAMPLES.md

IF user selects [Needs Change]:
  Show editable diff, capture revision, re-present
  Max 3 revision rounds; if unresolved after 3, mark as ASSUMPTION

IF user selects [Wrong]:
  Discard scenario, generate alternative, re-present
  Max 2 alternatives; if none accepted, flag story for rewrite

ALL scenarios for a story must be VALIDATED before PLAN proceeds
```

## Validation Prompt Template

Present to user:

```
--- Story: <story title> ---
Original: "<requirement text>"

Scenario 1 (Happy Path):
  <G/W/T>
  [Correct] [Needs Change] [Wrong]

Scenario 2 (Edge Case):
  <G/W/T>
  [Correct] [Needs Change] [Wrong]

Scenario 3 (Failure Path):
  <G/W/T>
  [Correct] [Needs Change] [Wrong]

Summary: <N> scenarios validated, <M> pending
Blockers: <list if any>
```

## Handling Complex Stories

For stories with multiple actors or states, generate a **scenario matrix**:

```
States:    [Guest] [Free User] [Pro User] [Admin]
Actions:   [View] [Create] [Edit] [Delete]

Generate G/W/T only for cells marked X in coverage matrix:
        View  Create  Edit  Delete
Guest    X     X
Free     X            X
Pro      X     X      X
Admin    X     X      X     X
```

Only generate scenarios for permission combinations that differ from default. Do not generate redundant scenarios.

## Anti-Patterns to Reject

| Pattern | Problem | Fix |
|---------|---------|-----|
| "Then it should work" | Not observable | Specify exact output/state change |
| "Given the user does X" | Given is action, not state | Move action to When, set state in Given |
| Multiple Whens | Unclear trigger | Split into separate scenarios |
| Placeholder data | Not testable | Use realistic concrete values |
| Business logic in Then | Implementation leak | Describe outcome, not mechanism |
