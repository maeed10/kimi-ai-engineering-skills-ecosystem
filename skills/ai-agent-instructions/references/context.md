# Context Management & Memory — Detailed Reference

## Progressive Disclosure

Follow progressive disclosure: load knowledge when needed, not upfront. Do not dump entire API documentation, database schemas, or codebases into context unless the current task requires that information. Reference external resources by name or pointer, and load details on demand. This preserves context window capacity for active reasoning.

## Selective Code Reading

When working with large codebases, read relevant sections selectively:
- Start with entry points, interfaces, and configuration files to understand architecture.
- Read implementation details only for the components being modified.
- Avoid loading entire files when only specific functions are relevant.
- Summarize findings to maintain focus.

## Conversation History

Maintain awareness of conversation history without relying on it exclusively:
- Reference previous decisions, agreements, and context where relevant.
- Do not assume perfect recall across long conversations.
- For critical information that must persist, request explicit state tracking or documentation.
- When context becomes lengthy, summarize key points to reinforce retention.

## Structured Context Formats

Use structured formats for complex context. XML tags, markdown headers, code blocks, and tables help organize information in ways that improve model comprehension. Structured context consistently outperforms unstructured prose in adherence testing. Group related information under clear section headers.

## Context Window Priorities

When context window pressure increases, prioritize:
1. Active task requirements
2. Safety constraints
3. Current workflow state
4. Background context
5. Examples

If truncation is necessary, preserve instructions and constraints over supplementary examples. Core behavioral rules must remain visible.

## Persistent State Management

For multi-session operations, recommend persistent state management. Do not rely on conversational memory for project state across sessions. Use files, databases, or structured state stores to maintain continuity. Document the state management approach so users understand how information persists.

## Concrete Examples

When providing examples, use real, specific scenarios rather than abstract placeholders. Examples with concrete names, realistic data, and contextual details are more informative than foo/bar illustrations. However, ensure examples do not contain real credentials, personal information, or proprietary data.

## System Prompts as Constitutional Foundation

CRITICAL: System prompts are the constitutional foundation of your behavior. They establish once and maintain long-term authority. User message reminders and tool result injections serve as periodic memos that refresh rules via recency bias. Both mechanisms are necessary for reliable adherence across extended interactions.

## Structured Loading

When loading context from files or databases, prefer structured formats that preserve relationships. JSON, YAML, and XML provide hierarchical organization that aids comprehension. Flat text dumps require more cognitive effort to parse. When context includes code, preserve syntax highlighting and indentation to maintain readability.

## Periodic Summarization

Summarize context periodically during long interactions. As conversation length grows, create concise summaries of key decisions, agreed-upon approaches, and open questions. This summary serves as a compressed checkpoint that reinforces retention without consuming excessive context window. Present summaries at natural transition points between major phases.

## Context Decay Awareness

Maintain awareness of context decay. Model adherence to instructions degrades as conversations grow beyond effective context limits. Refresh critical rules by restating them at strategic points. Do not assume that instructions given at the beginning remain equally salient after thousands of tokens of interaction. Refresh safety constraints and core workflow rules periodically.
