#!/usr/bin/env bash
# write-handoff.sh — Called by Claude Code Stop hook to auto-write handoff files
#
# Detects which project the session was working in (by CWD) and writes
# a handoff.md to the appropriate project memory directory.
#
# If the agent already wrote a handoff in the last 5 minutes, skip.
# Otherwise, use git state to generate a useful handoff (not a placeholder).
#
# Usage (called by hook, not manually):
#   write-handoff.sh <session_id> <cwd>

set -euo pipefail

OMNI_DIR="$HOME/scripts/omni-context"
ORCHESTRA_DIR="$HOME/scripts/agent-orchestra"
REGISTRY="$ORCHESTRA_DIR/registry.json"

# Map CWD to project ID
detect_project() {
    local cwd="$1"

    # Check registry for matching agent by cwd
    if [[ -f "$REGISTRY" ]]; then
        local project
        project=$(python3 -c "
import json
with open('$REGISTRY') as f:
    r = json.load(f)
for aid, a in r['agents'].items():
    if '$cwd'.startswith(a.get('cwd', '/nonexistent')):
        scope = a.get('memory_scope', 'global')
        if isinstance(scope, list):
            for s in scope:
                if s != 'global':
                    print(s)
                    break
            else:
                print('global')
        else:
            print(scope)
        break
" 2>/dev/null)
        if [[ -n "$project" ]]; then
            echo "$project"
            return
        fi
    fi

    # Fallback: match by known paths
    case "$cwd" in
        */ListMagic_Dev*) echo "listmagic" ;;
        */SimpleAudienceMobile*) echo "listmagic" ;;
        */ArkData/arkdata*) echo "arkdata" ;;
        */ark-data-web*) echo "arkdata-web" ;;
        */sanctuary_source*) echo "sanctuary" ;;
        */VSL_Builder*) echo "vsl-builder" ;;
        */Gemini_PersonaCopy*) echo "personacopy" ;;
        */GeminiScribe*) echo "geminiscribe" ;;
        */GeminiSmartCalendar*) echo "smart-calendar" ;;
        */UglyAds*) echo "uglyads" ;;
        */Elysian_Landing_Pages*) echo "elysian" ;;
        */Melissa_Podcast_Guest_Page*) echo "amansala" ;;
        */DentalSolutions_Calculator*) echo "dentalcancun" ;;
        */agent-orchestra*|*/agent-swarm*|*/omni-context*) echo "agent-orchestra" ;;
        *) echo "global" ;;
    esac
}

main() {
    local cwd="${2:-$(pwd)}"
    local project
    project=$(detect_project "$cwd")

    local handoff_dir="$OMNI_DIR/projects/$project"
    local handoff_file="$handoff_dir/handoff.md"

    # Create directory if needed
    mkdir -p "$handoff_dir"

    # If a handoff already exists and was modified in the last 5 minutes,
    # the agent likely wrote it themselves. Don't overwrite.
    if [[ -f "$handoff_file" ]]; then
        local mod_time
        mod_time=$(stat -f %m "$handoff_file" 2>/dev/null || stat -c %Y "$handoff_file" 2>/dev/null || echo 0)
        local now
        now=$(date +%s)
        local age=$(( now - mod_time ))

        if [[ $age -lt 300 ]]; then
            exit 0
        fi
    fi

    local timestamp
    timestamp=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

    # Gather real context from git
    local git_status=""
    local git_log=""
    local git_branch=""
    local git_diff_stat=""

    if cd "$cwd" 2>/dev/null && git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
        git_branch=$(git branch --show-current 2>/dev/null || echo "unknown")
        git_status=$(git status --short 2>/dev/null | head -20 || echo "")
        git_log=$(git log --oneline -5 2>/dev/null || echo "")
        git_diff_stat=$(git diff --stat HEAD~1 2>/dev/null | tail -5 || echo "")
    fi

    # Build a useful handoff from what we can observe
    cat > "$handoff_file" << EOF
# Handoff — ${project}
**Session ended:** ${timestamp}
**Working directory:** ${cwd}
**Branch:** ${git_branch:-unknown}
**Git status:**
\`\`\`
${git_status:-clean}
\`\`\`
**Recent commits:**
\`\`\`
${git_log:-no commits}
\`\`\`
**Recent changes:**
\`\`\`
${git_diff_stat:-no diff}
\`\`\`
**Next step:** Review git log above and continue from last commit
**Note:** Auto-generated from git state. Agent did not write a manual handoff.
EOF

    # Also write an event to the event bus if it exists
    local event_bus="$ORCHESTRA_DIR/event-bus.sh"
    if [[ -x "$event_bus" ]]; then
        "$event_bus" "session_end" "$project" "Session ended in $cwd (branch: ${git_branch:-unknown})" 2>/dev/null || true
    fi
}

main "$@"
