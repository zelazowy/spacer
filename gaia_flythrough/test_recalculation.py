import csv
import json
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import numpy as np
from PIL import Image
from astropy.io import fits
from astropy.wcs import WCS
from flythrough import png_data
from siril_pipeline import (recalculate_project, calculation_folder, read_project,
    save_project, resume_project)


class RecalculationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.folder=Path(self.temp.name).resolve();w,h=180,100;yy,xx=np.mgrid[:h,:w]
        light=np.zeros((h,w));centers=[(30,30),(80,30),(130,30)]
        for x,y in centers: light+=.25*np.exp(-((xx-x)**2+(yy-y)**2)/5)
        photo=np.repeat((.04+light)[...,None],3,axis=2)
        Image.fromarray(np.uint8(photo*255)).save(self.folder/'photo.png')
        Image.fromarray(np.full((h,w,3),10,dtype=np.uint8)).save(self.folder/'starless.png')
        wcs=WCS(naxis=2);wcs.wcs.ctype=['RA---TAN','DEC--TAN'];wcs.wcs.crval=[56,24]
        wcs.wcs.crpix=[90,50];wcs.wcs.cdelt=[-.001,.001]
        header=wcs.to_header();header['DATE-OBS']='2016-01-01'
        fits.PrimaryHDU(np.zeros((h,w)),header).writeto(self.folder/'source_wcs.fits')
        rows=[]
        for i,(x,y) in enumerate(centers):
            sky=wcs.pixel_to_world(x,h-1-y)
            rows.append(dict(source_id=str(i),ra=sky.ra.deg,dec=sky.dec.deg,pmra=0,pmdec=0,
                ruwe=1,phot_g_mean_mag=15,r_med_geo=200,r_lo_geo=190,r_hi_geo=210))
        with (self.folder/'catalog.csv').open('w') as file:
            writer=csv.DictWriter(file,fieldnames=rows[0]);writer.writeheader();writer.writerows(rows)
        scene=dict(width=w,height=h,stars=[],background=png_data(photo),extraction_version=6,
            iterative_revision=2,prepared_with_version='0.10.0',motion_selection=dict(limit=1,moving_stars=0))
        for name in ('scene.json','scene_iterative.json'): (self.folder/name).write_text(json.dumps(scene))
        for name in ('matched_stars.csv','rejected_blends.csv','iterative_report.json','old.mp4','old.html'):
            (self.folder/name).write_text('keep previous output')
        save_project(self.folder,stage='ready',max_stars=1,last_render='old')
        self.before={p.name:p.read_bytes() for p in self.folder.iterdir()}
        self.options=SimpleNamespace(max_stars=50000)

    def assert_originals_kept(self,include_project=True):
        for name,data in self.before.items():
            if include_project or name!='project.json': self.assertEqual((self.folder/name).read_bytes(),data,name)

    def test_refresh_uses_cached_layers_and_publishes_new_revision_for_render(self):
        with patch('siril_pipeline.run_engine') as engine,patch('catalog.query_region') as fetch:
            recalculate_project(self.folder,self.options)
            engine.assert_not_called();fetch.assert_not_called()
        active=calculation_folder(self.folder)
        self.assertNotEqual(active,self.folder)
        scene=json.loads((active/'scene_iterative.json').read_text())
        self.assertEqual(len(scene['stars']),3);self.assertEqual(scene['motion_selection']['limit'],50000)
        self.assertTrue((active/'matched_stars.csv').is_file());self.assertTrue((active/'iterative_report.json').is_file())
        self.assert_originals_kept(include_project=False)
        self.assertEqual(read_project(self.folder)['last_render'],'old')
        options=SimpleNamespace(seconds=4,zoom=30,ffmpeg='ffmpeg')
        with patch('siril_pipeline.render_video') as render,patch('siril_pipeline.prepare') as prepare:
            resume_project(self.folder,options)
            self.assertEqual(len(render.call_args.args[0]['stars']),3);prepare.assert_not_called()
        metadata=json.loads((self.folder/(options.result_stem+'.json')).read_text())
        self.assertEqual(metadata['calculation_path'],str(active.relative_to(self.folder)))
        recalculate_project(self.folder,self.options)
        self.assertNotEqual(calculation_folder(self.folder),active)
        self.assertTrue((active/'scene_iterative.json').is_file())

    def test_cancel_keeps_active_revision_and_removes_incomplete_work(self):
        event=threading.Event();event.set()
        with self.assertRaises(InterruptedError): recalculate_project(self.folder,self.options,cancel=event)
        self.assert_originals_kept();self.assertFalse(list(self.folder.glob('.recalculate-*')))
        self.assertEqual(calculation_folder(self.folder),self.folder)

    def test_refinement_failure_keeps_previous_calculations_and_diagnostics(self):
        with patch('iterative_deblend.refine_prepared_field',side_effect=RuntimeError('fit failed')):
            with self.assertRaisesRegex(RuntimeError,'fit failed'): recalculate_project(self.folder,self.options)
        self.assert_originals_kept();self.assertFalse(list(self.folder.glob('.recalculate-*')))

    def test_missing_cache_fails_before_creating_work(self):
        (self.folder/'catalog.csv').unlink()
        with self.assertRaisesRegex(ValueError,'catalog.csv'): recalculate_project(self.folder,self.options)
        self.assertFalse(list(self.folder.glob('.recalculate-*')))

    def test_active_revision_cannot_escape_project_or_silently_fall_back(self):
        for relative in ('../elsewhere','calculations/missing'):
            save_project(self.folder,calculation_path=relative)
            with self.assertRaisesRegex(ValueError,'active star calculations'): calculation_folder(self.folder)
