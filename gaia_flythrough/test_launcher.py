"""Qt workflow checks using saved fixtures; no Siril connection or rendering."""
from contextlib import nullcontext
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
try:
    from PyQt6.QtWidgets import QApplication
except ImportError:
    QApplication=None


@unittest.skipIf(QApplication is None,'PyQt6 is needed for launcher checks')
class LauncherTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([])
        spec=importlib.util.spec_from_file_location('spacer_launcher',Path(__file__).resolve().parents[1]/'Siril_Gaia_Flythrough.py')
        cls.launcher=importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules,sirilpy=SimpleNamespace(ensure_installed=lambda *args:None)):
            spec.loader.exec_module(cls.launcher)

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.folder=Path(self.temp.name)
        self.window=self.launcher.FlythroughWindow(SimpleNamespace(get_image_filename=lambda:str(self.folder/'M45.fits')))
        self.window.show();self.app.processEvents()

    def tearDown(self):
        self.window.close();self.temp.cleanup()

    def test_disclosures_keep_setup_out_of_main_workflow(self):
        w=self.window
        self.assertFalse(w.advanced_dialog.isVisible());self.assertFalse(w.log.isVisible())
        original_size=w.size()
        w.advanced_toggle.setChecked(True);self.app.processEvents()
        self.assertTrue(w.advanced_dialog.isVisible());self.assertEqual(w.size(),original_size)
        w.advanced_dialog.close()
        self.assertFalse(w.advanced_toggle.isChecked())
        w.zoom.setValue(900);self.assertIn('10×',w.zoom_hint.text())

    def test_project_restore_and_switch_clear_previous_exports(self):
        w=self.window;saved=self.folder/'saved';saved.mkdir()
        (saved/'scene_iterative.json').write_text('{}')
        (saved/'project.json').write_text(json.dumps(dict(seconds=25,zoom=150,last_render='flight')))
        for suffix in ('.mp4','.html'): (saved/('flight'+suffix)).touch()
        w.use_prepared(saved)
        self.assertEqual(w.seconds.value(),25);self.assertEqual(w.zoom.value(),150)
        self.assertTrue(w.video.isEnabled());self.assertFalse(w.preparation.isEnabled())
        self.assertEqual(w.start.text(),'Render flight')
        w.output.setText(str(self.folder/'new'));w.refresh_project()
        self.assertFalse(w.video.isEnabled());self.assertFalse(w.preview.isEnabled())
        self.assertTrue(w.preparation.isEnabled());self.assertIsNone(w.result)

    def test_busy_and_failure_states_recover_controls(self):
        w=self.window
        options=SimpleNamespace(output=w.output.text(),result_stem='flight')
        with patch.object(self.launcher,'Worker') as worker:
            worker.return_value.cancel=threading.Event()
            w.launch(None,None,options)
            self.assertFalse(w.project_group.isEnabled());self.assertFalse(w.flight_group.isEnabled())
            self.assertFalse(w.advanced.isEnabled());self.assertTrue(w.cancel_button.isVisible())
            self.assertTrue(w.progress_bar.isVisible())
            with patch.object(self.launcher.QMessageBox,'warning'):
                w.failed('FFmpeg could not finish.')
            self.assertTrue(w.log.isVisible())
            w.finished()
            self.assertTrue(w.project_group.isEnabled());self.assertTrue(w.flight_group.isEnabled())
            self.assertFalse(w.progress_bar.isVisible());self.assertIn('could not finish',w.status.text())
            w.worker.cancel.set()
            with patch.object(self.launcher.QMessageBox,'warning') as warning:
                w.failed('Interrupted')
                warning.assert_not_called()
            self.assertIn('Cancelled',w.status.text())
            w.worker=None

    def test_partial_project_has_resume_action(self):
        saved=self.folder/'partial';saved.mkdir()
        (saved/'project.json').write_text(json.dumps(dict(stage='matching')))
        self.window.use_prepared(saved)
        self.assertEqual(self.window.start.text(),'Resume and render')
        self.assertFalse(self.window.preparation.isEnabled())
        self.assertFalse(self.window.preview.isEnabled())

    def test_missing_date_reveals_required_setup_without_starting_worker(self):
        import numpy as np
        from astropy.wcs import WCS
        wcs=WCS(naxis=2);wcs.wcs.ctype=['RA---TAN','DEC--TAN']
        wcs.wcs.crval=[56,24];wcs.wcs.crpix=[8,6];wcs.wcs.cdelt=[-.01,.01]
        w=self.window
        w.executable.setText('/bin/sh');w.ffmpeg.setText('/bin/sh')
        w.siril.image_lock=lambda:nullcontext()
        w.siril.get_image_fits_header=lambda:wcs.to_header().tostring(sep='\n')
        w.siril.get_image_pixeldata=lambda **kwargs:np.zeros((3,12,16),dtype=np.float32)
        with patch.object(self.launcher.QMessageBox,'warning') as warning,patch.object(w,'launch') as launch:
            w.begin()
            launch.assert_not_called();warning.assert_called_once()
        self.assertTrue(w.advanced_dialog.isVisible())
        self.assertIn('observation date',w.status.text())
