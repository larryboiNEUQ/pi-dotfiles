import json
import os
import pty
import select
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path


SOURCE = Path(__file__).resolve().parents[2]


class SyncTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.repo = self.root / 'repo'
        self.agent = self.root / 'agent'
        self.home = self.root / 'home'
        self.bin = self.root / 'bin'
        for p in (self.repo / 'scripts', self.agent, self.home, self.bin):
            p.mkdir(parents=True)
        for name in ('sync.py', 'install.sh', 'dump.sh', 'quick-install.sh'):
            src = SOURCE / 'scripts' / name
            if src.exists():
                shutil.copy2(src, self.repo / 'scripts' / name)
        self.env = dict(os.environ, HOME=str(self.home), PI_CODING_AGENT_DIR=str(self.agent),
                        PATH=str(self.bin) + ':' + os.environ['PATH'], FAKE_LOG=str(self.root / 'commands'))
        self.executable('pi', '''import json, os, sys
from pathlib import Path
with open(os.environ['FAKE_LOG'], 'a') as f: f.write(json.dumps(['pi'] + sys.argv[1:]) + '\\n')
p = Path(os.environ['PI_CODING_AGENT_DIR']) / 'settings.json'
d = json.loads(p.read_text()) if p.exists() else {}
if os.environ.get('PI_FAIL') == sys.argv[2]:
 print('PRIVATE_SUBPROCESS_ERROR', file=sys.stderr); sys.exit(9)
if sys.argv[1] == 'install':
 d.setdefault('packages', []).append(sys.argv[2]); p.parent.mkdir(parents=True, exist_ok=True)
 p.write_text(json.dumps(d) + '\\n')
if sys.argv[1] == 'remove':
 d['packages'] = [x for x in d.get('packages', []) if (x if isinstance(x,str) else x['source']) != sys.argv[2]]
 p.write_text(json.dumps(d) + '\\n')
''')
        self.executable('git', '''import json, os, re, sys
with open(os.environ['FAKE_LOG'], 'a') as f: f.write(json.dumps(['git'] + sys.argv[1:]) + '\\n')
a = sys.argv[1:]
if 'ls-remote' in a:
    if not os.environ.get('BRANCH_MISSING'): print('a'*40 + '\\t' + a[-1])
elif 'status' in a:
    f = os.environ.get('GIT_DIRTY_FILE')
    print(os.environ.get('GIT_DIRTY') or (open(f).read() if f and os.path.exists(f) else ''), end='')
elif 'get-url' in a:
    c = a[a.index('-C') + 1] if '-C' in a else ''
    m = re.search(r'/git/(.+)', c)
    print(os.environ.get('GIT_ORIGIN', 'https://' + m.group(1) if m else 'https://github.com/larryboiNEUQ/pi-dotfiles.git'))
elif 'rev-parse' in a and '--abbrev-ref' in a: print(os.environ.get('GIT_BRANCH', 'main'))
elif 'rev-parse' in a and '--verify' in ' '.join(a): print('a' * 40)
elif 'rev-parse' in a: print('true')
elif 'rev-list' in a: print(os.environ.get('GIT_AHEAD', '0'))
elif 'pull' in a: sys.exit(int(os.environ.get('PULL_FAIL', '0')))
elif 'clone' in a:
    import shutil
    from pathlib import Path
    shutil.copytree(os.environ['FAKE_CLONE_SRC'], a[-1]); (Path(a[-1]) / '.git').mkdir()
''')
        self.manifest = {'schemaVersion': 2, 'packages': [], 'resources': [],
                         'external': [], 'excluded': [], 'orphans': [], 'removals': []}
        self.resource('prefs', 'settings.partial.json', 'settings.json',
                      {'/theme': 'public', '/defaultModel': 'personal', '/queue': 'public'})
        self.put(self.repo / 'settings.partial.json', {'theme': 'dark', 'defaultModel': 'owner', 'queue': ['a']})
        self.save()

    def executable(self, name, body):
        p = self.bin / name
        p.write_text('#!/usr/bin/env python3\n' + body)
        p.chmod(0o755)

    def put(self, path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, indent=2) + '\n')

    def get(self, path):
        return json.loads(path.read_text())

    def resource(self, rid, repo, target, fields=None, kind='json', root='agent', scope='personal'):
        r = dict(id=rid, kind=kind, repo=repo, target=target, root=root)
        r.update(fields=fields) if fields is not None else r.update(scope=scope)
        self.manifest['resources'].append(r)

    def save(self):
        self.put(self.repo / 'packages.json', self.manifest)

    def run_cli(self, command, *args, env=None, preexec_fn=None):
        return subprocess.run(['python3', str(self.repo / 'scripts/sync.py'), command, *args],
                              cwd=self.repo, env=env or self.env, input='', text=True,
                              capture_output=True, preexec_fn=preexec_fn)

    def tty(self, command, answers, *args):
        master, slave = pty.openpty()
        proc = subprocess.Popen(['python3', str(self.repo / 'scripts/sync.py'), command, *args],
                                cwd=self.repo, env=self.env, stdin=slave, stdout=slave, stderr=slave)
        os.close(slave)
        out = b''
        deadline = time.monotonic() + 10
        answers = iter(answers)
        sent = 0
        while time.monotonic() < deadline:
            ready, _, _ = select.select([master], [], [], .05)
            if ready:
                try:
                    chunk = os.read(master, 65536)
                except OSError:
                    break
                if not chunk:
                    break
                out += chunk
                count = out.count(b'Choice [') + out.count(b'Confirm [')
                while sent < count:
                    os.write(master, (next(answers, 'no') + '\n').encode())
                    sent += 1
            if proc.poll() is not None and not ready:
                break
        if proc.poll() is None:
            proc.kill()
        code = proc.wait()
        os.close(master)
        return code, out.decode(errors='replace')

    def tree(self):
        return {str(p.relative_to(self.root)): (p.stat().st_mode, p.read_bytes() if p.is_file() else None)
                for p in self.root.rglob('*')}

    def logs(self):
        p = self.root / 'commands'
        return [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []

    def base(self):
        return self.agent / 'config-sync/baseline.json'

    def assert_ok(self, result):
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_audit_dry_run_no_writes_unknown_names_only(self):
        self.resource('nested', 'configs/nested.json', 'nested.json', {'/workflow/on': 'public'})
        self.put(self.repo / 'configs/nested.json', {'workflow': {'on': True}})
        self.put(self.agent / 'nested.json', {'workflow': {'on': False, 'future': 'NEVER_PRINT', 'api_token_hint': 'NEVER_PRINT'}})
        self.put(self.agent / 'settings.json', {'theme': 'light', 'authToken': 'NEVER_PRINT'})
        (self.agent / 'new.json').write_text('NOT_VALID_JSON_NEVER_PRINT')
        self.save()
        before = self.tree()
        for cmd in ('audit', 'export', 'apply', 'install', 'update'):
            r = self.run_cli(cmd, '--dry-run')
            self.assert_ok(r)
            self.assertIn('coverage incomplete', r.stdout)
            self.assertIn('/workflow/future', r.stdout)
            self.assertNotIn('NEVER_PRINT', r.stdout + r.stderr)
            self.assertNotIn('api_token_hint', r.stdout + r.stderr)
            self.assertEqual(before, self.tree())

    def test_public_apply_and_secret_retention_export(self):
        self.resource('langsmith', 'configs/langsmith.json', 'langsmith.json',
                      {'/enabled': 'personal', '/api_url': 'personal', '/project': 'personal'}, root='pi')
        self.put(self.repo / 'configs/langsmith.json', {'enabled': True, 'api_url': 'https://api.smith.langchain.com', 'project': 'demo'})
        pi = self.home / '.pi'
        self.put(pi / 'langsmith.json', {'api_key': 'SECRET_LS', 'future': 'UNKNOWN_LS'})
        self.save()
        self.assert_ok(self.run_cli('apply', '--public'))
        self.assertEqual(self.get(self.agent / 'settings.json'), {'theme': 'dark', 'queue': ['a']})
        self.assertEqual(self.get(pi / 'langsmith.json')['api_key'], 'SECRET_LS')
        self.assert_ok(self.run_cli('apply'))
        self.assertEqual(self.get(pi / 'langsmith.json')['project'], 'demo')
        self.assert_ok(self.run_cli('export'))
        self.assertNotIn('SECRET_LS', self.base().read_text())
        self.assertNotIn('api_key', (self.repo / 'configs/langsmith.json').read_text())
        self.assertNotIn('UNKNOWN_LS', (self.repo / 'configs/langsmith.json').read_text())

    def test_three_way_destination_edits_array_conflict_missing_null(self):
        self.assert_ok(self.run_cli('apply'))
        original = self.base().read_bytes()
        local = self.get(self.agent / 'settings.json'); local['theme'] = 'light'
        self.put(self.agent / 'settings.json', local)
        self.assert_ok(self.run_cli('apply'))
        self.assertEqual(self.get(self.agent / 'settings.json')['theme'], 'light')
        self.assertEqual(original, self.base().read_bytes())
        repo = self.get(self.repo / 'settings.partial.json'); repo['defaultModel'] = 'new'
        self.put(self.repo / 'settings.partial.json', repo)
        self.assert_ok(self.run_cli('apply'))
        self.assertEqual(self.get(self.agent / 'settings.json'), {'theme': 'light', 'defaultModel': 'new', 'queue': ['a']})
        self.assert_ok(self.run_cli('export'))
        self.assertEqual(self.get(self.repo / 'settings.partial.json')['theme'], 'light')
        local = self.get(self.agent / 'settings.json'); local['queue'] = ['local']; local['defaultModel'] = None
        self.put(self.agent / 'settings.json', local)
        repo = self.get(self.repo / 'settings.partial.json'); repo['queue'] = ['repo']
        self.put(self.repo / 'settings.partial.json', repo)
        before = self.tree()
        r = self.run_cli('apply')
        self.assertNotEqual(r.returncode, 0); self.assertIn('conflict', r.stdout)
        self.assertEqual(before, self.tree())
        code, output = self.tty('apply', ['keep'])
        self.assertEqual(code, 0, output)
        self.assertEqual(self.get(self.agent / 'settings.json')['queue'], ['local'])
        self.assert_ok(self.run_cli('export', '--dry-run'))
        local.pop('queue'); self.put(self.agent / 'settings.json', local)
        self.assert_ok(self.run_cli('export'))
        self.assertEqual(self.get(self.repo / 'settings.partial.json')['queue'], ['repo'])
        self.assertIsNone(self.get(self.repo / 'settings.partial.json')['defaultModel'])

    def test_tty_first_difference_keep_does_not_advance(self):
        self.put(self.agent / 'settings.json', {'theme': 'light'})
        self.manifest['packages'] = [dict(id='one',kind='npm',source='npm:one',scope='public')]
        self.save()
        before = self.tree()
        r = self.run_cli('install')
        self.assertNotEqual(r.returncode, 0); self.assertIn('terminal', r.stderr)
        self.assertEqual(before, self.tree())
        code, out = self.tty('apply', ['keep'])
        self.assertEqual(code, 0, out)
        self.assertEqual(self.get(self.agent / 'settings.json')['theme'], 'light')
        self.assertNotIn('prefs#/theme', self.get(self.base())['units'])
        code, out = self.tty('apply', ['write'])
        self.assertEqual(code, 0, out)
        self.assertEqual(self.get(self.agent / 'settings.json')['theme'], 'dark')
        before = self.tree(); self.assert_ok(self.run_cli('apply')); self.assertEqual(before, self.tree())

    def test_schema_paths_duplicate_keys_and_urls_block_before_packages(self):
        self.manifest['packages'] = [dict(id='one', kind='npm', source='npm:one', scope='public')]
        cases = [lambda: self.manifest['resources'][0].update(target='../escape'),
                 lambda: self.manifest['resources'][0].update(fields={'/api_key': 'personal'}),
                 lambda: self.manifest['resources'][0].update(target='.env'),
                 lambda: self.manifest['packages'][0].update(source='npm:one@1'),
                 lambda: self.manifest['resources'].append(dict(self.manifest['resources'][0]))]
        initial = json.dumps(self.manifest)
        for mutate in cases:
            self.manifest = json.loads(initial); mutate(); self.save()
            r = self.run_cli('install'); self.assertNotEqual(r.returncode, 0)
            self.assertEqual(self.logs(), [])
        (self.repo / 'packages.json').write_text('{"schemaVersion":2,"schemaVersion":2}')
        self.assertNotEqual(self.run_cli('audit').returncode, 0)
        self.manifest = json.loads(initial)
        self.resource('url', 'configs/langsmith.json', 'langsmith.json', {'/api_url': 'personal'}, root='pi')
        self.put(self.repo / 'configs/langsmith.json', {'api_url': 'https://user:secret@example.com'})
        self.save(); r = self.run_cli('install')
        self.assertNotEqual(r.returncode, 0); self.assertNotIn('secret', r.stderr)
        self.assertEqual(self.logs(), [])

    def test_links_and_special_targets_rejected(self):
        elsewhere = self.root / 'elsewhere'; elsewhere.write_text('{}')
        target = self.agent / 'settings.json'
        target.symlink_to(elsewhere)
        self.assertNotEqual(self.run_cli('apply').returncode, 0)
        target.unlink(); os.link(elsewhere, target)
        self.assertNotEqual(self.run_cli('apply').returncode, 0)
        target.unlink(); os.mkfifo(target)
        self.assertNotEqual(self.run_cli('apply').returncode, 0)
        self.assertEqual(elsewhere.read_text(), '{}')

    def test_package_partial_failure_registration_and_filters(self):
        self.manifest['packages'] = [dict(id=x, kind='npm', source='npm:' + x, scope='public') for x in ('one','two','three')]
        self.manifest['packages'][0]['extensions'] = ['!hidden/**']
        self.put(self.agent / 'settings.json', {'packages': [{'source':'npm:one@1','future':'keep','extensions':['!hidden/**']}, 'npm:unmanaged@3']})
        self.save()
        env = dict(self.env, PI_FAIL='npm:two')
        r = self.run_cli('install', env=env)
        self.assertNotEqual(r.returncode, 0)
        self.assertNotIn('PRIVATE_SUBPROCESS_ERROR', r.stdout + r.stderr)
        self.assertIn('completed one', r.stdout); self.assertIn('not attempted three', r.stdout)
        self.assertEqual(self.logs(), [['pi','install','npm:one','--no-approve'], ['pi','install','npm:two','--no-approve']])
        self.assertEqual(self.get(self.agent / 'settings.json')['packages'],
                         [{'source':'npm:one','future':'keep','extensions':['!hidden/**']}, 'npm:unmanaged@3'])
        self.assertFalse(self.base().exists())

    def test_git_preflight_all_before_first_package(self):
        self.manifest['packages'] = [dict(id='one', kind='npm', source='npm:one', scope='public'),
                                     dict(id='git-one', kind='git', source='git:github.com/example/plugin', branch='main', scope='public')]
        self.save()
        checkout = self.agent / 'git/github.com/example/plugin'; checkout.mkdir(parents=True)
        for dirty in (' M index.ts\n', ' M package-lock.json\n', '?? package-lock.json\n?? new.ts\n'):
            r = self.run_cli('install', env=dict(self.env, GIT_DIRTY=dirty))
            self.assertNotEqual(r.returncode, 0); self.assertFalse(any(x[0]=='pi' for x in self.logs()))
        r = self.run_cli('install', env=dict(self.env, BRANCH_MISSING='1'))
        self.assertNotEqual(r.returncode, 0); self.assertFalse(any(x[0]=='pi' for x in self.logs()))
        r = self.run_cli('install', env=dict(self.env, GIT_DIRTY='?? package-lock.json\n'))
        self.assert_ok(r)
        self.assertIn(['pi','install','git:github.com/example/plugin@main','--no-approve'], self.logs())

    def test_config_rollback_without_test_hook(self):
        import resource
        import signal
        self.resource('large', 'configs/large.txt', 'large.txt', kind='text', scope='public')
        (self.repo / 'configs').mkdir(); (self.repo / 'configs/large.txt').write_text('original')
        (self.agent / 'large.txt').write_text('original')
        self.save()
        # A real OS write failure exercises rollback after the smaller settings write.
        def limit():
            signal.signal(signal.SIGXFSZ, signal.SIG_IGN)
            resource.setrlimit(resource.RLIMIT_FSIZE, (8192, 8192))
        self.assert_ok(self.run_cli('apply'))
        (self.agent / 'settings.json').chmod(0o644)
        self.put(self.repo / 'settings.partial.json', {'theme':'new', 'defaultModel':'owner', 'queue':['a']})
        (self.repo / 'configs/large.txt').write_text('y' * 20000)
        before_settings = (self.agent / 'settings.json').read_bytes(); before_base = self.base().read_bytes()
        r = self.run_cli('apply', preexec_fn=limit)
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual((self.agent / 'settings.json').read_bytes(), before_settings)
        self.assertEqual((self.agent / 'settings.json').stat().st_mode & 0o777,0o644)
        self.assertEqual((self.agent / 'large.txt').read_text(), 'original')
        self.assertEqual(self.base().read_bytes(), before_base)
        for p in (self.agent / 'config-sync/backups').rglob('*'):
            if p.is_file(): self.assertEqual(p.stat().st_mode & 0o777, 0o600)

    def test_permission_rule_order_is_semantic(self):
        self.resource('permission', 'configs/permission.json', 'permission.json', {'/permission':'personal'})
        self.put(self.repo / 'configs/permission.json', {'permission':{'*':'deny','read':'allow'}})
        self.save(); self.assert_ok(self.run_cli('apply'))
        self.put(self.agent / 'permission.json', {'permission':{'read':'allow','*':'deny'}})
        self.assert_ok(self.run_cli('export'))
        self.assertEqual(list(self.get(self.repo / 'configs/permission.json')['permission']), ['read','*'])

    def test_persistent_removals_late_home_and_id_reuse(self):
        self.resource('worker', 'agents/worker.md', 'agents/worker.md', kind='text')
        (self.repo / 'agents').mkdir(); (self.repo / 'agents/worker.md').write_text('worker')
        self.manifest['packages'] = [dict(id='one', kind='npm', source='npm:one', scope='public')]
        self.save(); self.assert_ok(self.run_cli('install'))
        self.manifest['removals'] = [dict(id='reset-theme', action='restore-default', resource='prefs', field='/theme'),
                                     dict(id='delete-worker', action='delete-file', resource='worker'),
                                     dict(id='remove-one', action='uninstall-package', resource='one')]
        self.save(); before = self.tree()
        self.assertNotEqual(self.run_cli('apply').returncode, 0); self.assertEqual(before, self.tree())
        code, out = self.tty('apply', ['yes'])
        self.assertEqual(code, 0, out)
        self.assertNotIn('theme', self.get(self.agent / 'settings.json'))
        self.assertFalse((self.agent / 'agents/worker.md').exists())
        self.assertEqual(self.get(self.agent / 'settings.json')['packages'], [])
        self.assertEqual(len(self.get(self.repo / 'packages.json')['removals']), 3)
        before = self.tree(); self.assert_ok(self.run_cli('apply')); self.assertEqual(before, self.tree())
        self.manifest['removals'][0]['field'] = '/defaultModel'; self.save()
        self.assertNotEqual(self.run_cli('apply').returncode, 0)
        self.manifest['removals'][0]['field'] = '/theme'; self.save()
        shutil.rmtree(self.agent); self.agent.mkdir()
        self.put(self.agent / 'settings.json', {'theme':'dark','packages':['npm:one']})
        (self.agent / 'agents').mkdir(); (self.agent / 'agents/worker.md').write_text('worker')
        code, out = self.tty('apply', ['yes'])
        self.assertEqual(code, 0, out)
        self.assertNotIn('theme', self.get(self.agent / 'settings.json'))
        self.assertFalse((self.agent / 'agents/worker.md').exists())

    def test_deletion_conflict_and_unmanage_are_not_silent(self):
        self.assert_ok(self.run_cli('apply'))
        self.put(self.agent / 'settings.json', {'theme':'local','queue':['a'],'defaultModel':'owner'})
        self.manifest['removals'] = [dict(id='reset', action='restore-default', resource='prefs', field='/theme')]
        self.save(); r = self.run_cli('apply')
        self.assertNotEqual(r.returncode, 0); self.assertIn('conflict', r.stdout)
        code, out = self.tty('apply', ['keep'])
        self.assertEqual(code, 0, out); self.assertEqual(self.get(self.agent / 'settings.json')['theme'], 'local')
        self.manifest['removals'] = []; self.manifest['resources'][0]['fields'].pop('/theme'); self.save()
        repo = self.get(self.repo / 'settings.partial.json'); repo.pop('theme')
        self.put(self.repo / 'settings.partial.json', repo)
        r = self.run_cli('apply'); self.assert_ok(r)
        self.assertEqual(self.get(self.agent / 'settings.json')['theme'], 'local')

    def test_quick_install_failed_ff_only_stops(self):
        destination = self.root / 'clone'; (destination / '.git').mkdir(parents=True)
        env = dict(self.env, PI_DOTFILES_DIR=str(destination), PULL_FAIL='1')
        r = subprocess.run(['bash', str(self.repo / 'scripts/quick-install.sh')], env=env,
                           text=True, input='', capture_output=True)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn(['git','-C',str(destination),'pull','--ff-only'], self.logs())
        self.assertFalse(any(x[0]=='pi' for x in self.logs()))
        marker = destination / 'keep'; marker.write_text('safe')
        shutil.rmtree(destination / '.git')
        r = subprocess.run(['bash', str(self.repo / 'scripts/quick-install.sh')], env=env,
                           text=True, input='', capture_output=True)
        self.assertNotEqual(r.returncode, 0); self.assertEqual(marker.read_text(), 'safe')


    def test_export_preserves_repo_edit_and_advances_only_equal_fields(self):
        self.assert_ok(self.run_cli('apply'))
        baseline = self.base().read_bytes()
        repo = self.get(self.repo / 'settings.partial.json'); repo['theme'] = 'repo-only'
        self.put(self.repo / 'settings.partial.json', repo)
        self.assert_ok(self.run_cli('export'))
        self.assertEqual(self.get(self.repo / 'settings.partial.json')['theme'], 'repo-only')
        self.assertEqual(self.base().read_bytes(), baseline)
        local = self.get(self.agent / 'settings.json'); local['queue'] = ['local']
        self.put(self.agent / 'settings.json', local)
        self.assert_ok(self.run_cli('export'))
        self.assertEqual(self.get(self.repo / 'settings.partial.json'),
                         {'theme':'repo-only','defaultModel':'owner','queue':['local']})
        repo['theme'] = 'same'; repo['queue'] = ['local']
        local['theme'] = 'same'
        self.put(self.repo / 'settings.partial.json', repo); self.put(self.agent / 'settings.json', local)
        self.assert_ok(self.run_cli('apply'))
        before = self.tree(); self.assert_ok(self.run_cli('export')); self.assertEqual(before, self.tree())

    def test_public_scope_ignores_personal_conflict_before_install(self):
        self.manifest['packages'] = [dict(id='one',kind='npm',source='npm:one',scope='public')]
        self.save(); self.assert_ok(self.run_cli('install'))
        local = self.get(self.agent / 'settings.json'); local['defaultModel'] = 'local'
        repo = self.get(self.repo / 'settings.partial.json'); repo['defaultModel'] = 'repo'; repo['theme'] = 'new'
        self.put(self.agent / 'settings.json', local); self.put(self.repo / 'settings.partial.json', repo)
        r = self.run_cli('update', '--public'); self.assert_ok(r)
        self.assertNotIn('defaultModel', r.stdout)
        self.assertEqual(self.get(self.agent / 'settings.json')['defaultModel'], 'local')
        self.assertEqual(self.get(self.agent / 'settings.json')['theme'], 'new')

    def test_text_conflict_is_atomic_and_missing_does_not_delete(self):
        self.resource('worker','agents/worker.md','agents/worker.md',kind='text')
        (self.repo / 'agents').mkdir(); (self.repo / 'agents/worker.md').write_text('initial')
        self.save(); self.assert_ok(self.run_cli('apply'))
        (self.repo / 'agents/worker.md').write_text('repo')
        (self.agent / 'agents/worker.md').write_text('local')
        before = self.tree(); r = self.run_cli('export')
        self.assertNotEqual(r.returncode,0); self.assertIn('worker# conflict',r.stdout)
        self.assertEqual(before,self.tree())
        code,out = self.tty('apply',['write']); self.assertEqual(code,0,out)
        self.assertEqual((self.agent / 'agents/worker.md').read_text(),'repo')
        (self.agent / 'agents/worker.md').unlink()
        self.assert_ok(self.run_cli('export'))
        self.assertEqual((self.repo / 'agents/worker.md').read_text(),'repo')

    def test_external_excluded_and_orphan_files_are_not_opened_or_changed(self):
        self.manifest['external'] = [dict(root='agent',target='agents/poteto-agent.md')]
        self.manifest['excluded'] = [dict(root='agent',target='skills',tree=True),
                                     dict(root='agent',target='settings.json',fields=['/obsolete']),
                                     dict(root='agent',target='extensions/herdr-agent-state.ts')]
        self.manifest['orphans'] = [dict(root='agent',target='sandbox.json')]
        for rel in ('agents/poteto-agent.md','skills/private/SKILL.md','extensions/herdr-agent-state.ts',
                    'auth.json','trust.json','models.json','sandbox.json'):
            path = self.agent / rel; path.parent.mkdir(parents=True,exist_ok=True)
            path.write_text('NOT_JSON_PRIVATE_VALUE')
        self.put(self.agent / 'settings.json', {'obsolete':{'future':'NOT_JSON_PRIVATE_VALUE'}})
        self.save(); before = self.tree(); r = self.run_cli('audit'); self.assert_ok(r)
        self.assertIn('orphan sandbox.json',r.stdout)
        self.assertNotIn('pending',r.stdout); self.assertNotIn('NOT_JSON_PRIVATE_VALUE',r.stdout)
        self.assertEqual(before,self.tree())
        self.assert_ok(self.run_cli('apply'))
        self.assertEqual((self.agent / 'agents/poteto-agent.md').read_text(),'NOT_JSON_PRIVATE_VALUE')
        self.assertEqual(self.get(self.agent / 'settings.json')['obsolete'],{'future':'NOT_JSON_PRIVATE_VALUE'})

    def test_adapters_and_legacy_options_are_one_behavior(self):
        before = self.tree()
        for adapter,args in (('install.sh',['--latest','--with-settings','--skip-packages','--dry-run']),
                             ('dump.sh',['--sync-locals','--dry-run'])):
            r = subprocess.run(['bash',str(self.repo / 'scripts' / adapter),*args],cwd=self.repo,env=self.env,
                               input='',text=True,capture_output=True)
            self.assert_ok(r); self.assertIn('compatibility option has no effect',r.stdout)
            self.assertEqual(before,self.tree())
        r = subprocess.run(['bash',str(self.repo / 'scripts/install.sh'),'--skip-packages'],
                           cwd=self.repo,env=self.env,input='',text=True,capture_output=True)
        self.assert_ok(r); self.assertEqual(self.get(self.agent / 'settings.json')['defaultModel'],'owner')
        self.assertEqual(self.logs(),[])

    def test_package_filters_export_without_adopting_unknown_packages_or_refs(self):
        self.manifest['packages'] = [dict(id='one',kind='npm',source='npm:one',scope='public',extensions=[])]
        self.put(self.agent / 'settings.json', {'packages':[{'source':'npm:one@1','extensions':[]},'npm:new@2','npm:pi-mcp-adapter@3'],
                                               'extensions':['-builtin:mcp']})
        self.manifest['excluded'] = [dict(package='pi-mcp-adapter')]
        self.save(); self.assert_ok(self.run_cli('export'))
        settings = self.get(self.agent / 'settings.json')
        settings['packages'][0] = {'source':'npm:one@2','extensions':['!new/**'],'future':'DO_NOT_EXPORT'}
        self.put(self.agent / 'settings.json',settings)
        self.assert_ok(self.run_cli('export'))
        self.assertEqual(self.get(self.repo / 'packages.json')['packages'],
                         [{'id':'one','kind':'npm','source':'npm:one','scope':'public','extensions':['!new/**']}])
        self.assertNotIn('builtin:mcp',(self.repo / 'settings.partial.json').read_text())
        self.assertNotIn('DO_NOT_EXPORT',(self.repo / 'packages.json').read_text())

    def test_config_rollback_retains_successful_plugin_registration(self):
        import resource
        import signal
        self.manifest['packages'] = [dict(id='one',kind='npm',source='npm:one',scope='public',extensions=['!hidden/**'])]
        self.resource('large','configs/large.txt','large.txt',kind='text',scope='public')
        (self.repo / 'configs').mkdir(); (self.repo / 'configs/large.txt').write_text('original')
        self.save(); self.assert_ok(self.run_cli('apply'))
        baseline = self.base().read_bytes()
        repo = self.get(self.repo / 'settings.partial.json'); repo['theme'] = 'new'
        self.put(self.repo / 'settings.partial.json',repo)
        (self.repo / 'configs/large.txt').write_text('x'*20000)
        def limit():
            signal.signal(signal.SIGXFSZ,signal.SIG_IGN)
            resource.setrlimit(resource.RLIMIT_FSIZE,(8192,8192))
        r = self.run_cli('install',preexec_fn=limit)
        self.assertNotEqual(r.returncode,0); self.assertIn('completed one',r.stdout)
        self.assertIn('configuration rolled back',r.stderr)
        self.assertEqual(self.get(self.agent / 'settings.json'),
                         {'theme':'dark','defaultModel':'owner','queue':['a'],
                          'packages':[{'source':'npm:one','extensions':['!hidden/**']}]})
        self.assertEqual((self.agent / 'large.txt').read_text(),'original')
        self.assertEqual(self.base().read_bytes(),baseline)

    def test_uninstall_failure_stops_later_deletions_and_baseline(self):
        self.manifest['packages'] = [dict(id=x,kind='npm',source='npm:'+x,scope='public') for x in ('one','two')]
        self.save(); self.assert_ok(self.run_cli('install'))
        baseline = self.base().read_bytes(); original = (self.agent / 'settings.json').read_bytes()
        self.manifest['removals'] = [dict(id='remove-'+x,action='uninstall-package',resource=x) for x in ('one','two')]
        self.manifest['removals'].append(dict(id='reset',action='restore-default',resource='prefs',field='/theme'))
        self.save(); self.env['PI_FAIL'] = 'npm:one'
        code,out = self.tty('apply',['yes'])
        self.assertNotEqual(code,0); self.assertIn('not attempted two',out)
        self.assertEqual((self.agent / 'settings.json').read_bytes(),original)
        self.assertEqual(self.base().read_bytes(),baseline)
        self.assertNotIn(['pi','remove','npm:two','--no-approve'],self.logs())

    def test_preflight_backup_link_and_unknown_leaf_object_stop_before_package(self):
        self.manifest['packages'] = [dict(id='one',kind='npm',source='npm:one',scope='public')]
        self.save(); (self.agent / 'config-sync').mkdir()
        elsewhere = self.root / 'elsewhere'; elsewhere.mkdir()
        (self.agent / 'config-sync/backups').symlink_to(elsewhere)
        self.assertNotEqual(self.run_cli('install').returncode,0); self.assertEqual(self.logs(),[])
        (self.agent / 'config-sync/backups').unlink()
        self.put(self.repo / 'settings.partial.json',{'theme':{'future':'NEVER_EXPORT'}})
        r = self.run_cli('install'); self.assertNotEqual(r.returncode,0)
        self.assertNotIn('NEVER_EXPORT',r.stdout+r.stderr); self.assertEqual(self.logs(),[])
        self.put(self.repo / 'settings.partial.json',{'theme':'dark','defaultModel':'owner','queue':['a']})
        self.manifest['excluded'] = [dict(root='agent',target='skills',tree=True)]
        self.resource('forbidden','configs/forbidden.md','skills/forbidden.md',kind='text')
        (self.repo / 'configs').mkdir(); (self.repo / 'configs/forbidden.md').write_text('not managed')
        self.save(); self.assertNotEqual(self.run_cli('apply').returncode,0)

    def test_compare_and_swap_preserves_concurrent_nonpackage_edit(self):
        self.manifest['packages'] = [dict(id='one',kind='npm',source='npm:one',scope='public')]
        self.save(); self.assert_ok(self.run_cli('apply'))
        baseline = self.base().read_bytes()
        script = (self.bin / 'pi').read_text()
        script += "\nd = json.loads(p.read_text()); d['theme'] = 'concurrent'; p.write_text(json.dumps(d)+'\\n')\n"
        (self.bin / 'pi').write_text(script)
        r = self.run_cli('install'); self.assertNotEqual(r.returncode,0)
        self.assertIn('concurrent non-package settings edit',r.stderr)
        self.assertEqual(self.get(self.agent / 'settings.json')['theme'],'concurrent')
        self.assertEqual(self.get(self.agent / 'settings.json')['packages'],['npm:one'])
        self.assertEqual(self.base().read_bytes(),baseline)


    def test_filter_unmanage_missing_and_explicit_default_are_distinct(self):
        self.manifest['packages'] = [dict(id='one',kind='npm',source='npm:one',scope='public',extensions=['!one/**'])]
        self.save(); self.assert_ok(self.run_cli('install'))
        self.manifest['packages'][0].pop('extensions'); self.save()
        self.assert_ok(self.run_cli('apply'))
        self.assertEqual(self.get(self.agent / 'settings.json')['packages'],[{'source':'npm:one','extensions':['!one/**']}])
        self.manifest['packages'][0]['extensions'] = ['!one/**']; self.save()
        self.assert_ok(self.run_cli('apply'))
        self.put(self.agent / 'settings.json',{'theme':'dark','defaultModel':'owner','queue':['a'],'packages':['npm:one']})
        self.assert_ok(self.run_cli('export'))
        self.assertEqual(self.get(self.repo / 'packages.json')['packages'][0]['extensions'],['!one/**'])
        self.manifest['removals'] = [dict(id='filter-default',action='restore-default',resource='one',field='/extensions')]
        self.save(); self.assert_ok(self.run_cli('apply'))
        before = self.tree(); self.assert_ok(self.run_cli('apply')); self.assertEqual(before,self.tree())
        self.put(self.agent / 'settings.json',{'theme':'dark','defaultModel':'owner','queue':['a'],
                                               'packages':[{'source':'npm:one','extensions':['!one/**']}]})
        self.assertNotEqual(self.run_cli('apply').returncode,0)
        code,out = self.tty('apply',['write','yes']); self.assertEqual(code,0,out)
        self.assertEqual(self.get(self.agent / 'settings.json')['packages'],['npm:one'])
        self.assertEqual(self.get(self.repo / 'packages.json')['removals'][0]['id'],'filter-default')

    def test_public_does_not_open_personal_linked_resource(self):
        self.resource('owner','agents/owner.md','agents/owner.md',kind='text')
        self.save(); (self.repo / 'agents').mkdir(); (self.repo / 'agents/owner.md').write_text('owner')
        (self.agent / 'agents').mkdir(); (self.agent / 'agents/owner.md').symlink_to(self.root / 'private')
        self.assert_ok(self.run_cli('apply','--public'))
        self.assertTrue((self.agent / 'agents/owner.md').is_symlink())
        self.assertNotEqual(self.run_cli('apply').returncode,0)

    def test_concurrent_package_filter_edit_is_not_overwritten(self):
        self.manifest['packages'] = [dict(id='one',kind='npm',source='npm:one',scope='public',extensions=['!one/**'])]
        self.save(); self.assert_ok(self.run_cli('install'))
        baseline = self.base().read_bytes()
        script = (self.bin / 'pi').read_text()
        script += "\nd = json.loads(p.read_text()); d['packages'][0]['extensions'] = ['!concurrent/**']; p.write_text(json.dumps(d)+'\\n')\n"
        (self.bin / 'pi').write_text(script)
        r = self.run_cli('install'); self.assertNotEqual(r.returncode,0)
        self.assertIn('concurrent managed package filter edit',r.stderr)
        self.assertEqual(self.get(self.agent / 'settings.json')['packages'][0]['extensions'],['!concurrent/**'])
        self.assertEqual(self.base().read_bytes(),baseline)

    def test_quick_dry_run_and_wrong_origin_have_no_install(self):
        dest = self.root / 'clone'; (dest / '.git').mkdir(parents=True)
        env = dict(self.env,PI_DOTFILES_DIR=str(dest))
        before = self.tree()
        r = subprocess.run(['bash',str(self.repo / 'scripts/quick-install.sh'),'--dry-run'],env=env,
                           input='',text=True,capture_output=True)
        self.assert_ok(r); self.assertEqual(before,self.tree())
        script = (self.bin / 'git').read_text().replace('https://github.com/larryboiNEUQ/pi-dotfiles.git','https://github.com/other/repo.git')
        (self.bin / 'git').write_text(script)
        r = subprocess.run(['bash',str(self.repo / 'scripts/quick-install.sh')],env=env,
                           input='',text=True,capture_output=True)
        self.assertNotEqual(r.returncode,0); self.assertIn('origin differs',r.stderr)
        self.assertFalse(any(x[0]=='pi' for x in self.logs()))
        self.assertFalse(any('pull' in x for x in self.logs()))


    def test_quick_clone_and_successful_ff_only_use_the_install_adapter(self):
        self.manifest['packages'] = [dict(id='one',kind='npm',source='npm:one',scope='public')]
        self.save(); dest = self.root / 'clone'
        env = dict(self.env,PI_DOTFILES_DIR=str(dest),FAKE_CLONE_SRC=str(self.repo))
        def quick():
            return subprocess.run(['bash',str(self.repo / 'scripts/quick-install.sh')],env=env,
                                  input='',text=True,capture_output=True)
        self.assert_ok(quick())
        self.assertIn(['git','clone','--','https://github.com/larryboiNEUQ/pi-dotfiles.git',str(dest)],self.logs())
        self.assertEqual(self.get(self.agent / 'settings.json'),
                         {'theme':'dark','defaultModel':'owner','queue':['a'],'packages':['npm:one']})
        self.assert_ok(quick())
        self.assertIn(['git','-C',str(dest),'pull','--ff-only'],self.logs())
        self.assertEqual(self.get(self.agent / 'settings.json')['packages'],['npm:one'])

    def test_null_existing_value_is_not_missing_on_first_apply(self):
        self.put(self.agent / 'settings.json',{'theme':None})
        before = self.tree(); r = self.run_cli('apply')
        self.assertNotEqual(r.returncode,0); self.assertEqual(before,self.tree())
        code,out = self.tty('apply',['write']); self.assertEqual(code,0,out)
        self.assertEqual(self.get(self.agent / 'settings.json')['theme'],'dark')


    def prepare_concurrent_apply(self):
        self.manifest['packages'] = [dict(id='one',kind='npm',source='npm:one',scope='public')]
        self.resource('large','configs/large.txt','large.txt',kind='text',scope='public')
        (self.repo / 'configs').mkdir(); (self.repo / 'configs/large.txt').write_text('original')
        self.save(); self.assert_ok(self.run_cli('install'))
        baseline = self.base().read_bytes()
        repo = self.get(self.repo / 'settings.partial.json'); repo['theme'] = 'new'
        self.put(self.repo / 'settings.partial.json',repo)
        (self.repo / 'configs/large.txt').write_text('x' * (32 * 1024 * 1024))
        return baseline

    def concurrent_actor(self, action, pid=0):
        script = self.root / 'actor.py'
        script.write_text('''import json, os, signal, sys, time
from pathlib import Path
settings, registry, action, pid = sys.argv[1:]
print('ready', flush=True)
deadline = time.monotonic() + 10
while time.monotonic() < deadline:
 try: data = json.loads(Path(settings).read_text())
 except (OSError, ValueError): data = {}
 if data.get('theme') == 'new':
  if action == 'local':
   data['theme'] = 'concurrent'; Path(settings).write_text(json.dumps(data)+'\\n')
  elif action == 'repo': Path(registry).write_text('{}\\n')
  else: os.kill(int(pid), signal.SIGINT)
  sys.exit(0)
 time.sleep(.001)
sys.exit(2)
''')
        actor = subprocess.Popen(['python3',str(script),str(self.agent / 'settings.json'),
                                  str(self.repo / 'packages.json'),action,str(pid)],
                                 env=self.env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        self.addCleanup(lambda: actor.kill() if actor.poll() is None else None)
        self.assertEqual(actor.stdout.readline(),'ready\n')
        return actor

    def test_rollback_refuses_overwriting_concurrent_config_edit(self):
        baseline = self.prepare_concurrent_apply()
        actor = self.concurrent_actor('local')
        r = self.run_cli('apply'); actor.communicate(timeout=10)
        self.assertEqual(actor.returncode,0)
        self.assertNotEqual(r.returncode,0); self.assertIn('rollback refused a concurrent change',r.stderr)
        self.assertEqual(self.get(self.agent / 'settings.json')['theme'],'concurrent')
        self.assertEqual((self.agent / 'large.txt').read_text(),'original')
        self.assertEqual(self.base().read_bytes(),baseline)

    def test_concurrent_malformed_repo_verification_rolls_back_config(self):
        baseline = self.prepare_concurrent_apply()
        actor = self.concurrent_actor('repo')
        r = self.run_cli('apply'); actor.communicate(timeout=10)
        self.assertEqual(actor.returncode,0)
        self.assertNotEqual(r.returncode,0); self.assertIn('configuration rolled back',r.stderr)
        self.assertEqual(self.get(self.agent / 'settings.json')['theme'],'dark')
        self.assertEqual((self.agent / 'large.txt').read_text(),'original')
        self.assertEqual(self.base().read_bytes(),baseline)
        self.assertEqual(self.get(self.repo / 'packages.json'),{})

    def test_interrupt_rolls_back_config_before_baseline_commit(self):
        baseline = self.prepare_concurrent_apply()
        proc = subprocess.Popen(['python3',str(self.repo / 'scripts/sync.py'),'apply'],cwd=self.repo,
                                env=self.env,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        self.addCleanup(lambda: proc.kill() if proc.poll() is None else None)
        actor = self.concurrent_actor('interrupt',proc.pid)
        out,err = proc.communicate(timeout=10); actor.communicate(timeout=10)
        self.assertEqual(actor.returncode,0)
        self.assertNotEqual(proc.returncode,0,out+err); self.assertIn('configuration rolled back',err)
        self.assertEqual(self.get(self.agent / 'settings.json')['theme'],'dark')
        self.assertEqual((self.agent / 'large.txt').read_text(),'original')
        self.assertEqual(self.base().read_bytes(),baseline)


    def managed_git(self):
        self.manifest['packages'] = [dict(id='git-one', kind='git',
            source='https://github.com/owner/plugin', branch='main', scope='public')]
        self.save()
        self.assert_ok(self.run_cli('install'))

    def test_git_source_conflict_blocks_before_subprocesses(self):
        self.managed_git()
        local = self.get(self.agent / 'settings.json')
        local['packages'] = ['https://github.com/owner/plugin@feature/local']
        self.put(self.agent / 'settings.json', local)
        self.manifest['packages'][0]['branch'] = 'release'; self.save()
        before = self.tree(); commands = self.logs()
        result = self.run_cli('install')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('conflict', result.stdout)
        self.assertEqual(commands, self.logs())
        self.assertEqual(before, self.tree())

    def test_git_local_source_exports_and_repo_source_installs(self):
        self.managed_git()
        local = self.get(self.agent / 'settings.json')
        local['packages'] = ['https://github.com/owner/plugin@feature/local']
        self.put(self.agent / 'settings.json', local)
        self.assert_ok(self.run_cli('export'))
        self.assertEqual(self.get(self.repo / 'packages.json')['packages'][0]['branch'], 'feature/local')
        self.manifest = self.get(self.repo / 'packages.json')
        self.manifest['packages'][0]['branch'] = 'release'; self.save()
        self.assert_ok(self.run_cli('install'))
        self.assertEqual(self.get(self.agent / 'settings.json')['packages'],
                         ['https://github.com/owner/plugin@release'])

    def test_git_keep_source_is_not_overwritten_by_install(self):
        self.managed_git()
        local = self.get(self.agent / 'settings.json')
        local['packages'] = ['https://github.com/owner/plugin@feature/local']
        self.put(self.agent / 'settings.json', local)
        self.manifest['packages'][0]['branch'] = 'release'; self.save()
        commands = self.logs()
        code, out = self.tty('install', ['keep'])
        self.assertNotEqual(code, 0, out)
        self.assertIn('export', out)
        self.assertEqual(commands, self.logs())
        self.assertEqual(self.get(self.agent / 'settings.json')['packages'],
                         ['https://github.com/owner/plugin@feature/local'])

    def test_valid_permission_deny_objects_round_trip(self):
        self.resource('permission', 'configs/permission.json', 'permission.json',
                      {'/permission': 'personal'})
        rule = {'permission': {'bash': {'rm *': {'action': 'deny', 'reason': 'Use the trash'},
                                        'mv *': {'action': 'deny'}}}}
        self.put(self.agent / 'permission.json', rule); self.save()
        self.assert_ok(self.run_cli('audit'))
        self.assert_ok(self.run_cli('export'))
        self.assertEqual(self.get(self.repo / 'configs/permission.json'), rule)
        self.assert_ok(self.run_cli('apply'))
        self.assertEqual(self.get(self.agent / 'permission.json'), rule)
        for bad in ({'action': 'allow'}, {'action': 'deny', 'reason': 3},
                    {'action': 'deny', 'future': 'NEVER_PRINT'}):
            self.put(self.agent / 'permission.json', {'permission': {'bash': {'rm *': bad}}})
            result = self.run_cli('audit')
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn('NEVER_PRINT', result.stdout + result.stderr)

    def test_remove_only_keeps_unrelated_filter_application(self):
        self.manifest['packages'] = [dict(id=x, kind='npm', source='npm:' + x, scope='public')
                                     for x in ('one', 'two')]
        self.manifest['packages'][1]['extensions'] = []; self.save()
        self.assert_ok(self.run_cli('install'))
        self.manifest['packages'][1]['extensions'] = ['!hidden/**']
        self.manifest['removals'] = [dict(id='remove-one', action='uninstall-package', resource='one')]
        self.save()
        code, out = self.tty('apply', ['yes'])
        self.assertEqual(code, 0, out)
        self.assertEqual(self.get(self.agent / 'settings.json')['packages'],
                         [{'source': 'npm:two', 'extensions': ['!hidden/**']}])
        before = self.tree()
        self.assert_ok(self.run_cli('apply'))
        self.assertEqual(before, self.tree())

    def test_confirmation_shows_direction_and_managed_difference(self):
        self.put(self.agent / 'settings.json', {'theme': 'light'})
        code, out = self.tty('apply', ['write'])
        self.assertEqual(code, 0, out)
        self.assertIn('Destination (local)', out); self.assertIn('Incoming (repo)', out)
        self.assertIn('"light"', out); self.assertIn('"dark"', out)
        local = self.get(self.agent / 'settings.json'); local['theme'] = 'local-edit'
        self.put(self.agent / 'settings.json', local)
        repo = self.get(self.repo / 'settings.partial.json'); repo['theme'] = 'repo-edit'
        self.put(self.repo / 'settings.partial.json', repo)
        code, out = self.tty('export', ['write'])
        self.assertEqual(code, 0, out)
        self.assertIn('Destination (repo)', out); self.assertIn('Incoming (local)', out)
        self.assertEqual(self.get(self.repo / 'settings.partial.json')['theme'], 'local-edit')

    def test_text_confirmation_diff_and_sensitive_projection(self):
        self.resource('worker', 'agents/worker.md', 'agents/worker.md', kind='text', scope='public')
        (self.repo / 'agents').mkdir(); (self.repo / 'agents/worker.md').write_text('new worker\n')
        (self.agent / 'agents').mkdir(); (self.agent / 'agents/worker.md').write_text('old worker\n')
        self.resource('langsmith', 'configs/langsmith.json', 'langsmith.json', {'/project': 'personal'}, root='pi')
        self.put(self.repo / 'configs/langsmith.json', {'project': 'REPO_PRIVATE_PROJECT'})
        self.put(self.home / '.pi/langsmith.json', {'project': 'LOCAL_PRIVATE_PROJECT', 'api_key': 'UNKNOWN_SECRET'})
        self.save()
        code, out = self.tty('apply', ['write', 'keep'])
        self.assertEqual(code, 0, out)
        self.assertIn('--- destination (local)', out); self.assertIn('+new worker', out)
        self.assertNotIn('REPO_PRIVATE_PROJECT', out); self.assertNotIn('LOCAL_PRIVATE_PROJECT', out)
        self.assertNotIn('UNKNOWN_SECRET', out)
        self.assertEqual((self.agent / 'agents/worker.md').read_text(), 'new worker\n')


    def test_declared_legacy_ref_normalizes_only_before_source_baseline(self):
        package = dict(id='git-one', kind='git', source='https://github.com/owner/plugin',
                       branch='main', defaultBranch='main', legacyRefs=['v2.4.0'], scope='public')
        self.manifest['packages'] = [package]; self.save()
        self.put(self.agent / 'settings.json', {'packages': ['https://github.com/owner/plugin@v2.4.0']})
        self.assert_ok(self.run_cli('export'))
        self.assertEqual(self.get(self.repo / 'packages.json')['packages'][0]['branch'], 'main')
        self.assertNotIn('package/git-one#/source', self.get(self.base())['units'])
        self.assert_ok(self.run_cli('install'))
        self.assertEqual(self.get(self.agent / 'settings.json')['packages'], ['https://github.com/owner/plugin@main'])
        local = self.get(self.agent / 'settings.json')
        local['packages'] = ['https://github.com/owner/plugin@v2.4.0']
        self.put(self.agent / 'settings.json', local)
        commands = self.logs()
        result = self.run_cli('install')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.logs(), commands)
        self.assertEqual(self.get(self.agent / 'settings.json')['packages'], ['https://github.com/owner/plugin@v2.4.0'])

    def test_declared_default_branch_is_not_the_selected_branch(self):
        self.manifest['packages'] = [dict(id='git-one', kind='git',
            source='https://github.com/owner/plugin', branch='main', defaultBranch='main', scope='public')]
        self.put(self.agent / 'settings.json', {'packages': ['https://github.com/owner/plugin']})
        self.save(); self.assert_ok(self.run_cli('apply'))
        self.manifest['packages'][0]['branch'] = 'release'; self.save()
        commands = self.logs()
        self.assert_ok(self.run_cli('apply'))
        self.assertEqual(self.logs(), commands)
        self.assertEqual(self.get(self.agent / 'settings.json')['packages'], ['https://github.com/owner/plugin'])
        self.assert_ok(self.run_cli('install'))
        self.assertEqual(self.get(self.agent / 'settings.json')['packages'], ['https://github.com/owner/plugin@release'])

    def test_git_checkout_guard_blocks_unsafe_states(self):
        self.manifest['packages'] = [dict(id='git-one', kind='git',
            source='https://github.com/owner/plugin', branch='main', scope='public')]
        self.save()
        (self.agent / 'git/github.com/owner/plugin').mkdir(parents=True)
        for env in (dict(GIT_AHEAD='1'), dict(GIT_BRANCH='feature/local'),
                    dict(GIT_ORIGIN='https://github.com/fork/plugin'),
                    dict(GIT_DIRTY='!! .env\n')):
            commands = len(self.logs())
            r = self.run_cli('install', env=dict(self.env, **env))
            self.assertNotEqual(r.returncode, 0, env)
            self.assertFalse(any(x[0] == 'pi' for x in self.logs()[commands:]))
        self.assert_ok(self.run_cli('install'))

    def test_git_guard_rechecks_before_each_late_plugin(self):
        self.manifest['packages'] = [
            dict(id='one', kind='git', source='https://github.com/owner/one', branch='main', scope='public'),
            dict(id='two', kind='git', source='https://github.com/owner/two', branch='main', scope='public')]
        self.save()
        (self.agent / 'git/github.com/owner/one').mkdir(parents=True)
        (self.agent / 'git/github.com/owner/two').mkdir(parents=True)
        dirty = self.root / 'dirty'
        script = (self.bin / 'pi').read_text()
        script += "\nif sys.argv[1] == 'install': open(os.environ['GIT_DIRTY_FILE'], 'w').write(' M late.ts\\n')\n"
        (self.bin / 'pi').write_text(script)
        r = self.run_cli('install', env=dict(self.env, GIT_DIRTY_FILE=str(dirty)))
        self.assertNotEqual(r.returncode, 0)
        installs = [x for x in self.logs() if x[:2] == ['pi', 'install']]
        self.assertEqual(len(installs), 1)

    def test_uninstall_requires_deregistration(self):
        self.manifest['packages'] = [dict(id='one', kind='npm', source='npm:one', scope='public')]
        self.save(); self.assert_ok(self.run_cli('install'))
        self.manifest['removals'] = [dict(id='remove-one', action='uninstall-package', resource='one')]
        self.save()
        script = (self.bin / 'pi').read_text()
        script = script.replace("d['packages'] = [x for x in d.get('packages', []) if (x if isinstance(x,str) else x['source']) != sys.argv[2]]", 'pass')
        (self.bin / 'pi').write_text(script)
        code, out = self.tty('apply', ['yes'])
        self.assertNotEqual(code, 0, out)
        self.assertEqual(self.get(self.agent / 'settings.json')['packages'], ['npm:one'])

    def test_ssh_local_source_matches_managed_identity(self):
        self.manifest['packages'] = [dict(id='git-one', kind='git',
            source='https://github.com/owner/plugin', branch='main', scope='public')]
        self.save()
        self.put(self.agent / 'settings.json', {'packages': ['git:ssh://git@github.com/owner/plugin@main']})
        r = self.run_cli('audit')
        self.assert_ok(r)
        self.assertNotIn('package/[unrecognized]', r.stdout)
        self.assertIn('package/git-one registered', r.stdout)
        self.assertIn('source normalization pending', r.stdout)


    def test_npm_source_pin_policy_preserves_unknown_metadata(self):
        self.manifest['packages'] = [dict(id='one', kind='npm', source='npm:one', scope='public')]
        self.put(self.agent / 'settings.json', {'packages': [{'source': 'npm:one@1.0.0', 'future': 'PRIVATE_UNKNOWN'}]})
        self.save(); self.assert_ok(self.run_cli('install'))
        self.assertEqual(self.get(self.agent / 'settings.json')['packages'],
                         [{'source': 'npm:one', 'future': 'PRIVATE_UNKNOWN'}])


if __name__ == '__main__':
    unittest.main()
