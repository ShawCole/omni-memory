#!/usr/bin/env python3
"""
Memory Lifecycle Engine — Retention, Compression, Forgetting, Integrity

Implements the full memory lifecycle from the "Memory as Infrastructure" pattern:
  1. Retention Scoring — 5-dimension weighted score for every memory
  2. Compression — LLM-powered reduction (80% target)
  3. Forgetting — Below-threshold removal, contradiction detection, capacity limits
  4. Integrity — Duplicate detection, stale flagging, conflict resolution
  5. Governance — PII blocking, confidence floor, audit logging

Usage:
    python3 memory_lifecycle.py score <project> [--all]       # Score all memories
    python3 memory_lifecycle.py compress <project>             # Compress verbose memories
    python3 memory_lifecycle.py forget <project>               # Run forgetting cycle
    python3 memory_lifecycle.py integrity <project>            # Run integrity checks
    python3 memory_lifecycle.py consolidate <project>          # Full lifecycle (all 4)
    python3 memory_lifecycle.py consolidate --all              # All projects
    python3 memory_lifecycle.py governance-check <text>        # Check text for PII

Works with claude CLI (Max plan) — no API key needed.
"""

import json
import os
import re
import subprocess
import sys
import time
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
from dataclasses import dataclass, asdict

# --- Config ---
OMNI_DIR = Path(__file__).parent
PROJECTS_DIR = OMNI_DIR / "projects"
GLOBAL_DIR = OMNI_DIR / "global"
LOGS_DIR = OMNI_DIR / "logs"
AUDIT_LOG = LOGS_DIR / "audit.jsonl"

RETENTION_THRESHOLD = 0.5
MAX_MEMORIES_PER_TYPE = 200  # Default fallback — each store's max_facts takes precedence
STALE_DAYS = 45
DUPLICATE_JACCARD_THRESHOLD = 0.65
COMPRESSION_TOKEN_THRESHOLD = 40  # Compress memories longer than this

MEMORY_TYPES = ["semantic", "episodic", "procedural"]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("lifecycle")


# ============================================================
# 1. RETENTION SCORING
# ============================================================

@dataclass
class RetentionScore:
    durability: float       # Will this still be true next week? (0-1)
    actionability: float    # Does it change agent behavior? (0-1)
    explicitness: float     # Was it stated clearly? (0-1)
    recency: float          # How recent? (0-1, decays over 90 days)
    access_frequency: float # How often retrieved? (0-1, saturates at 10)

    @property
    def composite(self) -> float:
        return (
            self.durability * 0.25
            + self.actionability * 0.20
            + self.explicitness * 0.15
            + self.recency * 0.25
            + self.access_frequency * 0.15
        )


EPHEMERAL_MARKERS = [
    "today", "right now", "this time", "this session", "just for now",
    "currently", "at the moment", "for now", "temporarily"
]

ACTION_MARKERS = [
    "prefer", "always", "never", "instead", "don't", "allergic", "require",
    "must", "should", "needs", "critical", "blocker", "deadline", "overdue",
    "uses", "runs on", "deployed", "password", "key", "account", "login"
]


def score_memory(text: str, metadata: dict) -> RetentionScore:
    """Score a memory on 5 dimensions."""
    text_lower = text.lower()

    # Durability: ephemeral markers reduce it
    durability = 0.9
    for marker in EPHEMERAL_MARKERS:
        if marker in text_lower:
            durability = 0.2
            break
    # Explicit durability override from metadata
    if metadata.get("durable") is True:
        durability = 1.0

    # Actionability: action markers increase it
    actionability = 0.3
    action_count = sum(1 for m in ACTION_MARKERS if m in text_lower)
    if action_count >= 2:
        actionability = 0.95
    elif action_count == 1:
        actionability = 0.7

    # Explicitness: explicit > observed > inferred
    source = metadata.get("source", "inferred")
    explicitness_map = {
        "explicit_statement": 1.0,
        "explicit": 1.0,
        "observed_interaction": 0.7,
        "observed": 0.7,
        "feedback_pattern": 0.8,
        "inferred": 0.4,
        "seed": 0.6,  # seeded from MASTER_ANALYSIS
    }
    explicitness = explicitness_map.get(source, 0.5)

    # Recency: linear decay over 45 days
    created = metadata.get("created_at") or metadata.get("timestamp")
    if not created:
        # Backfill missing timestamp so this doesn't happen again
        created = datetime.now().strftime("%Y-%m-%d")
        metadata["timestamp"] = created
        metadata["_timestamp_backfilled"] = True
    try:
        if isinstance(created, str) and len(created) == 10:  # "2026-03-29"
            created_dt = datetime.fromisoformat(created + "T00:00:00")
        else:
            created_dt = datetime.fromisoformat(str(created).replace("Z", "+00:00"))
            if created_dt.tzinfo:
                created_dt = created_dt.replace(tzinfo=None)
    except (ValueError, TypeError):
        created_dt = datetime.now()
    age_days = (datetime.now() - created_dt).days
    recency = max(0.05, 1.0 - (age_days / 45))

    # Access frequency: weighted by agent tier (T0=+4, T1=+3, T2=+2, T3=+1)
    # Saturates at 40 weighted accesses (~10 GM reads or ~20 specialist reads)
    access_count = metadata.get("access_count", 0)
    access_frequency = min(1.0, access_count / 40)

    return RetentionScore(
        durability=round(durability, 3),
        actionability=round(actionability, 3),
        explicitness=round(explicitness, 3),
        recency=round(recency, 3),
        access_frequency=round(access_frequency, 3),
    )


def score_all_memories(project: str) -> list[dict]:
    """Score all memories in a project and update their metadata."""
    results = []
    project_dir = PROJECTS_DIR / project if project != "global" else GLOBAL_DIR

    for mem_type in MEMORY_TYPES + ["facts_db"]:
        store_file = project_dir / f"{mem_type}.json"
        if not store_file.exists():
            # Fallback: check for facts_db.json (legacy format)
            if mem_type == "facts_db":
                store_file = project_dir / "facts_db.json"
            if not store_file.exists():
                continue

        try:
            data = json.loads(store_file.read_text())
        except json.JSONDecodeError:
            continue

        memories = data.get("facts", data.get("memories", []))
        updated = False

        for mem in memories:
            text = mem.get("fact", mem.get("text", ""))
            score = score_memory(text, mem)
            old_confidence = mem.get("confidence", 0)

            # Update metadata with full score
            mem["retention_score"] = asdict(score)
            mem["retention_composite"] = round(score.composite, 3)
            # Keep confidence as alias for backward compat
            mem["confidence"] = round(score.composite, 3)
            updated = True

            results.append({
                "project": project,
                "type": mem_type,
                "id": mem.get("id", "?"),
                "text": text[:80],
                "old_confidence": old_confidence,
                "new_composite": score.composite,
                "score": asdict(score),
            })

        if updated:
            data["last_scored"] = datetime.now(timezone.utc).isoformat()
            store_file.write_text(json.dumps(data, indent=2))

    return results


# ============================================================
# 2. COMPRESSION
# ============================================================

def compress_memory_via_cli(text: str) -> str | None:
    """Use claude CLI to compress a memory. Returns compressed text or None."""
    prompt = (
        "Compress the following memory into a single precise sentence. "
        "Preserve the core fact or preference. Remove conversational fluff, "
        "timestamps, and non-essential context. Output ONLY the compressed text, "
        "nothing else.\n\n"
        f"Memory: {text}"
    )
    try:
        result = subprocess.run(
            ["/Users/ShawCole/.local/bin/claude", "-p", prompt, "--output-format", "text", "--max-turns", "1"],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode == 0 and result.stdout.strip():
            compressed = result.stdout.strip()
            # Sanity check: compressed should be shorter
            if len(compressed) < len(text) * 0.9:
                return compressed
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return None


def compress_project_memories(project: str, dry_run: bool = False) -> list[dict]:
    """Compress verbose memories in a project."""
    results = []
    project_dir = PROJECTS_DIR / project if project != "global" else GLOBAL_DIR

    for mem_type in MEMORY_TYPES + ["facts_db"]:
        store_file = project_dir / f"{mem_type}.json"
        if not store_file.exists():
            continue

        data = json.loads(store_file.read_text())
        memories = data.get("facts", data.get("memories", []))
        updated = False

        for mem in memories:
            text = mem.get("fact", mem.get("text", ""))
            # Rough token estimate: words / 0.75
            token_est = len(text.split()) / 0.75

            if token_est > COMPRESSION_TOKEN_THRESHOLD:
                if dry_run:
                    results.append({
                        "project": project, "type": mem_type,
                        "id": mem.get("id", "?"),
                        "tokens_est": int(token_est),
                        "action": "would_compress",
                    })
                else:
                    compressed = compress_memory_via_cli(text)
                    if compressed:
                        original_tokens = int(token_est)
                        new_tokens = int(len(compressed.split()) / 0.75)
                        reduction = round(1 - new_tokens / max(original_tokens, 1), 2)

                        # Store original as backup
                        mem["_original_text"] = text
                        mem["_compressed_at"] = datetime.now(timezone.utc).isoformat()

                        # Update text
                        if "fact" in mem:
                            mem["fact"] = compressed
                        else:
                            mem["text"] = compressed
                        updated = True

                        results.append({
                            "project": project, "type": mem_type,
                            "id": mem.get("id", "?"),
                            "original_tokens": original_tokens,
                            "compressed_tokens": new_tokens,
                            "reduction": f"{int(reduction*100)}%",
                        })
                        audit_log("compress", project, mem.get("id"), "success")

        if updated:
            store_file.write_text(json.dumps(data, indent=2))

    return results


# ============================================================
# 3. INTELLIGENT FORGETTING
# ============================================================

def run_forgetting_cycle(project: str, dry_run: bool = False) -> list[dict]:
    """Archive low-value memories to cold storage. Never truly delete.

    Facts below threshold, duplicates, and capacity overflows are moved to
    an archive file (facts_archive.json) in the same directory. They remain
    searchable for historical context but don't consume token budget or
    clutter the active store.
    """
    archived = []
    project_dir = PROJECTS_DIR / project if project != "global" else GLOBAL_DIR

    for mem_type in MEMORY_TYPES + ["facts_db"]:
        store_file = project_dir / f"{mem_type}.json"
        if not store_file.exists():
            continue

        data = json.loads(store_file.read_text())
        memories = data.get("facts", data.get("memories", []))
        to_archive = []

        for i, mem in enumerate(memories):
            text = mem.get("fact", mem.get("text", ""))
            score = score_memory(text, mem)

            # Rule 1: Below retention threshold → archive
            if score.composite < RETENTION_THRESHOLD:
                to_archive.append((i, "below_threshold", score.composite))
                continue

        # Rule 2: Duplicates (Jaccard similarity) → archive the weaker one
        for i in range(len(memories)):
            if any(idx == i for idx, _, _ in to_archive):
                continue
            for j in range(i + 1, len(memories)):
                if any(idx == j for idx, _, _ in to_archive):
                    continue
                text_a = memories[i].get("fact", memories[i].get("text", ""))
                text_b = memories[j].get("fact", memories[j].get("text", ""))
                if _jaccard_similarity(text_a, text_b) > DUPLICATE_JACCARD_THRESHOLD:
                    score_a = score_memory(text_a, memories[i]).composite
                    score_b = score_memory(text_b, memories[j]).composite
                    victim = j if score_a >= score_b else i
                    to_archive.append((victim, "duplicate", min(score_a, score_b)))

        # Rule 3: Capacity limit → archive lowest-scoring overflow
        # Use per-store max_facts if set, otherwise fall back to global default
        store_max = data.get("max_facts", MAX_MEMORIES_PER_TYPE)
        if len(memories) - len(to_archive) > store_max:
            scored = []
            archive_indices = {idx for idx, _, _ in to_archive}
            for i, mem in enumerate(memories):
                if i not in archive_indices:
                    text = mem.get("fact", mem.get("text", ""))
                    scored.append((i, score_memory(text, mem).composite))
            scored.sort(key=lambda x: x[1], reverse=True)
            for idx, sc in scored[store_max:]:
                to_archive.append((idx, "capacity_overflow", sc))

        # Deduplicate archive list
        seen = set()
        unique_archives = []
        for idx, reason, sc in to_archive:
            if idx not in seen:
                seen.add(idx)
                unique_archives.append((idx, reason, sc))

        for idx, reason, sc in unique_archives:
            mem = memories[idx]
            text = mem.get("fact", mem.get("text", ""))
            archived.append({
                "project": project, "type": mem_type,
                "id": mem.get("id", "?"),
                "text": text[:80],
                "reason": reason,
                "score": round(sc, 3),
            })

        if not dry_run and unique_archives:
            archive_indices = {idx for idx, _, _ in unique_archives}

            # Move archived facts to cold storage (never delete)
            archive_file = project_dir / "facts_archive.json"
            if archive_file.exists():
                archive_data = json.loads(archive_file.read_text())
            else:
                archive_data = {"project": project, "archived_facts": []}

            for idx, reason, sc in unique_archives:
                mem = memories[idx]
                mem["_archived_at"] = datetime.now(timezone.utc).isoformat()
                mem["_archive_reason"] = reason
                mem["_archive_score"] = round(sc, 3)
                archive_data["archived_facts"].append(mem)

            archive_data["last_updated"] = datetime.now(timezone.utc).isoformat()
            tmp = archive_file.with_suffix(".tmp")
            tmp.write_text(json.dumps(archive_data, indent=2))
            tmp.rename(archive_file)

            # Remove from active store
            remaining = [m for i, m in enumerate(memories) if i not in archive_indices]
            if "facts" in data:
                data["facts"] = remaining
            else:
                data["memories"] = remaining
            data["last_archived"] = datetime.now(timezone.utc).isoformat()
            store_file.write_text(json.dumps(data, indent=2))

            for item in archived:
                if item["type"] == mem_type:
                    audit_log("archive", project, item["id"], item["reason"])

    return archived


def _jaccard_similarity(text_a: str, text_b: str) -> float:
    words_a = set(text_a.lower().split())
    words_b = set(text_b.lower().split())
    intersection = words_a & words_b
    union = words_a | words_b
    return len(intersection) / max(len(union), 1)


# ============================================================
# 4. INTEGRITY CHECKING
# ============================================================

def check_integrity(project: str) -> dict:
    """Find duplicates, stale memories, and missing metadata."""
    issues = []
    all_memories = []
    project_dir = PROJECTS_DIR / project if project != "global" else GLOBAL_DIR

    for mem_type in MEMORY_TYPES + ["facts_db"]:
        store_file = project_dir / f"{mem_type}.json"
        if not store_file.exists():
            continue
        data = json.loads(store_file.read_text())
        memories = data.get("facts", data.get("memories", []))
        for mem in memories:
            all_memories.append((mem_type, mem))

    # Check 1: Duplicates
    for i, (type_a, mem_a) in enumerate(all_memories):
        text_a = mem_a.get("fact", mem_a.get("text", ""))
        for j, (type_b, mem_b) in enumerate(all_memories[i+1:], i+1):
            text_b = mem_b.get("fact", mem_b.get("text", ""))
            sim = _jaccard_similarity(text_a, text_b)
            if sim > DUPLICATE_JACCARD_THRESHOLD:
                issues.append({
                    "type": "duplicate",
                    "similarity": round(sim, 2),
                    "memory_a": f"[{type_a}] {text_a[:60]}",
                    "memory_b": f"[{type_b}] {text_b[:60]}",
                    "action": "merge_or_remove",
                })

    # Check 2: Stale memories (no access in 60+ days)
    for mem_type, mem in all_memories:
        last_access = mem.get("last_validated") or mem.get("created_at") or mem.get("timestamp")
        if last_access:
            try:
                ts = str(last_access)
                if len(ts) == 10:
                    ts += "T00:00:00"
                access_dt = datetime.fromisoformat(ts.replace("Z", "+00:00")).replace(tzinfo=None)
                age = (datetime.now() - access_dt).days
                if age > STALE_DAYS:
                    text = mem.get("fact", mem.get("text", ""))
                    issues.append({
                        "type": "stale",
                        "memory": f"[{mem_type}] {text[:60]}",
                        "days_since_access": age,
                        "action": "validate_or_remove",
                    })
            except (ValueError, TypeError):
                pass

    # Check 3: Missing metadata
    for mem_type, mem in all_memories:
        missing = []
        if "confidence" not in mem and "retention_composite" not in mem:
            missing.append("confidence/retention_composite")
        if "source" not in mem:
            missing.append("source")
        if missing:
            text = mem.get("fact", mem.get("text", ""))
            issues.append({
                "type": "missing_metadata",
                "memory": f"[{mem_type}] {text[:60]}",
                "missing_fields": missing,
                "action": "add_metadata",
            })

    return {
        "project": project,
        "total_memories": len(all_memories),
        "issues_found": len(issues),
        "issues": issues,
    }


# ============================================================
# 5. GOVERNANCE
# ============================================================

BLOCKED_PATTERNS = [
    (r"\b\d{3}-\d{2}-\d{4}\b", "SSN"),
    (r"\b\d{16}\b", "credit_card"),
    (r"\bpassword\s*[:=]\s*\S+", "password"),
    (r"\b[A-Za-z0-9+/]{40,}={0,2}\b", "api_key_or_token"),
    (r"\b\d{10,11}\b", "phone_number"),  # 10-11 digit numbers
    (r"sk-[a-zA-Z0-9]{20,}", "openai_key"),
    (r"AIza[a-zA-Z0-9_-]{35}", "google_api_key"),
]


def governance_check(text: str, metadata: dict = None) -> dict:
    """Validate text before storing as memory."""
    metadata = metadata or {}
    issues = []

    for pattern, name in BLOCKED_PATTERNS:
        if re.search(pattern, text):
            issues.append({"type": "blocked_content", "pattern": name, "action": "reject"})

    if metadata.get("confidence", 1.0) < 0.3:
        issues.append({"type": "low_confidence", "confidence": metadata["confidence"], "action": "warn"})

    if any(i["action"] == "reject" for i in issues):
        return {"allowed": False, "issues": issues}
    return {"allowed": True, "issues": issues}


def audit_log(operation: str, project: str, key, result: str):
    """Append to audit log."""
    AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "operation": operation,
        "project": project,
        "key": str(key),
        "result": result,
    }
    with open(AUDIT_LOG, "a") as f:
        f.write(json.dumps(entry) + "\n")


# ============================================================
# 6. FULL CONSOLIDATION CYCLE
# ============================================================

def consolidate(project: str, dry_run: bool = False) -> dict:
    """Run the full memory lifecycle for a project."""
    log.info(f"=== Consolidation: {project} ===")

    # Step 1: Score all memories
    log.info("Step 1: Scoring...")
    scores = score_all_memories(project)
    log.info(f"  Scored {len(scores)} memories")

    # Step 2: Integrity check
    log.info("Step 2: Integrity check...")
    integrity = check_integrity(project)
    log.info(f"  Found {integrity['issues_found']} issues")

    # Step 3: Forgetting cycle
    log.info("Step 3: Forgetting cycle...")
    forgotten = run_forgetting_cycle(project, dry_run=dry_run)
    log.info(f"  Archived {len(forgotten)} memories to cold storage")

    # Step 4: Compression
    log.info("Step 4: Compression...")
    compressed = compress_project_memories(project, dry_run=dry_run)
    log.info(f"  Compressed {len(compressed)} memories")

    result = {
        "project": project,
        "scored": len(scores),
        "integrity_issues": integrity["issues_found"],
        "forgotten": len(forgotten),
        "compressed": len(compressed),
        "dry_run": dry_run,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    audit_log("consolidate", project, "full_cycle", json.dumps(result))
    return result


def consolidate_all(dry_run: bool = False) -> list[dict]:
    """Run consolidation across all projects + global."""
    results = []

    # Global
    results.append(consolidate("global", dry_run))

    # All projects
    if PROJECTS_DIR.exists():
        for pd in sorted(PROJECTS_DIR.iterdir()):
            if pd.is_dir() and (pd / "facts_db.json").exists():
                results.append(consolidate(pd.name, dry_run))

    return results


# ============================================================
# CLI
# ============================================================

def main():
    if len(sys.argv) < 2:
        print("Usage: python3 memory_lifecycle.py <command> [project] [--dry-run] [--all]")
        print("")
        print("Commands:")
        print("  score <project>        Score all memories")
        print("  compress <project>     Compress verbose memories")
        print("  forget <project>       Run forgetting cycle")
        print("  integrity <project>    Run integrity checks")
        print("  consolidate <project>  Full lifecycle (score→integrity→forget→compress)")
        print("  consolidate --all      All projects")
        print("  governance-check <txt> Check text for PII")
        return

    cmd = sys.argv[1]
    project = sys.argv[2] if len(sys.argv) > 2 else None
    dry_run = "--dry-run" in sys.argv
    do_all = "--all" in sys.argv

    if cmd == "score":
        if not project:
            print("Usage: memory_lifecycle.py score <project>")
            return
        results = score_all_memories(project)
        for r in results:
            comp = r["new_composite"]
            icon = "●" if comp >= 0.7 else "◐" if comp >= 0.4 else "○"
            print(f"  {icon} {comp:.3f} [{r['type']:<10}] {r['text']}")
        print(f"\n--- {len(results)} memories scored ---")

    elif cmd == "compress":
        results = compress_project_memories(project or "global", dry_run)
        for r in results:
            print(f"  [{r['type']}] {r.get('reduction', 'N/A')} reduction — id={r['id']}")
        print(f"\n--- {len(results)} compressed ---")

    elif cmd == "forget":
        results = run_forgetting_cycle(project or "global", dry_run)
        for r in results:
            print(f"  → [{r['type']}] {r['reason']} (score={r['score']}) — {r['text']}")
        print(f"\n--- {len(results)} archived to cold storage ---")

    elif cmd == "integrity":
        result = check_integrity(project or "global")
        print(f"Total memories: {result['total_memories']}")
        print(f"Issues found: {result['issues_found']}")
        for issue in result["issues"]:
            print(f"  [{issue['type']}] {issue.get('memory', issue.get('memory_a', '?'))[:70]}")
            print(f"    Action: {issue['action']}")

    elif cmd == "consolidate":
        if do_all:
            results = consolidate_all(dry_run)
            for r in results:
                print(f"  {r['project']}: scored={r['scored']} forgotten={r['forgotten']} compressed={r['compressed']}")
        else:
            result = consolidate(project or "global", dry_run)
            print(json.dumps(result, indent=2))

    elif cmd == "governance-check":
        text = " ".join(sys.argv[2:])
        result = governance_check(text)
        print(json.dumps(result, indent=2))

    else:
        print(f"Unknown command: {cmd}")


if __name__ == "__main__":
    main()
