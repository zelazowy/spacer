import threading
import unittest
from unittest.mock import patch
from task_progress import StageProgress


class StageProgressTests(unittest.TestCase):
    def test_counts_completed_items_including_skips_and_throttles(self):
        events=[]
        with patch('task_progress.time.monotonic',return_value=10):
            stage=StageProgress('Groups',5000,lambda *args:events.append(args))
            for item in stage.track(range(5000)):
                if item%2: continue
        self.assertEqual([(e[1],e[2]) for e in events],[(0,5000),(1,5000),(5000,5000)])

    def test_failed_or_cancelled_item_does_not_claim_completion(self):
        for failure in ('error','cancel'):
            events=[];cancel=threading.Event()
            stage=StageProgress('Stars',3,lambda *args:events.append(args),cancel=cancel)
            with self.assertRaises((ValueError,InterruptedError)):
                for item in stage.track(range(3)):
                    if item==1:
                        if failure=='error': raise ValueError('fit failed')
                        cancel.set()
            self.assertEqual(events[-1][1],1)
