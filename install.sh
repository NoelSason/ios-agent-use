#!/usr/bin/env bash
# Put `iosagent` on PATH and register the Claude Code skill.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

BIN="${HOME}/.local/bin"
mkdir -p "$BIN"
ln -sf "$ROOT/bin/iosagent" "$BIN/iosagent"
echo "linked $BIN/iosagent"
case ":$PATH:" in
  *":$BIN:"*) ;;
  *) echo "note: $BIN is not on your PATH" ;;
esac

SKILLS="${HOME}/.claude/skills"
if [ -d "$SKILLS" ]; then
  ln -sfn "$ROOT/skill" "$SKILLS/ios-agent-use"
  echo "linked $SKILLS/ios-agent-use"
fi

echo "done. Run 'iosagent doctor' in a project to check the setup."
