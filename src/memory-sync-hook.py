#!/usr/bin/env python3
"""
Memory Sync Hook — Bridges auto-memory and omni-context.

When a feedback file is written/updated in auto-memory, this creates
a corresponding procedural fact in the relevant omni-context facts_db.

When a project file is written/updated in auto-memory, this updates
the project handoff or facts in omni-context.

Usage:
    python3 memory-sync-hook.py                    # Sync all feedback → facts
    python3 memory-sync-hook.py --file <path>      # Sync a specific file
    python3 memory-sync-hook.py --dry-run           # Preview without writing
"""

import json
import argparse
from pathlib import Path
from datetime import datetime, timezone

MEMORY_DIR = Path.home() / ".claude/projects/-Users-ShawCole/memory"
OMNI_DIR = Path(__file__).parent
GLOBAL_FACTS = OMNI_DIR / "global" / "facts_db.json"


def extract_frontmatter(filepath: Path) -> dict | None:
    text = filepath.read_text(errors="replace")
    if not text.startswith("---"):
        return None
    end = text.find("---", 3)
    if end == -1:
        return None
    block = text[3:end].strip()
    result = {}
    for line in block.split("\n"):
        if ":" in line:
            key, val = line.split(":", 1)
            result[key.strip()] = val.strip()
    return result


def load_facts(path: Path) -> dict:
    if path.exists():
        return json.loads(path.read_text())
    return {"version": 1, "max_facts": 150, "project": "global", "facts": []}


def save_facts(path: Path, data: dict):
    data["last_updated"] = datetime.now(timezone.utc).isoformat()
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    tmp.rename(path)


def fact_exists(facts: list, text: str) -> bool:
    """Check if a similar fact already exists (simple substring match)."""
    text_lower = text.lower()
    for f in facts:
        existing = f.get("fact", f.get("text", "")).lower()
        # If >60% of words overlap, consider it a duplicate
        words_new = set(text_lower.split())
        words_old = set(existing.split())
        if len(words_new & words_old) / max(len(words_new | words_old), 1) > 0.6:
            return True
    return False


def sync_feedback_to_facts(filepath: Path, dry_run: bool = False) -> str | None:
    """Convert a feedback memory file into an omni-context fact."""
    fm = extract_frontmatter(filepath)
    if not fm or fm.get("type") != "feedback":
        return None

    name = fm.get("name", filepath.stem)
    desc = fm.get("description", "")

    # Use description as the fact text (it's the one-liner)
    fact_text = desc if desc else name

    data = load_facts(GLOBAL_FACTS)
    facts = data.get("facts", [])

    if fact_exists(facts, fact_text):
        return f"  SKIP (duplicate): {fact_text[:60]}"

    max_id = max((f.get("id", 0) for f in facts), default=0)
    new_fact = {
        "id": max_id + 1,
        "category": "procedural",
        "fact": fact_text,
        "confidence": 0.95,
        "source": "auto-memory-sync",
        "timestamp": datetime.now().strftime("%Y-%m-%d"),
        "access_count": 0,
    }

    if dry_run:
        return f"  WOULD ADD: [{new_fact['id']}] {fact_text[:60]}"

    facts.append(new_fact)
    data["facts"] = facts
    save_facts(GLOBAL_FACTS, data)
    return f"  ADDED: [{new_fact['id']}] {fact_text[:60]}"


def sync_all(dry_run: bool = False):
    """Sync all feedback files to omni-context."""
    print(f"Syncing auto-memory feedback → omni-context facts_db")
    print(f"  Source: {MEMORY_DIR}")
    print(f"  Target: {GLOBAL_FACTS}")
    print()

    synced = 0
    skipped = 0
    for f in sorted(MEMORY_DIR.glob("*.md")):
        if f.name == "MEMORY.md":
            continue
        result = sync_feedback_to_facts(f, dry_run)
        if result:
            print(result)
            if "ADDED" in result or "WOULD ADD" in result:
                synced += 1
            else:
                skipped += 1

    print(f"\n--- {synced} synced, {skipped} skipped ---")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", type=str, help="Sync a specific file")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.file:
        result = sync_feedback_to_facts(Path(args.file), args.dry_run)
        if result:
            print(result)
        else:
            print("Not a feedback file or no frontmatter")
    else:
        sync_all(args.dry_run)


if __name__ == "__main__":
    main()
