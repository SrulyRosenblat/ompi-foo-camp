"""The file watcher must coalesce its own writes and keep API access responsive."""
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from omp_live.cli import Watcher, build


class WatcherTests(unittest.TestCase):
    def test_bursts_during_reconcile_never_overlap(self):
        with tempfile.TemporaryDirectory() as tmp:
            sync = build(Path(tmp))
            entered, release = threading.Event(), threading.Event()
            counts = {'active': 0, 'maximum': 0, 'calls': 0}

            def reconcile():
                counts['active'] += 1
                counts['maximum'] = max(counts['maximum'], counts['active'])
                counts['calls'] += 1
                entered.set()
                release.wait(2)
                counts['active'] -= 1
                return 0

            sync.reconcile = reconcile
            watcher = Watcher(sync, debounce=.02)
            worker = threading.Thread(target=watcher._fire)
            worker.start()
            self.assertTrue(entered.wait(1))
            for _ in range(50):
                watcher.schedule()
            watcher._fire()  # a heartbeat racing a filesystem pass
            self.assertEqual(counts['calls'], 1)
            release.set()
            worker.join(2)
            deadline = time.monotonic() + 1
            while counts['calls'] < 2 and time.monotonic() < deadline:
                time.sleep(.01)
            watcher._stop.set()
            if watcher._timer:
                watcher._timer.cancel()
            self.assertEqual(counts['maximum'], 1)
            self.assertEqual(counts['calls'], 2)

    def test_idle_reads_do_not_create_a_reconcile_loop(self):
        with tempfile.TemporaryDirectory() as tmp:
            sync = build(Path(tmp))
            sync.systems['wiki'].write_page('note.md', '# A note')
            sync.reconcile()
            state_mtime = sync.state_path.stat().st_mtime_ns
            calls = []
            reconcile = sync.reconcile

            def counted():
                calls.append(time.monotonic())
                return reconcile()

            sync.reconcile = counted
            watcher = Watcher(sync, debounce=.04, heartbeat=10)
            worker = threading.Thread(target=watcher.run)
            worker.start()
            try:
                for _ in range(12):
                    sync.systems['wiki'].export()
                    sync.systems['graph'].snapshot()
                    sync.systems['search'].docs()
                    time.sleep(.05)
                self.assertLessEqual(len(calls), 3, 'idle reads caused a watcher feedback loop')
                self.assertEqual(sync.state_path.stat().st_mtime_ns, state_mtime)
                sync.systems['wiki'].write_page('note.md', '# Changed')
                deadline = time.monotonic() + 3
                while sync.export.get('note.md')['body'] != '# Changed' and time.monotonic() < deadline:
                    time.sleep(.03)
                self.assertEqual(sync.export.get('note.md')['body'], '# Changed')
            finally:
                watcher._stop.set()
                worker.join(3)
                self.assertFalse(worker.is_alive())


if __name__ == '__main__':
    unittest.main()
