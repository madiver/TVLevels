import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from daily_levels import MCP
from mcp_dependency import READY_FILE, dependency_lock, installation_record, managed_mcp_root
from runtime_config import resolve_mcp_root


class RuntimeConfigTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name).resolve()
        self.app = self.base / 'TVLevels'
        self.app.mkdir()
        (self.app / 'dependencies.lock.json').write_text(json.dumps({'tradingview_mcp': {
            'repository': 'https://github.com/madiver/TradingView-MCP.git', 'commit': 'a' * 40}}))
        self.dependency = self.make_dependency(self.base / 'tradingview-mcp')

    def make_dependency(self, path):
        (path / 'src').mkdir(parents=True)
        (path / 'src/server.js').write_text('// MCP server fixture')
        (path / 'package.json').write_text('{}')
        return path.resolve()

    def test_default_requires_managed_pin_even_when_sibling_exists(self):
        with self.assertRaisesRegex(RuntimeError, 'Run python3 install.py'):
            resolve_mcp_root(self.app, {})

    def test_installed_pin_is_default_independent_of_working_directory(self):
        spec = dependency_lock(self.app)
        managed = self.make_dependency(managed_mcp_root(self.app))
        (managed / 'package-lock.json').write_text('{}')
        (managed / 'node_modules').mkdir()
        (managed / 'node_modules/.package-lock.json').write_text('{}')
        (managed / READY_FILE).write_text(json.dumps(installation_record(managed, spec)))
        # Other local settings do not opt out of the managed pin.
        (self.app / 'tvlevels.json').write_text('{"other_setting": true}')
        self.assertEqual(resolve_mcp_root(self.app, {}), managed)
        (managed / READY_FILE).write_text('{}')
        with self.assertRaisesRegex(RuntimeError, 'pinned TradingView MCP'):
            resolve_mcp_root(self.app, {})

    def test_relative_configuration_with_spaces(self):
        other = self.make_dependency(self.base / 'other MCP checkout')
        config = self.app / 'tvlevels.json'
        config.write_text(json.dumps({'mcp_root': '../other MCP checkout'}))
        self.assertEqual(resolve_mcp_root(self.app, {}), other)

    def test_environment_override_takes_precedence_over_local_settings(self):
        other = self.make_dependency(self.base / 'override')
        (self.app / 'tvlevels.json').write_text(json.dumps({'mcp_root': '/missing'}))
        self.assertEqual(resolve_mcp_root(self.app, {'TVLEVELS_MCP_ROOT': str(other)}), other)

    def test_invalid_or_missing_dependency_has_actionable_error(self):
        for value in ('/missing', '', 12, None):
            with self.subTest(value=value):
                (self.app / 'tvlevels.json').write_text(json.dumps({'mcp_root': value}))
                with self.assertRaises((ValueError, RuntimeError)):
                    resolve_mcp_root(self.app, {})
        (self.app / 'tvlevels.json').write_text('[]')
        with self.assertRaisesRegex(ValueError, 'JSON object'):
            resolve_mcp_root(self.app, {})
        (self.app / 'tvlevels.json').write_text('{')
        with self.assertRaisesRegex(ValueError, 'Cannot read TVLevels settings'):
            resolve_mcp_root(self.app, {})

    def test_empty_environment_override_does_not_silently_fall_back(self):
        with self.assertRaisesRegex(ValueError, 'nonempty path'):
            resolve_mcp_root(self.app, {'TVLEVELS_MCP_ROOT': ''})

    def test_mcp_process_uses_dependency_but_keeps_app_state_in_tvlevels(self):
        with patch.dict('os.environ', {'TVLEVELS_MCP_ROOT': str(self.dependency)}), \
                patch('daily_levels.subprocess.Popen') as start, \
                patch.object(MCP, 'request', return_value={}), patch.object(MCP, 'send'):
            client = MCP(self.app)
        self.assertEqual(start.call_args.args[0], ['node', str(self.dependency / 'src/server.js')])
        self.assertEqual(start.call_args.kwargs['cwd'], self.dependency)
        self.assertEqual(client.ownership_path, self.app / 'python/.daily-levels-owned.json')
        self.assertEqual(client.details_path, self.app / '.local/panel/level-details.json')

    def test_bad_dependency_fails_before_starting_a_process(self):
        with patch.dict('os.environ', {'TVLEVELS_MCP_ROOT': '/missing'}), \
                patch('daily_levels.subprocess.Popen') as start:
            with self.assertRaisesRegex(RuntimeError, 'TradingView MCP was not found'):
                MCP(self.app)
        start.assert_not_called()


if __name__ == '__main__':
    unittest.main()
