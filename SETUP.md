# Setup Guide

Get the omni-memory system running in under 10 minutes.

## Prerequisites

- Python 3.10+
- Claude Code CLI (`claude`) installed and authenticated
- (Optional) `tiktoken` for accurate token counting: `pip install tiktoken`

## Quick Start

### 1. Create the directory structure

```bash
./scripts/scaffold.sh
```

Or manually:

```bash
mkdir -p ~/scripts/omni-context/{global,projects,shared,logs}
```

### 2. Seed the context layer

Copy and customize the example:

```bash
cp examples/context_layer.json ~/scripts/omni-context/global/context_layer.json
```

Edit the 3 surfaces to match your situation:
- `work_context` — who you are, what you run
- `personal_context` — location, timezone, working style
- `top_of_mind` — current blockers, deadlines, urgent priorities

### 3. Create project directories

For each project you want agents to remember:

```bash
mkdir -p ~/scripts/omni-context/projects/my-project
cp examples/facts_db.json ~/scripts/omni-context/projects/my-project/facts_db.json
```

Clear the example facts and add your own.

### 4. Install the Claude Code skill

Copy the skill into your Claude Code plugins:

```bash
# If using Superpowers
cp skill/SKILL.md ~/.claude/skills/omni-memory.md

# Or add to your project's .claude/ directory
cp skill/SKILL.md /path/to/your/project/.claude/skills/omni-memory.md
```

### 5. (Optional) Start the memory daemon

The daemon watches session logs and auto-extracts facts:

```bash
# Run once (single extraction + consolidation cycle)
python3 src/memory_daemon.py --once

# Run as background daemon (30-min consolidation cycles)
python3 src/memory_daemon.py &

# Check status
python3 src/memory_daemon.py --status
```

### 6. (Optional) Set up cross-machine sync

If you run agents on multiple machines (Mac + VPS):

```bash
# Install Syncthing on both machines
# Share ~/scripts/omni-context/ as a Syncthing folder
# Both machines will stay in sync automatically
```

## Directory Structure

After setup, your directory looks like:

```
~/scripts/omni-context/
├── global/
│   ├── context_layer.json      ← 3 cognitive surfaces
│   ├── facts_db.json           ← cross-cutting facts
│   └── history_layer.md        ← chronological ledger
├── projects/
│   ├── my-project/
│   │   ├── facts_db.json       ← project-scoped facts
│   │   ├── handoff.md          ← last session state
│   │   └── ROADMAP.md          ← project status (optional)
│   └── another-project/
│       ├── facts_db.json
│       └── handoff.md
├── shared/
│   └── cross_project.json      ← project relationship graph
├── logs/
│   └── audit.jsonl             ← all memory operations
└── src/                        ← (symlinked from this repo)
    ├── memory_daemon.py
    ├── memory_lifecycle.py
    └── token_enforcer.py
```

## Verifying It Works

### Test retention scoring

```bash
python3 src/memory_lifecycle.py score global
```

You should see each fact scored on 5 dimensions with a composite score.

### Test token enforcement

```bash
python3 src/token_enforcer.py --stats
```

Shows global fact count, project counts, and tier budgets.

### Test a scoped payload

```bash
python3 src/token_enforcer.py --scope my-project --tokens 2000
```

Generates a token-budgeted payload for a project agent.

## Agent Tier Reference

| Tier | Budget | Role | What Gets Loaded |
|------|--------|------|-----------------|
| T0 | 4,000 tokens | General Manager | Global + all critical facts + history |
| T1 | 3,000 tokens | Project Managers | Global summary + multi-project facts |
| T2 | 2,000 tokens | Specialists | Top-of-mind + single project facts |
| T3 | 500 tokens | Workers | Task description only |

## Lifecycle Commands

```bash
# Score all memories in a project
python3 src/memory_lifecycle.py score my-project

# Compress verbose memories (requires Claude CLI)
python3 src/memory_lifecycle.py compress my-project

# Run forgetting cycle (removes below-threshold + duplicates)
python3 src/memory_lifecycle.py forget my-project

# Check integrity (find dupes, stale entries, missing metadata)
python3 src/memory_lifecycle.py integrity my-project

# Full lifecycle: score → integrity → forget → compress
python3 src/memory_lifecycle.py consolidate my-project

# All projects at once
python3 src/memory_lifecycle.py consolidate --all

# Check text for PII before storing
python3 src/memory_lifecycle.py governance-check "my API key is sk-abc123"
```
