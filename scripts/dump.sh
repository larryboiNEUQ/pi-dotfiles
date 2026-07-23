#!/usr/bin/env bash
# Snapshot current machine Pi packages into packages.json (+ optional local copies).
# Usage:
#   ./scripts/dump.sh
#   ./scripts/dump.sh --sync-locals
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PACKAGES_JSON="${ROOT}/packages.json"
PI_AGENT_DIR="${PI_CODING_AGENT_DIR:-${HOME}/.pi/agent}"
SETTINGS_JSON="${PI_AGENT_DIR}/settings.json"
NPM_PKG="${PI_AGENT_DIR}/npm/package.json"

SYNC_LOCALS=0
if [[ "${1:-}" == "--sync-locals" ]]; then
  SYNC_LOCALS=1
fi

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || { echo "Missing: $1" >&2; exit 1; }
}
require_cmd python3

if [[ ! -f "$SETTINGS_JSON" ]]; then
  echo "No settings at $SETTINGS_JSON" >&2
  exit 1
fi

python3 - "$SETTINGS_JSON" "$NPM_PKG" "$PACKAGES_JSON" <<'PY'
import json, sys
from datetime import date
from pathlib import Path

settings = json.loads(Path(sys.argv[1]).read_text())
npm_path = Path(sys.argv[2])
out_path = Path(sys.argv[3])

deps = {}
if npm_path.exists():
    deps = json.loads(npm_path.read_text()).get("dependencies", {})

packages = []
for src in settings.get("packages", []):
    if isinstance(src, dict):
        source = src.get("source", "")
    else:
        source = str(src)
    if not source:
        continue

    kind = "other"
    pkg_id = source
    pinned = source

    if source.startswith("npm:"):
        kind = "npm"
        bare = source[len("npm:"):]
        # strip existing version pin for lookup
        name = bare
        if "@" in bare[1:]:  # scoped or versioned
            # npm:@scope/name@1.2.3 or npm:name@1.2.3
            if bare.startswith("@"):
                # @scope/name or @scope/name@version
                parts = bare.rsplit("@", 1)
                if len(parts) == 2 and parts[1][0].isdigit():
                    name, ver = parts[0], parts[1]
                else:
                    name, ver = bare, None
            else:
                if "@" in bare:
                    name, ver = bare.split("@", 1)
                else:
                    name, ver = bare, None
        else:
            name, ver = bare, None

        pkg_id = name
        # prefer installed lock version from npm package.json
        installed = deps.get(name)
        if installed:
            ver = installed.lstrip("^~>=<")
            pinned = f"npm:{name}@{ver}"
        elif ver:
            pinned = f"npm:{name}@{ver}"
        else:
            pinned = f"npm:{name}"
    elif source.startswith("git:") or source.startswith("https://") or source.startswith("http://") or source.startswith("ssh://"):
        kind = "git"
        pkg_id = source.rstrip("/").split("/")[-1].removesuffix(".git")

    packages.append({
        "source": pinned,
        "id": pkg_id,
        "kind": kind,
        "note": ""
    })

# Preserve existing notes / local sections if present
old = {}
if out_path.exists():
    try:
        old = json.loads(out_path.read_text())
    except Exception:
        old = {}

notes = {p.get("id"): p.get("note", "") for p in old.get("packages", [])}
for p in packages:
    if p["id"] in notes and notes[p["id"]]:
        p["note"] = notes[p["id"]]

doc = {
    "$schema_note": "Declarative list of Pi packages for this machine setup. Used by scripts/install.sh and scripts/dump.sh.",
    "meta": {
        "name": old.get("meta", {}).get("name", "larryboiNEUQ/pi-dotfiles"),
        "description": old.get("meta", {}).get("description", "Personal Pi coding-agent plugins + local extensions bootstrap"),
        "pi_version_hint": old.get("meta", {}).get("pi_version_hint", ">=0.81.0"),
        "updated": date.today().isoformat(),
    },
    "packages": packages,
    "local_extensions": old.get("local_extensions", [
        {
            "path": "extensions/plan-mode",
            "target": "~/.pi/agent/extensions/plan-mode",
            "note": "Official Pi monorepo plan-mode example"
        }
    ]),
    "local_agents": old.get("local_agents", [
        {
            "path": "agents",
            "target": "~/.pi/agent/agents",
            "note": "Subagent definitions"
        }
    ]),
    "optional_templates": old.get("optional_templates", []),
}

out_path.write_text(json.dumps(doc, indent=2) + "\n")
print(f"Wrote {out_path}")
for p in packages:
    print(f"  - {p['source']}")
PY

if [[ "$SYNC_LOCALS" -eq 1 ]]; then
  echo "==> Syncing local plan-mode + agents from machine into repo"
  if [[ -d "${PI_AGENT_DIR}/extensions/plan-mode" ]]; then
    rm -rf "${ROOT}/extensions/plan-mode"
    mkdir -p "${ROOT}/extensions"
    cp -R "${PI_AGENT_DIR}/extensions/plan-mode" "${ROOT}/extensions/plan-mode"
    echo "  synced extensions/plan-mode"
  fi
  if [[ -d "${PI_AGENT_DIR}/agents" ]]; then
    mkdir -p "${ROOT}/agents"
    cp -f "${PI_AGENT_DIR}/agents/"*.md "${ROOT}/agents/" 2>/dev/null || true
    echo "  synced agents/*.md"
  fi
fi

echo "Done. Review packages.json, then commit & push."
