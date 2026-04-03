# Omni-Memory: Agent Memory That Actually Works

> **Live explainer:** [memoryos-vision.netlify.app](https://memoryos-vision.netlify.app)

A production memory system for autonomous AI agents. Not a toy. Runs 24/7 across 21 projects, 28 agents, 2 machines.

Built for [OrchestraOS](https://orchestraos-vision.netlify.app). Based on ["Memory as Infrastructure"](https://patch-foe-06d.notion.site/Memory-as-Infrastructure-Building-Intelligent-State-Management-for-AI-Agents-with-LangGraph) (LangGraph/LangMem research).

---

## What This Solves

Every AI session forgets everything when it ends. This system gives agents:
- **Continuity** — handoffs carry state between sessions
- **Knowledge** — durable facts survive across conversations
- **Hygiene** — stale facts decay, duplicates merge, PII is blocked
- **Scoping** — each agent gets only the facts it needs, within a token budget

## What's In This Package

```
omni-memory/
├── README.md                     # You are here
├── SETUP.md                      # 10-minute setup guide
├── OWNERSHIP.md                  # Which system owns what (avoids duplication)
├── ARCHITECTURE.md               # Full technical reference (33KB)
├── ARTICLE.md                    # Source theory: "Memory as Infrastructure"
│
├── skill/
│   └── SKILL.md                  # Claude Code skill (928 tokens — just the protocol)
│
├── src/
│   ├── memory_daemon.py          # Background extraction + 30-min consolidation
│   ├── memory_lifecycle.py       # Retention scoring, compression, forgetting, integrity
│   ├── token_enforcer.py         # Scoped payload builder with tier budgets
│   ├── memory-sync-hook.py       # Bridges auto-memory ↔ omni-context
│   └── generate-memory-index.py  # Auto-generates MEMORY.md from frontmatter
│
├── scripts/
│   ├── scaffold.sh               # One-command directory setup
│   └── write-handoff.sh          # Stop hook — captures git state on session end
│
├── examples/
│   ├── context_layer.json        # Example 3-surface context
│   ├── facts_db.json             # Example fact store
│   └── handoff.md                # Example session handoff
│
└── site/
    ├── index.html                # MemoryOS landing page (Netlify-ready)
    └── netlify.toml
```

---

## How It Works

```
Session starts → Agent reads 3 surfaces + handoff + facts (skill protocol)
                          │
         Agent works, writes durable facts, updates top_of_mind
                          │
         Session ends → Agent writes handoff (mandatory)
                          │
              Stop hook captures git state if agent didn't write one
                          │
         Daemon extracts memories from session logs (every 30 min)
                          │
         Lifecycle: score → integrity → forget → compress
                          │
         Sync hook bridges feedback rules ↔ fact stores
                          │
         Next agent spawns with scoped, token-budgeted payload
```

## The 3 Surfaces

Agents interact through `context_layer.json`:

| Surface | Volatility | What It Holds |
|---------|-----------|---------------|
| **top_of_mind** | High — update every session | Blockers, deadlines, urgent priorities |
| **work_context** | Low — update on structural changes | Identity, companies, partnerships |
| **personal_context** | Medium — update on state changes | Location, timezone, working style |

## Retention Scoring

Every fact is scored on 5 dimensions. Low-scoring facts are forgotten automatically.

```
Durability     × 0.25  — Will this still be true next week?
Actionability  × 0.20  — Does it change agent behavior?
Explicitness   × 0.15  — Was it stated clearly?
Recency        × 0.25  — Linear decay over 45 days
Access Freq    × 0.15  — How often retrieved? Saturates at 10
```

Composite below **0.5** = forgotten. Max **150 facts** per store.

## Memory Routing

Different queries go to different systems:

| Query | Route to |
|-------|----------|
| "What did we discuss about X?" | Episodic memory (conversation archive) |
| "Check notes on X" | Obsidian vault |
| "Status of X?" | omni-context handoff + facts |
| "What's the rule about X?" | Auto-memory feedback files |
| "What happened today?" | Event bus activity log |

## Ownership Rules

Two memory systems exist. They don't duplicate each other. See [OWNERSHIP.md](OWNERSHIP.md).

| System | Owner | Stores |
|--------|-------|--------|
| **Auto-memory** (`~/.claude/.../memory/`) | Claude Code sessions | Preferences, correction rules, project overviews, people |
| **Omni-context** (`~/scripts/omni-context/`) | Orchestra agents | Live state, facts, handoffs, roadmaps, surfaces |
| **Episodic** (Superpowers plugin) | Conversation archive | Past session recall |
| **Obsidian** (`~/ALL_CONTEXT/`) | Shaw (manual) | Research, competitive analysis, client docs |

## Agent Tier System

```
              Human
                │
          GM (T0 — 4,000 tokens)
          ┌─────┼─────┐
       PM-Prod PM-Cli PM-Infra  (T1 — 3,000 tokens)
       ┌──┼──┐  ┌─┼─┐  ┌──┼──┐
      [Proj] [Proj] [Proj] [Proj]  (T2 — 2,000 tokens)
            Workers  (T3 — 500 tokens)
```

---

## Quick Start

```bash
git clone https://github.com/ShawCole/omni-memory.git
cd omni-memory

# Scaffold directories
./scripts/scaffold.sh

# Edit your 3 surfaces
vi ~/scripts/omni-context/global/context_layer.json

# Install the skill (928 tokens — won't bloat your sessions)
cp skill/SKILL.md ~/.claude/skills/omni-memory.md

# Run consolidation
python3 src/memory_lifecycle.py consolidate --all

# Start the daemon
nohup python3 src/memory_daemon.py >> ~/scripts/omni-context/logs/daemon.log 2>&1 &

# Sync feedback rules → fact stores
python3 src/memory-sync-hook.py

# Auto-generate memory index
python3 src/generate-memory-index.py --write
```

See **[SETUP.md](SETUP.md)** for the full guide.

## Deployed

- **Vision page:** [memoryos-vision.netlify.app](https://memoryos-vision.netlify.app)
- **OrchestraOS:** [orchestraos-vision.netlify.app](https://orchestraos-vision.netlify.app)

## License

MIT
