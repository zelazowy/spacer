import argparse
import base64
import csv
import io
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image
from astropy.io import fits
from astropy.wcs import WCS
from flythrough import prepare, sample_sprite, ease_progress, fit_compact_sprite
from scipy import ndimage
from scipy.spatial import cKDTree


class MatchingTest(unittest.TestCase):
    def test_compact_fit_does_not_transport_long_spike_and_skips_bright_core(self):
        yy,xx=np.mgrid[:41,:41]
        light=.3*np.exp(-((xx-20)**2+(yy-20)**2)/(2*1.5**2))
        light+=.04*np.exp(-(yy-20)**2/1.5)
        residual=np.repeat(light[...,None],3,axis=2)
        fit=fit_compact_sprite(residual,20,20,cKDTree([[20,20]]))
        self.assertIsNotNone(fit)
        sy,sx,model,_=fit
        self.assertLess(model[20-sy.start,28-sx.start,0],.001)
        residual[20,20]=1
        self.assertIsNone(fit_compact_sprite(residual,20,20,cKDTree([[20,20]])))

    def test_unmatched_neighbour_in_connected_halo_is_not_carried(self):
        with tempfile.TemporaryDirectory() as folder:
            out=Path(folder)
            wcs=WCS(naxis=2);wcs.wcs.crpix=[50,40];wcs.wcs.crval=[56,24]
            wcs.wcs.cdelt=[-.001,.001];wcs.wcs.ctype=['RA---TAN','DEC--TAN']
            fits.PrimaryHDU(np.zeros((80,100)),wcs.to_header()).writeto(out/'wcs.fits')
            yy,xx=np.mgrid[:80,:100]
            light=np.exp(-((xx-20)**2+(yy-20)**2)/6)*.4
            light+=np.exp(-((xx-26)**2+(yy-20)**2)/6)*.25
            light+=np.exp(-((xx-75)**2+(yy-55)**2)/6)*.4
            photo=np.repeat((.04+light)[...,None],3,axis=2)
            Image.fromarray(np.uint8(photo*255)).save(out/'photo.png')
            Image.fromarray(np.full((80,100,3),10,dtype=np.uint8)).save(out/'starless.png')
            rows=[]
            for i,(x,y) in enumerate([(20,20),(75,55)]):
                sky=wcs.pixel_to_world(x,79-y)
                rows.append(dict(source_id=str(i),ra=sky.ra.deg,dec=sky.dec.deg,pmra=0,pmdec=0,
                    ruwe=1,r_med_geo=200,r_lo_geo=190,r_hi_geo=210))
            with (out/'catalog.csv').open('w') as f:
                writer=csv.DictWriter(f,fieldnames=rows[0]);writer.writeheader();writer.writerows(rows)
            args=argparse.Namespace(photo=out/'photo.png',starless=out/'starless.png',wcs=out/'wcs.fits',
                epoch='2016-01-01',magnitude=18,threshold=.008,match_pixels=3,max_uncertainty=.2,raster_bottom_up=False)
            scene,bg=prepare(args,out)
            self.assertEqual([s['source_id'] for s in scene['stars']],['0','1'])
            # The primary's fitted PSF tail may cross this pixel, but less than
            # 1% of the unmatched neighbour's 0.25 peak may move with it.
            np.testing.assert_allclose(bg[20,26],np.uint8(photo*255)[20,26]/255,atol=.0025)
            first=scene['stars'][0]
            patch=np.asarray(Image.open(io.BytesIO(base64.b64decode(first['image'].split(',')[1]))))
            lx=round(26-(first['x']-first['ax']));ly=round(20-(first['y']-first['ay']))
            self.assertTrue(np.all(patch[ly,lx]==0))
            sky=wcs.pixel_to_world(26,59)
            rows.append(dict(source_id='2',ra=sky.ra.deg,dec=sky.dec.deg,pmra=0,pmdec=0,
                ruwe=1,r_med_geo=500,r_lo_geo=490,r_hi_geo=510))
            with (out/'catalog.csv').open('w') as f:
                writer=csv.DictWriter(f,fieldnames=rows[0]);writer.writeheader();writer.writerows(rows)
            revised,_=prepare(args,out)
            distances={s['source_id']:s['distance_pc'] for s in revised['stars']}
            self.assertEqual(distances['0'],200)
            self.assertEqual(distances['2'],500)
            args.mode='dynamic'
            dynamic,_=prepare(args,out)
            self.assertEqual(dynamic['mode'],'dynamic')
            self.assertIn('blended neighbours',dynamic['label'])
            self.assertLess(len(dynamic['stars']),len(revised['stars']))
            primary=next(s for s in dynamic['stars'] if s['source_id']=='0')
            model=np.asarray(Image.open(io.BytesIO(base64.b64decode(primary['image'].split(',')[1]))))
            lx=round(26-(primary['x']-primary['ax']));ly=round(20-(primary['y']-primary['ay']))
            self.assertGreater(model[ly,lx].max(),40)

    def test_clipped_sprite_matches_full_sprite_at_deep_zoom(self):
        yy,xx=np.mgrid[-5:6,-5:6]
        a=np.repeat(np.exp(-(xx*xx+yy*yy)/8)[...,None],3,axis=2)
        ix,iy,full=sample_sprite(a,-10.3,-4.2,3.7)
        cx,cy,clipped=sample_sprite(a,-10.3,-4.2,3.7,viewport=(20,20))
        self.assertEqual((cx,cy),(0,0))
        np.testing.assert_allclose(clipped,full[-iy:20-iy,-ix:20-ix],atol=1e-6)
        _,_,huge=sample_sprite(a,-100,-100,101,viewport=(20,20))
        self.assertLessEqual(huge.shape[0]*huge.shape[1],400)

    def test_short_velocity_ramps(self):
        self.assertEqual(ease_progress(0),0)
        self.assertEqual(ease_progress(1),1)
        t=np.linspace(0,1,1001)
        motion=np.array([ease_progress(x) for x in t])
        self.assertTrue(np.all(np.diff(motion)>=0))
        np.testing.assert_allclose(motion+motion[::-1],1,atol=1e-12)
        np.testing.assert_allclose(np.diff(motion)[60:940],.001/.95,atol=1e-12)

    def test_fractional_motion_preserves_centroid_and_flux(self):
        yy,xx=np.mgrid[-12:13,-12:13]
        gaussian=np.exp(-(xx*xx+yy*yy)/8)
        coefficients=np.repeat(gaussian[...,None],3,axis=2)
        centers,flux=[],[]
        for offset in (0,.25,.5,.75,1):
            ix,iy,a=sample_sprite(coefficients,10+offset,20,1)
            cy,cx=ndimage.center_of_mass(a[:,:,0])
            centers.append(ix+cx);flux.append(a[:,:,0].sum())
        np.testing.assert_allclose(np.diff(centers),.25,atol=.01)
        self.assertLess(np.ptp(flux)/np.mean(flux),.005)

    def test_orientation_uncertainty_and_original_reconstruction(self):
        with tempfile.TemporaryDirectory() as folder:
            out = Path(folder)
            wcs = WCS(naxis=2)
            wcs.wcs.crpix = [65, 49]
            wcs.wcs.crval = [56, 24]
            wcs.wcs.cdelt = [-.001, .001]
            wcs.wcs.ctype = ['RA---TAN', 'DEC--TAN']
            fits.PrimaryHDU(np.zeros((96,128)), wcs.to_header()).writeto(out/'wcs.fits')
            bg = np.full((96,128,3), 10, dtype=np.uint8)
            photo = bg.copy()
            rows = []
            for i,(x,y) in enumerate([(30,20),(80,60)]):
                photo[y-2:y+3,x-2:x+3] += 100
                sky = wcs.pixel_to_world(x,95-y)
                rows.append(dict(source_id=str(i),ra=sky.ra.deg,dec=sky.dec.deg,
                    pmra=0,pmdec=0,ruwe=1,r_med_geo=200,
                    r_lo_geo=190 if i==0 else 10,r_hi_geo=210 if i==0 else 1000))
            for name,a in [('photo',photo),('starless',bg)]:
                Image.fromarray(a).save(out/f'{name}.png')
            with (out/'catalog.csv').open('w') as f:
                writer=csv.DictWriter(f,fieldnames=rows[0]);writer.writeheader();writer.writerows(rows)
            args=argparse.Namespace(photo=out/'photo.png',starless=out/'starless.png',
                wcs=out/'wcs.fits',epoch='2016-01-01',magnitude=18,
                threshold=.008,match_pixels=3,max_uncertainty=.2,raster_bottom_up=False)
            scene,background=prepare(args,out)
            self.assertEqual(len(scene['stars']),1)
            s=scene['stars'][0]
            self.assertAlmostEqual(s['x'],30)
            self.assertAlmostEqual(s['y'],20)
            self.assertLessEqual(s['depth'],200)
            patch=np.asarray(Image.open(io.BytesIO(base64.b64decode(s['image'].split(',')[1]))))/255
            x,y=round(s['x']-s['ax']),round(s['y']-s['ay'])
            background[y:y+s['h'],x:x+s['w']]+=patch
            np.testing.assert_allclose(background,photo/255,atol=1/255)


if __name__=='__main__':
    unittest.main()
