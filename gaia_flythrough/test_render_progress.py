import argparse
import io
from pathlib import Path
import threading
import unittest
from unittest.mock import patch
import numpy as np
from flythrough import render_video


class RenderProgressTests(unittest.TestCase):
    def args(self,**changes):
        value=dict(seconds=2,fps=4,video_width=16,zoom=1.3,travel=80,ease_seconds=.2)
        value.update(changes)
        return argparse.Namespace(**value)

    def test_exact_frame_counts_and_finalization_after_final_frame(self):
        events=[]
        class Encoder:
            stdin=io.BytesIO()
            def wait(self): events.append(('encoder_finished',));return 0
        def counter(done,total,elapsed): events.append(('frames',done,total,elapsed))
        def status(message): events.append(('status',message))
        args=self.args(frame_progress=counter,progress=status)
        with patch('flythrough.subprocess.Popen',return_value=Encoder()):
            render_video(dict(width=16,height=12,stars=[]),np.zeros((12,16,3)),args,Path('test.mp4'))
        counts=[event for event in events if event[0]=='frames']
        self.assertEqual(counts[0][1:3],(0,8));self.assertEqual(counts[-1][1:3],(8,8))
        self.assertTrue(all(a[1]<=b[1] for a,b in zip(counts,counts[1:])))
        self.assertEqual(events[-2],('status','Finalizing MP4…'))
        self.assertEqual(events[-1],('encoder_finished',))

    def test_partial_audit_counts_and_cancellation_do_not_claim_completion(self):
        counts=[];cancel=threading.Event()
        class Encoder:
            stdin=io.BytesIO()
            def wait(self): return 0
        def counter(done,total,elapsed):
            counts.append((done,total))
            if done==1: cancel.set()
        with patch('flythrough.subprocess.Popen',return_value=Encoder()):
            with self.assertRaises(InterruptedError):
                render_video(dict(width=16,height=12,stars=[]),np.zeros((12,16,3)),
                    self.args(frame_indices=[0,3,7],frame_progress=counter,cancel_event=cancel),Path('test.mp4'))
        self.assertEqual(counts,[(0,3),(1,3)])
