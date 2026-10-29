"""Native preview projection, read-only assets, loading and interaction regressions."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import hashlib,json,tempfile,threading,unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
from PyQt6.QtCore import QEventLoop,QTimer,QPoint,Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication
from PyQt6 import sip
from flythrough import png_data
from preview import prepare_preview,PreviewWindow


class PreviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'scene_iterative.json';self.windows=[]
        stars=[]
        for i,(x,d,a) in enumerate([(30,200,.3),(80,1000,.6),(140,50,.1)]):
            stars.append(dict(source_id=str(i),x=x,y=30,depth=d,distance_pc=d,ax=2,ay=2,w=5,h=5,
                lower_pc=d*.9,upper_pc=d*1.1,image=png_data(np.full((5,5,3),a))))
        self.scene=dict(width=180,height=90,stars=stars,background=png_data(np.full((90,180,3),.02)),prepared_with_version='0.17.0')
        self.path.write_text(json.dumps(self.scene));self.original=self.path.read_bytes()
        self.settings=dict(zoom_mode='independent',zoom=1.3,travel_pc=80,target_distance_pc=300,seconds=12)
    def tearDown(self):
        for window in self.windows:
            if sip.isdeleted(window):continue
            window.close()
            if not sip.isdeleted(window.loader) and window.loader.isRunning():self.wait(window)
        self.app.processEvents()
        self.assertEqual(self.path.read_bytes(),self.original)
    def wait(self,window):
        loop=QEventLoop();window.loader.finished.connect(loop.quit);QTimer.singleShot(5000,loop.quit)
        if window.loader.isRunning():loop.exec()
        self.app.processEvents()
        self.assertTrue(sip.isdeleted(window.loader) or not window.loader.isRunning())
    def window(self):
        window=PreviewWindow(self.path,self.settings);self.windows.append(window);window.show();self.wait(window)
        self.assertTrue(window.finished_loading);return window
    def test_downsampling_preserves_all_metadata_coordinates_and_selection_cap(self):
        data=prepare_preview(self.path,width=90)
        self.assertEqual(len(data.stars),3);self.assertEqual(data.background.width(),90)
        for before,after,tile in zip(self.scene['stars'],data.stars,data.tiles):
            self.assertEqual(after,{k:v for k,v in before.items() if k!='image'})
            self.assertEqual(tile.width(),3)
            self.assertLessEqual(tile.right(),data.atlas.width());self.assertLessEqual(tile.bottom(),data.atlas.height())
        limited=prepare_preview(self.path,max_stars=1)
        self.assertEqual([s['source_id'] for s in limited.stars],['1'])
        # Omitted star light is returned to the flat layer, not discarded.
        self.assertGreater(limited.background.pixelColor(30,30).red(),data.background.pixelColor(15,15).red())
        event=threading.Event();event.set()
        with self.assertRaises(InterruptedError):prepare_preview(self.path,cancel=event)
    def test_projection_matches_export_modes_and_omits_crossed_stars(self):
        w=self.window();c=w.canvas;w.position.setValue(10000)
        z,sz,move,left,top,valid=c.geometry_at()
        self.assertAlmostEqual(z,1.3);self.assertAlmostEqual(move,80)
        self.assertAlmostEqual(left[0]+self.scene['stars'][0]['ax']*sz,90+(30-90)*(200/120)*1.3)
        self.assertFalse(valid[2])
        w.mode.setCurrentIndex(1)
        z,sz,move,left,top,valid=c.geometry_at()
        self.assertAlmostEqual(z,300/220);self.assertEqual(sz,1)
        self.assertAlmostEqual(left[0]+2,90+(30-90)*200/120)
        # Fractional positions remain continuous in preview geometry.
        w.position.setValue(5000);a=c.geometry_at()[3][1]
        w.position.setValue(5001);b=c.geometry_at()[3][1]
        self.assertNotEqual(a,b);self.assertLess(abs(a-b),.1)
    def test_invalid_target_disables_play_apply_and_never_invents_a_distance(self):
        w=self.window();w.distance.setValue(0);w.mode.setCurrentIndex(1)
        self.assertFalse(w.play.isEnabled());self.assertFalse(w.apply.isEnabled())
        self.assertIn('greater than travel',w.canvas.message)
        w.distance.setValue(300)
        self.assertTrue(w.play.isEnabled());self.assertTrue(w.apply.isEnabled());self.assertFalse(w.zoom.isEnabled())
        values=[];w.settings_chosen.connect(values.append);w.apply.click()
        self.assertEqual(values[0]['zoom_mode'],'target_distance');self.assertEqual(values[0]['target_distance_pc'],300)
        w.mode.setCurrentIndex(0);self.assertTrue(w.zoom.isEnabled());self.assertFalse(w.distance.isEnabled())
    def test_play_scrub_inspection_and_close_stop_animation(self):
        w=self.window();w.play.click();self.assertTrue(w.timer.isActive())
        w.position.sliderPressed.emit();self.assertFalse(w.timer.isActive())
        rect=w.canvas.view_rect();scale=rect.width()/180
        QTest.mouseClick(w.canvas,Qt.MouseButton.LeftButton,pos=QPoint(round(rect.left()+80*scale),round(rect.top()+30*scale)))
        self.assertIn('Gaia 1',w.selection.text());self.assertIn('3261.6 ly',w.selection.text())
        w.play.click();w.close();self.assertFalse(w.timer.isActive())
    def test_close_during_load_cancels_before_window_destruction(self):
        entered=threading.Event()
        def until_cancel(path,limit,cancel):
            entered.set();cancel.wait(3);raise InterruptedError()
        with patch('preview.prepare_preview',side_effect=until_cancel):
            w=PreviewWindow(self.path,self.settings);self.windows.append(w);w.show()
            self.assertTrue(entered.wait(1));w.close();self.assertTrue(w.loader.cancel.is_set())
            self.wait(w);self.assertTrue(sip.isdeleted(w) or not w.isVisible())
