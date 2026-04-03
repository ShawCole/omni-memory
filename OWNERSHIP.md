# Memory System Ownership Rules

Two memory systems exist. They serve different consumers and must NOT duplicate each other.

## Auto-Memory (`~/.claude/projects/.../memory/`)
**Owner:** Claude Code sessions (direct interaction with Shaw)
**Consumer:** Every Claude Code session reads MEMORY.md on startup
**What belongs here:**
- Shaw's identity, preferences, working style (user type)
- Correction rules: "don't do X" / "always do Y" (feedback type)
- Project overview state: what exists, where it lives, what's the stack (project type)
- Pointers to external systems: Linear, Obsidian, Grafana (reference type)

**What does NOT belong here:**
- Live agent state, handoffs, or task queues (that's omni-context)
- Granular facts that change daily (that's facts_db.json)
- Session logs or conversation content (that's episodic memory)

## Omni-Context (`~/scripts/omni-context/`)
**Owner:** Agent orchestra (GM, PMs, specialists, workers)
**Consumer:** Every orchestrated agent reads context_layer + handoff on spawn
**What belongs here:**
- 3 cognitive surfaces: top_of_mind, work_context, personal_context
- Per-project facts_db.json with scored, expirable facts
- Per-project handoff.md with last session state
- Per-project ROADMAP.md with authoritative status
- Cross-project relationships
- Event bus activity

**What does NOT belong here:**
- Correction rules for Claude Code behavior (that's auto-memory feedback)
- Project architecture overviews (that's auto-memory project type)
- Person profiles (that's auto-memory reference type)

## Episodic Memory (Superpowers Plugin)
**Owner:** Conversation archive system
**Consumer:** Any session that needs to recall past conversations
**What belongs here:** Automatically — every conversation is archived
**When to query:** "What did we discuss?", "What approach did we try?", "What was decided?"

## Obsidian Vault (`~/ALL_CONTEXT/`)
**Owner:** Shaw (manual knowledge base)
**Consumer:** Agents via MCP or Syncthing
**What belongs here:** Research, competitive analysis, meeting notes, upgrade specs, client docs
**When to query:** "Check the notes on X", "What's in Obsidian about Y"

## Sync Rules

1. **Feedback → Facts:** When auto-memory writes a feedback rule, the sync hook should create a corresponding fact in the relevant project's facts_db.json (category: "procedural", confidence: 0.95+)
2. **Facts → Auto-memory:** When omni-context learns a durable infrastructure or partner fact, check if auto-memory has a stale version and update it
3. **Neither system should store the same fact in the same format.** Auto-memory stores the human-readable rule with context. Omni-context stores the machine-parseable one-liner.
