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
        spec=importlib.util.spec_from_file_location('spacer_launcher',Path(__file__).with_name('app.py'))
        cls.launcher=importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules,sirilpy=None):
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
        self.assertFalse(hasattr(w,'zoom_hint'))
        w.zoom.setValue(10);self.assertEqual(w.zoom_percent(),900)
        self.assertEqual(w.zoom.text(),'10×')

    def test_project_restore_and_switch_clear_previous_exports(self):
        w=self.window;saved=self.folder/'saved';saved.mkdir()
        (saved/'scene_iterative.json').write_text('{}')
        (saved/'project.json').write_text(json.dumps(dict(seconds=25,zoom=150,last_render='flight')))
        for suffix in ('.mp4','.html'): (saved/('flight'+suffix)).touch()
        w.use_prepared(saved)
        self.assertEqual(w.seconds.value(),25);self.assertEqual(w.zoom.value(),2.5)
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

    def test_zoom_scale_preserves_existing_project_units(self):
        w=self.window
        self.assertEqual(w.zoom.value(),1.3);self.assertEqual(w.zoom_percent(),30)
        for scale,percent in ((1,0),(2,100),(10,900),(101,10000),(1.301,30.1)):
            w.zoom.setValue(scale)
            self.assertEqual(w.zoom_percent(),percent)
        saved=self.folder/'older';saved.mkdir()
        (saved/'project.json').write_text(json.dumps(dict(zoom=30.1)))
        w.use_prepared(saved)
        self.assertAlmostEqual(w.zoom.value(),1.301)
        self.assertEqual(w.zoom_percent(),30.1)

    def test_standalone_opens_image_and_project_without_siril(self):
        import numpy as np
        from astropy.io import fits
        from astropy.wcs import WCS
        wcs=WCS(naxis=2);wcs.wcs.ctype=['RA---TAN','DEC--TAN']
        wcs.wcs.crval=[56,24];wcs.wcs.crpix=[8,6];wcs.wcs.cdelt=[-.01,.01]
        path=self.folder/'disk.fits'
        fits.PrimaryHDU(np.zeros((3,12,16),dtype=np.float32),wcs.to_header()).writeto(path)
        with patch.dict(sys.modules,sirilpy=None):
            w=self.launcher.FlythroughWindow()
            try:
                self.assertFalse(w.start.isEnabled())
                self.assertEqual(w.new_project.text(),'Open image…')
                w.use_image(path)
                self.assertTrue(w.start.isEnabled())
                self.assertEqual(w.stretch.count(),1)
                w.executable.setText('/bin/sh');w.ffmpeg.setText('/bin/sh');w.epoch.setText('2026-10-15')
                with patch.object(w,'launch') as launch:
                    w.begin()
                    launch.assert_called_once()
                    self.assertEqual(launch.call_args.args[0].shape,(3,12,16))
                    self.assertEqual(launch.call_args.args[2].source,str(path.resolve()))
                project=self.folder/'prepared';project.mkdir()
                (project/'scene_iterative.json').write_text('{}')
                w.use_prepared(project)
                with patch.object(w,'launch') as launch:
                    w.begin()
                    launch.assert_called_once()
                    self.assertIsNone(launch.call_args.args[0])
                    self.assertTrue(launch.call_args.args[2].reuse)
            finally: w.close()

    def test_open_raster_has_no_surprise_second_dialog(self):
        from PIL import Image
        path=self.folder/'photo.png';Image.new('RGB',(16,12)).save(path)
        w=self.launcher.FlythroughWindow();w.show()
        try:
            with patch.object(self.launcher.QFileDialog,'getOpenFileName',return_value=(str(path),'')) as chooser:
                w.open_image()
                chooser.assert_called_once()
            self.assertEqual(w.file_source.path,path.resolve())
            self.assertTrue(w.coordinates.isVisible())
            self.assertFalse(w.start.isEnabled())
            self.assertIn('Sky coordinates needed',w.coordinates_hint.text())
            with patch.object(self.launcher.QFileDialog,'getOpenFileName',return_value=('','')):
                w.open_coordinates()
            self.assertEqual(w.file_source.path,path.resolve())
            self.assertFalse(w.start.isEnabled())
        finally: w.close()

    def test_solved_astro_tiff_needs_no_reference_dialog(self):
        import numpy as np
        import tifffile
        from astropy.wcs import WCS
        from astropy.io import fits
        wcs=WCS(naxis=2);wcs.wcs.ctype=['RA---TAN','DEC--TAN']
        wcs.wcs.crval=[56,24];wcs.wcs.crpix=[8,6];wcs.wcs.cdelt=[-.01,.01]
        header=wcs.to_header();header.insert(0,('SIMPLE',True));header['DATE-OBS']='2026-10-15'
        path=self.folder/'astro.tif'
        tifffile.imwrite(path,np.zeros((12,16,3),dtype=np.float32),photometric='rgb',description=header.tostring(sep='\n',padding=False),metadata=None)
        w=self.launcher.FlythroughWindow();w.show()
        try:
            with patch.object(self.launcher.QFileDialog,'getOpenFileName',return_value=(str(path),'')) as chooser:
                w.open_image();chooser.assert_called_once()
            self.assertTrue(w.start.isEnabled());self.assertFalse(w.coordinates.isVisible())
            self.assertIn('Astro-TIFF',w.project_hint.text())
            w.executable.setText('/bin/sh');w.ffmpeg.setText('/bin/sh')
            with patch.object(w,'launch') as launch:
                w.begin();launch.assert_called_once()
                self.assertEqual(launch.call_args.args[2].epoch,'2026-10-15')
        finally: w.close()
