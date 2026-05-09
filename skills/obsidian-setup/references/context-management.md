## Context Management & Memory

### Progressive Disclosure

Load vault content when needed, not upfront:
1. **Session start**: Load `index.md` and `_agent/memory/working/current_session.md` — ~200 tokens
2. **Project orientation**: Load `_agent/memory/semantic/project_overview.md` and community MOCs — ~500 tokens
3. **Deep reasoning**: Load specific notes referenced by user's query — scales with topic
4. **Historical context**: Load recent episodic logs only when user asks "what did we do last time?" — ~300 tokens per log

### Structured Context Format

Pass vault context to LLM in structured form:

```yaml
vault_state:
  total_notes: 342
  communities: 7
  last_updated: 2025-07-01T14:30:00Z
  active_session: session_042
loaded_notes:
  - note: project_overview.md
    type: semantic
    relevance: high
  - note: community_3_api.md
    type: moc
    relevance: high
  - note: user_service_authenticate.md
    type: function
    relevance: high
    linked_from: [jwt_middleware.md, auth_controller.md]
recent_episodic:
  - 2025-07-01_14-30-00_session_042.md
  - 2025-07-01_10-00-00_session_041.md
```

### Priority Under Context Pressure

When context window is constrained, preserve in this order:
1. **Task requirements** (what the user is asking)
2. **Safety constraints** (what must not be done)
3. **Working memory** (active session state)
4. **Semantic memory — project overview** (high-level context)
5. **Semantic memory — relevant topic notes** (directly related to query)
6. **Episodic memory — most recent log** (continuity)
7. **Episodic memory — older logs** (can be summarized or omitted)
8. **Community MOCs** (navigation structure)
9. **Full index.md** (can be summarized)

### Multi-Session Persistence Architecture

The vault IS the memory substrate. No separate database is required [^38^]. The AI agent reads and writes markdown files directly.

```
Persistence Layer:
├── Session (transient)
│   └── _agent/memory/working/current_session.md
├── Short-Term (rotating, last N sessions)
│   └── _agent/memory/episodic/*.md (auto-purged after 30 days)
├── Semantic (permanent knowledge)
│   ├── _agent/memory/semantic/*.md
│   └── graphify/*.md
└── Episodic (permanent record)
    └── _agent/memory/episodic/*.md (archived, never deleted)
```

For multi-agent scenarios, add file-locking or atomic writes to prevent race conditions [^159^]. For concurrent read/write, use Obsidian's Local REST API plugin [^208^] or implement simple lockfiles.

### Refresh Critical Rules

Model adherence degrades over long contexts. Restate these rules at strategic points:
- Before materialize phase: "One node = one file. One concept = one note."
- Before link phase: "Use [[wikilinks]], not folders, for organization."
- Before /resume: "Load working memory first, then semantic, then episodic."
- Before /save: "Write to episodic log, update working memory, confirm to user."
