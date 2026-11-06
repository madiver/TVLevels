"""Installer preflight and configuration migration without touching installed apps."""
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('tvlevels_setup', Path(__file__).resolve().parents[1] / 'install.py')
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)


class InstallerTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.settings = self.root / 'tvlevels.json'
        self.original = b'{ "mcp_root": "../old checkout", "keep": {"value": 42} }\n'
        self.settings.write_bytes(self.original)
        self.environment = patch.dict(os.environ, {}, clear=True)
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def test_explicit_pin_switch_preserves_other_settings_and_exact_backup(self):
        with setup.pinned_settings(self.root, True):
            self.assertEqual(json.loads(self.settings.read_text()), {'keep': {'value': 42}})
        backups = list((self.root / '.local/settings-backups').glob('*.json'))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), self.original)

    def test_failed_install_restores_original_settings(self):
        with self.assertRaisesRegex(RuntimeError, 'build failed'):
            with setup.pinned_settings(self.root, True):
                raise RuntimeError('build failed')
        self.assertEqual(self.settings.read_bytes(), self.original)

    def test_default_preserves_existing_override(self):
        with setup.pinned_settings(self.root, False):
            self.assertEqual(self.settings.read_bytes(), self.original)
        self.assertFalse((self.root / '.local').exists())

    def test_environment_override_blocks_explicit_migration(self):
        with patch.dict(os.environ, {'TVLEVELS_MCP_ROOT': '/developer/checkout'}):
            with self.assertRaisesRegex(RuntimeError, 'Unset TVLEVELS_MCP_ROOT'):
                with setup.pinned_settings(self.root, True):
                    self.fail('must reject environment override')
        self.assertEqual(self.settings.read_bytes(), self.original)

    def test_dependency_only_does_not_install_apps(self):
        with patch.object(setup, 'ROOT', self.root), patch.object(setup, 'preflight'), \
                patch.object(setup, 'ensure_dependency', return_value=self.root / 'managed'), \
                patch.object(setup, 'resolve_mcp_root', return_value=self.root / 'managed'), \
                patch.object(setup.subprocess, 'run') as run:
            self.assertEqual(setup.main(['--dependency-only']), 0)
        run.assert_not_called()

    def test_full_flow_installs_panel_and_pinned_launcher(self):
        managed = self.root / 'managed'
        with patch.object(setup, 'ROOT', self.root), patch.object(setup, 'preflight'), \
                patch.object(setup, 'ensure_dependency', return_value=managed), \
                patch.object(setup, 'resolve_mcp_root', return_value=managed), \
                patch.object(setup.subprocess, 'run') as run:
            self.assertEqual(setup.main(['--use-pinned']), 0)
        self.assertEqual([call.args[0][1] for call in run.call_args_list],
                         [str(self.root / 'panel/install.py'), str(managed / 'launcher/install.py')])

    def test_non_mac_install_stops_before_any_download(self):
        with patch.object(setup, 'ROOT', self.root), patch.object(setup.sys, 'platform', 'win32'), \
                patch.object(setup, 'ensure_dependency') as download:
            self.assertEqual(setup.main([]), 1)
        download.assert_not_called()
