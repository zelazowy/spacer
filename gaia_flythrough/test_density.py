import base64,copy,csv,io,tempfile,threading,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import numpy as np
from PIL import Image
from astropy.io import fits
from astropy.wcs import WCS
from density import decode_layer,limit_scene_stars,moving_star_limit
from flythrough import png_data,prepare


def reconstruct(scene):
    image=decode_layer(scene['background']).astype(np.uint32);h,w=image.shape[:2]
    for star in scene['stars']:
        tile=decode_layer(star['image']);th,tw=tile.shape[:2]
        x,y=round(star['x']-star['ax']),round(star['y']-star['ay'])
        xa,xb=max(0,x),min(w,x+tw);ya,yb=max(0,y),min(h,y+th)
        if xb>xa and yb>ya: image[ya:yb,xa:xb]+=tile[ya-y:yb-y,xa-x:xb-x].astype(np.uint32)
    return np.minimum(image,255).astype(np.uint8)


class DensityTests(unittest.TestCase):
    def test_existing_scene_limit_preserves_reconstruction_and_saved_analysis(self):
        stars=[]
        for i,(value,x,y) in enumerate(((.1,-1,1),(.8,3,2),(.2,4,2),(.2,6,6))):
            stars.append(dict(source_id=str(i),image=png_data(np.full((4,4,3),value)),
                x=x+.3,y=y+.6,ax=.3,ay=.6,w=4,h=4))
        scene=dict(stars=stars,background=png_data(np.full((8,9,3),.1)),prepared_with_version='0.9.8')
        original=copy.deepcopy(scene);limited,bg=limit_scene_stars(scene,1)
        self.assertEqual([s['source_id'] for s in limited['stars']],['1'])
        np.testing.assert_array_equal(reconstruct(limited),reconstruct(scene))
        self.assertEqual(scene,original);self.assertEqual(limited['prepared_with_version'],'0.9.8')
        np.testing.assert_array_equal(np.uint8(np.rint(bg*255)),decode_layer(limited['background']))

    def test_invalid_limit_and_cancellation_do_not_mutate_scene(self):
        self.assertEqual(moving_star_limit(),50000)
        for value in (1,20001,50000): self.assertEqual(moving_star_limit(value),value)
        for value in (0,-1,50001,2.5,None):
            with self.assertRaises(ValueError): moving_star_limit(value)
        event=threading.Event();event.set()
        scene=dict(stars=[dict(image=png_data(np.ones((2,2,3))))]*3,background=png_data(np.zeros((3,3,3))))
        before=copy.deepcopy(scene)
        with self.assertRaises(InterruptedError): limit_scene_stars(scene,1,cancel=event)
        self.assertEqual(scene,before)

    def test_new_preparation_limits_fits_without_losing_ambiguity_checks(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);w,h=180,100;yy,xx=np.mgrid[:h,:w]
            centers=[(25,30,.15),(65,30,.25),(105,30,.35),(145,30,.3)]
            light=np.zeros((h,w))
            for x,y,a in centers: light+=a*np.exp(-((xx-x)**2+(yy-y)**2)/5)
            photo=np.repeat((.04+light)[...,None],3,axis=2)
            Image.fromarray(np.uint8(photo*255)).save(root/'photo.png')
            Image.fromarray(np.full((h,w,3),10,dtype=np.uint8)).save(root/'starless.png')
            wcs=WCS(naxis=2);wcs.wcs.ctype=['RA---TAN','DEC--TAN'];wcs.wcs.crval=[56,24]
            wcs.wcs.crpix=[90,50];wcs.wcs.cdelt=[-.001,.001]
            fits.PrimaryHDU(np.zeros((h,w)),wcs.to_header()).writeto(root/'source_wcs.fits')
            rows=[]
            for i,(x,y,a) in enumerate(centers):
                sky=wcs.pixel_to_world(x,h-1-y)
                rows.append(dict(source_id=str(i),ra=sky.ra.deg,dec=sky.dec.deg,pmra=0,pmdec=0,ruwe=1,r_med_geo=200,r_lo_geo=190,r_hi_geo=210))
            # A second reference at the brightest detected core must still reject
            # that core, even though the expensive fitting budget is only one.
            rows.append(dict(rows[2],source_id='faint-neighbour',r_med_geo=2000,r_lo_geo=1000,r_hi_geo=4000))
            with (root/'catalog.csv').open('w') as file:
                writer=csv.DictWriter(file,fieldnames=rows[0]);writer.writeheader();writer.writerows(rows)
            options=SimpleNamespace(photo=root/'photo.png',starless=root/'starless.png',wcs=root/'source_wcs.fits',epoch='2016-01-01',magnitude=18,threshold=.008,match_pixels=3,max_uncertainty=.2,raster_bottom_up=False,max_stars=1,progress=lambda _:None)
            import flythrough
            with patch('flythrough.fit_compact_sprite',wraps=flythrough.fit_compact_sprite) as fit:
                scene,bg=prepare(options,root)
            self.assertEqual(fit.call_count,1);self.assertEqual([s['source_id'] for s in scene['stars']],['3'])
            for x,y,a in centers[:3]: np.testing.assert_allclose(bg[y,x],np.uint8(photo*255)[y,x]/255,atol=1e-7)

    def test_prepared_render_limit_preserves_saved_scene_and_restores_preference(self):
        import json
        from siril_pipeline import render_prepared,read_project
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory);stars=[]
            for i,value in enumerate((.1,.4,.2)):
                stars.append(dict(source_id=str(i),image=png_data(np.full((2,2,3),value)),x=i*3,y=2,ax=0,ay=0,w=2,h=2))
            scene=dict(stars=stars,width=12,height=8,background=png_data(np.zeros((8,12,3))),extraction_version=6,iterative_revision=2,prepared_with_version='0.9.8')
            path=folder/'scene_iterative.json';original=json.dumps(scene);path.write_text(original)
            options=SimpleNamespace(seconds=20,zoom=30,ffmpeg='ffmpeg',max_stars=1)
            with patch('siril_pipeline.render_video') as render:
                render_prepared(folder,options)
                view=render.call_args.args[0]
                self.assertEqual(len(view['stars']),1)
                np.testing.assert_array_equal(reconstruct(view),reconstruct(scene))
                self.assertEqual(path.read_text(),original)
                metadata=json.loads((folder/(options.result_stem+'.json')).read_text())
                self.assertEqual(metadata['max_stars'],1);self.assertEqual(metadata['field_version'],'0.9.8')
                self.assertEqual(read_project(folder)['max_stars'],1)
                del options.max_stars
                render_prepared(folder,options)
                self.assertEqual(len(render.call_args.args[0]['stars']),1)
