# The 5-Layer 3-Phase Memory System

> A comprehensive reference for OrchestraOS's distributed agent memory architecture,  
> inspired by ["Memory as Infrastructure"](https://www.notion.so/) and built for Shaw Cole's  
> multi-business, multi-agent operation at `~/scripts/omni-context/`.

---

## Table of Contents

1. [Overview](#overview)
2. [The 5 Layers](#the-5-layers)
   - [Layer 1: Context Layer](#layer-1-context-layer)
   - [Layer 2: History Layer](#layer-2-history-layer)
   - [Layer 3: Facts Database](#layer-3-facts-database)
   - [Layer 4: Memory Lifecycle Engine](#layer-4-memory-lifecycle-engine)
   - [Layer 5: Token Enforcer](#layer-5-token-enforcer)
3. [The 3 Phases](#the-3-phases)
   - [Phase 1: Extraction (Wake)](#phase-1-extraction-wake)
   - [Phase 2: Consolidation (Dream)](#phase-2-consolidation-dream)
   - [Phase 3: Retrieval (Recall)](#phase-3-retrieval-recall)
4. [Memory Types](#memory-types)
5. [Directory Structure](#directory-structure)
6. [Retention Scoring](#retention-scoring)
7. [Governance & Safety](#governance--safety)
8. [Agent Tier System](#agent-tier-system)
9. [Infrastructure](#infrastructure)
10. [CLI Reference](#cli-reference)

---

## Overview

The 5-Layer 3-Phase Memory System is the distributed memory architecture powering OrchestraOS — Shaw Cole's autonomous agent orchestration platform. It solves the fundamental problem of **context loss across AI agent sessions**: when a Claude Code session ends, everything it learned disappears.

This system ensures that:
- **Every agent picks up exactly where the last one left off** — no copy-pasting conversation histories
- **Memory is scoped** — a ListMagic specialist gets ListMagic facts, not DentalCancun details
- **Memory stays healthy** — stale facts decay, duplicates merge, PII is blocked, verbose memories compress
- **Token budgets are enforced** — the GM gets 4,000 tokens of context, a worker gets 500
- **Memory consolidation happens asynchronously** — like human sleep, not during active work

The system manages 20+ projects, 16+ agents (1 GM + 3 PMs + 12+ specialists), and operates across two machines (Mac + VPS) connected via Tailscale mesh.

### Core Analogy: The Human Memory Model

| Human | System | What It Does |
|-------|--------|--------------|
| Working memory | Context Layer | What's top-of-mind right now |
| Autobiography | History Layer | Chronological record of what happened |
| Long-term memory | Facts Database | Durable facts, preferences, infrastructure details |
| Sleep consolidation | Memory Lifecycle | Score, compress, forget, verify memories |
| Attention / focus | Token Enforcer | Decide what to load given limited capacity |

---

## The 5 Layers

### Layer 1: Context Layer

**File:** `~/scripts/omni-context/global/context_layer.json`  
**Purpose:** The "working memory" — what Shaw is doing right now, what's urgent, who he is.

```json
{
  "work_context": "Founder of ArkData, ListMagic.ai, and Sanctuary.Source...",
  "personal_context": "Based in Tulum, Mexico. Currently traveling in France...",
  "top_of_mind": "ListMagic GENERATE payload bug is #1 blocker. Itamar scheduling window is NOW...",
  "last_updated": "2026-03-29T05:30:00Z",
  "version": 1
}
```

**Key properties:**
- **Volatile** — updated frequently (by daemon extraction or manual override)
- **Global scope** — every agent reads this, regardless of tier
- **4 fields:** `work_context` (role/companies), `personal_context` (location/style), `top_of_mind` (urgent priorities), `last_updated`
- **`top_of_mind`** is the most dynamic field — the daemon updates it when new priorities emerge from session logs

**When it's used:** Every agent payload starts with the context layer. It answers "Who is Shaw and what does he care about right now?"

---

### Layer 2: History Layer

**File:** `~/scripts/omni-context/global/history_layer.md`  
**Purpose:** The "episodic autobiography" — a chronological ledger of what happened, organized into time epochs.

```markdown
# History Layer — Shaw Cole

## Recent Months (Feb-Mar 2026)

### Mar 22-29, 2026 — Europe Trip
- Flying to France for Tomorrowland Winter, then London, Berlin Apr 11
- Agent swarm failover system production-tested (2 successful failovers)
...

### Mar 12-21, 2026 — Client Blitz + Pre-Travel
- Amansala Soulful Singles campaign: 89 deliverables, 72 ad copy variations
- ListMagic Dev Platform deployed
...

## Earlier Context (Oct 2025 - Jan 2026)
...

## Long-Term Background (Pre-Oct 2025)
...
```

**Key properties:**
- **Append-only** — new events are prepended; old epochs compress over time
- **3 time epochs:** Recent Months (detailed), Earlier Context (summary), Long-Term Background (foundational)
- **Human-readable markdown** — agents and humans can both scan it
- **Truncation-aware** — the Token Enforcer only loads "Recent Months" for scoped agents, dropping older epochs first under budget pressure

**When it's used:** GM and PM agents reference it for temporal context — "when did we last touch Sanctuary?" or "what happened during the client blitz?"

---

### Layer 3: Facts Database

**Files:**
- `~/scripts/omni-context/global/facts_db.json` — cross-cutting facts
- `~/scripts/omni-context/projects/<project>/facts_db.json` — per-project facts

**Purpose:** The "long-term memory" — durable, structured, scored facts organized by project.

```json
{
  "version": 1,
  "max_facts": 200,
  "last_updated": "2026-03-29T05:30:00Z",
  "facts": [
    {
      "id": 1,
      "category": "infrastructure",
      "fact": "AudienceLab data access costs $0 via Rob's partner account",
      "confidence": 1.0,
      "source": "observed",
      "timestamp": "2026-03-29",
      "access_count": 5,
      "retention_score": {
        "durability": 0.9,
        "actionability": 0.95,
        "explicitness": 0.7,
        "recency": 0.85,
        "access_frequency": 0.5
      },
      "retention_composite": 0.868
    }
  ]
}
```

**Key properties:**
- **Hierarchical** — global facts (52+) + 20+ project-specific stores
- **Categorized** — `infrastructure`, `blocker`, `client`, `prospect`, `partner`, `team`, `product`, `pricing`, `competitive`, `technical`, `security`, `travel`, `billing`, `preference`
- **Scored** — every fact carries a 5-dimension `retention_score` and `retention_composite` (see [Retention Scoring](#retention-scoring))
- **Capacity-limited** — 200 facts max per store; overflow triggers the forgetting cycle
- **Access-tracked** — `access_count` increments each time a fact is loaded into a payload, feeding the access_frequency retention dimension

**Three memory subtypes within facts:**
| Type | What It Stores | Durability |
|------|---------------|------------|
| `semantic` | Infrastructure, credentials, technical specs, pricing | High |
| `episodic` | What happened in sessions, what worked/failed | Medium |
| `procedural` | Behavioral rules, user preferences, communication style | High |

---

### Layer 4: Memory Lifecycle Engine

**File:** `~/scripts/omni-context/memory_lifecycle.py`  
**Purpose:** The "sleep consolidation" — maintains memory health through 5 operations.

This is the most complex layer. It implements the full lifecycle that keeps the facts database healthy:

#### 4a. Retention Scoring

Every memory gets scored on 5 weighted dimensions (see [Retention Scoring](#retention-scoring) for details). The composite score determines whether a memory lives or dies.

#### 4b. Compression

Verbose memories (>40 estimated tokens) are compressed via Claude CLI:

```
Original: "Shaw mentioned during the March 3rd call with Rob that the AudienceLab 
           API has been having issues lately and ManyReach integration is currently 
           broken, which is affecting their workflow"

Compressed: "AudienceLab API unreliable; ManyReach integration broken (Rob call Mar 3)"
```

- Target: 80% reduction
- Preserves `_original_text` as backup
- Records `_compressed_at` timestamp
- Only compresses if result is <90% of original length

#### 4c. Intelligent Forgetting

Three rules for what to forget:

1. **Threshold** — Composite score below 0.4 = removed
2. **Duplicates** — Jaccard word similarity >0.7 between two facts = lower-scored one removed
3. **Capacity** — If store exceeds 200 facts after dedup, lowest-scored overflow is removed

#### 4d. Integrity Checking

Finds problems without fixing them:
- **Duplicate detection** — Jaccard similarity >0.7 across all memory types
- **Stale flagging** — No access in 60+ days
- **Missing metadata** — Facts without `confidence`, `retention_composite`, or `source`

#### 4e. Governance

Pre-storage validation (see [Governance & Safety](#governance--safety)):
- PII pattern blocking (SSN, credit cards, passwords, API keys, phone numbers)
- Low-confidence warnings (below 0.3)
- All operations logged to `logs/audit.jsonl`

---

### Layer 5: Token Enforcer

**File:** `~/scripts/omni-context/token_enforcer.py`  
**Purpose:** The "attention mechanism" — builds right-sized memory payloads for each agent tier.

The Token Enforcer is the final gatekeeper. It reads the agent registry, determines the agent's tier and project scope, then assembles a payload that fits within the token budget.

#### Tier Budgets

| Tier | Role | Token Budget | Payload Composition |
|------|------|-------------|---------------------|
| T0 | General Manager | 4,000 | Global context + all critical facts + recent history + additional context |
| T1 | Project Managers | 3,000 | Global summary + project-specific facts + handoffs |
| T2 | Specialists | 2,000 | Global summary + single project facts + handoff |
| T3 | Workers | 500 | Task description only |

#### Truncation Cascade

When a payload exceeds its budget, the enforcer drops content in priority order:

```
1. Drop lowest-confidence additional facts (< 0.95 confidence)
2. Truncate history (remove oldest lines, keep min 5)
3. Drop high-confidence facts (last resort, from lowest up)
```

For scoped payloads (T1/T2):
```
1. Truncate handoffs to 800 chars
2. Drop lowest-confidence facts across all included projects
```

#### Access Counting

Every time a fact survives truncation and makes it into a payload, its `access_count` is incremented. This feeds the `access_frequency` dimension of retention scoring — frequently-retrieved facts become harder to forget.

---

## The 3 Phases

The 3 phases describe the **temporal lifecycle** of memory — when and how memories flow through the 5 layers. They map to the human wake/dream/recall cycle.

### Phase 1: Extraction (Wake)

**When:** During or immediately after a Claude Code session  
**Driven by:** `memory_daemon.py` in watch mode  
**What happens:**

```
Session log appended to ~/ALL_CONTEXT/Claude Code Session Log.md
                              │
                    memory_daemon.py detects file change (30s debounce)
                              │
                    Reads new content since last cursor position
                              │
                    Sends to Claude CLI with extraction prompt
                              │
                    Claude extracts structured memories:
                    ├── new_memories[] (project, type, text, confidence)
                    ├── updates[] (id, new_text, reason)
                    ├── removals[] (id, reason)
                    └── context_update (top_of_mind)
                              │
                    Governance check on each new memory (PII blocking)
                              │
                    Retention scoring on each new memory
                              │
                    Route to correct project store (global or project-specific)
                              │
                    Atomic write (tmp → rename) to facts_db.json
                              │
                    Audit log entry for every operation
```

**Key details:**
- The daemon watches `~/ALL_CONTEXT/Claude Code Session Log.md` for changes
- Uses a file cursor (`.daemon_cursor`) to only process new content since last extraction
- Max 12,000 chars per extraction batch
- Extraction prompt provides current `context_layer.json` and top 30 existing facts for dedup context
- Project routing uses the project list from `~/scripts/omni-context/projects/`
- **Security:** Extraction prompt explicitly instructs Claude to NOT extract passwords, API keys, SSNs, or credit card numbers
- Source can be `explicit_statement`, `observed_interaction`, `feedback_pattern`, or `inferred` — each gets different explicitness scores

### Phase 2: Consolidation (Dream)

**When:** Every 30 minutes (background daemon) or on-demand via `omni consolidate`  
**Driven by:** `memory_daemon.py` in consolidation mode → `memory_lifecycle.py`  
**What happens:**

```
Consolidation timer fires (every 1800s)
            │
            ▼
    ┌───────────────────┐
    │ For each project: │
    └───────────────────┘
            │
    Step 1: SCORE ──────────── Recompute 5-dimension retention scores
            │                   for every memory. Recency decays over
            │                   time. Access frequency updates from
            │                   payload retrieval counts.
            │
    Step 2: INTEGRITY ──────── Scan for duplicates (Jaccard >0.7),
            │                   stale memories (60+ days no access),
            │                   missing metadata fields.
            │
    Step 3: FORGET ─────────── Remove below-threshold (composite <0.4),
            │                   deduplicate (keep higher-scored),
            │                   enforce capacity limits (200/store).
            │
    Step 4: COMPRESS ───────── LLM-powered compression of verbose
            │                   memories (>40 token estimate).
            │                   Preserves original as _original_text.
            │
            ▼
    Audit log: scored=N, forgotten=N, compressed=N
```

**Key details:**
- Runs across **all** projects + global in a single cycle
- Consolidation is the "subconscious" — it runs **between** conversations, not during them
- On VPS: runs as `memory-daemon.service` (systemd), always-on
- On Mac: runs via launchd plist (`com.shaw.memory-daemon`)
- Dry-run mode (`--dry-run`) available for testing without writes
- Results logged to `logs/daemon-YYYYMMDD.log`
- The lifecycle engine imports `memory_lifecycle.py` functions: `score_all_memories()`, `check_integrity()`, `run_forgetting_cycle()`, `compress_project_memories()`

### Phase 3: Retrieval (Recall)

**When:** At agent spawn time  
**Driven by:** `token_enforcer.py` (called by `spawn-agent.sh` or `omni payload`)  
**What happens:**

```
Agent spawned (e.g., listmagic-dev)
            │
    token_enforcer.py reads registry.json
            │
    Determines: tier=T2, memory_scope=["listmagic"], budget=2000
            │
    Loads layers:
    ├── context_layer.json (global top-of-mind)
    ├── projects/listmagic/facts_db.json (project facts, sorted by confidence)
    └── projects/listmagic/handoff.md (last session state)
            │
    Assembles payload, counting tokens (tiktoken cl100k_base)
            │
    If over budget → truncation cascade:
    │  1. Truncate handoffs to 800 chars
    │  2. Drop lowest-confidence facts
    │  3. Continue until within budget
            │
    Increment access_count for all included facts
            │
    Inject payload into agent's system prompt
            │
    Agent starts working with full, scoped context
```

**Key details:**
- Token counting uses `tiktoken` (cl100k_base encoding) when available, falls back to `len(text) // 4`
- Access count increment happens atomically after payload assembly
- The GM (T0) gets a **global payload**: full context + all critical facts + history + additional facts
- PMs (T1) get **scoped payloads**: compact global context + multi-project facts + handoffs
- Specialists (T2) get **narrowly scoped payloads**: top-of-mind + single project facts + handoff
- Workers (T3) get **minimal payloads**: just the task description (500 tokens)

---

## Memory Types

The system categorizes memories into three fundamental types (following cognitive science):

| Type | Description | Examples | Typical Durability |
|------|-------------|----------|-------------------|
| **Semantic** | Durable facts, infrastructure, specs, credentials | "Cloud SQL at 34.75.40.169", "AudienceLab costs $0" | High (0.9) |
| **Episodic** | Session events, what happened, what worked/failed | "Failover tested successfully Mar 25-27", "GENERATE fails HTTP 500" | Medium (0.5-0.7) |
| **Procedural** | Behavioral rules, preferences, communication style | "Never hardcode deployment IDs", "Shane voice = ElevenLabs PVC" | High (0.9) |

The extraction prompt instructs Claude to classify each extracted memory into one of these types. The type influences how the memory is scored and how long it persists.

---

## Directory Structure

```
~/scripts/omni-context/
├── context_layer.json          # Layer 1: Global working memory (symlink to global/)
├── history_layer.md            # Layer 2: Global chronological ledger (symlink to global/)
├── facts_db.json               # Layer 3: Global facts (symlink to global/)
├── memory_lifecycle.py         # Layer 4: Retention, compression, forgetting, integrity, governance
├── memory_daemon.py            # Phase 1+2: Async extraction + consolidation daemon
├── token_enforcer.py           # Layer 5 / Phase 3: Scoped payload builder
├── omni                        # Unified CLI (bash)
├── sync-to-vps.sh              # Mac→VPS bidirectional sync (cron every 5 min)
│
├── global/                     # Global-scope data
│   ├── context_layer.json      # Layer 1
│   ├── history_layer.md        # Layer 2
│   └── facts_db.json           # Layer 3 (global, 52+ facts)
│
├── projects/                   # Per-project stores (20+ directories)
│   ├── listmagic/
│   │   ├── facts_db.json       # Layer 3 (project-scoped)
│   │   ├── handoff.md          # Last session state
│   │   ├── recent_events.jsonl # Event stream
│   │   └── ROADMAP.md          # Machine-parseable roadmap
│   ├── arkdata/
│   ├── sanctuary/
│   ├── amansala/
│   ├── dentalcancun/
│   ├── elysian/
│   ├── yura/
│   ├── agent-orchestra/
│   ├── dashboard/
│   ├── vps-ops/
│   ├── ... (20+ total)
│   └── intentcore/
│
├── agents/                     # Per-agent state (currently empty dirs, reserved)
│   ├── gm/
│   ├── pm-products/
│   ├── pm-clients/
│   └── pm-infra/
│
├── shared/
│   └── cross_project.json      # Project relationship graph (20+ edges)
│
├── templates/
│   └── ROADMAP.md              # Template for project roadmaps
│
├── logs/
│   ├── audit.jsonl             # Every memory operation (extract, update, remove, compress, forget)
│   └── daemon-YYYYMMDD.log     # Daily daemon logs
│
├── backups/                    # Manual backups
├── .daemon_cursor              # File cursor for incremental extraction
└── .daemon.pid                 # PID file for daemon process
```

---

## Retention Scoring

Every memory is scored on 5 weighted dimensions. The composite score determines the memory's fate.

### Dimensions

| Dimension | Weight | Range | How It's Calculated |
|-----------|--------|-------|---------------------|
| **Durability** | 0.30 | 0-1 | Defaults to 0.9. Drops to 0.2 if text contains ephemeral markers ("today", "right now", "this session", "currently", "for now", "temporarily"). Override to 1.0 if `metadata.durable=true`. |
| **Actionability** | 0.25 | 0-1 | Defaults to 0.3. Jumps to 0.7 with 1 action marker, 0.95 with 2+. Markers: "prefer", "always", "never", "must", "critical", "blocker", "deadline", "deployed", "password", "key", etc. |
| **Explicitness** | 0.20 | 0-1 | Based on source: `explicit_statement`=1.0, `feedback_pattern`=0.8, `observed`=0.7, `seed`=0.6, `inferred`=0.4. |
| **Recency** | 0.15 | 0.1-1 | Linear decay: `max(0.1, 1.0 - (age_days / 90))`. A 45-day-old memory scores 0.5. A 90+ day memory floors at 0.1. |
| **Access Frequency** | 0.10 | 0-1 | `min(1.0, access_count / 10)`. Saturates at 10 retrievals. Never-retrieved facts score 0. |

### Composite Formula

```
composite = (durability × 0.30) + (actionability × 0.25) + (explicitness × 0.20)
          + (recency × 0.15) + (access_frequency × 0.10)
```

### Thresholds

| Composite Score | Icon | Fate |
|----------------|------|------|
| >= 0.7 | `●` | Safe — high-value memory |
| 0.4 - 0.7 | `◐` | At risk — may be forgotten if capacity is tight |
| < 0.4 | `○` | Forgotten — removed in next forgetting cycle |

### Scoring Examples

| Memory | Dur | Act | Exp | Rec | Acc | Composite |
|--------|-----|-----|-----|-----|-----|-----------|
| "AudienceLab costs $0" (explicit, 30 days old, accessed 8x) | 0.9 | 0.7 | 1.0 | 0.67 | 0.8 | **0.825** |
| "Shaw currently in France" (ephemeral, explicit, 5 days old) | 0.2 | 0.3 | 1.0 | 0.94 | 0.1 | **0.486** |
| "Tried using sed but it failed" (inferred, 80 days old, never accessed) | 0.9 | 0.3 | 0.4 | 0.11 | 0.0 | **0.442** |
| "Today's meeting went well" (ephemeral, inferred, 91 days old) | 0.2 | 0.3 | 0.4 | 0.1 | 0.0 | **0.230** |

---

## Governance & Safety

### Blocked Patterns

The governance layer rejects any memory containing these patterns before storage:

| Pattern | Type | Regex |
|---------|------|-------|
| `###-##-####` | SSN | `\b\d{3}-\d{2}-\d{4}\b` |
| 16 consecutive digits | Credit card | `\b\d{16}\b` |
| `password: ...` | Password | `\bpassword\s*[:=]\s*\S+` |
| 40+ char base64 | API key/token | `\b[A-Za-z0-9+/]{40,}={0,2}\b` |
| 10-11 digit numbers | Phone number | `\b\d{10,11}\b` |
| `sk-...` | OpenAI key | `sk-[a-zA-Z0-9]{20,}` |
| `AIza...` | Google API key | `AIza[a-zA-Z0-9_-]{35}` |

### Audit Trail

Every memory operation is logged to `logs/audit.jsonl`:

```json
{
  "timestamp": "2026-03-29T15:38:37Z",
  "operation": "extract",
  "project": "listmagic",
  "key": "53",
  "result": "added"
}
```

Operations logged: `extract`, `update`, `remove`, `compress`, `forget`, `consolidate`, `blocked`.

---

## Agent Tier System

The memory system is designed around a 4-tier agent hierarchy:

```
                    ┌─────────┐
                    │   Shaw  │  (Human — full context)
                    └────┬────┘
                         │
                    ┌────┴────┐
                    │   GM    │  T0 — 4,000 tokens
                    │ (Jarvis)│  Global + all facts + history
                    └────┬────┘
                         │
            ┌────────────┼────────────┐
            │            │            │
       ┌────┴────┐  ┌────┴────┐  ┌────┴────┐
       │   PM    │  │   PM    │  │   PM    │  T1 — 3,000 tokens
       │Products │  │Clients  │  │ Infra   │  Global summary + multi-project
       └────┬────┘  └────┬────┘  └────┬────┘
            │            │            │
     ┌──────┼──────┐   ┌─┼─┐    ┌────┼────┐
     │      │      │   │ │ │    │    │    │
   [LM]  [Ark] [San] [Am][DC] [VPS][Dash][Bot]   T2 — 2,000 tokens
                                                   Global summary + 1 project
                                                   
                    (Ad-hoc workers)               T3 — 500 tokens
                                                   Task description only
```

Each agent is defined in `~/scripts/agent-orchestra/registry.json` with:
- `tier` — T0/T1/T2/T3
- `memory_scope` — which projects it can see (e.g., `["listmagic"]` or `"global"`)
- `owner_pm` — which PM manages it

The Token Enforcer reads this registry to build the right payload for each agent.

---

## Infrastructure

### Cross-Machine Operation

```
┌──────────────────────────────────┐     ┌──────────────────────────────────┐
│         Mac (100.124.151.94)     │     │       VPS (100.68.171.99)        │
│                                  │     │                                  │
│  ~/scripts/omni-context/         │────▶│  /home/shaw/scripts/omni-context/│
│    (primary authoring)           │sync │    (always-on daemon)            │
│                                  │every│                                  │
│  Claude Code sessions            │5min │  memory-daemon.service (systemd) │
│  Agents: PM-Products, PM-Clients │     │  Agents: GM, PM-Infra            │
│  launchd memory-daemon           │     │  Dashboard (Streamlit :8501)     │
│                                  │◀────│                                  │
│                                  │state│  Telegram bot (ShawOpsBot)       │
└──────────────────────────────────┘     └──────────────────────────────────┘
                            ▲
                            │ Tailscale mesh
                            ▼
                     ┌──────────────┐
                     │  Shaw's Phone│
                     │  Telegram    │
                     │  WhatsApp    │
                     └──────────────┘
```

### Sync Flow (`sync-to-vps.sh`, cron every 5 minutes)

| Direction | What |
|-----------|------|
| Mac → VPS | Memory stores, prompts, hooks, scripts, plugin configs |
| VPS → Mac | Agent state, queue contents, audit log |
| Bidirectional | Project facts_db.json, handoff.md |

### Handoff Auto-Generation

A Claude Code hook (`write-handoff.sh`) fires on session end:
1. Detects which project the session was working on (from CWD)
2. Writes a structured `handoff.md` to `projects/<project>/handoff.md`
3. Includes: what was being done, where it stopped, key findings, files modified, git state, next step, blockers

---

## CLI Reference

The `omni` CLI (`~/scripts/omni-context/omni`) provides unified access:

### Memory Operations

| Command | Description |
|---------|-------------|
| `omni status` | Show daemon status + agent orchestra status |
| `omni context` | Print current context layer |
| `omni facts` | Show global facts |
| `omni facts <project>` | Show project-specific facts |
| `omni history` | Show history layer |
| `omni handoffs` | List all handoff files |
| `omni handoff <project>` | Show specific project handoff |

### Payload & Token Management

| Command | Description |
|---------|-------------|
| `omni payload` | Print global payload (2,000 tokens) |
| `omni payload <agent-id>` | Print scoped payload for a specific agent |
| `omni payload json` | Print payload as JSON with token metadata |
| `omni stats` | Show all project statistics |
| `omni stats <agent-id>` | Show token stats for a specific agent |

### Lifecycle Operations

| Command | Description |
|---------|-------------|
| `omni extract` | Run a single extraction cycle |
| `omni consolidate <project>` | Run full lifecycle (score→integrity→forget→compress) |
| `omni consolidate --all` | Consolidate all projects |
| `omni score <project>` | Score all memories in a project |
| `omni forget <project>` | Run forgetting cycle |
| `omni integrity <project>` | Check for duplicates, stale, missing metadata |
| `omni governance <text>` | Check text for PII patterns |
| `omni audit` | Show recent audit log |

### Agent Operations

| Command | Description |
|---------|-------------|
| `omni agents` | Show agent registry + status |
| `omni spawn <agent-id>` | Spawn an agent in tmux |
| `omni kill <agent-id>` | Kill an agent |
| `omni send <to> <msg>` | Queue a task for an agent |
| `omni dispatch` | Run a single dispatcher scan |

### Daemon Control

| Command | Description |
|---------|-------------|
| `omni start` | Start daemon via launchd |
| `omni stop` | Stop daemon |
| `omni restart` | Restart daemon |
| `omni logs` | Tail daemon logs |
| `omni backup` | Manual backup of all layers |

---

## How It All Fits Together

```
                        THE FULL CYCLE
                        
    ┌─────────────────────────────────────────────────┐
    │                                                 │
    │   PHASE 1: EXTRACTION                           │
    │   ┌──────────────────────────┐                  │
    │   │ Claude Code session ends │                  │
    │   │ Session log updated      │                  │
    │   │ Daemon detects change    │                  │
    │   │ Claude CLI extracts      │──┐               │
    │   │ memories                 │  │               │
    │   └──────────────────────────┘  │               │
    │                                 ▼               │
    │                        ┌────────────────┐       │
    │                        │   5 LAYERS     │       │
    │                        │                │       │
    │   ┌────────────────────┤ L1: Context    │       │
    │   │                    │ L2: History    │       │
    │   │   PHASE 2:         │ L3: Facts DB   │       │
    │   │   CONSOLIDATION    │ L4: Lifecycle  │       │
    │   │                    │ L5: Enforcer   │       │
    │   │   Score → Integrity│                │       │
    │   │   → Forget →       ├────────────────┘       │
    │   │   Compress         │                        │
    │   │   (every 30 min)   │                        │
    │   └────────────────────┘                        │
    │                                 │               │
    │                                 ▼               │
    │   PHASE 3: RETRIEVAL                            │
    │   ┌──────────────────────────┐                  │
    │   │ Agent spawned            │                  │
    │   │ Token Enforcer loads     │                  │
    │   │ scoped payload           │                  │
    │   │ Agent works with full    │                  │
    │   │ context                  │──────────────────┘
    │   └──────────────────────────┘     (back to Phase 1
    │                                     when session ends)
    └─────────────────────────────────────────────────┘
```

The cycle is continuous: sessions generate logs → extraction captures memories → consolidation maintains quality → retrieval delivers scoped context → new sessions generate new logs. Memory quality improves over time as frequently-accessed facts gain retention score and stale/duplicate facts are pruned.

---

## Design Principles

1. **Memory is infrastructure, not a feature** — It runs as background services, not inline during conversations
2. **Scope beats volume** — A specialist with 20 relevant facts outperforms a generalist with 200 generic ones
3. **Forgetting is a feature** — Actively removing low-value memories keeps signal-to-noise high
4. **Atomic writes everywhere** — All file updates use tmp→rename to prevent corruption
5. **Audit everything** — Every extract, update, remove, compress, and forget is logged
6. **Human-readable formats** — JSON + Markdown, not binary stores. Any agent or human can inspect the state
7. **Graceful degradation** — No tiktoken? Fall back to char/4. No Claude CLI? Skip compression. Daemon down? System still works, just without auto-consolidation
8. **The human is always in the loop** — Shaw can `omni facts`, `omni integrity`, `omni forget` at any time. The system is transparent by default.
