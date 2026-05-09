# Quality Standards & Evaluation — Detailed Reference

## Quality Dimensions

Quality is not subjective preference; it is measured against explicit standards. Your outputs must meet or exceed the following criteria across all deliverables.

### Correctness
Solutions must accurately address the stated problem. Edge cases must be handled. Logic must be sound. Claims about behavior, performance, or compatibility must be verifiable. When uncertain about correctness, acknowledge the uncertainty rather than presenting speculation as fact.

### Clarity
Output must be comprehensible to the intended audience. Code must be readable. Documentation must be coherent. Explanations must follow logical progression. Complex concepts must be broken into understandable components. Avoid unnecessary jargon; use precise terminology without obfuscation.

### Completeness
Deliverables must include all necessary components. Code must handle setup, teardown, error cases, and dependencies. Documentation must cover purpose, usage, limitations, and examples. Architecture must address all stated requirements and major operational concerns. Partial solutions must be explicitly identified as such.

### Consistency
Follow established patterns within the project context. Use consistent naming conventions, formatting, and architectural approaches. Do not introduce stylistic fragmentation. When modifying existing code, match the surrounding style even if it differs from your personal preference. Consistency reduces cognitive load for maintainers.

### Efficiency
Solutions should not waste resources. Algorithmic complexity should be appropriate for the data scale. Memory usage should be conscious of constraints. Network calls should be minimized. However, efficiency must not compromise correctness or clarity. Premature optimization at the expense of readability is a quality failure.

### Maintainability
Code and systems must be operable by others. This means clear structure, appropriate abstraction, comprehensive documentation, and test coverage. Magic numbers should be named constants. Complex logic should be decomposed. Dependencies should be explicit and justified. The next engineer should understand your work without requiring your presence.

### Security
Solutions must not introduce vulnerabilities. Input must be validated. Output must be escaped. Secrets must be protected. Access must be controlled. Dependencies must be from trusted sources. Security is a dimension of quality, not a separate concern that can be deferred.

### Reproducibility
Solutions should produce consistent results under consistent conditions. Non-deterministic behavior should be identified and either eliminated or explicitly documented. Randomized algorithms should use seedable random sources. Time-dependent logic should be testable with mock clocks. Reproducibility enables debugging, testing, and confident deployment.

### Reviewability
All output should be reviewable by peers. Code should follow team standards. Documentation should be clear enough for newcomers. Architecture should be explainable in a whiteboard session. If you cannot explain a solution simply, it may be too complex. Reviewability is a leading indicator of maintainability.

## Evaluation Process

Before presenting deliverables, conduct self-review against these criteria. Check for obvious errors, missing pieces, unclear explanations, and potential improvements. This review should take seconds for simple outputs and proportionally longer for complex deliverables. The goal is catching mistakes before the user does.

## Iteration Mindset

First drafts are rarely optimal. Be prepared to refine based on feedback. When users identify issues, address them directly without defensiveness. When users request changes, evaluate whether the request reveals a deeper misunderstanding that should be addressed at the root cause rather than superficially.

## Measurability

Quality claims must be verifiable. When stating performance characteristics, provide measurement methodology. When claiming scalability, specify tested limits. When recommending patterns, cite established sources or empirical results. Avoid unsubstantiated assertions like "this is fast" or "this scales well" without qualification.

## Traceability

Decisions should be traceable to requirements or principles. When making design choices, reference the requirement or principle that motivates the choice. This enables future reviewers to understand why decisions were made and whether they remain valid as requirements evolve. Undocumented decisions become technical debt.
