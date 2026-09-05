#!/usr/bin/env bash
#
# Install ios-agent-use.
#
#   git clone … && ./install.sh          installs from this checkout
#   curl -fsSL <raw-url>/install.sh | bash    clones first, then installs
#
# Puts `iosagent` on PATH and registers the Claude Code skill. Set IOSAGENT_HOME
# to control where a fresh clone lands (default ~/.ios-agent-use).
set -euo pipefail

REPO_URL="https://github.com/NoelSason/ios-agent-use.git"
BIN_DIR="${IOSAGENT_BIN_DIR:-$HOME/.local/bin}"
SKILL_DIR="${HOME}/.claude/skills"

# Work out whether we are inside a checkout or being piped from curl.
SOURCE="${BASH_SOURCE[0]:-}"
if [ -n "$SOURCE" ] && [ -f "$SOURCE" ]; then
  ROOT="$(cd "$(dirname "$SOURCE")" && pwd)"
else
  ROOT=""
fi

if [ -z "$ROOT" ] || [ ! -x "$ROOT/bin/iosagent" ]; then
  ROOT="${IOSAGENT_HOME:-$HOME/.ios-agent-use}"
  if [ -d "$ROOT/.git" ]; then
    echo "updating $ROOT"
    git -C "$ROOT" pull --ff-only --quiet
  else
    echo "cloning into $ROOT"
    git clone --depth 1 --quiet "$REPO_URL" "$ROOT"
  fi
fi

command -v xcodebuild >/dev/null 2>&1 || echo "warning: xcodebuild not found; this needs Xcode"
python3 --version >/dev/null 2>&1 || { echo "error: python3 is required"; exit 1; }

mkdir -p "$BIN_DIR"
ln -sf "$ROOT/bin/iosagent" "$BIN_DIR/iosagent"
echo "linked $BIN_DIR/iosagent"

case ":$PATH:" in
  *":$BIN_DIR:"*) ;;
  *) echo "note: $BIN_DIR is not on your PATH — add it, or call $ROOT/bin/iosagent directly" ;;
esac

if [ -d "$(dirname "$SKILL_DIR")" ]; then
  mkdir -p "$SKILL_DIR"
  ln -sfn "$ROOT/skills/ios-agent-use" "$SKILL_DIR/ios-agent-use"
  echo "linked $SKILL_DIR/ios-agent-use"
fi

echo
echo "done. Next:"
echo "  cd your-app-project"
echo "  $BIN_DIR/iosagent init      # writes .iosagent.json"
echo "  cp $ROOT/driver/AgentDriverUITests.swift YourAppUITests/"
echo "  $BIN_DIR/iosagent doctor"
