#!/bin/bash
# Installs (or reinstalls) the 09:00 daily launchd job for the current user.
# Usage: ./deploy/install_launchd.sh        (run from anywhere)
#        ./deploy/install_launchd.sh --uninstall
set -euo pipefail
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LABEL="com.sportplanner.daily"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"

if [[ "${1:-}" == "--uninstall" ]]; then
  launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
  rm -f "$PLIST"
  echo "removed $LABEL"
  exit 0
fi

case "$PROJECT_DIR" in
  "$HOME/Downloads"*|"$HOME/Desktop"*|"$HOME/Documents"*)
    echo "ERROR: $PROJECT_DIR is inside a macOS-protected folder (Downloads/Desktop/Documents)."
    echo "Background jobs get 'Operation not permitted' there. Move the project, e.g.:"
    echo "  mv \"$PROJECT_DIR\" ~/sport-planner   (then recreate .venv and re-run this script)"
    exit 1;;
esac
[[ -x "$PROJECT_DIR/.venv/bin/sport-planner" ]] || { echo "venv not found — run the install steps in README first"; exit 1; }
[[ -f "$PROJECT_DIR/.env" ]] || { echo ".env not found — copy .env.example and fill it in"; exit 1; }

mkdir -p "$HOME/Library/LaunchAgents" "$PROJECT_DIR/state"
sed "s#__PROJECT_DIR__#$PROJECT_DIR#g" "$PROJECT_DIR/deploy/com.sportplanner.daily.plist.template" > "$PLIST"
chmod +x "$PROJECT_DIR/deploy/run_daily.sh"
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
launchctl enable "gui/$(id -u)/$LABEL"
echo "installed $LABEL → runs daily at 09:00 local time"
echo "verify:   launchctl print gui/$(id -u)/$LABEL | head -20"
echo "test now: launchctl kickstart -k gui/$(id -u)/$LABEL   (then check your inbox and state/launchd.err.log)"
