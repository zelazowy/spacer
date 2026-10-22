import unittest
from motion import motion_scales,validate_motion

class MotionTests(unittest.TestCase):
    def test_target_plane_and_same_depth_star_agree_without_double_zoom(self):
        for t in (0,.25,.5,1):
            background,extra,move=motion_scales(t,1.9,80,'target_distance',400)
            self.assertAlmostEqual(background,400/(400-move)*extra)
            self.assertEqual(extra,1)
        self.assertEqual(motion_scales(1,1.9,80,'target_distance',400)[0],1.25)

    def test_distant_galaxy_and_independent_compatibility(self):
        self.assertLess(motion_scales(1,1.3,80,'target_distance',1e6)[0],1.0001)
        self.assertEqual(motion_scales(.5,1.3,80),(1.15,1.15,40))

    def test_no_arrival_crossing_or_nonfinite_parameters(self):
        for mode,travel,distance in [('target_distance',400,400),('target_distance',401,400),('target_distance',80,float('nan')),('independent',float('inf'),400),('independent',-1,400)]:
            with self.assertRaises(ValueError):validate_motion(mode,travel,distance)
