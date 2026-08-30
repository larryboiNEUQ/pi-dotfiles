#!/usr/bin/env bash
# Bootstrap Pi packages + local extensions from packages.json.
# Usage:
#   ./scripts/install.sh
#   ./scripts/install.sh --latest
#   ./scripts/install.sh --with-settings
#   ./scripts/install.sh --dry-run
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PACKAGES_JSON="${ROOT}/packages.json"
SETTINGS_PARTIAL="${ROOT}/settings.partial.json"
PI_AGENT_DIR="${PI_CODING_AGENT_DIR:-${HOME}/.pi/agent}"
SETTINGS_JSON="${PI_AGENT_DIR}/settings.json"

DRY_RUN=0
WITH_SETTINGS=0
SKIP_PACKAGES=0
INSTALL_PROFILE="pinned"

usage() {
  cat <<'EOF'
Usage: install.sh [options]

  --latest          Install unversioned/latest package sources.
  --with-settings    Merge settings.partial.json into ~/.pi/agent/settings.json
                     (theme / model / thinking / quiet display and queue prefs). Does not touch auth.
                     See settings.partial.json for current values.
  --skip-packages    Only copy local extensions/agents (no pi install).
  --dry-run          Print actions without changing the system.
  -h, --help         Show this help.

Requires: pi CLI on PATH, node/npm, git, python3.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --latest) INSTALL_PROFILE="latest"; shift ;;
    --with-settings) WITH_SETTINGS=1; shift ;;
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

PACKAGE_SOURCES="$(python3 - "$PACKAGES_JSON" "$INSTALL_PROFILE" <<'PY'
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

manifest_path = Path(sys.argv[1])
profile = sys.argv[2]

exact_version = re.compile(
    r"(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)"
    r"(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?\Z"
)

git_protocols = {"https", "http", "ssh", "git"}

def valid_git_source(value):
    if not isinstance(value, str) or any(character.isspace() for character in value):
        return False
    if value.startswith("git:") and not value.startswith("git://"):
        shorthand = value[len("git:"):]
        return "/" in shorthand and not shorthand.endswith("/")
    parsed = urlparse(value)
    return parsed.scheme in git_protocols and bool(parsed.netloc and parsed.path.strip("/"))

try:
    data = json.loads(manifest_path.read_text())
except (OSError, json.JSONDecodeError) as exc:
    print(f"Invalid package manifest {manifest_path}: {exc}", file=sys.stderr)
    raise SystemExit(1)

packages = data.get("packages")
if not isinstance(packages, list):
    print("Invalid package manifest: 'packages' must be a list", file=sys.stderr)
    raise SystemExit(1)

errors = []
seen_ids = set()
for index, package in enumerate(packages):
    if not isinstance(package, dict):
        errors.append(f"packages[{index}] must be an object")
        continue

    package_id = package.get("id")
    kind = package.get("kind")
    source = package.get("source")
    latest_source = package.get("latest_source")
    label = package_id or f"packages[{index}]"

    if not isinstance(package_id, str) or not package_id:
        errors.append(f"packages[{index}].id must be a non-empty string")
    elif package_id in seen_ids:
        errors.append(f"duplicate package id: {package_id}")
    else:
        seen_ids.add(package_id)

    if kind not in {"npm", "git"}:
        errors.append(f"{label}.kind must be 'npm' or 'git'")
    if not isinstance(source, str) or not source:
        errors.append(f"{label}.source must be a non-empty string")
    if not isinstance(latest_source, str) or not latest_source:
        errors.append(f"{label}.latest_source must be a non-empty string")

    if kind == "npm" and isinstance(package_id, str) and package_id:
        expected_latest = f"npm:{package_id}"
        pinned_prefix = f"{expected_latest}@"
        version = source[len(pinned_prefix):] if isinstance(source, str) and source.startswith(pinned_prefix) else ""
        if not exact_version.fullmatch(version):
            errors.append(f"{label}.source must pin an exact version as {pinned_prefix}<version>")
        if isinstance(latest_source, str) and latest_source != expected_latest:
            errors.append(f"{label}.latest_source must be {expected_latest}")
    elif kind == "git":
        for field_name, value in (("source", source), ("latest_source", latest_source)):
            if isinstance(value, str) and value and not valid_git_source(value):
                errors.append(f"{label}.{field_name} must be a valid single-line Git source")

    for filter_key in ("extensions", "skills", "prompts", "themes"):
        patterns = package.get(filter_key)
        if patterns is None:
            continue
        if not isinstance(patterns, list) or any(
            not isinstance(pattern, str) or not pattern for pattern in patterns
        ):
            errors.append(f"{label}.{filter_key} must be an array of non-empty strings")

if errors:
    for error in errors:
        print(f"Invalid package manifest: {error}", file=sys.stderr)
    raise SystemExit(1)

field = "latest_source" if profile == "latest" else "source"
for package in packages:
    print(package[field])
PY
)"

log "Pi: $(pi --version 2>/dev/null || echo unknown)"
log "Agent dir: $PI_AGENT_DIR"
log "Install profile: $INSTALL_PROFILE"
mkdir -p "$PI_AGENT_DIR/extensions" "$PI_AGENT_DIR/agents"

# ---------------------------------------------------------------------------
# Install remote packages via `pi install`
# ---------------------------------------------------------------------------
if [[ "$SKIP_PACKAGES" -eq 0 ]]; then
  log "Installing packages from packages.json ($INSTALL_PROFILE)"
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
  done <<< "$PACKAGE_SOURCES"
else
  log "Skipping package installs (--skip-packages)"
fi

# ---------------------------------------------------------------------------
# Apply package resource filters after `pi install` has written package sources.
# This is independent of --with-settings: filters are part of the package profile.
# ---------------------------------------------------------------------------
log "Applying package resource filters"
python3 - "$PACKAGES_JSON" "$SETTINGS_JSON" "$INSTALL_PROFILE" "$DRY_RUN" <<'PY'
import json
import sys
from pathlib import Path

manifest_path = Path(sys.argv[1])
settings_path = Path(sys.argv[2])
profile = sys.argv[3]
dry = sys.argv[4] == "1"
filter_keys = ("extensions", "skills", "prompts", "themes")

manifest = json.loads(manifest_path.read_text())
filtered_packages = [
    package
    for package in manifest.get("packages", [])
    if any(key in package for key in filter_keys)
]

if not filtered_packages:
    print("package filters done (none configured)")
    raise SystemExit(0)

source_field = "latest_source" if profile == "latest" else "source"
if dry:
    for package in filtered_packages:
        keys = ", ".join(key for key in filter_keys if key in package)
        print(f"  [dry-run] filter {package[source_field]} ({keys})")
    raise SystemExit(0)

if not settings_path.exists():
    print(f"  WARN: settings not found at {settings_path}; package filters not applied", file=sys.stderr)
    raise SystemExit(0)

settings = json.loads(settings_path.read_text())
configured = settings.get("packages")
if not isinstance(configured, list):
    print("  WARN: settings packages is not an array; package filters not applied", file=sys.stderr)
    raise SystemExit(0)

def entry_source(entry):
    return entry.get("source", "") if isinstance(entry, dict) else str(entry)

def npm_name(source):
    if not source.startswith("npm:"):
        return None
    bare = source[len("npm:"):]
    if bare.startswith("@"):
        package, separator, version = bare.rpartition("@")
        return package if separator and "/" in package and version else bare
    return bare.split("@", 1)[0]

def same_package(candidate, package):
    selected = package[source_field]
    if candidate in {selected, package["source"], package["latest_source"]}:
        return True
    selected_name = npm_name(selected)
    return selected_name is not None and npm_name(candidate) == selected_name

changed = False
for package in filtered_packages:
    selected = package[source_field]
    match = next(
        (index for index, entry in enumerate(configured) if same_package(entry_source(entry), package)),
        None,
    )
    if match is None:
        print(f"  WARN: {selected} is not configured; filters not applied", file=sys.stderr)
        continue

    current = configured[match]
    replacement = dict(current) if isinstance(current, dict) else {}
    replacement["source"] = selected
    for key in filter_keys:
        if key in package:
            replacement[key] = package[key]
        else:
            replacement.pop(key, None)
    configured[match] = replacement
    changed = True
    print(f"  filtered {selected}")

if changed:
    settings_path.write_text(json.dumps(settings, indent=2) + "\n")
print("package filters done")
PY

# ---------------------------------------------------------------------------
# Copy local extensions (plan-mode, footer-no-model.ts, etc.)
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

def install_path(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if src.is_dir():
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(src, dst)
    else:
        if dst.exists() and dst.is_dir():
            shutil.rmtree(dst)
        shutil.copy2(src, dst)

for item in pkg.get("local_extensions", []):
    src = root / item["path"]
    dst = expand(item["target"])
    print(f"  {src} -> {dst}")
    if not src.exists():
        print(f"  WARN: missing source {src}", file=sys.stderr)
        continue
    if dry:
        continue
    install_path(src, dst)
print("local extensions done")
PY

# ---------------------------------------------------------------------------
# Copy local config files (e.g. spark.json)
# ---------------------------------------------------------------------------
log "Installing local configs"
python3 - "$PACKAGES_JSON" "$ROOT" "$DRY_RUN" <<'PY'
import json, os, shutil, sys
from pathlib import Path

pkg = json.load(open(sys.argv[1]))
root = Path(sys.argv[2])
dry = sys.argv[3] == "1"

def expand(p: str) -> Path:
    return Path(os.path.expanduser(p))

for item in pkg.get("local_configs", []):
    src = root / item["path"]
    dst = expand(item["target"])
    print(f"  {src} -> {dst}")
    if not src.exists():
        print(f"  WARN: missing source {src}", file=sys.stderr)
        continue
    if dry:
        continue
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
print("local configs done")
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
  echo "  4. /plan or Ctrl+Alt+P for plan-mode; /gallery for images; /calm for Calm mode"
  echo "  5. Mid-prompt type \$skill-name for skill autocomplete (pi-inline-skill-complete)"
  echo "  6. /goal <objective> for autonomous goal mode (pi-goal)"
  echo "  7. /fff-health should report pi-fff; find/grep run through FFF override mode"
  echo "  8. Footer should show ↑↓ tokens + cost (footer-no-model); model only on editor border"
  echo
  echo "Optional: re-run with --with-settings to apply theme/model defaults"
  echo "  (values in settings.partial.json; does not touch auth)"
fi
