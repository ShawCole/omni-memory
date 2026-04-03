#!/usr/bin/env python3
"""
Layer 5: Token Enforcer — Scoped Memory Loading

Builds memory payloads for agents based on their tier and project scope.
Drops lowest-confidence facts first to fit within token budget.

Usage:
    python3 token_enforcer.py                          # Global payload (2000 tokens)
    python3 token_enforcer.py --agent listmagic-dev    # Scoped payload for agent
    python3 token_enforcer.py --scope listmagic        # Payload for a project
    python3 token_enforcer.py --tokens 3000            # Custom token limit
    python3 token_enforcer.py --json                   # JSON output with metadata
    python3 token_enforcer.py --stats                  # Token statistics
"""

import json
import sys
import argparse
from pathlib import Path

# --- Configuration ---
OMNI_DIR = Path(__file__).parent
ORCHESTRA_DIR = OMNI_DIR.parent / "agent-orchestra"
REGISTRY_FILE = ORCHESTRA_DIR / "registry.json"

# Token budgets per tier
TIER_BUDGETS = {
    "T0": 4000,  # GM: global + shared + PM summaries
    "T1": 3000,  # PM: global summary + project-specific
    "T2": 2000,  # Specialist: global summary + single project
    "T3": 500,   # Worker: task description only
}

DEFAULT_TOKEN_LIMIT = 2000

# tiktoken-based counting
try:
    import tiktoken
    _encoder = tiktoken.get_encoding("cl100k_base")
    def count_tokens(text: str) -> int:
        return len(_encoder.encode(text))
except ImportError:
    def count_tokens(text: str) -> int:
        return len(text) // 4


# --- Loaders ---
def load_json(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text())
        except json.JSONDecodeError:
            return {}
    return {}


def load_text(path: Path) -> str:
    if path.exists():
        return path.read_text().strip()
    return ""


def load_registry() -> dict:
    return load_json(REGISTRY_FILE)


def get_agent_config(agent_id: str) -> dict | None:
    registry = load_registry()
    return registry.get("agents", {}).get(agent_id)


def load_global_context() -> dict:
    return load_json(OMNI_DIR / "global" / "context_layer.json")


def load_global_history() -> str:
    text = load_text(OMNI_DIR / "global" / "history_layer.md")
    # Only return Recent Months section
    sections = text.split("## Earlier Context")
    return sections[0].strip() if sections else text[:2000]


def load_facts(store_path: Path, min_confidence: float = 0.7) -> list[dict]:
    data = load_json(store_path)
    facts = data.get("facts", [])
    facts = [f for f in facts if f.get("confidence", 0) >= min_confidence]
    facts.sort(key=lambda f: f.get("confidence", 0), reverse=True)
    return facts


def load_handoff(project: str) -> str:
    path = OMNI_DIR / "projects" / project / "handoff.md"
    return load_text(path)


# --- Payload Builders ---
def build_global_payload(token_limit: int) -> str:
    """Build payload for global scope (GM or fallback)."""
    ctx = load_global_context()
    history = load_global_history()
    facts = load_facts(OMNI_DIR / "global" / "facts_db.json")

    context_block = (
        "## Active Context\n"
        f"**Work:** {ctx.get('work_context', '')}\n"
        f"**Personal:** {ctx.get('personal_context', '')}\n"
        f"**Top of Mind:** {ctx.get('top_of_mind', '')}\n"
    )

    high_facts = [f for f in facts if f["confidence"] >= 0.95]
    low_facts = [f for f in facts if f["confidence"] < 0.95]

    high_block = "## Critical Facts\n" + "".join(
        f"- [{f['category']}] {f['fact']}\n" for f in high_facts
    )
    history_block = "## Recent Activity\n" + history + "\n"
    low_block = "## Additional Context\n" + "".join(
        f"- [{f['category']}] {f['fact']}\n" for f in low_facts
    )

    return _truncate(context_block, high_block, history_block, low_block, high_facts, low_facts, token_limit)


def build_scoped_payload(projects: list[str], token_limit: int) -> str:
    """Build payload scoped to specific projects."""
    ctx = load_global_context()

    # Compact global context (less detail for scoped agents)
    global_block = (
        "## Global Context\n"
        f"**Top of Mind:** {ctx.get('top_of_mind', '')}\n"
    )

    # Per-project sections
    project_blocks = []
    all_facts = []

    for project in projects:
        if project == "global":
            continue

        facts_path = OMNI_DIR / "projects" / project / "facts_db.json"
        facts = load_facts(facts_path)
        handoff = load_handoff(project)

        block = f"\n## Project: {project}\n"
        if handoff:
            # Truncate handoff to first 500 chars if too long
            if len(handoff) > 800:
                handoff = handoff[:800] + "\n...(truncated)"
            block += f"### Last Session\n{handoff}\n"

        if facts:
            block += "### Facts\n" + "".join(
                f"- [{f['category']}] {f['fact']}\n" for f in facts
            )
            all_facts.extend(facts)

        project_blocks.append(block)

    payload = global_block + "".join(project_blocks)
    current_tokens = count_tokens(payload)

    if current_tokens <= token_limit:
        return payload

    # Truncate: drop lowest-confidence facts across all projects
    all_facts.sort(key=lambda f: f.get("confidence", 0))
    while current_tokens > token_limit and all_facts:
        drop = all_facts.pop(0)
        # Rebuild project blocks without the dropped fact
        project_blocks = []
        for project in projects:
            if project == "global":
                continue
            facts_path = OMNI_DIR / "projects" / project / "facts_db.json"
            facts = load_facts(facts_path)
            facts = [f for f in facts if f["id"] != drop["id"]]
            handoff = load_handoff(project)

            block = f"\n## Project: {project}\n"
            if handoff:
                h = handoff[:800] + "\n...(truncated)" if len(handoff) > 800 else handoff
                block += f"### Last Session\n{h}\n"
            if facts:
                block += "### Facts\n" + "".join(
                    f"- [{f['category']}] {f['fact']}\n" for f in facts
                )
            project_blocks.append(block)

        payload = global_block + "".join(project_blocks)
        current_tokens = count_tokens(payload)

    return payload


TIER_WEIGHTS = {"T0": 4, "T1": 3, "T2": 2, "T3": 1}


def increment_access(facts_file: Path, included_fact_ids: set, tier: str = "T2"):
    """Increment access_count for facts used in a payload, weighted by agent tier.

    Higher-tier agents (GM=T0, PM=T1) give more weight to the facts they access,
    making those facts harder to archive. A fact the GM reads regularly is inherently
    more important than one only a worker touched.
    """
    weight = TIER_WEIGHTS.get(tier, 1)
    try:
        data = json.loads(facts_file.read_text())
        changed = False
        for fact in data.get("facts", []):
            if fact.get("id") in included_fact_ids:
                fact["access_count"] = fact.get("access_count", 0) + weight
                changed = True
        if changed:
            facts_file.write_text(json.dumps(data, indent=2))
    except Exception:
        pass  # Don't crash on counter increment failure


def _collect_included_fact_ids(projects: list[str], min_confidence: float = 0.7) -> dict[Path, set]:
    """Collect fact IDs that would be included in a payload, grouped by file."""
    result = {}
    for project in projects:
        if project == "global":
            facts_path = OMNI_DIR / "global" / "facts_db.json"
        else:
            facts_path = OMNI_DIR / "projects" / project / "facts_db.json"
        facts = load_facts(facts_path, min_confidence)
        if facts:
            result[facts_path] = {f.get("id") for f in facts if f.get("id") is not None}
    return result


def build_agent_payload(agent_id: str) -> str:
    """Build payload for a specific agent from the registry."""
    config = get_agent_config(agent_id)
    if not config:
        print(f"Unknown agent: {agent_id}", file=sys.stderr)
        return build_global_payload(DEFAULT_TOKEN_LIMIT)

    tier = config.get("tier", "T2")
    token_limit = TIER_BUDGETS.get(tier, DEFAULT_TOKEN_LIMIT)
    memory_scope = config.get("memory_scope", "global")

    if memory_scope == "global" or (isinstance(memory_scope, list) and "global" in memory_scope and len(memory_scope) == 1):
        payload = build_global_payload(token_limit)
        # Increment access counts for global facts, weighted by tier
        global_facts_path = OMNI_DIR / "global" / "facts_db.json"
        facts = load_facts(global_facts_path)
        increment_access(global_facts_path, {f.get("id") for f in facts if f.get("id") is not None}, tier)
        return payload

    if isinstance(memory_scope, str):
        projects = [memory_scope]
    else:
        projects = memory_scope

    payload = build_scoped_payload(projects, token_limit)

    # Increment access counts for all included facts, weighted by tier
    fact_groups = _collect_included_fact_ids(projects)
    for facts_path, fact_ids in fact_groups.items():
        increment_access(facts_path, fact_ids, tier)

    return payload


# --- Truncation Helper ---
def _truncate(context_block, high_block, history_block, low_block, high_facts, low_facts, token_limit):
    payload = context_block + "\n" + high_block + "\n" + history_block + "\n" + low_block
    current_tokens = count_tokens(payload)

    if current_tokens <= token_limit:
        return payload

    # Drop low-confidence facts
    low_reversed = list(reversed(low_facts))
    while current_tokens > token_limit and low_reversed:
        low_reversed.pop(0)
        low_block = "## Additional Context\n" + "".join(
            f"- [{f['category']}] {f['fact']}\n" for f in low_reversed
        )
        payload = context_block + "\n" + high_block + "\n" + history_block + "\n" + low_block
        current_tokens = count_tokens(payload)

    if current_tokens <= token_limit:
        return payload

    # Truncate history
    history_lines = history_block.split("\n")
    while current_tokens > token_limit and len(history_lines) > 5:
        history_lines.pop()
        history_block = "\n".join(history_lines) + "\n"
        payload = context_block + "\n" + high_block + "\n" + history_block
        current_tokens = count_tokens(payload)

    if current_tokens <= token_limit:
        return payload

    # Drop high-confidence facts (last resort)
    hf = list(high_facts)
    while current_tokens > token_limit and hf:
        hf.pop()
        high_block = "## Critical Facts\n" + "".join(
            f"- [{f['category']}] {f['fact']}\n" for f in hf
        )
        payload = context_block + "\n" + high_block
        current_tokens = count_tokens(payload)

    return payload


# --- Stats ---
def get_stats(agent_id: str = None) -> dict:
    if agent_id:
        config = get_agent_config(agent_id)
        if config:
            tier = config.get("tier", "T2")
            budget = TIER_BUDGETS.get(tier, DEFAULT_TOKEN_LIMIT)
            payload = build_agent_payload(agent_id)
            tokens = count_tokens(payload)
            return {
                "agent": agent_id,
                "tier": tier,
                "budget": budget,
                "payload_tokens": tokens,
                "headroom": budget - tokens,
                "memory_scope": config.get("memory_scope", "global"),
            }

    # Global stats
    global_facts = load_facts(OMNI_DIR / "global" / "facts_db.json")
    project_dirs = list((OMNI_DIR / "projects").iterdir()) if (OMNI_DIR / "projects").exists() else []

    project_stats = {}
    for pd in sorted(project_dirs):
        if pd.is_dir():
            facts_path = pd / "facts_db.json"
            facts = load_facts(facts_path) if facts_path.exists() else []
            has_handoff = (pd / "handoff.md").exists()
            project_stats[pd.name] = {
                "facts": len(facts),
                "has_handoff": has_handoff,
            }

    return {
        "global_facts": len(global_facts),
        "projects": project_stats,
        "total_facts": len(global_facts) + sum(p["facts"] for p in project_stats.values()),
        "tier_budgets": TIER_BUDGETS,
    }


# --- CLI ---
def main():
    parser = argparse.ArgumentParser(description="Token Enforcer — scoped memory loading")
    parser.add_argument("--agent", type=str, help="Agent ID (loads from registry)")
    parser.add_argument("--scope", type=str, help="Project scope (comma-separated)")
    parser.add_argument("--tokens", type=int, default=None, help="Override token limit")
    parser.add_argument("--output", type=str, default=None, help="Output file path")
    parser.add_argument("--json", action="store_true", help="JSON output with metadata")
    parser.add_argument("--stats", action="store_true", help="Show statistics")
    args = parser.parse_args()

    if args.stats:
        stats = get_stats(args.agent)
        print(json.dumps(stats, indent=2))
        return

    # Build payload
    if args.agent:
        payload = build_agent_payload(args.agent)
        config = get_agent_config(args.agent)
        token_limit = args.tokens or TIER_BUDGETS.get(config.get("tier", "T2") if config else "T2", DEFAULT_TOKEN_LIMIT)
    elif args.scope:
        projects = [p.strip() for p in args.scope.split(",")]
        token_limit = args.tokens or DEFAULT_TOKEN_LIMIT
        payload = build_scoped_payload(projects, token_limit)
    else:
        token_limit = args.tokens or DEFAULT_TOKEN_LIMIT
        payload = build_global_payload(token_limit)

    token_count = count_tokens(payload)

    if args.json:
        result = {
            "payload": payload,
            "token_count": token_count,
            "token_limit": token_limit,
            "headroom": token_limit - token_count,
            "agent": args.agent,
            "scope": args.scope,
        }
        output = json.dumps(result, indent=2)
    else:
        output = payload

    if args.output:
        Path(args.output).write_text(output)
        print(f"Written to {args.output} ({token_count} tokens)")
    else:
        print(output)
        if not args.json:
            print(f"\n--- {token_count}/{token_limit} tokens ---", file=sys.stderr)


if __name__ == "__main__":
    main()
