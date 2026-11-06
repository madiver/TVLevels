import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from daily_levels import run, clear_levels
from level_capture import record_completed
from test_daily_levels import Fake


class CaptureTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'details.json'

    def result(self):
        return dict(symbol='NASDAQ:TEST', scope='chart|NASDAQ:TEST|pane:2',
                    levels=[dict(price=1.2, kind='resistance')], drawn_at=10)

    def test_draw_clear_redraw_are_immutable_distinct_records(self):
        client = Fake(); client.details_path = self.path
        run(client, enabled_types=['gap'])
        originals = {p: p.read_bytes() for p in self.path.parent.joinpath('level-snapshots').glob('*.json')}
        clear_levels(client)
        run(client, enabled_types=['gap'])
        files = list(self.path.parent.joinpath('level-snapshots').glob('*.json'))
        self.assertEqual(len(files), 3)
        for p, data in originals.items(): self.assertEqual(p.read_bytes(), data)
        records = [json.loads(p.read_text()) for p in files]
        self.assertEqual(sum(r['kind'] == 'clear' for r in records), 1)
        self.assertTrue(all(r['completed_at'] == r['result']['completed_at'] for r in records))

    def test_completion_is_recorded_after_restoration(self):
        client = Fake(); client.details_path = self.path
        import level_capture
        original = level_capture.record_completed
        def checked(*args, **kwargs):
            self.assertEqual((client.resolution, client.session), ('5', 'regular'))
            return original(*args, **kwargs)
        with patch('level_capture.record_completed', side_effect=checked):
            result = run(client, enabled_types=['gap'])
        self.assertIn('completed_at', result)
        self.assertEqual(json.loads(self.path.read_text())['NASDAQ:TEST']['completed_at'], result['completed_at'])

    def test_failed_draw_and_dry_run_publish_nothing(self):
        client = Fake(True); client.details_path = self.path
        with self.assertRaises(RuntimeError): run(client, enabled_types=['gap'])
        self.assertFalse((self.path.parent / 'level-snapshots').exists())
        client = Fake(); client.details_path = self.path
        run(client, enabled_types=['gap'], dry_run=True)
        self.assertFalse((self.path.parent / 'level-snapshots').exists())

    def test_completion_creates_only_an_immutable_local_archive(self):
        capture = record_completed(self.path, self.result(), 'draw', wall=lambda: 20)
        archive = self.path.parent / 'level-snapshots' / (capture['id'] + '.json')
        self.assertEqual(json.loads(archive.read_text())['completed_at'], 20)
        self.assertEqual({p.name for p in self.path.parent.iterdir()}, {'level-snapshots'})

    def test_restore_failure_does_not_publish_completion(self):
        class BadRestore(Fake):
            def call(self, name, **args):
                if name == 'chart_set_timeframe' and args['timeframe'] == '5':
                    raise RuntimeError('cannot restore')
                return super().call(name, **args)
        client = BadRestore(); client.details_path = self.path
        with self.assertRaises(RuntimeError): run(client, enabled_types=['gap'])
        self.assertFalse((self.path.parent / 'level-snapshots').exists())

    def test_storage_failure_reports_draw_already_happened(self):
        client = Fake(); client.details_path = self.path
        with patch('level_capture.record_completed', side_effect=OSError('disk full')):
            with self.assertRaisesRegex(RuntimeError, 'Chart updated'):
                run(client, enabled_types=['gap'])


if __name__ == '__main__': unittest.main()
