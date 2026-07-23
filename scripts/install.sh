#!/usr/bin/env bash
# Bootstrap this machine's Pi packages + local extensions from packages.json.
# Usage:
#   ./scripts/install.sh
#   ./scripts/install.sh --with-settings
#   ./scripts/install.sh --with-templates
#   ./scripts/install.sh --dry-run
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PACKAGES_JSON="${ROOT}/packages.json"
SETTINGS_PARTIAL="${ROOT}/settings.partial.json"
PI_AGENT_DIR="${PI_CODING_AGENT_DIR:-${HOME}/.pi/agent}"
SETTINGS_JSON="${PI_AGENT_DIR}/settings.json"

DRY_RUN=0
WITH_SETTINGS=0
WITH_TEMPLATES=0
SKIP_PACKAGES=0

usage() {
  cat <<'EOF'
Usage: install.sh [options]

  --with-settings    Merge settings.partial.json into ~/.pi/agent/settings.json
                     (theme / default model / thinking). Does not touch auth.
  --with-templates   Also copy optional permission config templates.
  --skip-packages    Only copy local extensions/agents (no pi install).
  --dry-run          Print actions without changing the system.
  -h, --help         Show this help.

Requires: pi CLI on PATH, node/npm, git, python3.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --with-settings) WITH_SETTINGS=1; shift ;;
    --with-templates) WITH_TEMPLATES=1; shift ;;
    --skip-packages) SKIP_PACKAGES=1; shift ;;
    --dry-run) DRY_RUN=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage; exit 1 ;;
  esac
done

log() { printf '==> %s\n' "$*"; }
run() {
  if [[ "$DRY_RUN" -eq 1 ]]; then
    printf '[dry-run] %s\n' "$*"
  else
    eval "$@"
  fi
}

expand_home() {
  local p="$1"
  if [[ "$p" == "~/"* ]]; then
    printf '%s/%s\n' "$HOME" "${p#~/}"
  elif [[ "$p" == "~" ]]; then
    printf '%s\n' "$HOME"
  else
    printf '%s\n' "$p"
  fi
}

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing required command: $1" >&2
    exit 1
  fi
}

require_cmd pi
require_cmd python3
require_cmd git
require_cmd npm

if [[ ! -f "$PACKAGES_JSON" ]]; then
  echo "packages.json not found at $PACKAGES_JSON" >&2
  exit 1
fi

log "Pi: $(pi --version 2>/dev/null || echo unknown)"
log "Agent dir: $PI_AGENT_DIR"
mkdir -p "$PI_AGENT_DIR/extensions" "$PI_AGENT_DIR/agents"

# ---------------------------------------------------------------------------
# Install remote packages via `pi install`
# ---------------------------------------------------------------------------
if [[ "$SKIP_PACKAGES" -eq 0 ]]; then
  log "Installing packages from packages.json"
  while IFS= read -r source; do
    [[ -z "$source" ]] && continue
    log "pi install $source"
    if [[ "$DRY_RUN" -eq 1 ]]; then
      printf '[dry-run] pi install %q\n' "$source"
    else
      # Idempotent enough: pi install re-adds / refreshes settings entry
      if ! pi install "$source"; then
        echo "WARN: failed to install $source (continuing)" >&2
      fi
    fi
  done < <(python3 - "$PACKAGES_JSON" <<'PY'
import json, sys
data = json.load(open(sys.argv[1]))
for p in data.get("packages", []):
    print(p["source"])
PY
)
else
  log "Skipping package installs (--skip-packages)"
fi

# ---------------------------------------------------------------------------
# Copy local extensions (plan-mode, etc.)
# ---------------------------------------------------------------------------
log "Installing local extensions"
python3 - "$PACKAGES_JSON" "$ROOT" "$DRY_RUN" <<'PY'
import json, os, shutil, sys
from pathlib import Path

pkg = json.load(open(sys.argv[1]))
root = Path(sys.argv[2])
dry = sys.argv[3] == "1"

def expand(p: str) -> Path:
    return Path(os.path.expanduser(p))

for item in pkg.get("local_extensions", []):
    src = root / item["path"]
    dst = expand(item["target"])
    print(f"  {src} -> {dst}")
    if not src.exists():
        print(f"  WARN: missing source {src}", file=sys.stderr)
        continue
    if dry:
        continue
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)
print("local extensions done")
PY

# ---------------------------------------------------------------------------
# Copy agents
# ---------------------------------------------------------------------------
log "Installing local agents"
python3 - "$PACKAGES_JSON" "$ROOT" "$DRY_RUN" <<'PY'
import json, os, shutil, sys
from pathlib import Path

pkg = json.load(open(sys.argv[1]))
root = Path(sys.argv[2])
dry = sys.argv[3] == "1"

def expand(p: str) -> Path:
    return Path(os.path.expanduser(p))

for item in pkg.get("local_agents", []):
    src = root / item["path"]
    dst = expand(item["target"])
    print(f"  {src} -> {dst}")
    if not src.exists():
        print(f"  WARN: missing source {src}", file=sys.stderr)
        continue
    if dry:
        continue
    dst.mkdir(parents=True, exist_ok=True)
    for f in src.glob("*.md"):
        shutil.copy2(f, dst / f.name)
        print(f"    + {f.name}")
print("local agents done")
PY

# ---------------------------------------------------------------------------
# Optional templates
# ---------------------------------------------------------------------------
if [[ "$WITH_TEMPLATES" -eq 1 ]]; then
  log "Installing optional templates"
  python3 - "$PACKAGES_JSON" "$ROOT" "$DRY_RUN" <<'PY'
import json, os, shutil, sys
from pathlib import Path

pkg = json.load(open(sys.argv[1]))
root = Path(sys.argv[2])
dry = sys.argv[3] == "1"

def expand(p: str) -> Path:
    return Path(os.path.expanduser(p))

for item in pkg.get("optional_templates", []):
    src = root / item["path"]
    dst = expand(item["target"])
    print(f"  {src} -> {dst}")
    if not src.exists():
        print(f"  WARN: missing source {src}", file=sys.stderr)
        continue
    if dry:
        continue
    dst.mkdir(parents=True, exist_ok=True)
    for f in src.rglob("*"):
        if f.is_file():
            rel = f.relative_to(src)
            out = dst / rel
            out.parent.mkdir(parents=True, exist_ok=True)
            # do not overwrite existing configs unless missing
            if out.exists():
                print(f"    skip existing {out}")
            else:
                shutil.copy2(f, out)
                print(f"    + {rel}")
print("templates done")
PY
fi

# ---------------------------------------------------------------------------
# Optional settings merge (prefs only, never auth)
# ---------------------------------------------------------------------------
if [[ "$WITH_SETTINGS" -eq 1 ]]; then
  log "Merging settings.partial.json into $SETTINGS_JSON"
  if [[ ! -f "$SETTINGS_PARTIAL" ]]; then
    echo "WARN: $SETTINGS_PARTIAL missing" >&2
  elif [[ "$DRY_RUN" -eq 1 ]]; then
    echo "[dry-run] merge settings.partial.json"
  else
    python3 - "$SETTINGS_JSON" "$SETTINGS_PARTIAL" <<'PY'
import json, sys
from pathlib import Path

settings_path = Path(sys.argv[1])
partial_path = Path(sys.argv[2])
partial = json.loads(partial_path.read_text())
# Never allow secrets keys from partial
blocked = {"auth", "apiKey", "apiKeys", "token", "tokens"}
partial = {k: v for k, v in partial.items() if k not in blocked}

if settings_path.exists():
    settings = json.loads(settings_path.read_text())
else:
    settings = {}
    settings_path.parent.mkdir(parents=True, exist_ok=True)

# shallow merge prefs; do not clobber packages array (managed by pi install)
for k, v in partial.items():
    if k == "packages":
        continue
    settings[k] = v

settings_path.write_text(json.dumps(settings, indent=2) + "\n")
print("merged keys:", ", ".join(sorted(partial.keys())))
PY
  fi
fi

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
log "Done."
if [[ "$DRY_RUN" -eq 0 ]]; then
  echo
  echo "Installed packages (pi list):"
  pi list || true
  echo
  echo "Next steps:"
  echo "  1. Restart pi (or open a new session)"
  echo "  2. /login if models need auth on this machine"
  echo "  3. /mcp setup  (if using pi-mcp-adapter)"
  echo "  4. /plan or Ctrl+Alt+P for plan-mode; /gallery for images"
  echo
  echo "Optional: re-run with --with-settings to apply theme/model defaults"
fi
