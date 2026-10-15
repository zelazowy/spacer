import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import threading
import numpy as np
from PIL import Image
from astropy.io import fits
from astropy.wcs import WCS
import tifffile
from siril_pipeline import normalized_pixels, parse_header, run_pipeline, render_prepared, has_solution, UNSOLVED_MESSAGE, resume_project, save_project, read_project
from flythrough import png_data
from version import VERSION
import json


class PipelineTests(unittest.TestCase):
    def test_variants_reuse_saved_scene_and_never_overwrite(self):
        with tempfile.TemporaryDirectory() as folder:
            out=Path(folder)
            scene=dict(stars=[],width=16,height=12,background=png_data(np.zeros((12,16,3))),extraction_version=6,iterative_revision=2)
            (out/'scene_iterative.json').write_text(json.dumps(scene))
            options=SimpleNamespace(seconds=20,zoom=900,ffmpeg='ffmpeg')
            with patch('siril_pipeline.prepare') as prepare_field,patch('siril_pipeline.run_engine') as engine,patch('siril_pipeline.render_video') as render:
                render_prepared(out,options)
                self.assertEqual(options.result_stem,f'flythrough_v{VERSION}_iterative_20s_zoom900pct_24fps')
                html=(out/(options.result_stem+'.html')).read_text()
                self.assertIn('render_version',html)
                metadata=json.loads((out/(options.result_stem+'.json')).read_text())
                self.assertEqual(metadata['tool_version'],VERSION)
                self.assertEqual(metadata['field_version'],'unversioned')
                self.assertTrue(metadata['created_at'].endswith('+00:00'))
                self.assertNotIn('render_version',json.loads((out/'scene_iterative.json').read_text()))
                self.assertIn('value="10.0"',html)
                self.assertNotIn('MAXZOOM',html)
                render_prepared(out,options)
                self.assertEqual(options.result_stem,f'flythrough_v{VERSION}_iterative_20s_zoom900pct_24fps_02')
                prepare_field.assert_not_called();engine.assert_not_called()
                self.assertEqual(render.call_count,2)

    def test_old_iterative_cache_upgrades_from_saved_natural_field(self):
        with tempfile.TemporaryDirectory() as folder:
            out=Path(folder)
            bg=np.zeros((12,16,3))
            natural=dict(stars=[],width=16,height=12,background=png_data(bg),extraction_version=4)
            old=dict(natural,mode='iterative')
            updated=dict(natural,mode='iterative',iterative_revision=2)
            (out/'scene.json').write_text(json.dumps(natural))
            (out/'scene_iterative.json').write_text(json.dumps(old))
            options=SimpleNamespace(seconds=20,zoom=30,ffmpeg='ffmpeg',mode='iterative')
            with patch('iterative_deblend.refine_prepared_field',return_value=(updated,bg)) as refit,patch('siril_pipeline.run_engine') as engine,patch('siril_pipeline.prepare') as prepare,patch('siril_pipeline.render_video'):
                render_prepared(out,options)
                refit.assert_called_once()
                engine.assert_not_called();prepare.assert_not_called()
            self.assertEqual(json.loads((out/'scene_iterative.json').read_text())['iterative_revision'],2)
            self.assertEqual(json.loads((out/'scene_iterative_before_spike_refinement.json').read_text()),old)

    def test_unsolved_image_rejected_before_outputs_or_engine_start(self):
        with tempfile.TemporaryDirectory() as folder:
            out=Path(folder)/'flight'
            options=SimpleNamespace(output=str(out))
            with patch('siril_pipeline.run_engine') as engine:
                with self.assertRaisesRegex(ValueError,'Siril_ASTAP_PlateSolve'):
                    run_pipeline(np.zeros((3,12,16),dtype=np.float32),fits.Header(),options)
                engine.assert_not_called()
            self.assertFalse(out.exists())
            self.assertEqual(len(parse_header('',require_solution=False)),0)

    def test_uint16_normalization_and_invalid_header(self):
        a=normalized_pixels(np.array([[0,65535]],dtype=np.uint16))
        self.assertEqual(a.shape,(3,1,2))
        np.testing.assert_allclose(a[:,:,1],1)
        with self.assertRaises(ValueError): parse_header('')

    def test_both_engines_export_correct_orientation_and_leave_source_unchanged(self):
        wcs=WCS(naxis=2);wcs.wcs.ctype=['RA---TAN','DEC--TAN']
        wcs.wcs.crval=[56,24];wcs.wcs.crpix=[8,6];wcs.wcs.cdelt=[-.01,.01]
        header=wcs.to_header();header['DATE-OBS']='2026-08-15'
        photo=np.full((3,12,16),.2,dtype=np.float32)
        photo[:,0,:]=.8
        original=photo.copy()
        expected=photo*.7
        for engine in ('StarXTerminator','StarNet'):
            with self.subTest(engine=engine),tempfile.TemporaryDirectory() as folder:
                out=Path(folder)/'flight'
                options=SimpleNamespace(engine=engine,executable='/fake/engine',ffmpeg='ffmpeg',
                    output=str(out),epoch='',seconds=30,zoom=15,source='source.tif')
                def fake_engine(argv,*unused):
                    dest=Path(argv[argv.index('--output')+1])
                    if engine=='StarXTerminator':
                        h=fits.Header();h['ROWORDER']='TOP-DOWN'
                        fits.PrimaryHDU(np.flip(expected,axis=-2),h).writeto(dest)
                    else:
                        tifffile.imwrite(dest,np.uint16(np.flipud(np.moveaxis(expected,0,-1))*65535),photometric='rgb')
                def fake_prepare(args,output):
                    self.assertEqual(args.wcs,(out/'source_wcs.fits').resolve())
                    self.assertEqual(args.ease_seconds,1.5)
                    self.assertEqual(args.fps,24)
                    return dict(stars=[],width=16,height=12,background=png_data(np.zeros((12,16,3))),extraction_version=4),np.zeros((12,16,3))
                with patch('siril_pipeline.run_engine',fake_engine),patch('siril_pipeline.prepare',fake_prepare),patch('siril_pipeline.render_video') as render,patch('iterative_deblend.refine_prepared_field',return_value=(dict(stars=[],width=16,height=12,background=png_data(np.zeros((12,16,3))),extraction_version=6,iterative_revision=2),np.zeros((12,16,3)))):
                    run_pipeline(photo,header,options,cancel=threading.Event())
                    render.assert_called_once()
                    # A restarted project uses the saved field, even with no current pixels.
                    with patch('siril_pipeline.run_engine') as repeated_engine,patch('siril_pipeline.prepare') as repeated_prepare:
                        resume_project(out,options)
                        repeated_engine.assert_not_called();repeated_prepare.assert_not_called()
                    self.assertEqual(read_project(out)['seconds'],30)
                    (out/'scene.json').unlink()
                    (out/'scene_iterative.json').unlink()
                    with patch('siril_pipeline.run_engine') as repeated_engine:
                        resume_project(out,options)
                        repeated_engine.assert_not_called()
                raster=np.asarray(Image.open(out/'starless.png'))/255
                np.testing.assert_allclose(raster,np.flipud(np.moveaxis(expected,0,-1)),atol=1/255)
                self.assertTrue((out/'photo.jpg').exists())
                self.assertTrue((out/'starless.jpg').exists())
                self.assertNotIn('EASERAMP',(out/(options.result_stem+'.html')).read_text())
                np.testing.assert_array_equal(photo,original)


if __name__=='__main__': unittest.main()
