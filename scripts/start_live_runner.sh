#!/usr/bin/env bash
# Register and start the ephemeral self-hosted runner for Xtractor's live canary.
# The runner takes ONE job and then removes itself, so run this before each live run
# (the weekly schedule, or `gh workflow run "Live (latest yt-dlp)"`). Ctrl+C to stop early.
# Runner install dir defaults to ~/actions-runner; override with RUNNER_DIR.
set -euo pipefail

REPO="BelongaGezza/Xtractor"
LABEL="xtractor-live"
RUNNER_DIR="${RUNNER_DIR:-$HOME/actions-runner}"
cd "$RUNNER_DIR" || { echo "No runner at $RUNNER_DIR (set RUNNER_DIR, or install the runner from repo Settings > Actions > Runners)." >&2; exit 1; }

if pgrep -f "Runner.Listener" >/dev/null; then
  echo "A runner is already listening; not starting a second one." >&2
  exit 1
fi

# Needs the gh CLI logged in with admin rights on the repo.
token="$(gh api -X POST "repos/$REPO/actions/runners/registration-token" -q .token)"

./config.sh --url "https://github.com/$REPO" --token "$token" \
  --name "$(hostname -s)-live" --labels "$LABEL" --work _work \
  --unattended --ephemeral --replace

echo "Listening for one job. Trigger it with:"
echo "  gh workflow run \"Live (latest yt-dlp)\" --repo $REPO --ref main"
exec ./run.sh
