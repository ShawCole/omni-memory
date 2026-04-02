# Omni-Memory: 5-Phase 3-Surface Agent Memory System

A production implementation of the ["Memory as Infrastructure"](https://patch-foe-06d.notion.site/Memory-as-Infrastructure-Building-Intelligent-State-Management-for-AI-Agents-with-LangGraph) pattern for autonomous AI agent orchestration. Built for [OrchestraOS](https://github.com/ShawCole) — a multi-agent system running 20+ projects across Mac + VPS via Tailscale mesh.

## The Problem

Every AI agent session forgets everything when it ends. Copy-pasting conversation histories doesn't scale. Vector embeddings retrieve by similarity, not relevance. Larger context windows shift cost without solving quality. Most "memory" is storage with a marketing label.

## The Solution

Real memory is a lifecycle: **score, compress, forget, govern.** This system implements the 5-phase memory architecture from LangGraph/LangMem research, surfaced through 3 cognitive surfaces that agents read and write to.

## The 5 Phases

| Phase | What It Does | Implementation |
|-------|-------------|----------------|
| **1. Memory vs Storage** | Active curation, not passive accumulation | Facts must be durable, actionable, explicit |
| **2. Short-Term Memory** | Token-budgeted context loading per agent tier | `token_enforcer.py` — T0=4K, T1=3K, T2=2K, T3=500 |
| **3. Long-Term Memory** | 3 types: semantic, episodic, procedural | `facts_db.json` per project + handoffs + history |
| **4. Memory Lifecycle** | Retention scoring, compression, forgetting, integrity | `memory_lifecycle.py` — 5-dim scoring, Jaccard dedup |
| **5. Infrastructure** | Governance, multi-tenancy, async consolidation | `memory_daemon.py` — PII blocking, audit logging, 30-min cycles |

## The 3 Surfaces

Every agent interacts with memory through 3 cognitive surfaces in `context_layer.json`:

| Surface | Volatility | What It Holds |
|---------|-----------|---------------|
| **top_of_mind** | High — update every session | Blockers, deadlines, active deals, urgent priorities |
| **work_context** | Low — update on structural changes | Identity, companies, partnerships, revenue model |
| **personal_context** | Medium — update on state changes | Location, travel, timezone, working style |

## Repo Structure

```
omni-memory/
├── README.md              # This file
├── ARTICLE.md             # Original "Memory as Infrastructure" Notion article (source material)
├── ARCHITECTURE.md        # Full 5-layer 3-phase technical architecture reference
├── skill/
│   └── SKILL.md           # Claude Code skill — embed into any agent session
└── src/
    ├── memory_lifecycle.py # Phase 4: retention scoring, compression, forgetting, integrity, governance
    ├── memory_daemon.py    # Phase 1+2+5: async extraction + consolidation daemon
    └── token_enforcer.py   # Phase 2: scoped payload builder with tier budgets
```

## How It Works

```
Session starts → Agent reads 3 surfaces + project handoff + facts
                          │
         Agent works, writes facts, updates top_of_mind
                          │
         Session ends → Agent writes handoff (mandatory)
                          │
              Stop hook auto-generates placeholder if agent didn't
                          │
         Daemon extracts memories from session logs (Phase 1)
                          │
         Every 30 min: score → integrity → forget → compress (Phase 4)
                          │
         Next agent spawns with scoped, token-budgeted payload (Phase 2)
```

## Retention Scoring (5 Dimensions)

```
Durability     × 0.30  — Will this still be true next week?
Actionability  × 0.25  — Does it change agent behavior?
Explicitness   × 0.20  — Was it stated clearly?
Recency        × 0.15  — Linear decay over 90 days
Access Freq    × 0.10  — How often retrieved? Saturates at 10
```

Composite below **0.4** = forgotten. Above **0.7** = safe.

## Agent Tier System

```
              Shaw (human)
                  │
            GM (T0 — 4,000 tokens)
            ┌─────┼─────┐
         PM-Prod PM-Cli PM-Infra  (T1 — 3,000 tokens)
         ┌──┼──┐  ┌─┼─┐  ┌──┼──┐
        [LM][Ark] [Am][DC] [VPS][Dash]  (T2 — 2,000 tokens)
              Workers  (T3 — 500 tokens)
```

## Origin

Built March 2026 during a single 3+ hour Claude Code session after analyzing the Notion article ["Memory as Infrastructure: Building Intelligent State Management for AI Agents with LangGraph"](https://patch-foe-06d.notion.site/Memory-as-Infrastructure-Building-Intelligent-State-Management-for-AI-Agents-with-LangGraph) (60,375 chars). The article provided the theoretical framework; this repo is the production implementation adapted for OrchestraOS's multi-agent, multi-machine architecture.

## Using the Skill

Copy `skill/SKILL.md` into your Claude Code plugin's `skills/` directory. It teaches any Claude agent to:

1. **Read** the 3 surfaces + project context on session start
2. **Write** durable facts during work (semantic/episodic/procedural)
3. **Update** surfaces when priorities shift
4. **Handoff** before session end (mandatory, structured format)

## License

MIT
