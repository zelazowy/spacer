import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import numpy as np
from PIL import Image
from astropy.io import fits
from astropy.wcs import WCS
from astap_solver import solve_project
from siril_pipeline import read_project, resume_project


class SolverTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.image=self.root/'finished.jpg'
        raster=np.zeros((12,16,3),dtype=np.uint8);raster[:4]=150;raster[6:9,3:7]=250
        Image.fromarray(raster).save(self.image)
        self.original=self.image.read_bytes()
        self.options=SimpleNamespace(source=str(self.image),output=str(self.root/'project'),astap='/bin/sh',
            log_directory=self.root/'logs',database='',target='',fov=0,radius=180,binning=0,epoch='2026-10-15',seconds=60,zoom=30,
            engine='StarNet',executable='/fake/starnet',ffmpeg='ffmpeg')
        wcs=WCS(naxis=2);wcs.wcs.ctype=['RA---TAN','DEC--TAN']
        wcs.wcs.crval=[56,24];wcs.wcs.crpix=[8,6];wcs.wcs.cdelt=[-.01,.01]
        self.solution=wcs.to_header()

    def tearDown(self): self.temp.cleanup()

    def fake_process(self,argv,**kwargs):
        proxy=Path(argv[argv.index('-f')+1])
        with fits.open(proxy) as hdul:
            self.assertEqual(hdul[0].data.shape,(12,16))
            self.assertAlmostEqual(float(hdul[0].data.max()),65535,delta=.1)
        self.assertNotIn('-update',argv)
        self.assertTrue(0<=float(argv[argv.index('-ra')+1])<24)
        proxy.with_suffix('.ini').write_text('PLTSOLVD=T\n')
        proxy.with_suffix('.wcs').write_text(self.solution.tostring(padding=False))
        return SimpleNamespace(poll=lambda:0,returncode=0)

    def test_success_preserves_photo_and_reopens_without_solver(self):
        with patch('astap_solver.subprocess.Popen',side_effect=self.fake_process):
            out=solve_project(self.options)
        self.assertEqual(self.image.read_bytes(),self.original)
        with Image.open(self.image) as image: expected=np.flipud(np.asarray(image))/255
        with fits.open(out/'source_wcs.fits') as hdul:
            self.assertEqual(hdul[0].data.shape,(3,12,16))
            np.testing.assert_allclose(np.moveaxis(hdul[0].data,0,-1),expected,atol=1e-7)
            self.assertTrue(hdul[0].header['DATE-OBS'].startswith('2026-10-15'))
            self.assertEqual(hdul[0].header['DATESRC'],'Manual date')
            self.assertFalse(hdul[0].header['DATEAPPX'])
        state=read_project(out)
        self.assertEqual(state['stage'],'solved');self.assertEqual(state['astrometry']['solver'],'ASTAP')
        # Project preparation uses the committed pixels even if the input is gone.
        self.image.unlink()
        opts=SimpleNamespace(seconds=30,zoom=100,ffmpeg='ffmpeg',epoch='2025-01-01',engine='StarXTerminator',executable='/new/engine')
        with patch('siril_pipeline.run_pipeline',return_value=out) as prepare,patch('astap_solver.subprocess.Popen') as solver:
            resume_project(out,opts)
            solver.assert_not_called();prepare.assert_called_once()
            self.assertEqual(opts.engine,'StarXTerminator');self.assertEqual(opts.epoch,'2025-01-01')

    def test_failed_process_and_invalid_wcs_do_not_create_project(self):
        with patch('astap_solver.subprocess.Popen',return_value=SimpleNamespace(poll=lambda:1,returncode=1)):
            with self.assertRaisesRegex(RuntimeError,'could not solve'): solve_project(self.options)
        self.assertFalse(Path(self.options.output).exists())
        self.solution=fits.Header()
        with patch('astap_solver.subprocess.Popen',side_effect=self.fake_process):
            with self.assertRaisesRegex(RuntimeError,'valid celestial'): solve_project(self.options)
        self.assertFalse(Path(self.options.output).exists());self.assertEqual(self.image.read_bytes(),self.original)

    def test_cancel_stops_process_and_keeps_source(self):
        cancel=threading.Event()
        def start(*args,**kwargs):
            cancel.set()
            return SimpleNamespace(poll=lambda:None,terminate=lambda:None,wait=lambda **kw:None)
        with patch('astap_solver.subprocess.Popen',side_effect=start):
            with self.assertRaises(InterruptedError): solve_project(self.options,cancel=cancel)
        self.assertFalse(Path(self.options.output).exists());self.assertEqual(self.image.read_bytes(),self.original)

    def test_timeout_and_existing_project_are_safe(self):
        self.options.timeout=-1
        with patch('astap_solver.subprocess.Popen',return_value=SimpleNamespace(poll=lambda:None,terminate=lambda:None,wait=lambda **kw:None)):
            with self.assertRaisesRegex(RuntimeError,'timed out'): solve_project(self.options)
        self.assertFalse(Path(self.options.output).exists())
        Path(self.options.output).mkdir()
        with patch('astap_solver.subprocess.Popen') as solver:
            with self.assertRaisesRegex(ValueError,'existing projects'): solve_project(self.options)
            solver.assert_not_called()

    def test_solver_uses_labelled_filesystem_estimate_when_date_is_missing(self):
        self.options.epoch=''
        with patch('astap_solver.subprocess.Popen',side_effect=self.fake_process):
            out=solve_project(self.options)
        state=read_project(out)
        self.assertTrue(state['date_info']['approximate'])
        self.assertIn('File ',state['date_info']['source'])
        header=fits.getheader(out/'source_wcs.fits')
        self.assertTrue(header['DATEAPPX'])
        self.assertEqual(header['DATE-OBS'],state['date_info']['value'])

    def test_live_output_arrives_before_exit_and_log_survives_failure(self):
        events=[];state={'finished':False}
        def process(argv,**kwargs):
            self.fake_process(argv,**kwargs)
            writer=kwargs['stdout'];writer.write('Detecting stars\nPartial');writer.flush()
            class Process:
                returncode=0
                polls=0
                def poll(self):
                    self.polls+=1
                    if self.polls==1: return None
                    if not state['finished']:
                        writer.write(' line\n');writer.flush();state['finished']=True
                    return 0
            return Process()
        with patch('astap_solver.subprocess.Popen',side_effect=process):
            solve_project(self.options,lambda message:events.append((message,state['finished'])))
        self.assertIn(('ASTAP | Detecting stars',False),events)
        self.assertIn(('ASTAP | Partial line',True),events)
        log=Path(self.options.diagnostic_log)
        self.assertTrue(log.exists());self.assertIn('Detecting stars',log.read_text())
        self.options.output=str(self.root/'failed-project')
        with patch('astap_solver.subprocess.Popen',return_value=SimpleNamespace(poll=lambda:1,returncode=1)):
            with self.assertRaisesRegex(RuntimeError,'Diagnostic log:'): solve_project(self.options)
        self.assertTrue(Path(self.options.diagnostic_log).exists())

    def test_log_tail_preserves_split_utf8_and_carriage_return_updates(self):
        import io
        from astap_solver import SolverLogTail
        encoded='Field 4.2°\rStars: 500\n'.encode('utf-8')
        boundary=encoded.index('°'.encode('utf-8'))+1
        reader=io.BytesIO(encoded[:boundary]);events=[]
        tail=SolverLogTail(reader,events.append)
        tail.drain()
        cursor=reader.tell();reader.seek(0,2);reader.write(encoded[boundary:]);reader.seek(cursor)
        tail.drain(final=True)
        self.assertEqual(events,['ASTAP | Field 4.2°','ASTAP | Stars: 500'])

    def test_quiet_solver_reports_elapsed_time_while_running(self):
        def process(argv,**kwargs):
            self.fake_process(argv,**kwargs)
            class Process:
                returncode=0
                polls=0
                def poll(self):
                    self.polls+=1
                    return None if self.polls==1 else 0
            return Process()
        events=[];clock=iter(range(0,1000,11))
        with patch('astap_solver.subprocess.Popen',side_effect=process),patch('astap_solver.time.monotonic',side_effect=lambda:next(clock)):
            solve_project(self.options,events.append)
        self.assertTrue(any('ASTAP still working' in line for line in events))

    def test_compact_proxy_preserves_grid_and_detected_peaks(self):
        from astap_solver import compact_star_proxy
        from scipy import ndimage
        yy,xx=np.mgrid[:128,:160]
        mono=np.full((128,160),.05,dtype=np.float32)
        centers=[(y,x) for y in (16,40,64,88) for x in (16,40,64,88)]
        for y,x in centers: mono+=np.exp(-((yy-y)**2+(xx-x)**2)/3).astype(np.float32)
        before=mono.copy();proxy=compact_star_proxy(mono)
        self.assertEqual(proxy.shape,mono.shape);np.testing.assert_array_equal(mono,before)
        peaks=(proxy==ndimage.maximum_filter(proxy,9))&(proxy>proxy.max()*.3)
        detected=np.column_stack(np.where(peaks))
        for center in centers: self.assertLess(np.linalg.norm(detected-np.array(center),axis=1).min(),1)
        self.assertIsNone(compact_star_proxy(np.zeros((64,64),dtype=np.float32)))

    def test_compact_candidate_is_refined_against_original_pixels(self):
        result=[(None,'no match'),(self.solution.copy(),''),(self.solution.copy(),'')]
        with patch('astap_solver.run_attempt',side_effect=result) as run,patch('astap_solver.compact_star_proxy',return_value=np.ones((12,16),dtype=np.float32)):
            out=solve_project(self.options)
        self.assertEqual([call.args[5] for call in run.call_args_list],[2000,500,5000])
        self.assertEqual(read_project(out)['astrometry']['strategy'],'compact-peaks+original-refinement')
        self.assertEqual(self.image.read_bytes(),self.original)

    def test_unconfirmed_compact_candidate_never_creates_project(self):
        result=[(None,'no match'),(self.solution.copy(),''),(None,'no confirmation'),(None,'no confirmation'),(None,'no confirmation'),(None,'no match')]
        with patch('astap_solver.run_attempt',side_effect=result),patch('astap_solver.compact_star_proxy',return_value=np.ones((12,16),dtype=np.float32)):
            with self.assertRaisesRegex(RuntimeError,'could not solve'): solve_project(self.options)
        self.assertFalse(Path(self.options.output).exists())

    def test_bad_refinement_is_rejected_and_smaller_sample_is_used(self):
        bad=self.solution.copy();bad['CRVAL1']=bad['CRVAL1']+1
        result=[(self.solution.copy(),''),(bad,''),(self.solution.copy(),'')]
        with patch('astap_solver.run_attempt',side_effect=result):
            out=solve_project(self.options)
        state=read_project(out)['astrometry']
        self.assertEqual(state['maximum_stars'],2000)
        self.assertFalse(state['attempts'][1]['accepted'])
        self.assertTrue(state['attempts'][2]['accepted'])

    def test_named_target_starts_local_and_scale_bracket_confirms_candidate(self):
        self.options.target='03 47 13 +24 07 11'
        result=[(self.solution.copy(),''),(None,'no match'),(None,'no match'),(self.solution.copy(),'')]
        with patch('astap_solver.run_attempt',side_effect=result) as run:
            out=solve_project(self.options)
        self.assertEqual(run.call_args_list[0].args[2].radius,5)
        self.assertEqual([call.args[5] for call in run.call_args_list],[2000,5000,2000,3000])
        self.assertEqual(read_project(out)['astrometry']['maximum_stars'],3000)

    def test_refinement_rejects_edge_distortion_parity_and_inexact_scale(self):
        from astap_solver import refinement_consistent
        bad=self.solution.copy();bad['CDELT1']=-bad['CDELT1']
        self.assertFalse(refinement_consistent(self.solution,bad,16,12)[0])
        bad=self.solution.copy();bad['CTYPE1']='RA---TAN-SIP';bad['CTYPE2']='DEC--TAN-SIP'
        bad['A_ORDER']=2;bad['B_ORDER']=2;bad['A_2_0']=1
        self.assertFalse(refinement_consistent(self.solution,bad,16,12)[0])
        inexact=self.solution.copy();inexact['WARNING']='Warning inexact scale!'
        with patch('astap_solver.run_attempt',side_effect=[(self.solution.copy(),''),(inexact,''),(self.solution.copy(),'')]):
            state=read_project(solve_project(self.options))['astrometry']
        self.assertFalse(state['attempts'][1]['accepted'])
        self.assertTrue(state['attempts'][2]['accepted'])
