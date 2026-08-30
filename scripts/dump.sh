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

filter_keys = ("extensions", "skills", "prompts", "themes")
packages = []
for src in settings.get("packages", []):
    if isinstance(src, dict):
        source = src.get("source", "")
        filters = {key: src[key] for key in filter_keys if key in src}
    else:
        source = str(src)
        filters = {}
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
        "note": "",
        **filters,
    })

# Preserve existing notes / local sections if present
old = {}
if out_path.exists():
    try:
        old = json.loads(out_path.read_text())
    except Exception:
        old = {}

notes = {p.get("id"): p.get("note", "") for p in old.get("packages", [])}
latest_sources = {
    p.get("id"): p.get("latest_source", "")
    for p in old.get("packages", [])
}
for index, package in enumerate(packages):
    package_id = package["id"]
    latest_source = latest_sources.get(package_id)
    if not latest_source:
        latest_source = f"npm:{package_id}" if package["kind"] == "npm" else package["source"]
    entry = {
        "source": package["source"],
        "latest_source": latest_source,
        "id": package_id,
        "kind": package["kind"],
        "note": notes.get(package_id) or package["note"],
    }
    for filter_key in filter_keys:
        if filter_key in package:
            entry[filter_key] = package[filter_key]
    packages[index] = entry

doc = {
    "$schema_note": "Each package has a pinned source, an unversioned latest_source, and optional Pi resource filters. Used by scripts/install.sh and scripts/dump.sh.",
    "meta": {
        "name": old.get("meta", {}).get("name", "larryboiNEUQ/pi-dotfiles"),
        "description": old.get("meta", {}).get(
            "description",
            "Shared Pi coding-agent plugin setup (packages + plan-mode + agents)",
        ),
        "pi_version_hint": old.get("meta", {}).get("pi_version_hint", ">=0.81.0"),
        "updated": date.today().isoformat(),
    },
    "packages": packages,
    "local_extensions": old.get("local_extensions", [
        {
            "path": "extensions/plan-mode",
            "target": "~/.pi/agent/extensions/plan-mode",
            "note": "Official Pi monorepo plan-mode example"
        },
        {
            "path": "extensions/footer-no-model.ts",
            "target": "~/.pi/agent/extensions/footer-no-model.ts",
            "note": "Stock token/cost/context footer without right-side model"
        }
    ]),
    "local_configs": old.get("local_configs", [
        {
            "path": "configs/spark.json",
            "target": "~/.pi/agent/spark.json",
            "note": "Disable pi-spark footer so footer-no-model owns the status bar"
        },
        {
            "path": "configs/pi-fff.json",
            "target": "~/.pi/agent/pi-fff.json",
            "note": "Run pi-fff in override mode without root or home scanning"
        }
    ]),
    "local_agents": old.get("local_agents", [
        {
            "path": "agents",
            "target": "~/.pi/agent/agents",
            "note": "Subagent definitions"
        }
    ]),
}

out_path.write_text(json.dumps(doc, indent=2) + "\n")
print(f"Wrote {out_path}")
for p in packages:
    print(f"  - {p['source']}")
PY

if [[ "$SYNC_LOCALS" -eq 1 ]]; then
  echo "==> Syncing local extensions / configs / agents from machine into repo"
  if [[ -d "${PI_AGENT_DIR}/extensions/plan-mode" ]]; then
    rm -rf "${ROOT}/extensions/plan-mode"
    mkdir -p "${ROOT}/extensions"
    cp -R "${PI_AGENT_DIR}/extensions/plan-mode" "${ROOT}/extensions/plan-mode"
    echo "  synced extensions/plan-mode"
  fi
  if [[ -f "${PI_AGENT_DIR}/extensions/footer-no-model.ts" ]]; then
    mkdir -p "${ROOT}/extensions"
    cp -f "${PI_AGENT_DIR}/extensions/footer-no-model.ts" "${ROOT}/extensions/footer-no-model.ts"
    echo "  synced extensions/footer-no-model.ts"
  fi
  if [[ -f "${PI_AGENT_DIR}/spark.json" ]]; then
    mkdir -p "${ROOT}/configs"
    cp -f "${PI_AGENT_DIR}/spark.json" "${ROOT}/configs/spark.json"
    echo "  synced configs/spark.json"
  fi
  if [[ -f "${PI_AGENT_DIR}/pi-fff.json" ]]; then
    mkdir -p "${ROOT}/configs"
    cp -f "${PI_AGENT_DIR}/pi-fff.json" "${ROOT}/configs/pi-fff.json"
    echo "  synced configs/pi-fff.json"
  fi
  if [[ -d "${PI_AGENT_DIR}/agents" ]]; then
    mkdir -p "${ROOT}/agents"
    cp -f "${PI_AGENT_DIR}/agents/"*.md "${ROOT}/agents/" 2>/dev/null || true
    echo "  synced agents/*.md"
  fi
fi

echo "Done. Review packages.json, then commit & push."
