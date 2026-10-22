import unittest
from astropy.wcs import WCS
from targets import field_query,parse_targets,LIMIT

class TargetTests(unittest.TestCase):
    def setUp(self):
        w=WCS(naxis=2);w.wcs.crval=[359.9,24];w.wcs.crpix=[50,40];w.wcs.cdelt=[-.01,.01];w.wcs.ctype=['RA---TAN','DEC--TAN']
        self.header=w.to_header();self.header['NAXIS1']=100;self.header['NAXIS2']=80
        _,self.wcs,self.width,self.height=field_query(self.header)
        self.names=['main_id','otype','ra','dec','dist','unit','minus_err','plus_err','method','bibcode','qual']
    def parse(self,rows):
        return parse_targets(dict(metadata=[dict(name=n) for n in self.names],data=rows),self.wcs,100,80)
    def row(self,distance=2,unit='kpc',x=50):
        ra,dec=self.wcs.pixel_to_world_values(x,40)
        return ['M test','G',float(ra),float(dec),distance,unit,-.1,.2,'method','2025ref',None]
    def test_unit_conversion_errors_dedup_and_footprint(self):
        a=self.row()
        rows=self.parse([a,a,self.row(x=120)])
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['distance_pc'],2000)
        self.assertEqual(rows[0]['minus_error_pc'],100)
        self.assertEqual(rows[0]['plus_error_pc'],200)
        self.assertEqual(self.parse([self.row(2,'Mpc')])[0]['distance_pc'],2e6)
    def test_missing_invalid_measurements_stay_unknown(self):
        for value,unit in [(None,'pc'),(-2,'pc'),(float('nan'),'pc'),(2,'unknown')]:
            self.assertIsNone(self.parse([self.row(value,unit)])[0]['distance_pc'])
    def test_overflow_not_silently_truncated(self):
        with self.assertRaisesRegex(ValueError,'Too many'):self.parse([self.row()]*(LIMIT+1))
    def test_sky_query_uses_solved_field(self):
        query,*_=field_query(self.header)
        self.assertIn("CIRCLE('ICRS',359.",query)
        self.assertIn('LEFT JOIN mesDistance',query)
        self.assertIn('ORDER BY nbref DESC',query)
