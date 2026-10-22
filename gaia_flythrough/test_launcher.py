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
        from preferences import Preferences
        self.preference_patch=patch.object(self.launcher,'Preferences',side_effect=lambda:Preferences(self.folder/'settings.json'))
        self.preference_patch.start()
        self.window=self.launcher.FlythroughWindow(SimpleNamespace(get_image_filename=lambda:str(self.folder/'M45.fits')))
        self.window.show();self.app.processEvents()

    def tearDown(self):
        self.window.close();self.preference_patch.stop();self.temp.cleanup()

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
                Path(w.output.text()).mkdir(parents=True) # A folder chosen via Browse already exists.
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
            self.assertIn('Solve it with ASTAP',w.coordinates_hint.text())
            self.assertTrue(w.target.isVisible());self.assertFalse(w.advanced_dialog.isVisible())
            w.target.setText('M45')
            w.use_image(path)
            self.assertEqual(w.target.text(),'')
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
            self.assertTrue(w.solver_settings.isHidden())
            self.assertIn('Astro-TIFF',w.project_hint.text())
            w.executable.setText('/bin/sh');w.ffmpeg.setText('/bin/sh')
            with patch.object(w,'launch') as launch:
                w.begin();launch.assert_called_once()
                self.assertTrue(launch.call_args.args[2].epoch.startswith('2026-10-15'))
        finally: w.close()

    def test_unsolved_fits_can_start_optional_solver(self):
        import numpy as np
        from astropy.io import fits
        path=self.folder/'unsolved.fits';fits.PrimaryHDU(np.arange(192,dtype=np.float32).reshape(12,16)/192).writeto(path)
        w=self.launcher.FlythroughWindow();w.show()
        try:
            w.use_image(path)
            self.assertTrue(w.coordinates.isVisible());self.assertTrue(w.solve_button.isEnabled())
            self.assertFalse(w.solver_settings.isHidden())
            self.assertFalse(w.start.isEnabled())
            w.astap.setText('/bin/sh')
            with patch.object(w,'launch') as launch:
                w.solve_image();launch.assert_called_once()
                options=launch.call_args.args[2]
                self.assertTrue(options.solve);self.assertEqual(options.source,str(path.resolve()))
                self.assertEqual(options.fov,0);self.assertEqual(options.radius,180)
            project=self.folder/'solved';project.mkdir()
            fits.PrimaryHDU(np.zeros((3,12,16))).writeto(project/'source_wcs.fits')
            (project/'project.json').write_text(json.dumps(dict(stage='solved',engine='StarNet',executable='/saved/engine',epoch='')))
            w.use_prepared(project)
            self.assertTrue(w.preparation.isEnabled())
            self.assertEqual(w.engine.currentIndex(),1)
            self.assertTrue(w.start.isEnabled());self.assertFalse(w.coordinates.isVisible())
            self.assertTrue(w.solver_settings.isHidden())
        finally: w.close()

    def test_navigation_survives_restart_and_missing_paths_are_safe(self):
        from PIL import Image
        path=self.folder/'remember.jpg';Image.new('RGB',(16,12)).save(path)
        w=self.launcher.FlythroughWindow()
        try:
            w.use_image(path)
            restarted=self.launcher.FlythroughWindow()
            try:
                restarted.restore_last()
                self.assertEqual(restarted.file_source.path,path.resolve())
                self.assertEqual(restarted.preferences.directory('image_directory'),str(path.resolve().parent))
                project=self.folder/'last_project';project.mkdir()
                (project/'scene_iterative.json').write_text('{}')
                restarted.use_prepared(project)
                again=self.launcher.FlythroughWindow()
                try:
                    again.restore_last();self.assertEqual(again.prepared,project.resolve())
                finally: again.close()
                (project/'scene_iterative.json').unlink();project.rmdir()
                missing=self.launcher.FlythroughWindow()
                try:
                    missing.restore_last();self.assertIsNone(missing.prepared)
                finally: missing.close()
            finally: restarted.close()
        finally: w.close()

    def test_date_autofill_is_labelled_and_year_override_reaches_pipeline(self):
        import numpy as np
        from astropy.io import fits
        from astropy.wcs import WCS
        from PIL import Image
        wcs=WCS(naxis=2);wcs.wcs.ctype=['RA---TAN','DEC--TAN']
        wcs.wcs.crval=[56,24];wcs.wcs.crpix=[8,6];wcs.wcs.cdelt=[-.01,.01]
        path=self.folder/'capture.jpg';exif=Image.Exif();exif[36867]='2011:04:03 22:00:00'
        Image.new('RGB',(16,12)).save(path,exif=exif)
        reference=self.folder/'reference.fits'
        fits.PrimaryHDU(np.zeros((3,12,16)),wcs.to_header()).writeto(reference)
        w=self.launcher.FlythroughWindow()
        try:
            w.use_image(path,reference)
            self.assertTrue(w.epoch.text().startswith('2011-04-03'))
            self.assertIn('EXIF capture date',w.date_origin.text())
            w.epoch.setText('2005');w.update_date_origin()
            self.assertIn('Estimated',w.date_origin.text())
            w.executable.setText('/bin/sh');w.ffmpeg.setText('/bin/sh')
            with patch.object(w,'launch') as launch:
                w.begin();launch.assert_called_once()
                options=launch.call_args.args[2]
                self.assertTrue(options.epoch.startswith('2005-07-01'))
                self.assertTrue(options.date_info['approximate'])
            plain=self.folder/'plain.jpg';Image.new('RGB',(16,12)).save(plain)
            w.use_image(plain)
            self.assertTrue(w.epoch.text());self.assertTrue(w.selected_date_info()['approximate'])
            self.assertIn('File ',w.date_origin.text())
        finally: w.close()

    def test_render_progress_counts_wait_for_encoder_and_reset(self):
        from types import SimpleNamespace
        w=self.window
        w.show_frame_progress(720,1440,30)
        self.assertEqual(w.progress_bar.value(),500)
        self.assertIn('720 / 1,440',w.render_counter.text())
        self.assertIn('00:30 remaining',w.render_counter.text())
        w.show_frame_progress(1440,1440,60)
        self.assertEqual(w.progress_bar.value(),999)
        self.assertEqual(w.status.text(),'Finalizing MP4…')
        w.worker=SimpleNamespace(options=SimpleNamespace(result_stem='flight',solve=False),isRunning=lambda:False)
        try:
            w.prepared=self.folder.resolve();w.output.setText(str(w.prepared))
            (self.folder/'project.json').write_text(json.dumps(dict(stage='ready',last_render='flight')))
            (self.folder/'scene_iterative.json').write_text('{}')
            for suffix in ('.html','.mp4'): (self.folder/('flight'+suffix)).touch()
            w.completed(str(self.folder))
            self.assertEqual(w.progress_bar.value(),1000)
            w.finished()
            self.assertTrue(w.progress_bar.isVisible())
            self.assertTrue(w.render_counter.isVisible())
            w.output.setText(str(self.folder/'another'));w.refresh_project()
            self.assertFalse(w.progress_bar.isVisible());self.assertFalse(w.render_counter.isVisible())
        finally: w.worker=None

    def test_status_geometry_and_full_details_log_are_stable(self):
        import io
        from contextlib import redirect_stdout
        from astap_solver import Diagnostic
        w=self.window
        w.cancel_button.show();w.progress_bar.show();self.app.processEvents()
        before=(w.progress_bar.geometry(),w.cancel_button.geometry(),w.size())
        for message in ('Removing stars…','Matching stars to Gaia and screening distance uncertainty… '*4,'Line one\nLine two'):
            w.report_progress(message);self.app.processEvents()
            self.assertEqual((w.progress_bar.geometry(),w.cancel_button.geometry(),w.size()),before)
        stage=w.status.text()
        w.report_progress('ASTAP | 2000 stars detected',True)
        self.assertFalse(w.log.isVisible());self.assertFalse(hasattr(w,'verbose'))
        w.details_toggle.setChecked(True);self.app.processEvents()
        self.assertIn('2000 stars',w.log.toPlainText());self.assertEqual(w.status.text(),stage)
        w.details_toggle.setChecked(False)
        w.report_progress('ASTAP | final diagnostic',True)
        w.details_toggle.setChecked(True)
        self.assertIn('final diagnostic',w.log.toPlainText())
        worker=self.launcher.Worker(None,None,SimpleNamespace())
        received=[];worker.progress.connect(lambda message,detail:received.append((message,detail)))
        with redirect_stdout(io.StringIO()) as output:
            worker.report(Diagnostic('many quads'));worker.report('Solving sky position…')
        self.assertNotIn('many quads',output.getvalue());self.assertIn('Solving sky',output.getvalue())
        self.assertIn(('many quads',True),received)

    def test_known_stage_counters_reset_and_unknown_stages_use_activity(self):
        w=self.window
        w.show_stage_progress('Refining Iterative groups',0,20,0)
        self.assertEqual(w.progress_bar.maximum(),1000);self.assertEqual(w.progress_bar.value(),0)
        w.show_stage_progress('Refining Iterative groups',5,20,10)
        self.assertEqual(w.progress_bar.value(),250);self.assertIn('5 / 20',w.render_counter.text())
        self.assertIn('00:30 remaining',w.render_counter.text())
        self.app.processEvents()
        geometry=(w.progress_bar.geometry(),w.cancel_button.geometry(),w.header.geometry())
        w.show_stage_progress('Refining Iterative groups',20,20,40)
        self.assertEqual(w.progress_bar.value(),1000)
        w.show_stage_progress('Saving Iterative field',0,-1,0);self.app.processEvents()
        self.assertEqual(w.progress_bar.maximum(),0);self.assertFalse(w.render_counter.isVisible())
        w.show_stage_progress('Detecting stars',0,300,0);self.app.processEvents()
        self.assertEqual(w.progress_bar.value(),0);self.assertIn('0 / 300',w.render_counter.text())
        self.assertEqual((w.progress_bar.geometry(),w.cancel_button.geometry(),w.header.geometry()),geometry)
        w.show_stage_progress('Refining Iterative groups',0,0,0)
        self.assertEqual(w.progress_bar.value(),1000);self.assertIn('0 / 0',w.render_counter.text())
        w.worker=SimpleNamespace(cancel=threading.Event());w.worker.cancel.set()
        try:
            w.status.setText('Cancelling…');w.show_stage_progress('More groups',1,3,0)
            self.assertEqual(w.status.text(),'Cancelling…')
        finally: w.worker=None

    def test_solved_jpeg_hides_all_solver_controls_without_starting_astap(self):
        from astropy.io import fits
        from astropy.wcs import WCS
        from PIL import Image
        wcs=WCS(naxis=2);wcs.wcs.ctype=['RA---TAN','DEC--TAN']
        wcs.wcs.crval=[299.9,22.7];wcs.wcs.crpix=[8,6];wcs.wcs.cdelt=[-.001,.001]
        h=wcs.to_header();h.insert(0,('SIMPLE',True));h['NAXIS1']=16;h['NAXIS2']=12;h['DATE-OBS']='2026-07-17'
        exif=Image.Exif();exif[270]=h.tostring(sep='\n',padding=False)
        path=self.folder/'m27.jpg';Image.new('RGB',(16,12)).save(path,exif=exif)
        w=self.launcher.FlythroughWindow();w.show()
        try:
            with patch.object(self.launcher,'solve_project') as solver:
                w.use_image(path);self.app.processEvents();solver.assert_not_called()
            self.assertTrue(w.start.isEnabled());self.assertFalse(w.coordinates.isVisible())
            self.assertFalse(w.target.isVisible());self.assertTrue(w.solver_settings.isHidden())
            self.assertIn('JPEG EXIF',w.project_hint.text());self.assertEqual(w.epoch.text(),'2026-07-17')
        finally: w.close()

    def test_motion_limit_is_editable_for_saved_fields_and_restored(self):
        import json
        self.assertEqual(self.window.star_limit.value(),50000)
        saved=self.folder/'limited';saved.mkdir()
        (saved/'scene_iterative.json').write_text('{}')
        (saved/'project.json').write_text(json.dumps(dict(stage='ready',max_stars=2500)))
        w=self.window;w.use_prepared(saved)
        self.assertEqual(w.star_limit.value(),2500)
        self.assertFalse(w.preparation.isEnabled());self.assertTrue(w.star_limit.isEnabled())
        w.star_limit.setValue(50000)
        with patch.object(w,'launch') as launch:
            w.render_variant()
            self.assertEqual(launch.call_args.args[2].max_stars,50000)

    def test_recalculate_action_requires_saved_layers_and_forwards_limit(self):
        w=self.window
        self.assertFalse(w.recalculation.isHidden());self.assertFalse(w.recalculate_button.isEnabled())
        saved=self.folder/'recalculate';saved.mkdir()
        (saved/'project.json').write_text(json.dumps(dict(stage='ready',max_stars=5000)))
        (saved/'scene_iterative.json').write_text(json.dumps(dict(stars=[],motion_selection=dict(limit=5000))))
        w.use_prepared(saved)
        self.assertFalse(w.recalculate_button.isEnabled())
        self.assertIn('catalog.csv',w.calculation_hint.text())
        for name in ('photo.png','starless.png','source_wcs.fits','catalog.csv'): (saved/name).touch()
        w.star_limit.setValue(50000)
        self.assertTrue(w.recalculate_button.isEnabled());self.assertIn('higher limit',w.calculation_hint.text())
        with patch.object(w,'launch') as launch:
            w.recalculate_button.click()
            options=launch.call_args.args[2]
            self.assertTrue(options.recalculate);self.assertEqual(options.max_stars,50000)
            self.assertEqual(options.output,str(saved.resolve()))
        w.worker=SimpleNamespace(options=options)
        w.completed(str(saved))
        self.assertIn('calculations updated',w.status.text());self.assertEqual(w.progress_bar.value(),1000)
        w.worker=None

    def test_project_picker_starts_at_current_folder_or_existing_parent(self):
        from PyQt6.QtWidgets import QPushButton
        w=self.window;current=self.folder/'current';current.mkdir()
        row=w.path_row(w.output,True);button=row.findChild(QPushButton)
        for value,expected in ((str(current),current),(str(current/'new'/'project'),current)):
            w.output.setText(value)
            with patch.object(self.launcher.QFileDialog,'getExistingDirectory',return_value='') as picker:
                button.click()
                self.assertEqual(Path(picker.call_args.args[2]),expected.resolve())

    def test_advanced_dialog_fits_contents_when_screen_has_space(self):
        w=self.window
        w.advanced_toggle.setChecked(True);self.app.processEvents()
        self.assertLessEqual(w.advanced_dialog.height(),w.screen().availableGeometry().height()-64)
        self.assertEqual(w.advanced_scroll.verticalScrollBar().maximum(),0)

    def test_advanced_sections_and_geometry_stay_visible_across_project_stages(self):
        w=self.window
        def geometry():
            w.advanced_dialog.close();w.advanced_toggle.setChecked(True);self.app.processEvents()
            return (w.advanced_dialog.size(),w.preparation.geometry(),w.star_limit.geometry(),
                w.recalculation.geometry(),w.ffmpeg.geometry(),w.output.geometry())
        baseline=geometry()
        for stage in ('solved','matching','refinement','ready'):
            folder=self.folder/stage;folder.mkdir()
            (folder/'project.json').write_text(json.dumps(dict(stage=stage,engine='StarNet',executable='/saved/tools/starnet2')))
            if stage=='ready': (folder/'scene_iterative.json').write_text('{}')
            w.use_prepared(folder)
            self.assertFalse(w.preparation.isHidden());self.assertFalse(w.recalculation.isHidden())
            self.assertEqual(w.preparation.isEnabled(),stage=='solved')
            self.assertEqual(w.engine.currentIndex(),1);self.assertEqual(w.executable.text(),'/saved/tools/starnet2')
            self.assertEqual(geometry(),baseline,stage)
            if stage!='solved': self.assertIn('Completed star-removal output is reused',w.preparation_note.text())

    def test_new_image_uses_default_limit_after_opening_limited_project(self):
        from PIL import Image
        saved=self.folder/'old-limit';saved.mkdir()
        (saved/'project.json').write_text(json.dumps(dict(stage='ready',max_stars=5000)))
        (saved/'scene_iterative.json').write_text('{}')
        image=self.folder/'new.jpg';Image.new('RGB',(16,12)).save(image)
        w=self.launcher.FlythroughWindow()
        try:
            w.use_prepared(saved);self.assertEqual(w.star_limit.value(),5000)
            self.assertFalse(w.preparation.isHidden());self.assertFalse(w.preparation.isEnabled())
            w.use_image(image)
            self.assertEqual(w.star_limit.value(),50000);self.assertFalse(w.preparation.isHidden())
        finally: w.close()

    def test_target_selection_and_manual_override(self):
        w=self.window
        row=dict(name='M45',distance_pc=135,object_type='OpC',method='parallax',
            quality=None,bibcode='test-reference',minus_error_pc=1,plus_error_pc=1)
        from PyQt6.QtWidgets import QDialog
        with patch.object(w,'target_header',return_value=None),patch('targets.field_query',return_value=('field',None,None,None)),patch.object(QDialog,'exec',return_value=QDialog.DialogCode.Accepted):
            w.target_lookup_query='field'
            w.show_targets([row])
        self.assertEqual(w.target_distance_pc.value(),140)
        self.assertEqual(w.zoom_mode.currentData(),'target_distance')
        self.assertEqual(w.target_info['name'],'M45')
        self.assertIn('approximate',w.target_origin.text())
        self.assertEqual(w.target_info['measurements'][0]['bibcode'],'test-reference')
        w.target_distance_pc.setValue(150)
        self.assertIsNone(w.target_info)
        self.assertEqual(w.target_origin.text(),'Manual target distance')

    def test_new_image_clears_previous_target_distance(self):
        from PIL import Image
        image=self.folder/'M33.jpg';Image.new('RGB',(16,12)).save(image)
        w=self.window
        w.target_distance_pc.setValue(140)
        w.target_info=dict(name='M45',distance_pc=140)
        w.use_image(image)
        self.assertEqual(w.target_distance_pc.value(),0)
        self.assertIsNone(w.target_info)
        self.assertIn('No target distance',w.target_origin.text())

    def test_other_field_catalogue_target_not_restored(self):
        from astropy.io import fits
        from astropy.wcs import WCS
        import numpy as np
        saved=self.folder/'m33';saved.mkdir()
        wcs=WCS(naxis=2);wcs.wcs.ctype=['RA---TAN','DEC--TAN']
        wcs.wcs.crval=[23.4,30.6];wcs.wcs.crpix=[8,6];wcs.wcs.cdelt=[-.01,.01]
        fits.PrimaryHDU(np.zeros((12,16)),wcs.to_header()).writeto(saved/'source_wcs.fits')
        (saved/'project.json').write_text(json.dumps(dict(stage='ready',target_distance_pc=140,
            target_info=dict(name='M45',ra_deg=56.6,dec_deg=24.1))))
        (saved/'scene_iterative.json').write_text('{}')
        self.window.use_prepared(saved)
        self.assertEqual(self.window.target_distance_pc.value(),0)
        self.assertIsNone(self.window.target_info)

    def test_cancel_restores_previous_export_links(self):
        saved=self.folder/'with-export';saved.mkdir()
        (saved/'project.json').write_text(json.dumps(dict(stage='ready',last_render='previous')))
        (saved/'scene_iterative.json').write_text('{}')
        for suffix in ('.html','.mp4'): (saved/('previous'+suffix)).touch()
        w=self.window;w.use_prepared(saved)
        with patch.object(self.launcher,'Worker') as worker:
            worker.return_value.cancel=threading.Event()
            w.launch(None,None,SimpleNamespace(output=str(saved),recalculate=True))
            self.assertFalse(w.preview.isEnabled());self.assertFalse(w.video.isEnabled())
            w.worker.cancel.set();w.failed('cancelled');w.finished()
            self.assertTrue(w.preview.isEnabled());self.assertTrue(w.video.isEnabled())
            self.assertEqual(w.result_stem,'previous');w.worker=None

    def test_details_stays_on_screen_with_scroll_fallback(self):
        w=self.window
        w.details_toggle.setChecked(True);self.app.processEvents()
        self.assertLessEqual(w.height(),w.screen().availableGeometry().height()-64)
        w.main_scroll.verticalScrollBar().setValue(w.main_scroll.verticalScrollBar().maximum())
        self.assertTrue(w.log.isVisible())

    def test_missing_active_revision_offers_recalculation_instead_of_old_render(self):
        saved=self.folder/'missing-revision';saved.mkdir()
        (saved/'project.json').write_text(json.dumps(dict(stage='ready',calculation_path='calculations/missing')))
        (saved/'scene_iterative.json').write_text('{}')
        for name in ('photo.png','starless.png','source_wcs.fits','catalog.csv'): (saved/name).touch()
        w=self.window;w.use_prepared(saved)
        self.assertFalse(w.start.isEnabled());self.assertTrue(w.recalculate_button.isEnabled())
        self.assertIn('calculations are missing',w.status.text())

    def test_header_height_and_spacing_survive_resizing_and_state_changes(self):
        from PIL import Image
        w=self.window
        def geometry():
            return (w.header.y(),w.header.height(),(w.heading.y(),w.heading.height()),(w.subtitle.y(),w.subtitle.height()),w.project_group.y())
        self.app.processEvents();before=geometry()
        for width,height in ((680,1100),(900,1200),(600,800)):
            w.resize(width,height);self.app.processEvents()
            self.assertEqual(geometry(),before)
        for opened in (True,False,True):
            w.details_toggle.setChecked(opened);self.app.processEvents()
            self.assertEqual(geometry(),before)
        unsolved=self.folder/'plain.jpg';Image.new('RGB',(16,12)).save(unsolved)
        standalone=self.launcher.FlythroughWindow();standalone.show();self.app.processEvents()
        try:
            reference=(standalone.header.y(),standalone.header.height(),(standalone.heading.y(),standalone.heading.height()),(standalone.subtitle.y(),standalone.subtitle.height()),standalone.project_group.y())
            standalone.use_image(unsolved);self.app.processEvents()
            self.assertEqual((standalone.header.y(),standalone.header.height(),(standalone.heading.y(),standalone.heading.height()),(standalone.subtitle.y(),standalone.subtitle.height()),standalone.project_group.y()),reference)
            standalone.resize(800,1200);self.app.processEvents()
            self.assertEqual((standalone.header.y(),standalone.header.height(),(standalone.heading.y(),standalone.heading.height()),(standalone.subtitle.y(),standalone.subtitle.height()),standalone.project_group.y()),reference)
        finally: standalone.close()
