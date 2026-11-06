"""Exercise pinning and failed installs against a disposable local Git remote."""
import contextlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import mcp_dependency as dependency


@unittest.skipUnless(shutil.which('git'), 'Git is required for dependency installation')
class DependencyInstallationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='TVLevels install with spaces ')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.remote = self.root / 'remote'
        self.remote.mkdir()
        self.run = subprocess.run
        self.git('init', '--quiet', str(self.remote))
        (self.remote / 'src').mkdir()
        (self.remote / 'src/server.js').write_text('// pinned server')
        (self.remote / 'package.json').write_text('{}')
        (self.remote / 'package-lock.json').write_text('{"lockfileVersion": 3}')
        (self.remote / '.gitignore').write_text('node_modules/\n')
        self.git('-C', str(self.remote), 'add', '.')
        self.commit('pinned revision')
        revision = subprocess.check_output(['git', '-C', str(self.remote), 'rev-parse', 'HEAD'], text=True).strip()
        self.spec = {'repository': str(self.remote), 'commit': revision}
        # Remote HEAD advances; install must still use the older pinned revision.
        (self.remote / 'src/server.js').write_text('// newer unselected server')
        self.git('-C', str(self.remote), 'add', '.')
        self.commit('newer revision')
        self.app = self.root / 'TVLevels'
        self.app.mkdir()
        self.npm_calls = []
        self.addCleanup(patch.stopall)
        patch('mcp_dependency.dependency_lock', return_value=self.spec).start()
        patch('mcp_dependency.verify_node_dependencies').start()
        patch('mcp_dependency.subprocess.run', side_effect=self.run_with_fake_npm).start()
        self.output = contextlib.redirect_stdout(io.StringIO())
        self.output.__enter__()
        self.addCleanup(self.output.__exit__, None, None, None)

    def git(self, *args):
        self.run(['git', *args], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)

    def commit(self, message):
        self.git('-C', str(self.remote), '-c', 'user.name=Test', '-c', 'user.email=test@example.invalid',
                 '-c', 'commit.gpgsign=false', 'commit', '--quiet', '-m', message)

    def run_with_fake_npm(self, command, **kwargs):
        if command[0] != 'npm':
            return self.run(command, **kwargs)
        self.npm_calls.append(command)
        modules = Path(kwargs['cwd']) / 'node_modules'
        modules.mkdir()
        (modules / '.package-lock.json').write_text('{}')
        return subprocess.CompletedProcess(command, 0)

    def test_full_commit_is_installed_once_without_following_remote_head(self):
        installed = dependency.ensure_dependency(self.app)
        self.assertEqual((installed / 'src/server.js').read_text(), '// pinned server')
        self.assertEqual(dependency.ensure_dependency(self.app), installed)
        self.assertEqual(len(self.npm_calls), 1)
        self.assertIn('ci', self.npm_calls[0])
        self.assertIn('--ignore-scripts', self.npm_calls[0])
        self.assertTrue(dependency.dependency_ready(installed, self.spec))
        self.assertEqual((self.remote / 'src/server.js').read_text(), '// newer unselected server')

    def test_npm_failure_leaves_no_published_or_temporary_install(self):
        original = self.run_with_fake_npm
        def fail_npm(command, **kwargs):
            if command[0] == 'npm':
                raise subprocess.CalledProcessError(1, command)
            return original(command, **kwargs)
        with patch('mcp_dependency.subprocess.run', side_effect=fail_npm):
            with self.assertRaises(subprocess.CalledProcessError):
                dependency.ensure_dependency(self.app)
        self.assertFalse(dependency.managed_mcp_root(self.app).exists())
        self.assertEqual(list((self.app / '.local/dependencies').iterdir()), [])
        self.assertTrue(dependency.ensure_dependency(self.app).is_dir())

    def test_missing_commit_cannot_publish_a_different_revision(self):
        self.spec['commit'] = '0' * 40
        with self.assertRaises(subprocess.CalledProcessError):
            dependency.ensure_dependency(self.app)
        self.assertFalse(dependency.managed_mcp_root(self.app).exists())
        self.assertEqual(self.npm_calls, [])

    def test_modified_managed_source_is_preserved_and_rejected(self):
        installed = dependency.ensure_dependency(self.app)
        source = installed / 'src/server.js'
        source.write_text('// keep my edit')
        with self.assertRaisesRegex(RuntimeError, 'will not be overwritten'):
            dependency.ensure_dependency(self.app)
        self.assertEqual(source.read_text(), '// keep my edit')

    def test_changed_lock_or_missing_modules_invalidates_ready_record(self):
        installed = dependency.ensure_dependency(self.app)
        (installed / 'package-lock.json').write_text('{}')
        self.assertFalse(dependency.dependency_ready(installed, self.spec))
        with self.assertRaisesRegex(RuntimeError, 'incomplete'):
            dependency.ensure_dependency(self.app)


class DependencyLockTests(unittest.TestCase):
    def test_branch_names_and_malformed_pins_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for revision in ('main', '4f1d83e', '../escape', None):
                (root / 'dependencies.lock.json').write_text(json.dumps({'tradingview_mcp': {
                    'repository': 'https://github.com/madiver/TradingView-MCP.git', 'commit': revision}}))
                with self.subTest(revision=revision), self.assertRaises(ValueError):
                    dependency.dependency_lock(root)
