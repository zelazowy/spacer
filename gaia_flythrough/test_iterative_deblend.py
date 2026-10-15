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


if __name__=='__main__': unittest.main()
