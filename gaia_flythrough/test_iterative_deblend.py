import unittest
import numpy as np
from flythrough import fit_compact_sprite
from iterative_deblend import deblend_group


class IterativeSeparationTests(unittest.TestCase):
    def test_coloured_spike_knots_do_not_remain_in_background(self):
        yy,xx=np.mgrid[:121,:121];dx=xx-60;dy=yy-60
        core=.6*np.exp(-(dx*dx+dy*dy)/8)
        spike=.04*np.exp(-dy*dy/2)/(1+(dx/25)**2)
        spike+=.04*np.exp(-dx*dx/2)/(1+(dy/25)**2)
        data=np.repeat((core+spike)[...,None],3,axis=2)
        knot=.08*np.exp(-((dx-24)**2/12+dy*dy/2))
        data[:,:,2]+=knot
        layers,background,_=deblend_group(data,(60,60),[],fit_compact_sprite,iterations=4)
        np.testing.assert_allclose(layers[0]+background,data,atol=1e-6)
        region=(dx>18)&(dx<30)&(np.abs(dy)<3)
        self.assertLess(background[:,:,2][region].sum()/data[:,:,2][region].sum(),.25)

    def test_neighbour_on_spike_is_separated_and_initial_image_is_preserved(self):
        yy,xx=np.mgrid[:101,:101];dx=xx-50;dy=yy-50
        main=.55*np.exp(-(dx*dx+dy*dy)/8)+.04*np.exp(-(dx*dx+dy*dy)/128)
        main+=.035*np.exp(-dy*dy/2)/(1+(dx/20)**2)
        main+=.035*np.exp(-dx*dx/2)/(1+(dy/20)**2)
        neighbour=.2*np.exp(-((xx-63)**2+dy*dy)/(2*1.3**2))
        data=np.repeat((main+neighbour)[...,None],3,axis=2)
        layers,background,history=deblend_group(data,(50,50),[(63,50)],fit_compact_sprite,iterations=5)
        self.assertGreaterEqual(len(history),2)
        self.assertTrue(np.isfinite(layers).all())
        self.assertTrue(all(np.min(a)>=0 for a in layers))
        self.assertGreaterEqual(background.min(),-1e-6)
        np.testing.assert_allclose(background+sum(layers),data,atol=1e-6)
        self.assertLess(abs(layers[1][50,63,0]-.2),.045)
        self.assertLess(layers[1][50,50,0],.001)
        self.assertLess(layers[0][50,63,0],.08)
        self.assertLess(history[-1]['mean_absolute_residual'],.01)


    def test_retry_spike_direction_requires_consistency_with_strong_field_consensus(self):
        from iterative_deblend import consistent_spike_angle
        self.assertTrue(consistent_spike_angle(29.5,[30,29.5,30]))
        self.assertFalse(consistent_spike_angle(3.5,[30,29.5,30]))
        self.assertTrue(consistent_spike_angle(89,[0,1,89]))
        self.assertTrue(consistent_spike_angle(3.5,[30,29.5]))
        self.assertTrue(consistent_spike_angle(3.5,[0,30,60]))

    def test_stabilised_pass_preserves_light_and_independent_neighbour(self):
        yy,xx=np.mgrid[:101,:101];dx=xx-50;dy=yy-50
        main=.55*np.exp(-(dx*dx+dy*dy)/8)
        main+=.035*np.exp(-dy*dy/2)/(1+(dx/20)**2)
        main+=.035*np.exp(-dx*dx/2)/(1+(dy/20)**2)
        neighbour=.2*np.exp(-((xx-63)**2+dy*dy)/(2*1.3**2))
        data=np.repeat((main+neighbour)[...,None],3,axis=2)
        layers,background,history=deblend_group(data,(50,50),[(63,50)],fit_compact_sprite,iterations=20,stabilise=True)
        np.testing.assert_allclose(background+sum(layers),data,atol=1e-6)
        self.assertGreaterEqual(background.min(),-1e-6)
        self.assertLess(history[-1]['relative_model_change'],.001)
        self.assertLess(abs(layers[1][50,63,0]-.2),.045)
        self.assertLess(layers[1][50,50,0],.001)
        self.assertEqual(len({h['spike_angle_deg'] for h in history}),1)

    def test_group_progress_counts_deferred_and_failed_groups(self):
        import csv,tempfile
        from pathlib import Path
        from unittest.mock import patch
        from PIL import Image
        from astropy.io import fits
        from astropy.wcs import WCS
        from flythrough import png_data
        from iterative_deblend import refine_prepared_field
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory);width,height=1200,500
            yy,xx=np.mgrid[:height,:width];light=np.zeros((height,width))
            centers=[(250,250),(280,250),(900,250)]
            for x,y in centers: light+=.6*np.exp(-((xx-x)**2+(yy-y)**2)/32)
            photo=np.repeat(light[...,None],3,axis=2)
            Image.fromarray(np.uint8(photo*255)).save(folder/'photo.png')
            Image.new('RGB',(width,height)).save(folder/'starless.png')
            wcs=WCS(naxis=2);wcs.wcs.ctype=['RA---TAN','DEC--TAN']
            wcs.wcs.crval=[56,24];wcs.wcs.crpix=[600,250];wcs.wcs.cdelt=[-.001,.001]
            header=wcs.to_header();header['DATE-OBS']='2016-01-01'
            fits.PrimaryHDU(np.zeros((height,width),dtype=np.uint8),header).writeto(folder/'source_wcs.fits')
            rows=[]
            for i,(x,y) in enumerate(centers):
                sky=wcs.pixel_to_world(x,height-1-y)
                rows.append(dict(source_id=str(i),ra=sky.ra.deg,dec=sky.dec.deg,pmra=0,pmdec=0,
                    r_med_geo=200,r_lo_geo=190,r_hi_geo=210,ruwe=1,phot_g_mean_mag=10))
            faint=wcs.pixel_to_world(912,height-1-250)
            rows.append(dict(rows[-1],source_id='uncertain-neighbour',ra=faint.ra.deg,dec=faint.dec.deg,ruwe=2,phot_g_mean_mag=15))
            with (folder/'catalog.csv').open('w') as file:
                writer=csv.DictWriter(file,fieldnames=rows[0]);writer.writeheader();writer.writerows(rows)
            events=[]
            with patch('iterative_deblend.deblend_group',return_value=([],None,[{}])) as fit:
                result,_=refine_prepared_field(dict(stars=[],background=png_data(photo),motion_selection=dict(limit=5000,moving_stars=99)),folder,
                    stage_progress=lambda *event:events.append(event))
                fit.assert_called_once()
                self.assertEqual(len(fit.call_args.args[2]),1) # uncertain neighbour still participates
                self.assertEqual(result['motion_selection']['moving_stars'],len(result['stars']))
            # Only the isolated group is fitted; a failed low-residual fit
            # gets one bounded, explicitly stabilised retry.
            failed=[dict(relative_model_change=.02,mean_absolute_residual=.005)]*2
            success=[dict(relative_model_change=1,mean_absolute_residual=.005),dict(relative_model_change=.0005,mean_absolute_residual=.005)]
            zero_layers=[np.zeros((321,321,3),dtype=np.float32)]*2
            with patch('iterative_deblend.deblend_group',side_effect=[(zero_layers,None,failed),(zero_layers,None,success)]) as fit:
                recovered,_=refine_prepared_field(dict(stars=[],background=png_data(photo)),folder)
                self.assertEqual(fit.call_count,2)
                self.assertTrue(fit.call_args.kwargs['stabilise'])
                self.assertEqual(recovered['iterative_limits']['stabilised_retries'],1)
            groups=[e for e in events if e[0]=='Refining Iterative groups']
            self.assertEqual(groups[0][1:3],(0,3));self.assertEqual(groups[-1][1:3],(3,3))
            import json
            for setting,status in (('MAX_GROUP_NEIGHBOURS','deferred_dense_group'),('MAX_ITERATIVE_GROUPS','deferred_group_budget')):
                with patch('iterative_deblend.'+setting,0),patch('iterative_deblend.deblend_group') as fit:
                    refine_prepared_field(dict(stars=[],background=png_data(photo)),folder)
                    fit.assert_not_called()
                report=json.loads((folder/'iterative_report.json').read_text())
                self.assertIn(status,[entry['status'] for entry in report])



if __name__=='__main__': unittest.main()
