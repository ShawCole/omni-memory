#!/usr/bin/env bash
# scaffold.sh — Create the omni-context directory structure
set -euo pipefail

OMNI_DIR="${HOME}/scripts/omni-context"

echo "Creating omni-context directory structure at ${OMNI_DIR}..."

mkdir -p "${OMNI_DIR}/global"
mkdir -p "${OMNI_DIR}/projects"
mkdir -p "${OMNI_DIR}/shared"
mkdir -p "${OMNI_DIR}/logs"

# Seed context_layer.json if it doesn't exist
if [ ! -f "${OMNI_DIR}/global/context_layer.json" ]; then
  cat > "${OMNI_DIR}/global/context_layer.json" << 'EOF'
{
  "work_context": "REPLACE — who you are, what you run, your companies/projects",
  "personal_context": "REPLACE — location, timezone, working style, current travel",
  "top_of_mind": "REPLACE — current blockers, deadlines, urgent priorities",
  "last_updated": "REPLACE_WITH_ISO_TIMESTAMP",
  "version": 1
}
EOF
  echo "  Created global/context_layer.json (edit the 3 surfaces)"
fi

# Seed global facts_db.json if it doesn't exist
if [ ! -f "${OMNI_DIR}/global/facts_db.json" ]; then
  cat > "${OMNI_DIR}/global/facts_db.json" << 'EOF'
{
  "version": 1,
  "max_facts": 200,
  "project": "global",
  "facts": []
}
EOF
  echo "  Created global/facts_db.json (empty — facts accumulate over time)"
fi

# Seed history_layer.md if it doesn't exist
if [ ! -f "${OMNI_DIR}/global/history_layer.md" ]; then
  cat > "${OMNI_DIR}/global/history_layer.md" << 'EOF'
# History Layer

## Recent Activity

(The memory daemon will populate this automatically.)
EOF
  echo "  Created global/history_layer.md"
fi

# Seed cross_project.json if it doesn't exist
if [ ! -f "${OMNI_DIR}/shared/cross_project.json" ]; then
  cat > "${OMNI_DIR}/shared/cross_project.json" << 'EOF'
{
  "relationships": [],
  "notes": "Add project relationships here. Format: { from: 'project-a', to: 'project-b', type: 'depends_on|shares_infra|feeds_into', note: '...' }"
}
EOF
  echo "  Created shared/cross_project.json"
fi

echo ""
echo "Done. Structure:"
echo ""
find "${OMNI_DIR}" -type f | sort | sed "s|${OMNI_DIR}/|  |"
echo ""
echo "Next steps:"
echo "  1. Edit global/context_layer.json with your 3 surfaces"
echo "  2. Create project dirs: mkdir -p ${OMNI_DIR}/projects/<name>"
echo "  3. Copy the skill: cp skill/SKILL.md ~/.claude/skills/omni-memory.md"
echo "  4. Start the daemon: python3 src/memory_daemon.py --once"
