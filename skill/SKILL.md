---
name: omni-memory
description: Persistent agent memory — read context on start, write facts during work, handoff before end. Use when working on any project or when Shaw's context matters.
allowed-tools: [Read, Write, Edit, Bash, Grep, Glob]
---

# Agent Memory Protocol

You have persistent memory at `~/scripts/omni-context/`. Read it on start. Write to it during work. Hand off before you end.

## On Start: READ (do this immediately)

```bash
cat ~/scripts/omni-context/global/context_layer.json    # Who Shaw is, what's urgent
cat ~/scripts/omni-context/projects/<PROJECT>/handoff.md  # Where last agent stopped
cat ~/scripts/omni-context/projects/<PROJECT>/facts_db.json  # What's known
```

Detect project from CWD: `ListMagic_Dev|SimpleAudienceMobile` → listmagic, `ArkData` → arkdata, `sanctuary_source` → sanctuary, `agent-orchestra|omni-context` → agent-orchestra, `VSL_Builder` → vsl-builder, `Gemini_PersonaCopy` → personacopy, `UglyAds` → uglyads, home dir → global. If unsure, ask.

## During Work: WRITE FACTS

When you learn something durable, actionable, and explicit — write it:

```bash
python3 -c "
import json; from pathlib import Path; from datetime import datetime, timezone
store = Path.home() / 'scripts/omni-context/projects/<PROJECT>/facts_db.json'
data = json.loads(store.read_text()) if store.exists() else {'version':1,'max_facts':150,'facts':[]}
mx = max((f.get('id',0) for f in data['facts']), default=0)
data['facts'].append({'id':mx+1,'category':'<CAT>','fact':'<ONE SENTENCE>','confidence':0.9,'source':'observed','timestamp':datetime.now().strftime('%Y-%m-%d'),'access_count':0})
data['last_updated'] = datetime.now(timezone.utc).isoformat()
store.write_text(json.dumps(data, indent=2))
"
```

Categories: `infrastructure`, `blocker`, `client`, `partner`, `product`, `pricing`, `technical`, `preference`, `procedural`

Rules: One sentence per fact. Only durable info (true next week). Never store passwords/keys/PII. Check for duplicates first. Global facts → `global/facts_db.json`.

## During Work: UPDATE SURFACES

If priorities shift (blocker cleared, new urgency, location change):

```bash
python3 -c "
import json; from pathlib import Path; from datetime import datetime, timezone
f = Path.home() / 'scripts/omni-context/global/context_layer.json'
ctx = json.loads(f.read_text())
ctx['top_of_mind'] = 'NEW PRIORITIES HERE'
ctx['last_updated'] = datetime.now(timezone.utc).isoformat()
ctx['version'] = ctx.get('version',0) + 1
f.write_text(json.dumps(ctx, indent=2))
"
```

Only update `top_of_mind` (blockers/urgencies), `work_context` (structural business changes), or `personal_context` (location/timezone shifts).

## Before End: WRITE HANDOFF (mandatory)

```bash
cat > ~/scripts/omni-context/projects/<PROJECT>/handoff.md << 'HANDOFF'
# Handoff — <PROJECT>
**Session ended:** <ISO timestamp>
**Working directory:** <CWD>
**What I was doing:** <specific task>
**Where I stopped:** <file:line or step>
**Key finding:** <most important discovery>
**Files modified:** <list>
**Git state:** <branch, committed?>
**Next step:** <immediate next action>
**Blocked on:** <dependency or nothing>
HANDOFF
```

Write this BEFORE your final message. A good handoff saves the next agent 10 minutes.

## Memory Routing (for GM/orchestrated agents)

| Query type | Source |
|-----------|--------|
| "What did we discuss?" | Episodic memory (conversation archive) |
| "Check notes on X" | Obsidian (`~/ALL_CONTEXT/`) |
| "Status of X?" | `projects/<x>/handoff.md` + `facts_db.json` |
| "What's the rule about X?" | Auto-memory (`~/.claude/.../memory/` feedback files) |
| "What happened today?" | Event bus (`~/scripts/agent-orchestra/activity.jsonl`) |
