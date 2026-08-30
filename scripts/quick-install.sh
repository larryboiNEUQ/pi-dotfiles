#!/usr/bin/env bash
# One-liner friendly entrypoint for a fresh machine.
#   curl -fsSL https://raw.githubusercontent.com/larryboiNEUQ/pi-dotfiles/main/scripts/quick-install.sh | bash
#   curl -fsSL https://raw.githubusercontent.com/larryboiNEUQ/pi-dotfiles/main/scripts/quick-install.sh | bash -s -- --latest
# or:
#   git clone https://github.com/larryboiNEUQ/pi-dotfiles.git && cd pi-dotfiles && ./scripts/quick-install.sh
set -euo pipefail

REPO_URL="${PI_DOTFILES_URL:-https://github.com/larryboiNEUQ/pi-dotfiles.git}"
DEST="${PI_DOTFILES_DIR:-${HOME}/.pi-dotfiles}"

if ! command -v pi >/dev/null 2>&1; then
  echo "pi CLI not found. Install first, e.g.:"
  echo "  npm install -g @earendil-works/pi-coding-agent"
  exit 1
fi

if ! command -v git >/dev/null 2>&1; then
  echo "git is required" >&2
  exit 1
fi

if [[ -d "$DEST/.git" ]]; then
  echo "==> Updating existing clone at $DEST"
  git -C "$DEST" pull --ff-only || true
else
  echo "==> Cloning $REPO_URL -> $DEST"
  rm -rf "$DEST"
  git clone "$REPO_URL" "$DEST"
fi

exec bash "$DEST/scripts/install.sh" "$@"
