"""Applications-link migration without touching real Dock preferences."""
import importlib.util
from pathlib import Path
import plistlib
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('tvlevels_panel_install',
    Path(__file__).resolve().parents[1] / 'panel/install.py')
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class ApplicationLinkTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.destination = self.root / 'Applications/Daily Levels.app'
        self.app = self.bundle('TVLevels/.local/Daily Levels.app')

    def bundle(self, name, identifier=installer.IDENTIFIER):
        app = self.root / name
        (app / 'Contents').mkdir(parents=True)
        (app / 'Contents/Info.plist').write_bytes(plistlib.dumps({'CFBundleIdentifier': identifier}))
        return app

    def test_install_and_repeat_are_idempotent(self):
        self.assertTrue(installer.link_application(self.destination, self.app))
        self.assertEqual(self.destination.resolve(), self.app)
        self.assertFalse(installer.link_application(self.destination, self.app))

    def test_existing_managed_link_is_retargeted_to_new_checkout(self):
        old = self.bundle('previous-checkout/.local/Daily Levels.app')
        self.destination.parent.mkdir()
        self.destination.symlink_to(old, target_is_directory=True)
        self.assertTrue(installer.link_application(self.destination, self.app))
        self.assertEqual(self.destination.resolve(), self.app)
        self.assertTrue(old.exists())

    def test_unrelated_link_is_preserved(self):
        unrelated = self.bundle('Other.app', 'example.other')
        self.destination.parent.mkdir()
        self.destination.symlink_to(unrelated, target_is_directory=True)
        with self.assertRaisesRegex(RuntimeError, 'does not point to Daily Levels'):
            installer.link_application(self.destination, self.app)
        self.assertEqual(self.destination.resolve(), unrelated)

    def test_regular_destination_directory_is_preserved(self):
        self.destination.mkdir(parents=True)
        marker = self.destination / 'keep.txt'
        marker.write_text('keep')
        with self.assertRaisesRegex(RuntimeError, 'already exists'):
            installer.link_application(self.destination, self.app)
        self.assertEqual(marker.read_text(), 'keep')

    def test_broken_unidentified_link_is_not_replaced(self):
        self.destination.parent.mkdir()
        self.destination.symlink_to(self.root / 'missing')
        with self.assertRaisesRegex(RuntimeError, 'does not point to Daily Levels'):
            installer.link_application(self.destination, self.app)
        self.assertEqual(self.destination.readlink(), self.root / 'missing')

    def test_moved_source_receipt_recovers_only_its_own_broken_link(self):
        installer.link_application(self.destination, self.app)
        source = self.root / 'TVLevels'
        moved = self.root / 'moved TVLevels'
        source.rename(moved)
        moved_app = moved / '.local/Daily Levels.app'
        self.assertTrue(self.destination.is_symlink())
        self.assertFalse(self.destination.exists())
        self.assertTrue(installer.link_application(self.destination, moved_app))
        self.assertEqual(self.destination.resolve(), moved_app)
        self.assertFalse(installer.link_application(self.destination, moved_app))

    def test_receipt_does_not_authorize_an_unrelated_broken_link(self):
        installer.link_application(self.destination, self.app)
        self.destination.unlink()
        self.destination.symlink_to(self.root / 'unrelated missing app')
        with self.assertRaisesRegex(RuntimeError, 'leaving it untouched'):
            installer.link_application(self.destination, self.app)
        self.assertEqual(self.destination.readlink(), self.root / 'unrelated missing app')

    def test_corrupt_receipt_cannot_replace_a_broken_link(self):
        installer.link_application(self.destination, self.app)
        installer.link_receipt(self.app).write_text('{')
        self.app.rename(self.root / 'removed-app')
        replacement = self.bundle('new-checkout/.local/Daily Levels.app')
        installer.link_receipt(replacement).parent.mkdir(parents=True)
        installer.link_receipt(replacement).write_text('{')
        before = self.destination.readlink()
        with self.assertRaisesRegex(RuntimeError, 'leaving it untouched'):
            installer.link_application(self.destination, replacement)
        self.assertEqual(self.destination.readlink(), before)

    def test_dock_url_normalization_does_not_force_repeated_updates(self):
        for url in (self.destination.as_uri(), self.destination.as_uri()+'/',
                    'file://'+str(self.destination)):
            with self.subTest(url=url):
                self.assertTrue(installer.points_to_path({'file-data':{'_CFURLString':url}}, self.destination))
        self.assertFalse(installer.points_to_path({'file-data':{'_CFURLString':self.app.as_uri()}}, self.destination))


if __name__ == '__main__':
    unittest.main()
