#!/usr/bin/env python3
"""
Async Memory Consolidation Daemon ("Subconscious" Layer)

Runs as a background service. Two modes:
  1. WATCH MODE: Monitors Claude Code session logs for new content,
     extracts memories via claude CLI, routes to correct project stores.
  2. CONSOLIDATION MODE: Periodically runs the full lifecycle
     (score → integrity → forget → compress) across all project stores.

Both modes run concurrently. Watch triggers on file changes (30s debounce).
Consolidation runs every 30 minutes.

Usage:
    python3 memory_daemon.py                  # Run both modes
    python3 memory_daemon.py --watch-only     # Only watch for new content
    python3 memory_daemon.py --consolidate-only  # Only run lifecycle
    python3 memory_daemon.py --once           # Single extraction + consolidation, then exit
    python3 memory_daemon.py --dry-run        # No LLM calls, no writes
    python3 memory_daemon.py --status         # Show daemon status

Requires: watchdog, claude CLI (Max plan)
"""

import json
import os
import sys
import time
import logging
import argparse
import hashlib
import signal
import subprocess
from pathlib import Path
from datetime import datetime, timezone
from threading import Timer, Thread

# --- Config ---
OMNI_DIR = Path(__file__).parent
GLOBAL_DIR = OMNI_DIR / "global"
PROJECTS_DIR = OMNI_DIR / "projects"
LOG_DIR = OMNI_DIR / "logs"
CURSOR_FILE = OMNI_DIR / ".daemon_cursor"
PID_FILE = OMNI_DIR / ".daemon.pid"

DEFAULT_WATCH_PATH = Path.home() / "ALL_CONTEXT" / "Claude Code Session Log.md"
FALLBACK_WATCH_DIR = Path.home() / "ALL_CONTEXT"

DEBOUNCE_SECONDS = 30
MAX_CONTEXT_CHARS = 12000
CONSOLIDATION_INTERVAL = 1800  # 30 minutes

LOG_DIR.mkdir(parents=True, exist_ok=True)
log_file = LOG_DIR / f"daemon-{datetime.now().strftime('%Y%m%d')}.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(log_file),
    ],
)
log = logging.getLogger("memory_daemon")


# --- Extraction Prompt ---
EXTRACTION_PROMPT = """You are a memory extraction agent. Analyze the following conversation log
and extract STRUCTURED memories to update the agent memory system.

CURRENT GLOBAL CONTEXT:
{context}

EXISTING FACTS (top entries):
{existing_facts}

NEW CONVERSATION LOG:
{new_logs}

Extract memories and categorize each as:
- "semantic": durable facts, infrastructure details, credentials, technical specs
- "episodic": what happened in this session, what was learned, what worked/failed
- "procedural": behavioral rules, user preferences, communication style preferences

For each memory, also determine which PROJECT it belongs to:
{project_list}
Use "global" for cross-cutting facts.

Also identify if any existing facts should be UPDATED or REMOVED (contradicted, outdated).

Return ONLY valid JSON in this exact format:
{{
  "new_memories": [
    {{"project": "listmagic", "type": "semantic", "text": "...", "confidence": 0.9, "source": "observed"}},
    ...
  ],
  "updates": [
    {{"project": "global", "id": 5, "action": "update", "new_text": "...", "reason": "..."}},
    ...
  ],
  "removals": [
    {{"project": "global", "id": 3, "reason": "contradicted by newer information"}},
    ...
  ],
  "context_update": {{
    "top_of_mind": "Updated top-of-mind summary if anything changed (or null)"
  }}
}}

Rules:
- Only extract DURABLE, ACTIONABLE information. Skip ephemeral chatter.
- Do NOT extract passwords, API keys, SSNs, or credit card numbers.
- Confidence: 0.95+ for explicit statements, 0.7-0.9 for observed patterns, 0.5-0.7 for inferences.
- Keep each memory to one sentence.
- If nothing worth extracting, return empty arrays.
"""


# --- Claude CLI Client ---
def check_claude_cli() -> bool:
    try:
        result = subprocess.run(
            ["/Users/ShawCole/.local/bin/claude", "--version"],
            capture_output=True, text=True, timeout=10,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def extract_via_claude_cli(new_logs: str) -> dict | None:
    """Extract memories from session logs via claude CLI."""
    # Load current state
    ctx_file = GLOBAL_DIR / "context_layer.json"
    ctx = json.loads(ctx_file.read_text()) if ctx_file.exists() else {}

    # Load global facts summary
    facts_file = GLOBAL_DIR / "facts_db.json"
    facts = json.loads(facts_file.read_text()).get("facts", []) if facts_file.exists() else []
    facts_summary = "\n".join(
        f"[{f.get('id', '?')}] [{f.get('category', '?')}] {f.get('fact', f.get('text', ''))}"
        for f in facts[:30]
    )

    # Build project list
    project_names = ["global"]
    if PROJECTS_DIR.exists():
        project_names += [p.name for p in sorted(PROJECTS_DIR.iterdir()) if p.is_dir()]
    project_list = ", ".join(project_names)

    prompt = EXTRACTION_PROMPT.format(
        context=json.dumps(ctx, indent=2),
        existing_facts=facts_summary,
        new_logs=new_logs[:MAX_CONTEXT_CHARS],
        project_list=project_list,
    )

    try:
        result = subprocess.run(
            [
                "/Users/ShawCole/.local/bin/claude", "-p",
                prompt + "\n\nReturn ONLY valid JSON, nothing else.",
                "--output-format", "text",
                "--max-turns", "1",
            ],
            capture_output=True, text=True, timeout=120,
            cwd=str(OMNI_DIR),
        )

        if result.returncode != 0:
            log.error(f"Claude CLI failed (rc={result.returncode}): {result.stderr[:500]}")
            return None

        text = result.stdout.strip()

        # Extract JSON from response
        if "```json" in text:
            text = text.split("```json", 1)[1]
            if "```" in text:
                text = text[:text.rfind("```")]
        elif text.startswith("```"):
            text = text.split("\n", 1)[1]
            if text.endswith("```"):
                text = text[:text.rfind("```")]

        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            text = text[start:end]

        return json.loads(text)
    except subprocess.TimeoutExpired:
        log.error("Claude CLI timed out (120s)")
        return None
    except json.JSONDecodeError as e:
        log.error(f"Invalid JSON from Claude CLI: {e}")
        return None
    except Exception as e:
        log.error(f"Extraction failed: {e}")
        return None


# --- Memory Store Operations ---
def apply_extraction(updates: dict):
    """Apply extracted memories to the correct project stores."""
    from memory_lifecycle import governance_check, score_memory, audit_log

    new_memories = updates.get("new_memories", [])
    memory_updates = updates.get("updates", [])
    removals = updates.get("removals", [])
    context_update = updates.get("context_update", {})

    # Apply new memories
    added = 0
    for mem in new_memories:
        project = mem.get("project", "global")
        mem_type = mem.get("type", "semantic")
        text = mem.get("text", "")

        # Governance check
        check = governance_check(text, mem)
        if not check["allowed"]:
            log.warning(f"Blocked by governance: {text[:60]} — {check['issues']}")
            audit_log("blocked", project, "new", str(check["issues"]))
            continue

        # Score the memory
        score = score_memory(text, mem)

        # Determine store path
        if project == "global":
            store_path = GLOBAL_DIR / "facts_db.json"
        else:
            store_path = PROJECTS_DIR / project / "facts_db.json"

        store_path.parent.mkdir(parents=True, exist_ok=True)

        # Load or create store
        if store_path.exists():
            data = json.loads(store_path.read_text())
        else:
            data = {"version": 1, "max_facts": 200, "project": project, "facts": []}

        facts = data.get("facts", [])

        # Assign next ID
        max_id = max((f.get("id", 0) for f in facts), default=0)
        new_entry = {
            "id": max_id + 1,
            "category": mem_type,
            "fact": text,
            "confidence": round(score.composite, 3),
            "source": mem.get("source", "observed"),
            "timestamp": datetime.now().strftime("%Y-%m-%d"),
            "access_count": 0,
            "retention_score": {
                "durability": score.durability,
                "actionability": score.actionability,
                "explicitness": score.explicitness,
                "recency": score.recency,
                "access_frequency": score.access_frequency,
            },
            "retention_composite": round(score.composite, 3),
        }

        facts.append(new_entry)
        data["facts"] = facts
        data["last_updated"] = datetime.now(timezone.utc).isoformat()

        # Atomic write
        tmp = store_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2))
        tmp.rename(store_path)

        added += 1
        audit_log("extract", project, new_entry["id"], "added")
        log.info(f"  + [{project}/{mem_type}] {text[:60]}")

    # Apply updates to existing facts
    for upd in memory_updates:
        project = upd.get("project", "global")
        fact_id = upd.get("id")
        new_text = upd.get("new_text")
        if not fact_id or not new_text:
            continue

        store_path = (GLOBAL_DIR if project == "global" else PROJECTS_DIR / project) / "facts_db.json"
        if not store_path.exists():
            continue

        data = json.loads(store_path.read_text())
        for fact in data.get("facts", []):
            if fact.get("id") == fact_id:
                fact["_previous_text"] = fact.get("fact", fact.get("text", ""))
                fact["fact"] = new_text
                fact["timestamp"] = datetime.now().strftime("%Y-%m-%d")
                audit_log("update", project, fact_id, upd.get("reason", "updated"))
                log.info(f"  ~ [{project}] Updated fact #{fact_id}: {new_text[:60]}")
                break

        tmp = store_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2))
        tmp.rename(store_path)

    # Apply removals
    for rem in removals:
        project = rem.get("project", "global")
        fact_id = rem.get("id")
        if not fact_id:
            continue

        store_path = (GLOBAL_DIR if project == "global" else PROJECTS_DIR / project) / "facts_db.json"
        if not store_path.exists():
            continue

        data = json.loads(store_path.read_text())
        original_count = len(data.get("facts", []))
        data["facts"] = [f for f in data.get("facts", []) if f.get("id") != fact_id]
        if len(data["facts"]) < original_count:
            tmp = store_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, indent=2))
            tmp.rename(store_path)
            audit_log("remove", project, fact_id, rem.get("reason", "removed"))
            log.info(f"  - [{project}] Removed fact #{fact_id}: {rem.get('reason', '')}")

    # Update context layer
    new_top = context_update.get("top_of_mind")
    if new_top:
        ctx_file = GLOBAL_DIR / "context_layer.json"
        ctx = json.loads(ctx_file.read_text()) if ctx_file.exists() else {}
        ctx["top_of_mind"] = new_top
        ctx["last_updated"] = datetime.now(timezone.utc).isoformat()
        tmp = ctx_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(ctx, indent=2))
        tmp.rename(ctx_file)
        log.info(f"  Updated top_of_mind")

    log.info(f"Extraction complete: +{added} new, ~{len(memory_updates)} updated, -{len(removals)} removed")


# --- Watch Mode ---
def get_cursor() -> int:
    """Get the byte offset where we last read."""
    if CURSOR_FILE.exists():
        try:
            return int(CURSOR_FILE.read_text().strip())
        except ValueError:
            return 0
    return 0


def set_cursor(offset: int):
    CURSOR_FILE.write_text(str(offset))


def get_new_content(watch_path: Path) -> str:
    """Read new content since last cursor position."""
    if not watch_path.exists():
        return ""
    file_size = watch_path.stat().st_size
    cursor = get_cursor()
    if cursor >= file_size:
        return ""
    with open(watch_path, "r") as f:
        f.seek(cursor)
        content = f.read()
    set_cursor(file_size)
    return content


def run_extraction(watch_path: Path, dry_run: bool = False):
    """Single extraction cycle."""
    new_content = get_new_content(watch_path)
    if not new_content or len(new_content.strip()) < 50:
        log.info("No significant new content to process")
        return

    log.info(f"Processing {len(new_content)} chars of new content...")

    if dry_run:
        log.info(f"[DRY RUN] Would process:\n{new_content[:500]}...")
        return

    if not check_claude_cli():
        log.error("claude CLI not available. Cannot extract.")
        return

    log.info("Extracting via Claude CLI (Max plan)...")
    updates = extract_via_claude_cli(new_content)

    if updates:
        apply_extraction(updates)
    else:
        log.warning("No extractable content from this batch")


# --- Consolidation Mode ---
def run_consolidation(dry_run: bool = False):
    """Run full lifecycle across all projects."""
    from memory_lifecycle import consolidate_all
    log.info("=== Running consolidation cycle ===")
    results = consolidate_all(dry_run)
    total_scored = sum(r["scored"] for r in results)
    total_forgotten = sum(r["forgotten"] for r in results)
    total_compressed = sum(r["compressed"] for r in results)
    log.info(f"Consolidation complete: {len(results)} projects, "
             f"{total_scored} scored, {total_forgotten} forgotten, {total_compressed} compressed")


# --- Cron-callable wrapper ---
def check_and_extract():
    """Cron-callable: check for new content and extract if found. No loop, single run."""
    watch_path = Path.home() / "ALL_CONTEXT" / "Claude Code Session Log.md"
    if not watch_path.exists():
        log.info(f"Watch file not found: {watch_path}")
        return
    run_extraction(watch_path)
    run_consolidation()


# --- Daemon Loop ---
def daemon_loop(watch_path: Path, dry_run: bool = False,
                watch_only: bool = False, consolidate_only: bool = False):
    """Main daemon loop."""
    # Write PID
    PID_FILE.write_text(str(os.getpid()))

    log.info(f"Memory daemon starting (PID {os.getpid()})")
    log.info(f"  Watch: {watch_path}")
    log.info(f"  Consolidation interval: {CONSOLIDATION_INTERVAL}s")
    log.info(f"  Dry run: {dry_run}")

    last_consolidation = 0
    last_watch_check = 0
    last_file_mtime = 0

    def shutdown(signum, frame):
        log.info("Shutting down...")
        PID_FILE.unlink(missing_ok=True)
        sys.exit(0)

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    while True:
        now = time.time()

        # Watch mode: check for file changes
        if not consolidate_only and now - last_watch_check >= DEBOUNCE_SECONDS:
            last_watch_check = now
            try:
                if watch_path.exists():
                    mtime = watch_path.stat().st_mtime
                    if mtime > last_file_mtime:
                        last_file_mtime = mtime
                        run_extraction(watch_path, dry_run)
            except Exception as e:
                log.error(f"Watch error: {e}")

        # Consolidation mode: periodic lifecycle
        if not watch_only and now - last_consolidation >= CONSOLIDATION_INTERVAL:
            last_consolidation = now
            try:
                run_consolidation(dry_run)
            except Exception as e:
                log.error(f"Consolidation error: {e}")

        time.sleep(10)


# --- CLI ---
def show_status():
    """Show daemon status."""
    if PID_FILE.exists():
        pid = PID_FILE.read_text().strip()
        # Check if process is running
        try:
            os.kill(int(pid), 0)
            print(f"Daemon RUNNING (PID {pid})")
        except (OSError, ValueError):
            print(f"Daemon STALE (PID file exists but process {pid} not running)")
    else:
        print("Daemon NOT RUNNING")

    cursor = get_cursor()
    print(f"Cursor position: {cursor} bytes")

    # Audit log stats
    audit_file = OMNI_DIR / "logs" / "audit.jsonl"
    if audit_file.exists():
        lines = audit_file.read_text().strip().split("\n")
        print(f"Audit log entries: {len(lines)}")
        if lines:
            last = json.loads(lines[-1])
            print(f"Last operation: {last['operation']} on {last['project']} at {last['timestamp']}")


def main():
    parser = argparse.ArgumentParser(description="Async Memory Consolidation Daemon")
    parser.add_argument("--watch", type=str, default=str(DEFAULT_WATCH_PATH), help="Path to watch")
    parser.add_argument("--once", action="store_true", help="Single cycle, then exit")
    parser.add_argument("--dry-run", action="store_true", help="No writes")
    parser.add_argument("--watch-only", action="store_true", help="Only watch mode")
    parser.add_argument("--consolidate-only", action="store_true", help="Only consolidation mode")
    parser.add_argument("--status", action="store_true", help="Show status")
    args = parser.parse_args()

    watch_path = Path(args.watch)

    if args.status:
        show_status()
        return

    if args.once:
        log.info("Running single cycle...")
        if not args.consolidate_only:
            run_extraction(watch_path, args.dry_run)
        if not args.watch_only:
            run_consolidation(args.dry_run)
        return

    daemon_loop(
        watch_path,
        dry_run=args.dry_run,
        watch_only=args.watch_only,
        consolidate_only=args.consolidate_only,
    )


if __name__ == "__main__":
    main()
