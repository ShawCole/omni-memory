---
name: omni-memory
description: Use at session start and before session end — loads Shaw's 3 memory surfaces (top_of_mind, work_context, personal_context) from omni-context, guides fact writing during work, and writes handoffs on completion. Triggers when working on any project, spawning agents, or when context about Shaw's businesses/priorities/location matters.
allowed-tools: [Read, Write, Edit, Bash, Grep, Glob]
---

# Omni-Memory: 5-Phase 3-Surface Agent Memory

You have a persistent memory system at `~/scripts/omni-context/`. It survives across sessions. Every session you run is a link in a chain — read what the last agent left, do your work, leave context for the next one.

This system implements the "Memory as Infrastructure" pattern (from LangGraph/LangMem research) through 5 phases of memory management, surfaced to you through 3 cognitive surfaces.

---

## The 5 Phases of Memory

These phases are how memory WORKS — the engine underneath. You interact with them through the 3 surfaces and the session lifecycle below, but understanding the phases helps you write better memories and make better decisions about what to remember.

### Phase 1: Memory vs Storage

**Storage is passive. Memory is active curation.**

You are NOT just appending to a log. Every fact you write will be scored, compressed, potentially forgotten, and governed. This means:
- Write facts that are **durable** (still true next week), **actionable** (changes behavior), and **explicit** (stated clearly, not inferred)
- Don't store ephemeral chatter, redundant observations, or speculative inferences
- The system actively curates — it will forget your low-value facts and compress your verbose ones

### Phase 2: Short-Term Memory (Context Window)

**Your live working context — what you can see right now.**

This is what gets loaded at session start. It's finite and scoped by agent tier:

| Tier | Budget | What's Loaded |
|------|--------|---------------|
| T0 (GM) | 4,000 tokens | Global context + all critical facts + history |
| T1 (PMs) | 3,000 tokens | Global summary + multi-project facts + handoffs |
| T2 (Specialists) | 2,000 tokens | Top-of-mind + single project facts + handoff |
| T3 (Workers) | 500 tokens | Task description only |

When spawned via the orchestra, `token_enforcer.py` builds your payload. Lowest-confidence facts drop first. Facts that survive get their `access_count` incremented — making them harder to forget next cycle.

For direct Claude Code sessions (like this one): **you load your own context** by reading the files in the session lifecycle below.

### Phase 3: Long-Term Memory (3 Types)

**Durable knowledge that persists across sessions, stored in `facts_db.json` per project.**

Three memory types (mirrors cognitive science):

| Type | What It Stores | Examples | Durability |
|------|---------------|---------|------------|
| **Semantic** | Facts, infrastructure, specs, credentials | "Cloud SQL at 34.75.40.169", "AudienceLab costs $0" | High |
| **Episodic** | What happened in sessions, what worked/failed | "Failover tested Mar 25-27", "GENERATE returns HTTP 500" | Medium |
| **Procedural** | Behavioral rules, preferences, communication style | "Never hardcode deployment IDs", "Use Plaid not Stripe for ArkData" | High |

**Where they live:**
- `~/scripts/omni-context/global/facts_db.json` — cross-cutting facts (52+)
- `~/scripts/omni-context/projects/<project>/facts_db.json` — project-scoped (20+ stores)
- `~/scripts/omni-context/projects/<project>/handoff.md` — last session state (episodic)
- `~/scripts/omni-context/global/history_layer.md` — chronological ledger (episodic)

### Phase 4: The Memory Lifecycle

**Four operations maintain memory health automatically. You don't run these — the daemon does.**

1. **Retention Scoring** — Every fact scored on 5 weighted dimensions:
   ```
   Durability     × 0.30  — Will this still be true next week?
   Actionability  × 0.25  — Does it change agent behavior?
   Explicitness   × 0.20  — Was it stated clearly?
   Recency        × 0.15  — Linear decay over 90 days
   Access Freq    × 0.10  — How often retrieved? Saturates at 10
   ```
   Composite below 0.4 = forgotten. Above 0.7 = safe.

2. **Compression** — LLM-powered reduction (80% target). Verbose facts get compressed to one sentence. Originals preserved as `_original_text`.

3. **Intelligent Forgetting** — Three rules: below-threshold removal, duplicate detection (Jaccard >0.7), capacity enforcement (200 facts/store max).

4. **Integrity Checking** — Duplicate detection, stale flagging (60+ days no access), missing metadata alerts.

**Your job:** Write good facts (durable, actionable, explicit). The lifecycle keeps them healthy.

### Phase 5: Memory as Infrastructure

**Governance, multi-tenancy, and operational reliability.**

- **Governance:** PII patterns blocked before storage (SSN, credit cards, API keys, passwords, phone numbers). All operations audit-logged to `logs/audit.jsonl`.
- **Multi-tenancy:** 20+ project namespaces with isolated fact stores. Cross-project relationships mapped in `shared/cross_project.json`.
- **Async Consolidation:** `memory_daemon.py` runs every 30 min — extracts memories from session logs, runs the full lifecycle across all stores.
- **Cross-machine sync:** Mac ↔ VPS via `sync-to-vps.sh` every 5 minutes. Bidirectional for facts/handoffs.
- **Context freshness:** `context-sync.sh` runs daily at 3am — synthesizes all activity into context_layer.json. GM also updates in real-time when priorities shift.

---

## The 3 Surfaces

The 5 phases power the engine. The **3 surfaces** are how you interact with it. They live in `~/scripts/omni-context/global/context_layer.json`:

```json
{
  "top_of_mind": "...",
  "work_context": "...",
  "personal_context": "...",
  "last_updated": "ISO-8601",
  "version": N
}
```

### 1. Top of Mind (volatile — update often)

**What's urgent.** Blockers, deadlines, active deals, things that need attention NOW.

- Read this FIRST every session — it tells you what matters today
- Update it when priorities shift: a blocker clears, a deadline passes, a new urgency appears
- This is the field agents change most. If you fix a blocker, remove it. If you discover one, add it.
- Keep it to 2-4 sentences. Not a log — a living priority stack.

### 2. Work Context (stable — update on business changes)

**Who Shaw is and what he runs.** Companies, partnerships, revenue model, data engine.

- Read this to understand the landscape before making suggestions
- Only update when something structural changes: new company, new partner, pricing shift, role change
- This rarely changes within a single session

### 3. Personal Context (semi-stable — update on state changes)

**Where Shaw is, how he works, what tools he uses.** Location, travel, timezone, working style.

- Read this to calibrate your tone, timing, and assumptions
- Update when location changes, travel plans shift, or tooling changes
- Matters for: deadline calculations, meeting scheduling, deployment timing

---

## Session Lifecycle

### On Start: READ

```
1. Read ~/scripts/omni-context/global/context_layer.json     ← the 3 surfaces
2. Detect your project scope from CWD (see Project Detection)
3. Read ~/scripts/omni-context/projects/<project>/handoff.md  ← where last agent stopped
4. Read ~/scripts/omni-context/projects/<project>/facts_db.json ← what's known
```

The 3 surfaces tell you WHO and WHY. The handoff tells you WHERE. The facts tell you WHAT.

**If the handoff says "placeholder" or "auto-generated"** — the previous agent didn't write one. Check `git log --oneline -10` and `git status` to reconstruct state.

### During Work: WRITE FACTS (Phase 3 — Long-Term Memory)

When you learn something durable — write it:

```bash
python3 -c "
import json
from pathlib import Path
from datetime import datetime, timezone

store = Path.home() / 'scripts/omni-context/projects/<PROJECT>/facts_db.json'
data = json.loads(store.read_text()) if store.exists() else {'version': 1, 'max_facts': 200, 'facts': []}
facts = data['facts']
max_id = max((f.get('id', 0) for f in facts), default=0)

facts.append({
    'id': max_id + 1,
    'category': '<CATEGORY>',
    'fact': '<ONE SENTENCE FACT>',
    'confidence': 0.9,
    'source': 'observed',
    'timestamp': datetime.now().strftime('%Y-%m-%d'),
    'access_count': 0
})

data['facts'] = facts
data['last_updated'] = datetime.now(timezone.utc).isoformat()
store.write_text(json.dumps(data, indent=2))
"
```

**Categories:** `infrastructure`, `blocker`, `client`, `prospect`, `partner`, `team`, `product`, `pricing`, `competitive`, `technical`, `security`, `preference`

**Rules — think Phase 1 (Memory vs Storage):**
- One sentence per fact. Compress ruthlessly.
- Only write DURABLE, ACTIONABLE, EXPLICIT information. Skip ephemeral chatter.
- NEVER write passwords, API keys, SSNs, credit card numbers, or phone numbers (Phase 5 governance will block them anyway).
- Check if a similar fact already exists before adding a duplicate.
- Confidence: 0.95+ for explicit statements, 0.7-0.9 for observed patterns, 0.5-0.7 for inferences.
- Global facts → `global/facts_db.json`. Project facts → `projects/<project>/facts_db.json`.

### During Work: UPDATE SURFACES

If you clear a blocker, close a deal, discover a new urgency, or shift priorities — update the surfaces:

```bash
python3 -c "
import json
from pathlib import Path
from datetime import datetime, timezone

ctx_file = Path.home() / 'scripts/omni-context/global/context_layer.json'
ctx = json.loads(ctx_file.read_text())
ctx['top_of_mind'] = 'NEW TOP OF MIND TEXT HERE'
ctx['last_updated'] = datetime.now(timezone.utc).isoformat()
ctx['version'] = ctx.get('version', 0) + 1
tmp = ctx_file.with_suffix('.tmp')
tmp.write_text(json.dumps(ctx, indent=2))
tmp.rename(ctx_file)
"
```

| Surface | Update when... | Don't update when... |
|---------|---------------|---------------------|
| top_of_mind | Blocker cleared, new urgency, deadline passed, deal closed | Routine task progress |
| work_context | New company, new partner, pricing change, role shift | Learning about existing structure |
| personal_context | Location change, travel, timezone shift, new tooling | Same location, same tools |

### Before End: WRITE HANDOFF (Phase 3 — Episodic Memory)

**This is mandatory. No exceptions.**

Write to `~/scripts/omni-context/projects/<project>/handoff.md`:

```markdown
# Handoff — <project>
**Session ended:** <ISO timestamp>
**Working directory:** <CWD>
**What I was doing:** <specific task, not vague>
**Where I stopped:** <file:line or specific step>
**Key finding this session:** <most important discovery>
**Files modified:** <list with brief description>
**Git state:** <branch, committed/uncommitted>
**Next step:** <the immediate next action someone should take>
**Blocked on:** <dependency or "nothing">
```

**Write the handoff BEFORE your final message.** The Stop hook writes a placeholder if you don't — but placeholders are useless. A good handoff saves the next agent 10 minutes of archaeology.

---

## Project Detection

Map your CWD to a project ID:

| CWD contains | Project |
|--------------|---------|
| `ListMagic_Dev` or `listmagic` | `listmagic` |
| `SimpleAudienceMobile` | `listmagic` |
| `ark-data` or `arkdata` | `arkdata` |
| `ark-data-web` | `arkdata-web` |
| `sanctuary_source` or `sanctuary` | `sanctuary` |
| `agent-orchestra` or `omni-context` | `agent-orchestra` |
| `VSL_Builder` | `vsl-builder` |
| `Gemini_PersonaCopy` | `personacopy` |
| `UglyAds` | `uglyads` |
| `salesmatch` | `listmagic` |
| Home dir (`~`) with no project | `global` — use global stores |

If you can't determine the project, ask. Don't guess.

---

## Cross-Project Awareness

`~/scripts/omni-context/shared/cross_project.json` maps relationships. Read when your work might affect another project:

- `listmagic` ↔ `arkdata` share Cloud SQL
- `intentcore` → `listmagic` (VacuumEngine generates audiences)
- `elysian` → `vsl-builder` (PVC voices power VSL audio)
- `agent-orchestra` → everything (infrastructure layer)
- `listmagic` → `uglyads` (audience → ad creative pipeline)

---

## Quick Reference

| Action | Command |
|--------|---------|
| Read context (3 surfaces) | `cat ~/scripts/omni-context/global/context_layer.json` |
| Read project handoff | `cat ~/scripts/omni-context/projects/<project>/handoff.md` |
| Read project facts | `cat ~/scripts/omni-context/projects/<project>/facts_db.json` |
| Read cross-project graph | `cat ~/scripts/omni-context/shared/cross_project.json` |
| Read history layer | `cat ~/scripts/omni-context/global/history_layer.md` |
| List all projects | `ls ~/scripts/omni-context/projects/` |
| Show memory stats | `~/scripts/omni-context/omni stats` |
| Run consolidation | `~/scripts/omni-context/omni consolidate --all` |
| Check daemon status | `~/scripts/omni-context/omni status` |
| Read project ROADMAP | `cat ~/scripts/omni-context/projects/<project>/ROADMAP.md` |

---

## Red Flags — STOP

| You're thinking... | Do this instead |
|--------------------|----------------|
| "I'll remember this for next time" | Write it to facts_db.json NOW (Phase 3) |
| "The handoff can wait" | Write it BEFORE your final message |
| "This is probably still true" | Read the file. Memory decays. Verify. (Phase 4 — recency) |
| "I don't need to read the handoff" | The last agent left you context. Read it. |
| "I'll update top_of_mind later" | If a priority shifted, update it NOW |
| "This fact isn't important enough" | If you'd want to know it next session, write it |
| "I don't know which project this is" | ASK. Don't write to the wrong store. (Phase 5 — tenancy) |
| "I'll just store everything" | That's storage, not memory. Curate. (Phase 1) |
