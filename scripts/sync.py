#!/usr/bin/env python3
"""Synchronize only the resources declared in packages.json."""
import argparse
import copy
import difflib
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import signal
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from urllib.parse import unquote, urlsplit


ABSENT = object()
FILTERS = ('extensions', 'skills', 'prompts', 'themes')
SCOPES = {'public', 'personal'}
SECRET_KEY = re.compile(r'(?i)(token|secret|password|cookie|credential|api[_-]?key|^auth$|device)')
SECRET_FILE = re.compile(r'(?i)(auth|credential|trust|session|cache|logs?|runtime|backup|install|device|token|secret|password|cookie|api[_-]?key|models(?:-store)?\.json|config-sync|\.before-|\.bak(?:$|[.-])|^\.env(?:$|[.-])|^\.netrc$|^id_(?:rsa|ed25519)$|\.(?:pem|key)$)')
IDENTIFIER = re.compile(r'(?:@[a-zA-Z0-9_.-]+/)?[a-zA-Z0-9][a-zA-Z0-9_.-]*\Z')


class SyncError(Exception):
    pass


def require(condition, message):
    if not condition:
        raise SyncError(message)


def pairs(items):
    result = {}
    for key, value in items:
        require(key not in result, 'duplicate JSON key')
        result[key] = value
    return result

def decode(data):
    try:
        return json.loads(data, object_pairs_hook=pairs,
                          parse_constant=lambda _: (_ for _ in ()).throw(SyncError('nonfinite JSON number')))
    except (ValueError, UnicodeError):
        raise SyncError('invalid JSON') from None

def encode(value):
    return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode()


def relative(value):
    require(isinstance(value, str) and value and '\\' not in value and '\x00' not in value,
            'invalid relative path')
    p = PurePosixPath(value)
    require(not p.is_absolute() and all(x not in ('', '.', '..') for x in value.split('/')),
            'path must remain within its root')
    return value


def boundary(root, rel, directory=False):
    relative(rel)
    require(not any(p.is_symlink() for p in (root, *root.parents) if str(p) not in ('/var', '/tmp')),
            'unsafe root link')
    require(not root.exists() or root.is_dir(), 'invalid root directory')
    current = root
    for i, part in enumerate(PurePosixPath(rel).parts):
        current /= part
        try:
            info = current.lstat()
        except FileNotFoundError:
            continue
        require(not stat.S_ISLNK(info.st_mode), 'unsafe symlink')
        last = i == len(PurePosixPath(rel).parts) - 1
        if last and not directory:
            require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1,
                    'unsafe hardlink or special file')
        else:
            require(stat.S_ISDIR(info.st_mode), 'unsafe directory')
    return root / rel


def read_bytes(root, rel):
    path = boundary(root, rel)
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
    except FileNotFoundError:
        return ABSENT
    with os.fdopen(fd, 'rb') as file:
        info = os.fstat(file.fileno())
        require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1, 'unsafe read target')
        return file.read()


def pointer(value):
    require(isinstance(value, str) and value.startswith('/') and not re.search(r'~(?![01])', value),
            'invalid JSON pointer')
    parts = [x.replace('~1', '/').replace('~0', '~') for x in value[1:].split('/')]
    require(all(x and x not in ('.', '..') and not SECRET_KEY.search(x) for x in parts),
            'unsafe JSON pointer')
    return parts


def get_field(value, ptr):
    for key in pointer(ptr):
        if not isinstance(value, dict) or key not in value:
            return ABSENT
        value = value[key]
    return value

def set_field(value, ptr, incoming):
    parts = pointer(ptr)
    for key in parts[:-1]:
        require(key not in value or isinstance(value[key], dict), 'JSON pointer crosses a non-object')
        if key not in value:
            if incoming is ABSENT:
                return
            value[key] = {}
        value = value[key]
    if incoming is ABSENT:
        value.pop(parts[-1], None)
    else:
        value[parts[-1]] = copy.deepcopy(incoming)

def digest(value, ordered=False):
    content = {'present': False} if value is ABSENT else {'present': True, 'value': value}
    raw = json.dumps(content, ensure_ascii=False, separators=(',', ':'),
                     sort_keys=not ordered, allow_nan=False).encode()
    return hashlib.sha256(raw).hexdigest()


def safe_name(value):
    parts = str(value).split('/')
    return '/'.join('[redacted]' if SECRET_KEY.search(p) else re.sub(r'[^a-zA-Z0-9@_$:.!#~-]', '?', p)
                    for p in parts)


def git_source(source):
    require(isinstance(source, str) and not any(c.isspace() for c in source), 'invalid Git source')
    url = source[4:] if source.startswith('git:') else source
    if '://' not in url:
        url = 'https://' + url
    parsed = urlsplit(url)
    require(parsed.scheme == 'https' and parsed.hostname and not parsed.username and not parsed.password
            and not parsed.query and not parsed.fragment, 'Git URL must be HTTPS without credentials')
    path = parsed.path.lstrip('/').split('@', 1)[0].removesuffix('.git')
    relative(unquote(path))
    require(len(path.split('/')) >= 2 and re.fullmatch(r'[a-zA-Z0-9_.-]+', parsed.netloc), 'invalid Git repository')
    return parsed.hostname.lower(), path, 'https://' + parsed.netloc + '/' + path


def git_identity_parts(source):
    try:
        host, path, _ = git_source(source)
        return host, path
    except (SyncError, ValueError):
        pass
    url = source[4:] if source.startswith('git:') else source
    if url.startswith('ssh://'):
        parsed = urlsplit(url)
        host, path = (parsed.hostname or '').lower(), parsed.path.lstrip('/')
    else:
        match = re.fullmatch(r'(?:[a-zA-Z0-9_.-]+@)?([a-zA-Z0-9_.-]+):(.+)', url)
        if not match:
            return None
        host, path = match.group(1).lower(), match.group(2)
    path = path.split('@', 1)[0].removesuffix('.git')
    if not host or len(path.split('/')) < 2 or not all(path.split('/')):
        return None
    return host, path


def identity(source):
    if not isinstance(source, str):
        return None
    if source.startswith('npm:'):
        name = source[4:]
        if '@' in name[1:]:
            name = name.rsplit('@', 1)[0]
        return 'npm:' + name if IDENTIFIER.fullmatch(name) else None
    if source.startswith(('git:', 'https://', 'http://', 'ssh://')) or re.match(r'[a-zA-Z0-9_.-]+@[a-zA-Z0-9_.-]+:', source):
        parts = git_identity_parts(source)
        return 'git:' + parts[0] + '/' + parts[1] if parts else None
    return None


def source_of(entry):
    return entry.get('source') if isinstance(entry, dict) else entry

def package_identity(package):
    return identity(package['source'])

def declared_source(package):
    return package['source'] + '@' + package['branch'] if package['kind'] == 'git' else package['source']

def canonical_declared_source(package):
    return package['source'] if package['kind'] == 'npm' else git_source(package['source'])[2] + '@' + package['branch']

def canonical_local_source(package, entry):
    if entry is ABSENT:
        return ABSENT
    source = source_of(entry)
    require(identity(source) == package_identity(package), 'managed source identity changed')
    if package['kind'] == 'npm':
        return package['source']
    parts = git_identity_parts(source)
    require(parts is not None, 'invalid local Git source')
    url = 'https://' + parts[0] + '/' + parts[1]
    rest = source[4:] if source.startswith('git:') else source
    if rest.startswith('ssh://'):
        tail = urlsplit(rest).path
    elif re.match(r'[a-zA-Z0-9_.-]+@[a-zA-Z0-9_.-]+:', rest):
        tail = rest.split(':', 1)[1]
    else:
        tail = rest
    ref = tail.rsplit('@', 1)[1] if '@' in tail else package.get('defaultBranch')
    if ref is not None:
        ref = ref.removeprefix('refs/heads/')
        require(re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_./-]*', ref) and '..' not in ref and not ref.endswith('/'),
                'invalid local Git ref')
    return url + ('@' + ref if ref is not None else '')

def filter_value(entry):
    return ABSENT if entry is ABSENT else {k: entry[k] for k in FILTERS if isinstance(entry, dict) and k in entry}

def validate_filters(value):
    for key in FILTERS:
        if key in value:
            require(isinstance(value[key], list) and all(isinstance(x, str) and '\x00' not in x for x in value[key]),
                    'package filters must be string arrays')

def validate_value(resource, ptr, value):
    if value is ABSENT:
        return
    if ptr.endswith(('/api_url','/$schema')):
        require(isinstance(value, str) and not any(c.isspace() for c in value), 'invalid URL')
        url = urlsplit(value)
        require(url.scheme == 'https' and url.hostname and not url.username and not url.password
                and not url.query and not url.fragment, 'URL must be HTTPS without credentials')
    if resource['id'] == 'spark' and ptr == '/footer':
        require(value is False, 'Spark footer object needs explicit leaf declarations')
    if resource['id'] == 'calm':
        require(value.strip() in ('on', 'off'), 'Calm must contain on or off')
    require(not isinstance(value, dict) or ptr.endswith('/permission'),
            'managed JSON leaf contains an undeclared object')
    if ptr.endswith('/permission'):
        require(isinstance(value, dict), 'permission must be an ordered rule map')
        for rule in value.values():
            if isinstance(rule, str):
                require(rule in ('allow', 'deny', 'ask'), 'invalid permission action')
                continue
            require(isinstance(rule, dict), 'permission surface must be an action or pattern map')
            for action in rule.values():
                if isinstance(action, str):
                    require(action in ('allow', 'deny', 'ask'), 'invalid permission action')
                else:
                    require(isinstance(action, dict) and action.get('action') == 'deny'
                            and not (action.keys() - {'action', 'reason'})
                            and ('reason' not in action or isinstance(action['reason'], str)
                                 and len(action['reason']) <= 500), 'invalid permission deny object')
        return
    if isinstance(value, (dict, list)):
        def walk(item):
            if isinstance(item, dict):
                require(not any(SECRET_KEY.search(k) for k in item), 'secret-looking key within managed value')
                for child in item.values():
                    walk(child)
            elif isinstance(item, list):
                for child in item:
                    walk(child)
        walk(value)


def registry(repo):
    data = decode(read_bytes(repo, 'packages.json'))
    required = {'schemaVersion', 'packages', 'resources', 'external', 'excluded', 'orphans', 'removals'}
    require(isinstance(data, dict) and required <= data.keys() and type(data['schemaVersion']) is int and data['schemaVersion'] == 2,
            'packages.json requires schemaVersion 2 registry')
    require(not (data.keys() - required - {'meta'}), 'unknown registry section')
    require(all(isinstance(data[k], list) for k in required - {'schemaVersion'}), 'registry sections must be lists')
    seen, paths, package_ids = set(), set(), set()
    for package in data['packages']:
        require(isinstance(package, dict), 'invalid package')
        require(not (package.keys() - {'id', 'kind', 'source', 'branch', 'defaultBranch', 'legacyRefs', 'scope', 'note', *FILTERS}),
                'unknown package property')
        pid = package.get('id')
        require(isinstance(pid, str) and IDENTIFIER.fullmatch(pid) and pid not in seen, 'invalid or duplicate identifier')
        seen.add(pid)
        require(package.get('scope') in SCOPES and package.get('kind') in ('npm', 'git'), 'invalid package scope or kind')
        if package['kind'] == 'npm':
            require(package.get('source') == 'npm:' + pid and not {'branch', 'defaultBranch', 'legacyRefs'} & package.keys(),
                    'npm source must be unversioned')
        else:
            git_source(package.get('source'))
            require('@' not in package['source'] and isinstance(package.get('legacyRefs', []), list), 'invalid Git source or legacyRefs')
            refs = [package.get('branch'), *([package['defaultBranch']] if 'defaultBranch' in package else []), *package.get('legacyRefs', [])]
            require(all(isinstance(ref, str) and re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_./-]*', ref)
                        and '..' not in ref and not ref.endswith('/') for ref in refs), 'explicit safe Git branch required')
        require(package_identity(package) not in package_ids, 'duplicate package source identity')
        package_ids.add(package_identity(package))
        validate_filters(package)
    for resource in data['resources']:
        require(isinstance(resource, dict) and not (resource.keys() - {'id', 'kind', 'repo', 'target', 'root', 'scope', 'fields'}), 'invalid resource')
        rid = resource.get('id')
        require(isinstance(rid, str) and IDENTIFIER.fullmatch(rid) and rid not in seen, 'invalid or duplicate identifier')
        seen.add(rid)
        require(resource.get('kind') in ('json', 'text') and resource.get('root') in ('agent', 'pi'), 'invalid resource kind or root')
        for key in ('repo', 'target'):
            relative(resource.get(key))
            require(not any(SECRET_FILE.search(x) for x in PurePosixPath(resource[key]).parts), 'excluded filename cannot be managed')
        for location in (('repo', resource['repo']), (resource['root'], resource['target'])):
            require(location not in paths, 'duplicate resource path')
            paths.add(location)
        if resource['kind'] == 'json':
            require(isinstance(resource.get('fields'), dict) and resource['fields'] and 'scope' not in resource,
                    'JSON resources require pointer scope declarations')
            fields = list(resource['fields'])
            for ptr, scope in resource['fields'].items():
                pointer(ptr)
                require(scope in SCOPES and not any(other != ptr and other.startswith(ptr + '/') for other in fields),
                        'invalid or overlapping JSON pointer')
        else:
            require(resource.get('scope') in SCOPES and 'fields' not in resource, 'text resources require scope')
    for section in ('external', 'excluded', 'orphans'):
        for entry in data[section]:
            require(isinstance(entry, dict) and not (entry.keys() - {'root', 'target', 'tree', 'fields', 'note', 'package'}), 'invalid classification')
            if 'package' in entry:
                require(isinstance(entry['package'], str) and entry['package'] not in seen, 'invalid or managed excluded package')
                continue
            require(entry.get('root') in ('agent', 'pi') and ('tree' not in entry or isinstance(entry['tree'], bool)), 'invalid classification')
            relative(entry.get('target'))
            owned = [r for r in data['resources'] if r['root'] == entry['root']
                     and (r['target'] == entry['target'] or entry.get('tree') and r['target'].startswith(entry['target'] + '/'))]
            if 'fields' in entry:
                require(isinstance(entry['fields'], list) and all(isinstance(x, str) and x.startswith('/') for x in entry['fields']), 'invalid excluded fields')
                for resource in owned:
                    require(not any(p == q or p.startswith(q + '/') or q.startswith(p + '/')
                                    for p in resource.get('fields', {}) for q in entry['fields']), 'classified field is managed')
            else:
                require(not owned, 'classified file or tree is managed')
    resources = {r['id']: r for r in data['resources']}
    packages = {p['id']: p for p in data['packages']}
    removals, removal_targets = set(), set()
    for record in data['removals']:
        require(isinstance(record, dict) and not (record.keys() - {'id', 'action', 'resource', 'field'}), 'invalid removal record')
        rid, target = record.get('id'), record.get('resource')
        require(isinstance(rid, str) and IDENTIFIER.fullmatch(rid) and rid not in removals, 'invalid or duplicate removal id')
        require((target, record.get('field')) not in removal_targets, 'duplicate removal target')
        removals.add(rid)
        removal_targets.add((target, record.get('field')))
        if record.get('action') == 'uninstall-package':
            require(target in packages and 'field' not in record, 'removal must name a managed package')
        elif record.get('action') == 'delete-file':
            require(target in resources and resources[target]['kind'] == 'text' and 'field' not in record, 'file removal must name a managed text resource')
        elif record.get('action') == 'restore-default':
            field = record.get('field')
            require(target in resources and field in resources[target].get('fields', {})
                    or target in packages and field in {'/' + k for k in FILTERS if k in packages[target]}, 'default removal must name a managed field')
        else:
            raise SyncError('invalid removal action')
    return data


@dataclass
class Unit:
    key: str
    resource: dict
    pointer: str
    scope: str
    local: object
    repo: object
    package: bool = False
    removal: object = None
    filter_keys: tuple = ()
    source_unit: bool = False

    def hash(self, value):
        return digest(value, self.pointer.endswith('/permission'))


class Snapshot:
    def __init__(self, roots):
        self.roots, self.bytes, self.json = roots, {}, {}

    def raw(self, side, path):
        if (side, path) not in self.bytes:
            self.bytes[(side, path)] = read_bytes(self.roots[side], path)
        return self.bytes[(side, path)]

    def document(self, side, path):
        if (side, path) not in self.json:
            raw = self.raw(side, path)
            value = {} if raw is ABSENT else decode(raw)
            require(isinstance(value, dict), 'JSON document must be an object')
            self.json[(side, path)] = value
        return self.json[(side, path)]

    def unchanged(self, omit=()):
        for (side, path), observed in self.bytes.items():
            if (side, path) not in omit:
                require(read_bytes(self.roots[side], path) == observed, 'concurrent change before transaction')


def package_entries(settings):
    entries = settings.get('packages', [])
    require(isinstance(entries, list) and all(isinstance(x, (str, dict)) for x in entries), 'invalid package registrations')
    return entries

def find_entry(entries, package):
    matches = [x for x in entries if identity(source_of(x)) == package_identity(package)]
    require(len(matches) <= 1, 'duplicate local package identity')
    return matches[0] if matches else ABSENT

def unknown_fields(value, fields, excluded, prefix=''):
    if not isinstance(value, dict):
        return []
    found = []
    for key, child in value.items():
        ptr = prefix + '/' + key.replace('~', '~0').replace('/', '~1')
        if ptr in fields or any(ptr == x or ptr.startswith(x + '/') for x in excluded):
            continue
        found.extend(unknown_fields(child, fields, excluded, ptr)
                     if any(x.startswith(ptr + '/') for x in list(fields) + list(excluded)) else [safe_name(ptr)])
    return found

def selected_fields(resource, public):
    fields = resource['fields'] if resource['kind'] == 'json' else {'': resource['scope']}
    return {p: s for p, s in fields.items() if not public or s == 'public'}

def discover(data, snap, public):
    pending = []
    classified = data['external'] + data['excluded'] + data['orphans']
    known = {(r['root'], r['target']) for r in data['resources']} | {('agent', 'settings.json')}
    def recognized(side, path):
        if (side, path) in known or SECRET_FILE.search(Path(path).name):
            return True
        return any(e.get('root') == side and 'target' in e and 'fields' not in e
                   and (e['target'] == path or e.get('tree') and path.startswith(e['target'] + '/')) for e in classified)
    for side in ('agent', 'pi'):
        root = snap.roots[side]
        for folder in ('', 'agents', 'extensions') if side == 'agent' else ('',):
            base = root / folder
            if not base.is_dir() or base.is_symlink():
                continue
            for child in sorted(base.iterdir()):
                path = str(child.relative_to(root))
                if recognized(side, path) or side == 'agent' and folder == '' and path in ('agents', 'extensions'):
                    continue
                if child.is_dir() and folder == 'extensions' and not child.is_symlink():
                    pending.extend(side + '/' + safe_name(str(sub.relative_to(root)))
                                   for sub in sorted(child.iterdir()) if not recognized(side, str(sub.relative_to(root))))
                else:
                    pending.append(side + '/' + safe_name(path))
    for resource in data['resources']:
        if resource['kind'] != 'json' or not selected_fields(resource, public):
            continue
        excluded = [p for e in classified if e.get('root') == resource['root']
                    and e.get('target') == resource['target'] for p in e.get('fields', [])]
        if resource['target'] == 'settings.json' and resource['root'] == 'agent':
            excluded += ['/packages', '/extensions']
        for ptr in unknown_fields(snap.document(resource['root'], resource['target']), resource['fields'], excluded):
            pending.append(resource['id'] + '#' + ptr)
    ids = {package_identity(p) for p in data['packages']}
    excluded_ids = {'npm:' + e['package'] for e in classified if 'package' in e}
    for entry in package_entries(snap.document('agent', 'settings.json')):
        ident = identity(source_of(entry))
        if ident and ident not in ids | excluded_ids:
            pending.append('package/' + safe_name(ident))
        if ident is None:
            pending.append('package/[unrecognized]')
        package = next((p for p in data['packages'] if package_identity(p) == ident), None)
        if package and isinstance(entry, dict):
            pending.extend('package/' + package['id'] + '#/' + safe_name(key)
                           for key in entry if key != 'source' and (key not in FILTERS or key not in package))
    return sorted(set(pending))

def units(data, snap, public):
    result = []
    for resource in data['resources']:
        fields = selected_fields(resource, public)
        if not fields:
            continue
        for ptr, scope in fields.items():
            if ptr:
                local = get_field(snap.document(resource['root'], resource['target']), ptr)
                repo = get_field(snap.document('repo', resource['repo']), ptr)
            else:
                local, repo = snap.raw(resource['root'], resource['target']), snap.raw('repo', resource['repo'])
                try:
                    local = local.decode() if local is not ABSENT else ABSENT
                    repo = repo.decode() if repo is not ABSENT else ABSENT
                except UnicodeError:
                    raise SyncError('managed text must be UTF-8') from None
            validate_value(resource, ptr, local)
            validate_value(resource, ptr, repo)
            result.append(Unit(resource['id'] + '#' + ptr, resource, ptr, scope, local, repo))
        if resource['kind'] == 'json':
            require(not unknown_fields(snap.document('repo', resource['repo']), resource['fields'], []),
                    'repository JSON contains undeclared fields')
    entries = package_entries(snap.document('agent', 'settings.json'))
    for package in data['packages']:
        if public and package['scope'] != 'public':
            continue
        local = filter_value(find_entry(entries, package))
        if local is not ABSENT:
            validate_filters(local)
        declared = tuple(k for k in FILTERS if k in package)
        reset = {r['field'][1:] for r in data['removals'] if r['action'] == 'restore-default' and r['resource'] == package['id']}
        active = tuple(k for k in declared if k not in reset)
        projection = ABSENT if local is ABSENT else {k: local[k] for k in active if k in local}
        result.append(Unit('package/' + package['id'], package, '', package['scope'], projection,
                           {k: package[k] for k in active}, True, filter_keys=active))
        result.append(Unit('package/' + package['id'] + '#/source', package, '/source', package['scope'],
                           canonical_local_source(package, find_entry(entries, package)),
                           canonical_declared_source(package), True, source_unit=True))
        for key in declared:
            result.append(Unit('package/' + package['id'] + '#/' + key, package, '/' + key, package['scope'],
                               local.get(key, ABSENT) if local is not ABSENT else ABSENT, package[key], True))
    return result


@dataclass
class Change:
    unit: Unit
    incoming: object
    state: str
    write: bool
    confirm: bool = False

def plan(unit, command, baseline):
    local, repo = unit.local, unit.repo
    source, dest = (local, repo) if command == 'export' else (repo, local)
    if unit.hash(local) == unit.hash(repo):
        return Change(unit, source, 'equal', False)
    if source is ABSENT:
        return Change(unit, source, 'missing source, preserve destination', False)
    base = baseline.get(unit.key)
    if unit.source_unit and base is None and unit.resource['kind'] == 'git' and local is not ABSENT:
        ref = local.rsplit('@', 1)[1] if '@' in local else None
        if ref in unit.resource.get('legacyRefs', []):
            return Change(unit, source, 'declared legacy ref normalization pending', command != 'export')
    if base is None:
        return Change(unit, source, 'first difference' if dest is not ABSENT else 'create', True, dest is not ABSENT)
    src_changed, dst_changed = unit.hash(source) != base, unit.hash(dest) != base
    if src_changed and dst_changed:
        return Change(unit, source, 'conflict', True, True)
    return Change(unit, source, 'destination edit preserved', False) if dst_changed else Change(unit, source, 'source edit', True)

def removal_plan(unit, record, baseline):
    unit.removal = record
    if unit.local is ABSENT:
        return Change(unit, ABSENT, 'removal already absent', False)
    changed = baseline.get(unit.key) is not None and unit.hash(unit.local) != baseline.get(unit.key)
    return Change(unit, ABSENT, 'deletion conflict' if changed else 'explicit removal', True, changed)

def show_difference(change, mode):
    unit = change.unit
    destination, incoming = ('repo', 'local') if mode == 'export' else ('local', 'repo')
    old, new = (unit.repo if mode == 'export' else unit.local), change.incoming
    sensitive = unit.scope == 'personal' or unit.resource['id'] in ('permission', 'safe-allow', 'langsmith')
    def summary(value):
        if value is ABSENT:
            return '<absent>'
        if sensitive:
            return '<managed content sha256=' + unit.hash(value) + '>'
        text = json.dumps(value, ensure_ascii=False)
        return text[:600] + (' [truncated]' if len(text) > 600 else '')
    print('Destination (' + destination + '): ' + summary(old))
    print('Incoming (' + incoming + '): ' + summary(new))
    if not sensitive and not unit.package and not unit.pointer and isinstance(old, str) and isinstance(new, str):
        diff = difflib.unified_diff(old.splitlines(), new.splitlines(),
            fromfile='destination (' + destination + ')', tofile='incoming (' + incoming + ')', lineterm='')
        for index, line in enumerate(diff):
            if index >= 80:
                print('[diff truncated]')
                break
            print(line[:600])

def confirm(changes, mode):
    for change in changes:
        if not change.confirm:
            continue
        require(sys.stdin.isatty(), 'confirmation required; run in a terminal; no changes made')
        print('Resolve ' + safe_name(change.unit.key))
        show_difference(change, mode)
        choice = input('Choice [write/keep/abort]: ').strip().lower()
        require(choice in ('write','keep'), 'confirmation aborted; no changes made')
        change.write = choice == 'write'
    removals = [c for c in changes if c.unit.removal and c.write]
    if removals:
        require(sys.stdin.isatty(), 'removal confirmation required; run in a terminal; no changes made')
        for change in removals:
            print('remove ' + safe_name(change.unit.removal['id']) + ' ' + safe_name(change.unit.key))
        require(input('Confirm [yes/no]: ').strip().lower() == 'yes', 'removal aborted; no changes made')


def command(args, timeout=120):
    env = dict(os.environ, GIT_OPTIONAL_LOCKS='0') if args[0] == 'git' else None
    try:
        proc = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, start_new_session=True, env=env)
    except OSError:
        raise SyncError('external command unavailable') from None
    try:
        out, _ = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except OSError:
            pass
        proc.wait()
        raise SyncError('external command timed out') from None
    require(proc.returncode == 0, 'external command failed with exit ' + str(proc.returncode))
    return out.decode(errors='replace')


def writable_parent(path):
    parent = path.parent
    while not parent.exists():
        parent = parent.parent
    require(parent.is_dir() and os.access(parent,os.W_OK | os.X_OK), 'destination parent is not writable')


def checkout_guard(package, roots):
    host, path, _ = git_source(package['source'])
    checkout = boundary(roots['agent'], 'git/' + host + '/' + path, directory=True)
    if not checkout.exists():
        return
    status = command(['git', '-C', str(checkout), 'status', '--porcelain', '--untracked-files=all', '--ignored=matching'])
    ignored_ok = ('!! node_modules/', '!! package-lock.json')
    dirty = [line for line in status.splitlines()
             if line != '?? package-lock.json' and line not in ignored_ok]
    require(not dirty, 'unsafe Git checkout for ' + package['id'])
    origin = command(['git', '-C', str(checkout), 'remote', 'get-url', 'origin']).strip()
    require(identity(origin) == 'git:' + host + '/' + path, 'checkout origin differs for ' + package['id'])
    branch = command(['git', '-C', str(checkout), 'rev-parse', '--abbrev-ref', 'HEAD']).strip()
    require(branch == package['branch'], 'checkout on unexpected branch for ' + package['id'])
    tracking = 'origin/' + package['branch']
    command(['git', '-C', str(checkout), 'rev-parse', '--verify', tracking])
    ahead = command(['git', '-C', str(checkout), 'rev-list', '--count', tracking + '..HEAD']).strip()
    require(ahead == '0', 'local commits would be discarded for ' + package['id'])


def package_preflight(packages, roots, network):
    for package in packages:
        if package['kind'] == 'npm':
            boundary(roots['agent'],'npm',directory=True)
            boundary(roots['agent'],'npm/node_modules',directory=True)
            boundary(roots['agent'],'npm/node_modules/' + package['id'],directory=True)
            for filename in ('package.json','package-lock.json'):
                boundary(roots['agent'],'npm/' + filename)
            continue
        checkout_guard(package, roots)
        if network:
            _, _, url = git_source(package['source'])
            output = command(['git','ls-remote','--heads',url,'refs/heads/' + package['branch']])
            require(any(line.endswith('\trefs/heads/' + package['branch']) for line in output.splitlines()),
                    'declared Git branch absent for ' + package['id'])


def patch_entry(settings, package, filters, normalize=False, create=False):
    entries, wanted = package_entries(settings), package_identity(package)
    matching = [e for e in entries if identity(source_of(e)) == wanted]
    if not matching and not create:
        return
    merged = {}
    for entry in matching:
        if isinstance(entry, dict):
            merged.update(entry)
    merged['source'] = declared_source(package) if normalize or not matching else source_of(matching[0])
    for key in FILTERS:
        merged.pop(key, None)
    if filters is not ABSENT:
        merged.update(filters)
    replacement = merged if len(merged) > 1 else merged['source']
    output, inserted = [], False
    for entry in entries:
        if identity(source_of(entry)) == wanted:
            if not inserted:
                output.append(replacement)
                inserted = True
        else:
            output.append(entry)
    if not inserted:
        output.append(replacement)
    settings['packages'] = output


def atomic_write(root, rel, content, expected, mode=0o600):
    path = boundary(root, rel)
    require(read_bytes(root, rel) == expected, 'concurrent change refused')
    if expected is not ABSENT:
        require(stat.S_IMODE(path.stat().st_mode) == mode, 'concurrent permission change refused')
    if content is ABSENT:
        if expected is not ABSENT:
            path.unlink()
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    boundary(root, rel)
    fd, temp = tempfile.mkstemp(prefix='.sync-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as out:
            out.write(content)
            out.flush()
            os.fchmod(out.fileno(), mode)
            os.fsync(out.fileno())
        require(read_bytes(root, rel) == expected, 'concurrent change refused')
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def transaction(writes, roots, state_root, verify=None):
    changed = [(side, path, old, new) for (side, path), (old, new) in writes.items() if old != new]
    if not changed:
        if verify:
            verify()
        return
    boundary(state_root, 'backups', directory=True)
    state_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    backup_root = state_root / 'backups'
    backup_root.mkdir(mode=0o700, exist_ok=True)
    run = Path(tempfile.mkdtemp(prefix='sync-', dir=backup_root))
    applied, modes = [], {}
    stale_runs = sorted(p for p in backup_root.glob('sync-*') if p.is_dir() and p != run)
    for stale in stale_runs[:-4]:
        shutil.rmtree(stale, ignore_errors=True)
    try:
        for index, (side, path, old, new) in enumerate(changed):
            require(read_bytes(roots[side], path) == old, 'concurrent change before transaction')
            modes[(side, path)] = stat.S_IMODE((roots[side] / path).stat().st_mode) if old is not ABSENT else 0o600
            if old is not ABSENT:
                with os.fdopen(os.open(run / str(index), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'wb') as out:
                    out.write(old)
        verified = False
        for side, path, old, new in changed:
            if side == 'state' and verify:
                verify()
                verified = True
            atomic_write(roots[side], path, new, old, modes[(side, path)])
            applied.append((side, path, old, new))
        if verify and not verified:
            verify()
    except BaseException:
        blocked = False
        for side, path, old, new in reversed(applied):
            try:
                atomic_write(roots[side], path, old, new, modes[(side, path)])
            except BaseException:
                blocked = True
        raise SyncError('configuration transaction failed; ' + ('rollback refused a concurrent change' if blocked else 'configuration rolled back')) from None


def config_writes(changes, mode, snap):
    docs, writes = {}, {}
    def document(side, path):
        key = (side, path)
        if key not in docs:
            docs[key] = copy.deepcopy(snap.document(side, path))
            writes[key] = (snap.raw(side, path), snap.raw(side, path))
        return docs[key]
    for change in changes:
        if not change.write or change.unit.package and not change.unit.pointer:
            continue
        unit, resource = change.unit, change.unit.resource
        if unit.package:
            if unit.source_unit:
                if mode == 'export' and resource['kind'] == 'git':
                    require('@' in change.incoming, 'local default Git branch is unknown; declare it before export')
                    ref = change.incoming.rsplit('@', 1)[1]
                    require(ref not in resource.get('legacyRefs', []), 'pinned Git ref cannot become a tracking branch')
                    next(p for p in document('repo', 'packages.json')['packages'] if p['id'] == resource['id'])['branch'] = ref
                continue
            field = unit.pointer[1:]
            if mode == 'export':
                package = next(p for p in document('repo', 'packages.json')['packages'] if p['id'] == resource['id'])
                package.pop(field, None) if change.incoming is ABSENT else package.update({field: copy.deepcopy(change.incoming)})
            else:
                settings = document('agent', 'settings.json')
                filters = filter_value(find_entry(package_entries(settings), resource))
                if filters is not ABSENT:
                    filters.pop(field, None) if change.incoming is ABSENT else filters.update({field: copy.deepcopy(change.incoming)})
                    patch_entry(settings, resource, filters)
            continue
        side, path = ('repo', resource['repo']) if mode == 'export' else (resource['root'], resource['target'])
        if unit.pointer:
            set_field(document(side, path), unit.pointer, change.incoming)
        else:
            writes[(side, path)] = (snap.raw(side, path), ABSENT if change.incoming is ABSENT else change.incoming.encode())
    for key, value in docs.items():
        old, new = snap.raw(*key), encode(value)
        writes[key] = (old, old if old is not ABSENT and digest(decode(old), True) == digest(value, True) else new)
    return writes


def projected(unit, side, writes, snap):
    if unit.package:
        key = ('repo', 'packages.json') if side == 'repo' else ('agent', 'settings.json')
        raw = writes[key][1] if key in writes else snap.raw(*key)
        doc = {} if raw is ABSENT else decode(raw)
        require(isinstance(doc, dict), 'invalid package document during verification')
        if side == 'repo':
            matches = [p for p in package_entries(doc) if isinstance(p, dict) and p.get('id') == unit.resource['id']]
            require(len(matches) == 1, 'managed package missing during verification')
            if unit.source_unit:
                return canonical_declared_source(matches[0])
            value = filter_value(matches[0])
        else:
            entry = find_entry(package_entries(doc), unit.resource)
            if unit.source_unit:
                return canonical_local_source(unit.resource, entry)
            value = filter_value(entry)
        if value is ABSENT:
            return ABSENT
        return value.get(unit.pointer[1:], ABSENT) if unit.pointer else {k: value[k] for k in unit.filter_keys if k in value}
    resource = unit.resource
    key = ('repo', resource['repo']) if side == 'repo' else (resource['root'], resource['target'])
    raw = writes[key][1] if key in writes else snap.raw(*key)
    return get_field({} if raw is ABSENT else decode(raw), unit.pointer) if unit.pointer else (raw.decode() if raw is not ABSENT else ABSENT)


def removal_key(record, data):
    target = record['resource']
    prefix = 'package/' + target if any(p['id'] == target for p in data['packages']) else target
    return prefix + ('#' + record['field'] if 'field' in record else '' if prefix.startswith('package/') else '#')

class SafeParser(argparse.ArgumentParser):
    def error(self, message):
        self.print_usage(sys.stderr)
        self.exit(2, 'error: invalid CLI arguments; use --help\n')


def verify_plugin_delta(before, after, package, verb):
    require({k:v for k,v in before.items() if k != 'packages'} ==
            {k:v for k,v in after.items() if k != 'packages'}, 'concurrent non-package settings edit')
    wanted = package_identity(package)
    old = package_entries(before)
    new = package_entries(after)
    require([x for x in old if identity(source_of(x)) != wanted] ==
            [x for x in new if identity(source_of(x)) != wanted], 'concurrent sibling package edit')
    if verb == 'remove':
        require(not any(identity(source_of(x)) == wanted for x in new),
                'package still registered after removal')
    if verb == 'install':
        def metadata(entries):
            result = {}
            for entry in entries:
                if identity(source_of(entry)) == wanted and isinstance(entry,dict):
                    result.update({k:v for k,v in entry.items() if k != 'source'})
            return result
        require(digest(metadata(old),True) == digest(metadata(new),True), 'concurrent managed package filter edit')


def run_plugin_phase(operations, selected, roots):
    for index, (verb, package) in enumerate(operations):
        stage = 'command'
        try:
            if package['kind'] == 'git':
                checkout_guard(package, roots)
            before_step = Snapshot(roots).document('agent', 'settings.json')
            command(['pi', verb, declared_source(package), '--no-approve'], timeout=600)
            stage = 'registration'
            after_step = Snapshot(roots).document('agent', 'settings.json')
            verify_plugin_delta(before_step, after_step, package, verb)
            if verb == 'install':
                fresh = Snapshot(roots)
                settings = copy.deepcopy(fresh.document('agent', 'settings.json'))
                require(settings == after_step, 'concurrent settings edit after plugin command')
                filters = {}
                for entry in package_entries(settings):
                    if identity(source_of(entry)) == package_identity(package):
                        filters.update(filter_value(entry))
                for choice in selected:
                    if choice.unit.resource['id'] == package['id']:
                        value = choice.incoming if choice.write else choice.unit.local
                        filters.pop(choice.unit.pointer[1:], None) if value is ABSENT else filters.update({choice.unit.pointer[1:]: value})
                patch_entry(settings, package, filters, normalize=True, create=True)
                transaction({('agent', 'settings.json'): (fresh.raw('agent', 'settings.json'), encode(settings))}, roots, roots['state'])
            print('completed ' + package['id'])
        except (SyncError, OSError, ValueError, TypeError) as failure:
            if stage != 'command':
                print('completed plugin ' + package['id'] + '; registration phase failed')
            print('failed ' + package['id'])
            for _, later in operations[index + 1:]:
                print('not attempted ' + later['id'])
            reason = str(failure) if isinstance(failure, SyncError) else 'registration filesystem failure'
            raise SyncError('plugin phase stopped; successful plugins and registrations retained; ' + reason) from None


def commit_config_phase(data, managed, by_key, removed, deletions, changes, mode, operations, snap, roots, state, raw_base):
    snap.unchanged(omit=(('agent', 'settings.json'),))
    post = Snapshot(roots)
    for key, raw in snap.bytes.items():
        if key != ('agent', 'settings.json'):
            post.bytes[key] = raw
    post.document('agent', 'settings.json')
    before_settings, after_settings = snap.document('agent', 'settings.json'), post.document('agent', 'settings.json')
    require({k: v for k, v in before_settings.items() if k != 'packages'} ==
            {k: v for k, v in after_settings.items() if k != 'packages'}, 'concurrent non-package settings edit')
    installed = {p['id'] for verb, p in operations if verb == 'install'}
    for change in changes:
        if change.unit.package and not change.unit.removal and change.unit.resource['id'] in installed:
            change.write = False
    writes = config_writes(changes, mode, post)
    new_state = copy.deepcopy(state)
    advances = []
    for unit in managed:
        if unit.key not in removed and unit.hash(projected(unit, 'local', writes, post)) == unit.hash(projected(unit, 'repo', writes, post)):
            new_state['units'][unit.key] = unit.hash(projected(unit, 'local', writes, post))
            advances.append(unit)
    for record in data['removals']:
        if removal_key(record, data) in by_key:
            new_state['removals'][record['id']] = digest(record)
    deleted = []
    for change in deletions:
        if (change.write or change.unit.local is ABSENT) and projected(change.unit, 'local', writes, post) is ABSENT:
            new_state['units'][change.unit.key] = change.unit.hash(ABSENT)
            deleted.append(change.unit)
    new_base = encode(new_state)
    if raw_base is not ABSENT and decode(raw_base) == new_state:
        new_base = raw_base
    writes[('state', 'baseline.json')] = (raw_base, new_base)
    post.unchanged()
    def verify():
        observed = Snapshot(roots)
        for unit in advances:
            require(unit.hash(projected(unit, 'local', {}, observed)) == new_state['units'][unit.key]
                    and unit.hash(projected(unit, 'repo', {}, observed)) == new_state['units'][unit.key],
                    'post-write verification failed')
        for unit in deleted:
            require(projected(unit, 'local', {}, observed) is ABSENT, 'post-delete verification failed')
    transaction(writes, roots, roots['state'], verify)


def main():
    parser = SafeParser(description=__doc__)
    parser.add_argument('command', choices=('audit', 'export', 'apply', 'install', 'update'))
    parser.add_argument('--public', action='store_true', help='Compare and synchronize public units only.')
    parser.add_argument('--dry-run', action='store_true', help='Preview without writes, subprocesses, or network access.')
    parser.add_argument('--skip-packages', action='store_true', help='Make install/update apply configuration only.')
    for flag in ('latest', 'with-settings', 'sync-locals'):
        parser.add_argument('--' + flag, action='store_true', help='Compatibility notice; already the default.')
    args = parser.parse_args()
    for flag in ('latest', 'with_settings', 'sync_locals'):
        if getattr(args, flag):
            print('--' + flag.replace('_', '-') + ' is now the default; compatibility option has no effect')
    repo = Path(__file__).absolute().parent.parent
    home = Path(os.environ['HOME']).absolute()
    agent = Path(os.environ.get('PI_CODING_AGENT_DIR', str(home / '.pi/agent'))).expanduser().absolute()
    roots = {'repo': repo, 'agent': agent, 'pi': home / '.pi', 'state': agent / 'config-sync'}
    require(not roots['state'].is_relative_to(repo), 'state and backups must remain outside repository')
    data = registry(repo)
    snap = Snapshot(roots)
    snap.raw('repo', 'packages.json')
    targets = set()
    for resource in data['resources']:
        if selected_fields(resource, args.public):
            target = boundary(roots[resource['root']], resource['target'])
            require(target not in targets and not target.is_relative_to(repo), 'overlapping local target')
            targets.add(target)
            boundary(repo, resource['repo'])
    boundary(agent, 'settings.json')
    raw_base = snap.raw('state', 'baseline.json')
    state = {'schemaVersion': 1, 'units': {}, 'removals': {}} if raw_base is ABSENT else decode(raw_base)
    require(isinstance(state, dict) and set(state) == {'schemaVersion', 'units', 'removals'}
            and type(state.get('schemaVersion')) is int and state['schemaVersion'] == 1
            and isinstance(state.get('units'), dict) and isinstance(state.get('removals'), dict), 'invalid sync baseline')
    require(all(isinstance(k, str) and isinstance(v, str) and re.fullmatch('[0-9a-f]{64}', v)
                for section in ('units', 'removals') for k, v in state[section].items()), 'baseline must contain hashes only')
    for record in data['removals']:
        prior = state['removals'].get(record['id'])
        require(prior is None or prior == digest(record), 'removal ID reused with a different payload')
    managed = units(data, snap, args.public)
    pending = discover(data, snap, args.public)
    print('coverage incomplete' if pending else 'managed coverage complete')
    for name in pending:
        print('pending ' + name)
    for entry in data['orphans']:
        if 'target' in entry and (roots[entry['root']] / entry['target']).exists():
            print('orphan ' + safe_name(entry['target']))
    mode = 'export' if args.command == 'export' else 'apply'
    by_key = {u.key: u for u in managed}
    removed, deletions = set(), []
    for record in data['removals']:
        key = removal_key(record, data)
        if key in by_key:
            removed.add(key)
            if record['action'] == 'uninstall-package':
                removed.update(u.key for u in managed if u.package and u.resource['id'] == record['resource'])
            if mode != 'export':
                deletions.append(removal_plan(by_key[key], record, state['units']))
    changes = [plan(u, mode, state['units']) for u in managed
               if u.key not in removed and not (u.package and not u.pointer)] + deletions
    for unit in managed:
        if unit.package and not unit.pointer and unit.key not in removed:
            state_label = ' not installed' if unit.local is ABSENT else ' registered'
            if unit.local is not ABSENT and source_of(find_entry(package_entries(snap.document('agent', 'settings.json')), unit.resource)) != declared_source(unit.resource):
                state_label += '; source normalization pending'
            print(safe_name(unit.key) + state_label)
    for change in changes:
        print(safe_name(change.unit.key) + ' ' + change.state)
    packages = [p for p in data['packages'] if (not args.public or p['scope'] == 'public') and 'package/' + p['id'] not in removed]
    upgrading = args.command in ('install', 'update') and not args.skip_packages
    if args.command == 'audit' or args.dry_run:
        if upgrading:
            for package in packages:
                print('would install ' + package['id'] + ' ' + declared_source(package))
            print('Git branch and checkout checks deferred; preview makes no subprocess or network calls')
        return 0
    boundary(roots['state'], 'backups', directory=True)
    boundary(agent, 'config-sync', directory=True)
    confirm(changes, mode)
    for change in changes:
        if change.unit.source_unit and upgrading:
            require(change.write or change.unit.local is ABSENT or change.unit.hash(change.unit.local) == change.unit.hash(change.unit.repo),
                    'local Git source preserved; export source changes before install')
        elif change.unit.source_unit and mode != 'export':
            if change.write:
                print(safe_name(change.unit.key) + ' source change deferred; use install or export')
            change.write = False
    if upgrading:
        require(shutil.which('pi') and shutil.which('git'), 'pi and git are required')
        package_preflight(packages, roots, True)
    uninstalls = [c for c in changes if c.unit.package and not c.unit.pointer and c.unit.removal and c.write]
    if uninstalls:
        require(shutil.which('pi'), 'pi is required for explicit uninstall')
        package_preflight([c.unit.resource for c in uninstalls], roots, False)
    for side, path in (*config_writes(changes, mode, snap), ('state', 'backups/sync-run')):
        writable_parent(roots[side] / path)
    snap.unchanged()
    selected = [c for c in changes if c.unit.package and c.unit.pointer and not c.unit.source_unit and not c.unit.removal]
    operations = ([('install', p) for p in packages] if upgrading else []) + [('remove', c.unit.resource) for c in uninstalls]
    run_plugin_phase(operations, selected, roots)
    commit_config_phase(data, managed, by_key, removed, deletions, changes, mode, operations, snap, roots, state, raw_base)
    print('managed synchronization complete')
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (SyncError,OSError,ValueError,TypeError,KeyError) as error:
        message = str(error) if isinstance(error,SyncError) else 'invalid input or filesystem operation failed'
        print('error: ' + message,file=sys.stderr)
        sys.exit(1)
    except (KeyboardInterrupt,EOFError):
        print('error: confirmation interrupted',file=sys.stderr)
        sys.exit(1)
