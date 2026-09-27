#!/usr/bin/env bash
# Builds the site into the github.io repo next to this one, shows what
# changed, and (after you confirm) commits and pushes it.
#
#   ./publish.sh                     # uses ../justinmgarrigus.github.io
#   ./publish.sh path/to/site-repo
set -euo pipefail
cd "$(dirname "$0")"
TARGET=${1:-../justinmgarrigus.github.io}

uv run build.py --out "$TARGET"

cd "$TARGET"
git add -A
if git diff --cached --quiet; then
  echo "Nothing changed."
  exit 0
fi
git status --short | head -40
read -rp "Commit and push these changes? [y/N] " ok
[[ $ok == [yY] ]] || { echo "Left staged, not committed."; exit 0; }
git commit -q -m "Rebuild site $(date +%F)"
git push
