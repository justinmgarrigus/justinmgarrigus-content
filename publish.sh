#!/usr/bin/env bash
# Builds each site into its github.io repo next to this one, shows what
# changed, and (after you confirm, per site) commits and pushes it. Each
# repo commits with its own local git config and remote.
#
#   ./publish.sh                     # every site in site.toml's [sites]
#   ./publish.sh ../sophiegarrigus.github.io     # just this one
set -euo pipefail
cd "$(dirname "$0")"

if (( $# )); then
  TARGETS=("$@")
else
  # One ../<hostname> per [sites."<hostname>"] table.
  mapfile -t TARGETS < <(sed -n 's/^\[sites\."\([^"]*\)"\]$/..\/\1/p' site.toml)
fi

for TARGET in "${TARGETS[@]}"; do
  echo "=== $TARGET"
  uv run build.py --out "$TARGET"
  (
    cd "$TARGET"
    git add -A
    if git diff --cached --quiet; then
      echo "Nothing changed."
      exit 0
    fi
    git status --short | head -40
    read -rp "Commit and push $TARGET? [y/N] " ok
    [[ $ok == [yY] ]] || { echo "Left staged, not committed."; exit 0; }
    git commit -q -m "Rebuild site $(date +%F)"
    git push
  )
done
