#!/usr/bin/env bash
set -euo pipefail
CODE="$(cat <<'PY'
import os
from pathlib import Path
import subprocess
import sys
from urllib.parse import urlsplit


def fail(message):
    print(message, file=sys.stderr)
    sys.exit(1)


def git(*args):
    try:
        result = subprocess.run(['git', *args], stdin=subprocess.DEVNULL, capture_output=True, timeout=120, env=dict(os.environ, GIT_OPTIONAL_LOCKS='0'))
    except (OSError, subprocess.TimeoutExpired):
        fail('Git unavailable or timed out; installation not started')
    if result.returncode:
        fail('Git operation failed; installation not started')
    return result.stdout.decode(errors='replace').strip()


url = os.environ.get('PI_DOTFILES_URL', 'https://github.com/larryboiNEUQ/pi-dotfiles.git')
try:
    parsed = urlsplit(url)
except ValueError:
    fail('Invalid repository URL')
if any(c.isspace() for c in url) or parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
    fail('Repository URL must be HTTPS without credentials')
dest = Path(os.environ.get('PI_DOTFILES_DIR', str(Path.home() / '.pi-dotfiles'))).absolute()
if '..' in dest.parts or any(p.is_symlink() for p in (dest, *dest.parents) if str(p) not in ('/var', '/tmp')):
    fail('Unsafe destination')
preview = '--dry-run' in sys.argv[1:]
if dest.exists():
    if not dest.is_dir() or not (dest / '.git').is_dir() or (dest / '.git').is_symlink():
        fail('Destination is not a repository; existing content retained')
    if preview:
        print('Would verify origin and fast-forward repository; no subprocesses or changes made')
        sys.exit(0)
    if git('-C', str(dest), 'rev-parse', '--is-inside-work-tree') != 'true':
        fail('Destination is not a Git work tree')
    origin = git('-C', str(dest), 'remote', 'get-url', 'origin')
    if origin != url:
        fail('Destination origin differs; existing content retained')
    if git('-C', str(dest), 'status', '--porcelain', '--untracked-files=all'):
        fail('Destination is dirty; existing content retained')
    git('-C', str(dest), 'pull', '--ff-only')
else:
    if preview:
        print('Would clone repository and install; no changes made')
        sys.exit(0)
    git('clone', '--', url, str(dest))
script = dest / 'scripts' / 'install.sh'
if not script.is_file() or script.is_symlink() or script.parent.is_symlink():
    fail('Install adapter missing; installation not started')
os.execvp('bash', ['bash', str(script), *sys.argv[1:]])
PY
)"
exec python3 -c "$CODE" "$@"
