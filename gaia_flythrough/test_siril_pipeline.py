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
            options=SimpleNamespace(seconds=20,zoom=900,ffmpeg='ffmpeg',frame_progress=lambda *values:None)
            with patch('siril_pipeline.prepare') as prepare_field,patch('siril_pipeline.run_engine') as engine,patch('siril_pipeline.render_video') as render:
                render_prepared(out,options)
                self.assertEqual(options.result_stem,f'flythrough_v{VERSION}_iterative_20s_zoom900pct_24fps_1920px')
                html=(out/(options.result_stem+'.html')).read_text()
                self.assertIn('render_version',html)
                metadata=json.loads((out/(options.result_stem+'.json')).read_text())
                self.assertIs(render.call_args.args[2].frame_progress,options.frame_progress)
                self.assertEqual(metadata['tool_version'],VERSION)
                self.assertEqual(metadata['field_version'],'unversioned')
                self.assertTrue(metadata['created_at'].endswith('+00:00'))
                self.assertNotIn('render_version',json.loads((out/'scene_iterative.json').read_text()))
                self.assertIn('value="10.0"',html)
                self.assertNotIn('MAXZOOM',html)
                render_prepared(out,options)
                self.assertEqual(options.result_stem,f'flythrough_v{VERSION}_iterative_20s_zoom900pct_24fps_1920px_02')
                prepare_field.assert_not_called();engine.assert_not_called()
                self.assertEqual(render.call_count,2)

    def test_target_distance_export_reuses_field_and_records_geometry(self):
        with tempfile.TemporaryDirectory() as folder:
            out=Path(folder)
            scene=dict(stars=[],width=16,height=12,background=png_data(np.zeros((12,16,3))),extraction_version=6,iterative_revision=2)
            (out/'scene_iterative.json').write_text(json.dumps(scene))
            options=SimpleNamespace(seconds=20,zoom=30,ffmpeg='ffmpeg',zoom_mode='target_distance',target_distance_pc=400,travel_pc=80,target_info=dict(name='test target',bibcode='reference'))
            with patch('siril_pipeline.render_video') as render,patch('siril_pipeline.prepare') as prepare:
                render_prepared(out,options)
                prepare.assert_not_called()
                self.assertEqual(render.call_args.args[2].zoom_mode,'target_distance')
                self.assertEqual(render.call_args.args[2].travel,80)
            meta=json.loads((out/(options.result_stem+'.json')).read_text())
            self.assertEqual(meta['final_zoom'],1.25)
            self.assertEqual(meta['target_distance_pc'],400)
            self.assertEqual(meta['target_info'],options.target_info)
            self.assertEqual(read_project(out)['target_info'],options.target_info)
            self.assertIn('target400pc_travel80pc',options.result_stem)
            self.assertEqual(read_project(out)['zoom_mode'],'target_distance')
            self.assertIn('"target_distance"',(out/(options.result_stem+'.html')).read_text())

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
                if engine=='StarNet': out.mkdir() # Empty folders selected in Browse are valid new projects.
                options=SimpleNamespace(engine=engine,executable='/fake/engine',ffmpeg='ffmpeg',
                    output=str(out),epoch='',seconds=30,zoom=15,source='source.tif',stage_progress=lambda *args:None,
                    date_info=dict(value='2026-08-15T00:00:00.000',source='File creation date',approximate=True))
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
                    self.assertIs(args.stage_progress,options.stage_progress)
                    return dict(stars=[],width=16,height=12,background=png_data(np.zeros((12,16,3))),extraction_version=4),np.zeros((12,16,3))
                with patch('siril_pipeline.run_engine',fake_engine),patch('siril_pipeline.prepare',fake_prepare),patch('siril_pipeline.render_video') as render,patch('iterative_deblend.refine_prepared_field',side_effect=lambda natural,*args,**kwargs:(dict(natural,extraction_version=6,iterative_revision=2),np.zeros((12,16,3)))):
                    run_pipeline(photo,header,options,cancel=threading.Event())
                    render.assert_called_once()
                    self.assertEqual(read_project(out)['date_info'],options.date_info)
                    self.assertTrue(fits.getheader(out/'source_wcs.fits')['DATEAPPX'])
                    self.assertEqual(json.loads((out/'scene_iterative.json').read_text())['date_info'],options.date_info)
                    self.assertEqual(json.loads((out/(options.result_stem+'.json')).read_text())['date_info'],options.date_info)
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

    def test_excessive_fov_is_rejected_before_outputs_or_star_removal(self):
        with tempfile.TemporaryDirectory() as folder:
            out=Path(folder)/'too-wide'
            wcs=WCS(naxis=2);wcs.wcs.ctype=['RA---TAN','DEC--TAN']
            wcs.wcs.crval=[42,89.5];wcs.wcs.crpix=[8,6];wcs.wcs.cdelt=[-1,1]
            options=SimpleNamespace(output=str(out))
            with patch('siril_pipeline.run_engine') as engine:
                with self.assertRaisesRegex(ValueError,'central crop'):
                    run_pipeline(np.zeros((3,12,16)),wcs.to_header(),options)
                engine.assert_not_called()
            self.assertFalse(out.exists())



class WorkspaceStageTests(unittest.TestCase):
    def test_layer_preparation_stops_before_catalogues_and_encoding(self):
        wcs=WCS(naxis=2);wcs.wcs.ctype=['RA---TAN','DEC--TAN'];wcs.wcs.crval=[56,24];wcs.wcs.crpix=[8,6];wcs.wcs.cdelt=[-.01,.01]
        header=wcs.to_header();header['DATE-OBS']='2026-08-15';photo=np.full((3,12,16),.2,dtype=np.float32)
        with tempfile.TemporaryDirectory() as folder:
            out=Path(folder)/'project'
            options=SimpleNamespace(output=str(out),source='source.fit',engine='StarXTerminator',executable='/fake/engine',ffmpeg='',epoch='2026-08-15',seconds=60,zoom=30,layers_only=True)
            def engine(argv,*_):fits.PrimaryHDU(photo*.8).writeto(out/'starless_work.fits')
            with patch('siril_pipeline.run_engine',side_effect=engine) as remove,patch('siril_pipeline.prepare') as prepare,patch('siril_pipeline.render_video') as render:
                run_pipeline(photo,header,options)
                remove.assert_called_once();prepare.assert_not_called();render.assert_not_called()
            self.assertEqual(read_project(out)['stage'],'matching')
            self.assertTrue((out/'photo.png').is_file());self.assertTrue((out/'starless.png').is_file())
            self.assertFalse(list(out.glob('*.mp4')));self.assertFalse((out/'catalog.csv').exists())

    def test_star_calculation_can_finish_without_valid_target_or_encoder(self):
        with tempfile.TemporaryDirectory() as folder:
            out=Path(folder);scene=dict(stars=[],width=16,height=12,background=png_data(np.zeros((12,16,3))),extraction_version=6,iterative_revision=3)
            path=out/'scene_iterative.json';path.write_text(json.dumps(scene));before=path.read_bytes()
            options=SimpleNamespace(seconds=60,zoom=30,ffmpeg='',prepare_only=True,zoom_mode='target_distance',target_distance_pc=0,travel_pc=80)
            with patch('siril_pipeline.render_video') as render,patch('siril_pipeline.prepare') as prepare,patch('siril_pipeline.run_engine') as engine:
                render_prepared(out,options);render.assert_not_called();prepare.assert_not_called();engine.assert_not_called()
            self.assertEqual(path.read_bytes(),before);self.assertEqual(read_project(out)['stage'],'ready');self.assertFalse(list(out.glob('flythrough_*')))

    def test_export_quality_reaches_renderer_and_survives_restart(self):
        with tempfile.TemporaryDirectory() as folder:
            out=Path(folder);scene=dict(stars=[],width=80,height=60,background=png_data(np.zeros((60,80,3))),extraction_version=6,iterative_revision=3)
            (out/'scene_iterative.json').write_text(json.dumps(scene))
            options=SimpleNamespace(seconds=5,zoom=30,ffmpeg='ffmpeg',fps=30,video_width=3840)
            with patch('siril_pipeline.render_video') as render:
                render_prepared(out,options);args=render.call_args.args[2]
                self.assertEqual(args.fps,30);self.assertEqual(args.video_width,3840)
                first=options.result_stem;render_prepared(out,options);self.assertNotEqual(options.result_stem,first)
            self.assertIn('30fps_3840px',first);self.assertEqual(read_project(out)['fps'],30)
            meta=json.loads((out/(first+'.json')).read_text());self.assertEqual(meta['video_width'],3840);self.assertEqual(meta['fps'],30)
            options.video_width=0
            with patch('siril_pipeline.render_video') as render:
                render_prepared(out,options);self.assertEqual(render.call_args.args[2].video_width,80)
            self.assertIn('_original',options.result_stem)


if __name__=='__main__':unittest.main()
