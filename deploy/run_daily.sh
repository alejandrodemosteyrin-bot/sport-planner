#!/bin/bash
# Called by launchd every morning. Runs the planner from the project root and
# sends the report by Telegram. Exit code is logged by launchd.
set -euo pipefail
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"
source .venv/bin/activate
exec sport-planner run --send
